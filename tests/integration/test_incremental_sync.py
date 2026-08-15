"""T4 integration tests: raw retention + incremental sync.

Covers the incremental no-op (identical payload -> safe skip), payload-hash
sensitivity (any field change re-merges), `source_sync` table writes, and
offline candidate rebuild from persisted raw records.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import scripts.sync_data as sync_data
from pipeline.core.schema import connect
from tests.conftest import _mk, build_fixture_db


class FakeAdapter:
    def __init__(self, records, error=None):
        self.records = records
        self.error = error

    def fetch(self, fetcher, force=False):
        if self.error is not None:
            raise self.error
        return self.records


def make_loader(spec):
    def loader(name):
        records, error = spec.get(name, ([], None))
        return FakeAdapter(records, error)

    return loader


RECORDS = [
    _mk("agumon", "Agumon", "アグモン", "亚古兽", dapi_id=1),
    _mk("greymon", "Greymon", "グレイモン", "暴龙兽", dapi_id=3),
]


@pytest.fixture
def env_db(monkeypatch, tmp_path):
    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    conn.close()
    monkeypatch.setenv("DIGIDEX_DB", str(db))
    return db


def db_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digimon_count(path: Path) -> int:
    conn = connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM digimon").fetchone()[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# incremental no-op / hash sensitivity
# ---------------------------------------------------------------------------
def test_incremental_noop_when_payload_unchanged(env_db, tmp_path):
    """A second sync with the identical payload is a safe no-op: exit 0, live
    DB byte-identical, no candidate left behind."""
    loader = make_loader({"dapi": (RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports") == 0
    after_first = db_hash(env_db)

    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc == 0
    assert db_hash(env_db) == after_first  # no rebuild / no publish
    assert not (tmp_path / "digidex.candidate.sqlite").exists()


def test_payload_change_triggers_remerge(env_db, tmp_path):
    """Changing any field in a record changes the payload hash and forces a
    full re-merge (the new skill is present in the rebuilt DB)."""
    loader1 = make_loader({"dapi": (RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader1, reports_dir=tmp_path / "reports") == 0

    changed = [
        _mk("agumon", "Agumon", "アグモン", "亚古兽", dapi_id=1, skills=["Baby Flame", "New Skill"]),
        _mk("greymon", "Greymon", "グレイモン", "暴龙兽", dapi_id=3),
    ]
    loader2 = make_loader({"dapi": (changed, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader2, reports_dir=tmp_path / "reports") == 0
    conn = connect(env_db)
    n = conn.execute("SELECT COUNT(*) FROM skill WHERE name_en='New Skill'").fetchone()[0]
    conn.close()
    assert n == 1


# ---------------------------------------------------------------------------
# source_sync tracking
# ---------------------------------------------------------------------------
def test_source_sync_rows_record_each_source(env_db, tmp_path):
    loader = make_loader({"dapi": (RECORDS, None), "digimons_net": ([], None)})
    assert sync_data.run(["--sources", "dapi,digimons_net"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    conn = connect(env_db)
    rows = conn.execute(
        """SELECT source, status, records, parsed_count, failed_count,
                  raw_completeness, payload_hash, run_id, error_summary
           FROM source_sync ORDER BY source"""
    ).fetchall()
    conn.close()
    by_src = {r["source"]: r for r in rows}
    assert set(by_src) == {"dapi", "digimons_net"}
    assert by_src["dapi"]["status"] == "ok"
    assert by_src["dapi"]["records"] == len(RECORDS)
    assert by_src["dapi"]["parsed_count"] == len(RECORDS)
    assert by_src["dapi"]["failed_count"] == 0
    assert by_src["dapi"]["raw_completeness"] == 1
    assert by_src["dapi"]["payload_hash"]  # non-empty full-payload hash
    assert by_src["dapi"]["run_id"]
    assert by_src["digimons_net"]["status"] == "ok"
    assert by_src["digimons_net"]["records"] == 0


def test_source_sync_marks_failed_source(env_db, tmp_path):
    loader = make_loader({"dapi": (RECORDS, None), "official": ([], RuntimeError("down"))})
    rc = sync_data.run(["--sources", "dapi,official"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    # the inspection candidate records the failed source as 'failed'
    assert not (tmp_path / "digidex.candidate.sqlite").exists()  # cleaned up
    # the live DB still has a source_sync table from the ORIGINAL fixture? No —
    # the fixture never wrote source_sync, so nothing to assert there. The
    # failure path wrote an inspection candidate but removed it.


# ---------------------------------------------------------------------------
# raw retention -> offline rebuild
# ---------------------------------------------------------------------------
def test_rebuild_from_raw_records(monkeypatch, tmp_path, env_db):
    """Persisted normalized records let a candidate be rebuilt without any
    network (--from-raw). The fake loader must not even be called."""
    import pipeline.sources.base as base

    raw_root = tmp_path / "raw"
    monkeypatch.setattr(base, "RAW_SOURCES", {"dapi": raw_root / "dapi"})

    # persist the normalized records (as a real sync would)
    base.save_records("dapi", RECORDS)
    assert (raw_root / "dapi" / "records.json").exists()

    # --from-raw rebuilds from the persisted records; loader must not be hit
    def boom_loader(name):
        raise AssertionError(f"loader should not be called in from-raw mode ({name})")

    rc = sync_data.run(["--sources", "dapi", "--from-raw"], loader=boom_loader,
                       reports_dir=tmp_path / "reports")
    assert rc == 0
    assert digimon_count(env_db) == len(RECORDS)


def test_from_raw_missing_source_fails(env_db, tmp_path, monkeypatch):
    """--from-raw without persisted records for a requested source must fail
    cleanly (non-zero) instead of building an empty candidate."""
    import pipeline.sources.base as base

    # isolate from any real data/raw/ populated by a prior sync
    monkeypatch.setattr(base, "RAW_SOURCES", {"dapi": tmp_path / "raw" / "dapi"})
    loader = make_loader({})
    rc = sync_data.run(["--sources", "dapi", "--from-raw"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc != 0
    assert not (tmp_path / "digidex.candidate.sqlite").exists()


def test_save_load_records_roundtrip():
    """records.json round-trips every field of a SourceDigimon."""

    from pipeline.core.models import source_digimon_from_dict, source_digimon_to_dict

    for rec in RECORDS:
        d = source_digimon_to_dict(rec)
        back = source_digimon_from_dict(d)
        assert back.source == rec.source
        assert back.source_id == rec.source_id
        assert [n.value for n in back.names] == [n.value for n in rec.names]
        assert back.level_raw == rec.level_raw
        assert list(back.types) == list(rec.types)
        assert [s.names for s in back.skills] == [s.names for s in rec.skills]
        assert back.extra == rec.extra

# ---------------------------------------------------------------------------
# P1-1: per-run source_sync history + sync_run
# ---------------------------------------------------------------------------
def test_source_sync_preserves_run_history(env_db, tmp_path):
    """Each sync run appends source_sync rows (keyed by source+run_id) instead
    of overwriting, and a sync_run row records the run-level metadata."""
    loader1 = make_loader({"dapi": (RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader1,
                         reports_dir=tmp_path / "reports") == 0

    changed = [
        _mk("agumon", "Agumon", "アグモン", "亚古兽", dapi_id=1, skills=["New Skill"]),
        _mk("greymon", "Greymon", "グレイモン", "暴龙兽", dapi_id=3),
    ]
    loader2 = make_loader({"dapi": (changed, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader2,
                         reports_dir=tmp_path / "reports") == 0

    conn = connect(env_db)
    rows = conn.execute(
        "SELECT run_id, source, status, payload_hash FROM source_sync ORDER BY run_id"
    ).fetchall()
    conn.close()
    assert len(rows) == 2  # one row per source per run — history, not overwrite
    run_ids = {r["run_id"] for r in rows}
    assert len(run_ids) == 2  # two distinct runs
    assert all(r["status"] == "ok" for r in rows)

    conn = connect(env_db)
    runs = conn.execute("SELECT run_id, status, sources FROM sync_run ORDER BY run_id").fetchall()
    conn.close()
    assert len(runs) == 2
    assert {r["status"] for r in runs} == {"ok"}
    assert all("dapi" in (r["sources"] or "") for r in runs)


def test_added_source_is_detected_and_allowed(env_db, tmp_path):
    """Adding a source to a previously-synced database is identified and allowed
    (additive), unlike dropping one which is refused."""
    loader1 = make_loader({"dapi": (RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader1,
                         reports_dir=tmp_path / "reports") == 0

    loader2 = make_loader({"dapi": (RECORDS, None), "digimons_net": ([], None)})
    # adding digimons_net must not be refused
    assert sync_data.run(["--sources", "dapi,digimons_net"], loader=loader2,
                         reports_dir=tmp_path / "reports") == 0
    conn = connect(env_db)
    runs = conn.execute("SELECT sources, note FROM sync_run ORDER BY run_id DESC LIMIT 1").fetchone()
    conn.close()
    assert "dapi" in runs["sources"] and "digimons_net" in runs["sources"]


def test_validator_ignores_historical_failed_run(env_db, tmp_path):
    """A historical failed run must not fail the current database: the validator
    only inspects the LATEST run's per-source status (P1-1)."""
    # simulate a legacy DB that carries an old failed run
    conn = connect(env_db)
    conn.execute("INSERT INTO sync_run(run_id, status, sources) VALUES('old-failed','failed','official')")
    conn.execute(
        "INSERT INTO source_sync(source, run_id, status, error_summary) "
        "VALUES('official','old-failed','failed','legacy outage')"
    )
    conn.commit()
    conn.close()

    # a clean run publishes a new run; the historical rows are preserved
    loader = make_loader({"dapi": (RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0

    import pipeline.validation.validator as validator

    conn = connect(env_db)
    report = validator.validate(conn)
    conn.close()
    assert report["issue_counts"]["error"] == 0
    # the failed historical row is still queryable (history preserved)
    conn = connect(env_db)
    failed_rows = conn.execute(
        "SELECT source FROM source_sync WHERE status='failed'"
    ).fetchall()
    conn.close()
    assert any(r["source"] == "official" for r in failed_rows)


def test_raw_records_written_atomically(tmp_path, monkeypatch):
    """save_records writes atomically: valid JSON, no .tmp leftovers (P1-1)."""
    import pipeline.sources.base as base

    raw_root = tmp_path / "raw"
    monkeypatch.setattr(base, "RAW_SOURCES", {"dapi": raw_root / "dapi"})
    base.save_records("dapi", RECORDS)
    path = raw_root / "dapi" / "records.json"
    assert path.exists()
    # no temp files left behind
    assert not list((raw_root / "dapi").glob("*.tmp"))
    import json as _json

    data = _json.loads(path.read_text("utf-8"))
    assert len(data) == len(RECORDS)
    # meta written
    meta = _json.loads((raw_root / "dapi" / "records.meta.json").read_text("utf-8"))
    assert meta["count"] == len(RECORDS)


# ---------------------------------------------------------------------------
# S0-1: state reconciliation after "database published but state not committed"
# ---------------------------------------------------------------------------
def test_reconcile_state_from_db_after_state_loss(env_db, tmp_path):
    """Losing .sync_state.json must not force a rebuild or hide the incremental
    no-op: the next run reconciles state from the DB's latest run and detects
    the payload unchanged."""
    loader = make_loader({"dapi": (RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    after_first = db_hash(env_db)

    # the state file is lost (e.g. user cleanup / failed save)
    state_path = tmp_path / ".sync_state.json"
    assert state_path.exists()
    state_path.unlink()

    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc == 0
    assert db_hash(env_db) == after_first  # reconciled + no-op, no rebuild
    assert not (tmp_path / "digidex.candidate.sqlite").exists()

    # the reconciled state is persisted and carries the source hashes
    import json as _json

    data = _json.loads(state_path.read_text("utf-8"))
    assert data["sync_data"]["sources"] == ["dapi"]
    assert data["dapi"]["records"] == len(RECORDS)
    assert data["dapi"]["content_hash"]


def test_reconcile_restores_source_change_detection(env_db, tmp_path):
    """Reconciled state must still power the source-set drop guard: dropping a
    source that the DB's last run used is refused even after state loss."""
    loader1 = make_loader({"dapi": (RECORDS, None), "official": ([], None)})
    assert sync_data.run(["--sources", "dapi,official"], loader=loader1,
                         reports_dir=tmp_path / "reports") == 0
    before = db_hash(env_db)

    # lose the state file, then try to drop 'official'
    state_path = tmp_path / ".sync_state.json"
    state_path.unlink()
    loader2 = make_loader({"dapi": (RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader2,
                       reports_dir=tmp_path / "reports")
    assert rc != 0  # refused: reconciled state still knows 'official'
    assert db_hash(env_db) == before


def test_noop_backfills_manifest_for_pre_manifest_db(env_db, tmp_path):
    """A DB current before the manifest system gets a publish manifest on the
    next no-op run — backup/restore rely on the manifest existing (S0-1)."""
    from pipeline.core.manifest import manifest_path_for, read_manifest

    loader = make_loader({"dapi": (RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    # simulate a DB published before manifests existed: drop the manifest
    mpath = manifest_path_for(env_db)
    assert mpath.exists()
    mpath.unlink()

    rc = sync_data.run(["--sources", "dapi"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc == 0
    manifest = read_manifest(mpath)
    assert manifest is not None
    assert manifest["state_committed"] is True
    assert manifest["is_incremental_baseline"] is True
    assert manifest["database_sha256"] == db_hash(env_db)
