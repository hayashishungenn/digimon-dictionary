"""T1 integration tests: sync fail-safety and atomic publication.

Each test builds a fixture DB at a temp path, runs ``sync_data.run()`` with a
monkeypatched source loader (no network), and asserts the live DB is
byte-for-byte unchanged on every failure — and replaced only on a fully
successful run. Also covers lock/state/temp-file hygiene.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from pathlib import Path

import pytest

import scripts.sync_data as sync_data
from pipeline.core.manifest import manifest_path_for, read_manifest
from pipeline.core.schema import SCHEMA_VERSION, connect
from pipeline.core.sync_state import SyncState
from tests.conftest import _mk, build_fixture_db


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class FakeAdapter:
    def __init__(self, records, error=None, fetch_report=None):
        self.records = records
        self.error = error
        self.fetch_report = fetch_report  # P1-02: completeness report

    def fetch(self, fetcher, force=False):
        if self.error is not None:
            raise self.error
        return self.records


def make_loader(spec):
    """spec: {source: (records, error|None)} or {source: (records, error|None, fetch_report|None)};
    unspecified sources return empty (no fetch_report -> treated complete)."""
    def loader(name):
        entry = spec.get(name, ([], None, None))
        if len(entry) == 2:
            records, error = entry
            report = None
        else:
            records, error, report = entry
        return FakeAdapter(records, error, report)

    return loader


def db_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digimon_count(path: Path) -> int:
    conn = connect(path)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM digimon").fetchone()[0])
    finally:
        conn.close()


def candidate_sidecars(tmp: Path) -> list[str]:
    return sorted(
        p.name for p in tmp.glob("digidex.candidate.sqlite*") if p.name.endswith(("-wal", "-shm", "-journal"))
    )


SUCCESS_RECORDS = [
    _mk("agumon", "Agumon", "アグモン", "亚古兽", dapi_id=1),
    _mk("greymon", "Greymon", "グレイモン", "暴龙兽", dapi_id=3),
]


@pytest.fixture
def live_db(tmp_path):
    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    conn.close()
    return db


@pytest.fixture
def env_db(monkeypatch, live_db):
    monkeypatch.setenv("DIGIDEX_DB", str(live_db))
    return live_db


# ---------------------------------------------------------------------------
# failure keeps the live DB unchanged
# ---------------------------------------------------------------------------
def test_source_fails_before_fetch_keeps_db(env_db, tmp_path):
    """Source raises before returning anything: live DB unchanged, exit non-zero."""
    before = db_hash(env_db)
    loader = make_loader({"dapi": ([], RuntimeError("dapi down"))})
    rc = sync_data.run(["--sources", "dapi,official"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    assert db_hash(env_db) == before
    # no temp/candidate files leak
    assert not (tmp_path / "digidex.candidate.sqlite").exists()
    assert candidate_sidecars(tmp_path) == []


def test_source_fails_midway_keeps_db(env_db, tmp_path):
    """dapi succeeds, official fails during fetch: live DB unchanged."""
    before = db_hash(env_db)
    loader = make_loader({
        "dapi": (SUCCESS_RECORDS, None),
        "official": ([], RuntimeError("official down")),
    })
    rc = sync_data.run(["--sources", "dapi,official"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    assert db_hash(env_db) == before
    assert not (tmp_path / "digidex.candidate.sqlite").exists()
    assert candidate_sidecars(tmp_path) == []


def test_empty_result_after_populated_source_fails(env_db, tmp_path):
    """A source that previously had records must not silently go empty."""
    state_path = tmp_path / ".sync_state.json"
    state_path.write_text(json.dumps({"dapi": {"records": 1488}}), "utf-8")
    before = db_hash(env_db)
    loader = make_loader({"dapi": ([], None)})  # returns empty
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    assert db_hash(env_db) == before


def test_validation_error_blocks_publish(env_db, tmp_path, monkeypatch):
    """Candidate that fails validation must not be published."""
    import pipeline.validation.validator as validator

    before = db_hash(env_db)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})

    real_validate = validator.validate

    def fake_validate(conn):
        report = real_validate(conn)
        report["issues"].append({"level": "error", "check": "injected", "message": "boom"})
        report["issue_counts"]["error"] += 1
        return report

    monkeypatch.setattr(validator, "validate", fake_validate)
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    assert db_hash(env_db) == before
    assert not (tmp_path / "digidex.candidate.sqlite").exists()


# ---------------------------------------------------------------------------
# --partial-ok does not publish by default
# ---------------------------------------------------------------------------
def test_partial_ok_does_not_publish_by_default(env_db, tmp_path):
    """Dropping sources with --partial-ok builds a candidate but keeps the
    live DB untouched; publishing a partial requires --publish-partial."""
    state_path = tmp_path / ".sync_state.json"
    state_path.write_text(
        json.dumps({"sync_data": {"sources": ["dapi", "official", "digimons_net"]}}), "utf-8"
    )
    before = db_hash(env_db)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi", "--partial-ok"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc == 0
    assert db_hash(env_db) == before  # NOT overwritten
    # the partial candidate is kept for inspection, but WAL/SHM sidecars are gone
    assert (tmp_path / "digidex.candidate.sqlite").exists()
    assert candidate_sidecars(tmp_path) == []


def test_dropping_sources_without_partial_ok_refused(env_db, tmp_path):
    state_path = tmp_path / ".sync_state.json"
    state_path.write_text(
        json.dumps({"sync_data": {"sources": ["dapi", "official", "digimons_net"]}}), "utf-8"
    )
    before = db_hash(env_db)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    assert db_hash(env_db) == before


def test_publish_partial_overwrites_and_marks_partial(env_db, tmp_path):
    state_path = tmp_path / ".sync_state.json"
    state_path.write_text(
        json.dumps({"sync_data": {"sources": ["dapi", "official", "digimons_net"]}}), "utf-8"
    )
    before = db_hash(env_db)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi", "--partial-ok", "--publish-partial"],
                       loader=loader, reports_dir=tmp_path / "reports")
    assert rc == 0
    assert db_hash(env_db) != before  # explicitly published
    conn = connect(env_db)
    snap = conn.execute("SELECT notes FROM snapshot ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert snap is not None and "partial=true" in (snap["notes"] or "")


# ---------------------------------------------------------------------------
# success publishes atomically; no temp files leak
# ---------------------------------------------------------------------------
def test_successful_sync_publishes(env_db, tmp_path):
    before = db_hash(env_db)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc == 0
    after = db_hash(env_db)
    assert after != before  # replaced
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)
    # candidate + sidecars removed after a successful publish
    assert not (tmp_path / "digidex.candidate.sqlite").exists()
    assert candidate_sidecars(tmp_path) == []
    assert not (tmp_path / "digidex.candidate.sqlite").exists()
    assert not (tmp_path / ".sync_state.json.tmp").exists()


def test_success_updates_sync_state(env_db, tmp_path):
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    state_path = tmp_path / ".sync_state.json"
    data = json.loads(state_path.read_text("utf-8"))
    assert data["dapi"]["records"] == len(SUCCESS_RECORDS)
    assert data["sync_data"]["sources"] == ["dapi"]


# ---------------------------------------------------------------------------
# lock serialization
# ---------------------------------------------------------------------------
def test_lock_rejects_concurrent_sync(env_db, tmp_path):
    from pipeline.core.lock import SyncLock, SyncLockError

    lock_path = tmp_path / ".sync.lock"
    with SyncLock(lock_path):
        with pytest.raises(SyncLockError):
            with SyncLock(lock_path):
                pass  # second acquisition must fail
    # released — re-acquirable
    with SyncLock(lock_path):
        pass


# ---------------------------------------------------------------------------
# state file recovery
# ---------------------------------------------------------------------------
def test_sync_state_recovers_from_partial_write(tmp_path):
    state_path = tmp_path / ".sync_state.json"
    state_path.write_text('{"dapi": {"content_hash": "abc"', "utf-8")  # truncated JSON
    state = SyncState(state_path)
    assert state.get("dapi").get("content_hash") is None  # fell back to empty
    # save() works and replaces atomically; no .tmp leftover
    state.set("dapi", content_hash="xyz")
    state.save()
    assert json.loads(state_path.read_text("utf-8"))["dapi"]["content_hash"] == "xyz"
    assert not (tmp_path / ".sync_state.json.tmp").exists()


def test_sync_state_recovers_from_valid_but_wrong_type(tmp_path):
    """P2-02: valid JSON that is the wrong shape (e.g. `[]` / `null`) must not
    crash the sync — treat it as corrupt state and start empty."""
    for payload in ("[]", "null", '"just a string"', "42"):
        state_path = tmp_path / "state.json"
        state_path.write_text(payload, "utf-8")
        state = SyncState(state_path)
        assert state.get("dapi").get("content_hash") is None
        assert state.get("sync_data").get("sources") is None
        state.set("dapi", content_hash="ok")
        state.save()
        assert json.loads(state_path.read_text("utf-8"))["dapi"]["content_hash"] == "ok"


# ---------------------------------------------------------------------------
# --skip-validation must not bypass the publish gate (P0-2)
# ---------------------------------------------------------------------------
def test_skip_validation_never_publishes(env_db, tmp_path):
    """--skip-validation is a diagnosis/dev flag: the candidate is built for
    inspection but must NOT be published — an unvalidated database must not be
    marked publishable."""
    before = db_hash(env_db)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi", "--skip-validation"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc != 0  # signals "not ready to publish"
    assert db_hash(env_db) == before  # live DB untouched
    # candidate kept for inspection, sidecars cleaned
    assert (tmp_path / "digidex.candidate.sqlite").exists()
    assert candidate_sidecars(tmp_path) == []


# ---------------------------------------------------------------------------
# P1-1: image-stage failure + checkpoint + history checks
# ---------------------------------------------------------------------------
def test_image_stage_failure_returns_nonzero(env_db, tmp_path, monkeypatch):
    """--images runs after a successful publish; an image-stage failure makes
    the run exit non-zero so the incomplete cache is never a silent success."""
    import scripts.download_images as dl

    monkeypatch.setattr(dl, "download_all", lambda db_path: (0, 0, 3))  # 3 failures
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi", "--images"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc != 0
    # the DB itself was published (canonical data is valid)
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)


def test_image_stage_clean_returns_zero(env_db, tmp_path, monkeypatch):
    import scripts.download_images as dl

    monkeypatch.setattr(dl, "download_all", lambda db_path: (2, 0, 0))
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi", "--images"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc == 0
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)


def test_successful_run_writes_sync_run_row(env_db, tmp_path):
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    conn = connect(env_db)
    run = conn.execute("SELECT run_id, status, sources FROM sync_run ORDER BY run_id DESC LIMIT 1").fetchone()
    conn.close()
    assert run is not None
    assert run["status"] == "ok"
    assert run["sources"] == "dapi"


# ---------------------------------------------------------------------------
# S0-1: sync_run started_at + publish manifest
# ---------------------------------------------------------------------------
def test_sync_run_records_started_at_and_snapshot_date(env_db, tmp_path):
    """sync_run.started_at must be the run's real start (never NULL), and the
    snapshot_date must match the snapshot row for the same run (S0-1)."""
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    conn = connect(env_db)
    run = conn.execute(
        "SELECT started_at, finished_at, snapshot_date FROM sync_run ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    snap = conn.execute("SELECT snapshot_date FROM snapshot ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert run["started_at"] is not None
    assert run["finished_at"] is not None
    assert run["snapshot_date"] == snap["snapshot_date"]


def test_publish_manifest_written_on_success(env_db, tmp_path):
    """A clean publish writes a manifest describing run_id, snapshot date, the
    DB + report SHA-256, schema version, image stage, and baseline eligibility."""
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0

    manifest = read_manifest(manifest_path_for(env_db))
    assert manifest is not None
    assert manifest["state_committed"] is True
    assert manifest["is_incremental_baseline"] is True
    assert manifest["image_stage"] == "skipped"
    assert manifest["schema_version"] == SCHEMA_VERSION
    assert manifest["database_sha256"] == db_hash(env_db)
    assert manifest["sources"] == ["dapi"]

    conn = connect(env_db)
    run = conn.execute("SELECT run_id, snapshot_date FROM sync_run ORDER BY rowid DESC LIMIT 1").fetchone()
    conn.close()
    assert manifest["run_id"] == run["run_id"]
    assert manifest["snapshot_date"] == run["snapshot_date"]
    # report SHA-256 points at the report written for this run
    assert manifest["report_sha256"] == hashlib.sha256(
        (tmp_path / "reports" / "data-quality.json").read_bytes()
    ).hexdigest()


def test_partial_publish_is_not_a_baseline(env_db, tmp_path):
    """A partial (source-subset) publish must not claim to be an incremental
    baseline, even though its state is committed."""
    state_path = tmp_path / ".sync_state.json"
    state_path.write_text(
        json.dumps({"sync_data": {"sources": ["dapi", "official", "digimons_net"]}}), "utf-8"
    )
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    assert sync_data.run(["--sources", "dapi", "--partial-ok", "--publish-partial"],
                         loader=loader, reports_dir=tmp_path / "reports") == 0
    manifest = read_manifest(manifest_path_for(env_db))
    assert manifest is not None
    assert manifest["state_committed"] is True
    assert manifest["is_incremental_baseline"] is False
    assert manifest["notes"] == "partial"


# ---------------------------------------------------------------------------
# S0-1: failure injection — state save / manifest write / checkpoint /
#       candidate corruption / image stage / publish-window recovery
# ---------------------------------------------------------------------------
def test_state_save_failure_is_detected_and_recovers(env_db, tmp_path, monkeypatch):
    """state.save() failing AFTER a successful publish is the "database
    published but state not committed" split: non-zero exit, DB live, manifest
    records the split — and the next clean run reconciles state from the DB and
    safely no-ops instead of rebuilding."""
    from pipeline.core.sync_state import SyncState

    real_save = SyncState.save
    failing = {"on": True}

    def flaky_save(self):
        if failing["on"]:
            raise OSError("simulated state-save disk failure")
        return real_save(self)

    monkeypatch.setattr(SyncState, "save", flaky_save)

    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    # canonical DB was published (valid data) but the run must not be silent
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)
    manifest = read_manifest(manifest_path_for(env_db))
    assert manifest is not None
    assert manifest["state_committed"] is False

    # recovery: a clean rerun reconciles state from the DB and detects the
    # payload unchanged -> incremental no-op, DB byte-identical.
    failing["on"] = False
    after_fail = db_hash(env_db)
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    assert db_hash(env_db) == after_fail
    state_data = json.loads((tmp_path / ".sync_state.json").read_text("utf-8"))
    assert state_data["sync_data"]["sources"] == ["dapi"]
    assert state_data["dapi"]["records"] == len(SUCCESS_RECORDS)


def test_manifest_write_failure_is_detected(env_db, tmp_path, monkeypatch):
    """A publish whose manifest cannot be written must not silently succeed."""
    before = db_hash(env_db)

    def boom_manifest(manifest, path):
        raise OSError("simulated manifest disk failure")

    monkeypatch.setattr(sync_data, "write_manifest", boom_manifest)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    # the DB is live (canonical publish happened) but the run is non-zero and
    # the split is recoverable (state file has no source set yet).
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)
    assert before != db_hash(env_db)
    state_path = tmp_path / ".sync_state.json"
    data = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
    assert not data.get("sync_data", {}).get("sources")


def test_checkpoint_failure_keeps_db(env_db, tmp_path, monkeypatch):
    """A failed WAL checkpoint must never publish the candidate."""
    before = db_hash(env_db)

    def failing_checkpoint(conn):
        # mimic the real contract: checkpoint_and_close closes the connection
        # on failure so the candidate file is not locked on Windows
        try:
            conn.close()
        except sqlite3.Error:
            pass
        return False

    monkeypatch.setattr(sync_data, "checkpoint_and_close", failing_checkpoint)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    assert db_hash(env_db) == before
    assert not (tmp_path / "digidex.candidate.sqlite").exists()


def test_candidate_corruption_keeps_db(env_db, tmp_path, monkeypatch):
    """A candidate that fails integrity_check must never replace the live DB."""
    before = db_hash(env_db)
    monkeypatch.setattr(sync_data, "verify_integrity", lambda candidate: False)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    assert db_hash(env_db) == before
    # corrupt candidate is discarded, nothing leaks
    assert not (tmp_path / "digidex.candidate.sqlite").exists()
    assert candidate_sidecars(tmp_path) == []


def test_incomplete_fetch_is_refused(env_db, tmp_path):
    """P1-02: an adapter reporting raw_completeness=False (e.g. pagination hit
    its defensive cap) must abort the sync — the live DB stays unchanged."""
    before = db_hash(env_db)
    incomplete = {"raw_completeness": False, "expected_count": 1488, "parsed_count": 300}
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None, incomplete)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    assert db_hash(env_db) == before
    assert not (tmp_path / "digidex.candidate.sqlite").exists()


def test_first_sync_all_empty_refuses_empty_publish(tmp_path, monkeypatch):
    """P1-02: on a first sync, if every source comes back empty the candidate
    would be a blank encyclopedia — the run must refuse to publish."""
    from pipeline.core.schema import connect, create_schema

    db = tmp_path / "fresh.sqlite"
    conn = connect(db)
    create_schema(conn)
    conn.close()
    monkeypatch.setenv("DIGIDEX_DB", str(db))

    loader = make_loader({})  # every source returns empty
    rc = sync_data.run(["--sources", "dapi,official"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc != 0
    assert digimon_count(db) == 0  # nothing published
    assert not (tmp_path / "fresh.candidate.sqlite").exists()


def test_failed_validation_does_not_overwrite_reports(env_db, tmp_path, monkeypatch):
    """P2-01: a candidate that fails validation must NOT promote its report —
    data/reports/ keeps describing the live DB, not a rejected candidate."""
    import pipeline.validation.validator as validator

    real_validate = validator.validate

    def fake_validate(conn):
        report = real_validate(conn)
        report["issues"].append({"level": "error", "check": "injected", "message": "boom"})
        report["issue_counts"]["error"] += 1
        return report

    monkeypatch.setattr(validator, "validate", fake_validate)
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "data-quality.json").write_text("ORIGINAL", "utf-8")
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=reports)
    assert rc != 0
    assert (reports / "data-quality.json").read_text("utf-8") == "ORIGINAL"  # untouched
    assert not (reports / ".staging").exists()  # staged report discarded


def test_success_promotes_report_stamped_with_db_sha(env_db, tmp_path):
    """P2-01: after a successful publish the staged report is promoted and
    stamped with the published DB's sha-256 (report describes the live DB)."""
    import json as _json

    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    report = _json.loads((tmp_path / "reports" / "data-quality.json").read_text("utf-8"))
    assert report.get("db_sha256") == db_hash(env_db)
    assert (tmp_path / "reports" / "data-quality.md").exists()
    assert not (tmp_path / "reports" / ".staging").exists()


