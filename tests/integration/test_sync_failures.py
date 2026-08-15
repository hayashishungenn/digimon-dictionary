"""T1 integration tests: sync fail-safety and atomic publication.

Each test builds a fixture DB at a temp path, runs ``sync_data.run()`` with a
monkeypatched source loader (no network), and asserts the live DB is
byte-for-byte unchanged on every failure — and replaced only on a fully
successful run. Also covers lock/state/temp-file hygiene.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.sync_data as sync_data
from pipeline.core.schema import connect
from pipeline.core.sync_state import SyncState
from tests.conftest import _mk, build_fixture_db


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class FakeAdapter:
    def __init__(self, records, error=None):
        self.records = records
        self.error = error

    def fetch(self, fetcher, force=False):
        if self.error is not None:
            raise self.error
        return self.records


def make_loader(spec):
    """spec: {source: (records, error|None)}; unspecified sources return empty."""
    def loader(name):
        records, error = spec.get(name, ([], None))
        return FakeAdapter(records, error)

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
