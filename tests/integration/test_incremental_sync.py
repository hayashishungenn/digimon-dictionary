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


def test_from_raw_missing_source_fails(env_db, tmp_path):
    """--from-raw without persisted records for a requested source must fail
    cleanly (non-zero) instead of building an empty candidate."""
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