def test_image_stage_failure_distinguished_in_manifest(env_db, tmp_path, monkeypatch):
    """--images with a failing image stage publishes the canonical DB but the
    manifest records image_stage=failed and the sync_run note is updated — the
    two stages are never conflated (S0-1)."""
    import scripts.download_images as dl

    monkeypatch.setattr(dl, "download_all", lambda db_path: (0, 0, 3))  # 3 failures
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi", "--images"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc != 0
    # canonical DB published; image cache incomplete
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)
    manifest = read_manifest(manifest_path_for(env_db))
    assert manifest is not None
    assert manifest["image_stage"] == "failed"
    assert manifest["state_committed"] is True  # DB + state committed
    conn = connect(env_db)
    note = conn.execute("SELECT note FROM sync_run ORDER BY rowid DESC LIMIT 1").fetchone()["note"]
    conn.close()
    assert "image stage failed" in (note or "")


def test_publish_before_state_interruption_is_recoverable(env_db, tmp_path, monkeypatch):
    """Simulate the exact crash window (publish done, state not saved) and prove
    the next run recognizes it via the manifest and reconciles from the DB."""
    from pipeline.core.sync_state import SyncState

    real_save = SyncState.save
    first_run = {"done": False}

    def kill_after_publish(self):
        # crash after the DB replace but before state is durable
        if not first_run["done"]:
            first_run["done"] = True
            raise OSError("process killed mid-publish")
        return real_save(self)

    monkeypatch.setattr(SyncState, "save", kill_after_publish)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi"], loader=loader, reports_dir=tmp_path / "reports")
    assert rc != 0
    # split is recognizable
    manifest = read_manifest(manifest_path_for(env_db))
    assert manifest["state_committed"] is False
    assert manifest["run_id"]  # a run_id exists for this publish

    # recovery run reconciles and reports the payload unchanged
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)
    assert read_manifest(manifest_path_for(env_db))["state_committed"] is True


def test_reconcile_does_not_mark_committed_when_state_save_fails(env_db, tmp_path, monkeypatch):
    """P1-04: during recovery, if state.save() fails the manifest must stay
    state_committed=false — a later run must still see the split and retry."""
    from pipeline.core.sync_state import SyncState

    real_save = SyncState.save
    failing = {"on": True}

    def flaky_save(self):
        if failing["on"]:
            raise OSError("disk down")
        return real_save(self)

    monkeypatch.setattr(SyncState, "save", flaky_save)

    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    # 1) publish succeeds but the state save fails -> split
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") != 0
    assert read_manifest(manifest_path_for(env_db))["state_committed"] is False

    # 2) next run reconciles state from the DB but ITS save also fails -> the
    #    manifest must NOT be flipped to committed
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    assert read_manifest(manifest_path_for(env_db))["state_committed"] is False

    # 3) once the save works, the reconcile persists state and heals the manifest
    failing["on"] = False
    assert sync_data.run(["--sources", "dapi"], loader=loader,
                         reports_dir=tmp_path / "reports") == 0
    assert read_manifest(manifest_path_for(env_db))["state_committed"] is True
    state_data = json.loads((tmp_path / ".sync_state.json").read_text("utf-8"))
    assert state_data["sync_data"]["sources"] == ["dapi"]


# ---------------------------------------------------------------------------
# third-round review: P1-1 (--images leaves db_sha256 stale), P1-2 (report
# promotion not atomic + misleading error), P2 (partial run is not a baseline)
# ---------------------------------------------------------------------------
def test_images_recompute_db_and_report_hashes(env_db, tmp_path, monkeypatch):
    """P1-1: the image stage modifies the live DB AFTER publish, so the manifest
    database_sha256 and the report db_sha256 must be recomputed to match the
    actual post-image file — never left pointing at the pre-image DB."""
    import scripts.download_images as dl

    def fake_download_all(db_path):
        # simulate a real download that writes rows into the live DB
        conn = connect(db_path)
        conn.execute(
            "INSERT INTO digimon_image(digimon_id, image_type, download_status) "
            "VALUES (1, 'main', 'downloaded')"
        )
        conn.commit()
        conn.close()
        return (1, 0, 0)

    def fake_ensure_thumbnails(conn, force=False):
        conn.execute("UPDATE digimon SET thumbnail='derived' WHERE id=1")
        conn.commit()
        return (1, 0)

    monkeypatch.setattr(dl, "download_all", fake_download_all)
    monkeypatch.setattr(dl, "ensure_thumbnails", fake_ensure_thumbnails)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    rc = sync_data.run(["--sources", "dapi", "--images"], loader=loader,
                       reports_dir=tmp_path / "reports")
    assert rc == 0
    manifest = read_manifest(manifest_path_for(env_db))
    assert manifest["image_stage"] == "ok"
    # manifest and report both describe the ACTUAL post-image DB file
    assert manifest["database_sha256"] == db_hash(env_db)
    report = json.loads((tmp_path / "reports" / "data-quality.json").read_text("utf-8"))
    assert report["db_sha256"] == db_hash(env_db)


def test_report_md_promotion_failure_is_nonfatal_and_preserved(env_db, tmp_path, monkeypatch, caplog):
    """P1-2: when the Markdown report cannot be promoted after the DB is replaced,
    the run still completes (the JSON is the authoritative report), manifest+state
    are committed, and the staged MD is retained for the next real rebuild."""
    md_target = tmp_path / "reports" / "data-quality.md"
    real_replace = os.replace
    fail_md = {"on": True}

    def flaky_replace(src, dst):
        if fail_md["on"] and os.path.normpath(str(dst)) == os.path.normpath(str(md_target)):
            raise OSError("simulated lock on data-quality.md")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    with caplog.at_level(logging.WARNING):
        rc = sync_data.run(["--sources", "dapi"], loader=loader,
                           reports_dir=tmp_path / "reports")
    assert rc == 0
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)
    # manifest + state committed despite the cosmetic MD failure
    manifest = read_manifest(manifest_path_for(env_db))
    assert manifest["state_committed"] is True
    assert manifest["report_sha256"] == hashlib.sha256(
        (tmp_path / "reports" / "data-quality.json").read_bytes()
    ).hexdigest()
    # the staged (new) MD is retained for the next real rebuild
    assert (tmp_path / "reports" / ".staging" / "data-quality.md").exists()
    assert "Markdown report" in caplog.text


def test_report_json_promotion_failure_is_honest(env_db, tmp_path, monkeypatch, caplog):
    """P1-2: when the authoritative JSON report cannot be promoted after the DB is
    replaced, the run fails with an HONEST error (never 'official database
    unchanged'), keeps the staged report, and the next run can reconcile."""
    json_target = tmp_path / "reports" / "data-quality.json"
    real_replace = os.replace

    def flaky_replace(src, dst):
        if os.path.normpath(str(dst)) == os.path.normpath(str(json_target)):
            raise OSError("simulated lock on data-quality.json")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    loader = make_loader({"dapi": (SUCCESS_RECORDS, None)})
    with caplog.at_level(logging.ERROR):
        rc = sync_data.run(["--sources", "dapi"], loader=loader,
                           reports_dir=tmp_path / "reports")
    assert rc != 0
    # the DB WAS published — never claim otherwise
    assert digimon_count(env_db) == len(SUCCESS_RECORDS)
    assert "official database unchanged" not in caplog.text
    assert "DATABASE PUBLISHED" in caplog.text
    # staged JSON retained for recovery
    assert (tmp_path / "reports" / ".staging" / "data-quality.json").exists()
