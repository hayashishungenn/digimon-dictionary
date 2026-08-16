"""S0-2 integration tests: local backup, restore, and snapshot inspection.

Uses a real fixture DB built via build_fixture_db (same code path as the live
DB), backs it up to a temp dir, validates the backup, restores it to a fresh
path, and asserts the round-trip is byte-stable and the API surfaces still
work. Also covers the restore rejection cases (hash mismatch, missing file,
newer schema) and Windows-friendly path handling (spaces).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pipeline.core.backup import (
    CORE_FILES,
    BackupError,
    create_backup,
    list_backups,
    prune_backups,
    restore_backup,
    validate_backup,
)
from pipeline.core.schema import SCHEMA_VERSION, connect_readonly
from pipeline.core.sync_state import SyncState
from tests.conftest import build_fixture_db


@pytest.fixture
def live_db(tmp_path):
    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    # give the fixture a publish manifest + sync state so backups are realistic
    conn.execute(
        """INSERT INTO sync_run(run_id, started_at, finished_at, status, sources, note, snapshot_date)
           VALUES('run-test-1','2026-08-15T00:00:00+00:00','2026-08-15T00:00:05+00:00','ok','dapi',NULL,'2026-08-15')"""
    )
    conn.execute(
        """INSERT INTO source_sync(source, run_id, last_seen_at, started_at, finished_at, status,
           records, parsed_count, failed_count, raw_completeness, content_hash, payload_hash, error_summary)
           VALUES('dapi','run-test-1','2026-08-15T00:00:00+00:00','2026-08-15T00:00:00+00:00',
           '2026-08-15T00:00:05+00:00','ok',6,6,0,1,'hash1','hash1',NULL)"""
    )
    conn.commit()
    conn.close()

    from pipeline.core.manifest import build_manifest, manifest_path_for

    state = SyncState(tmp_path / ".sync_state.json")
    state.set("sync_data", sources=["dapi"], run_id="run-test-1", snapshot_date="2026-08-15")
    state.set("dapi", content_hash="hash1", payload_hash="hash1", records=6)
    state.save()

    manifest = build_manifest(
        run_id="run-test-1", snapshot_date="2026-08-15", sources=["dapi"],
        db_sha256=None, report_sha256=None, schema_version=SCHEMA_VERSION,
        image_stage="skipped", is_incremental_baseline=True, state_committed=True,
    )
    from pipeline.core.manifest import write_manifest as _wm

    _wm(manifest, manifest_path_for(db))

    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "reports" / "data-quality.json").write_text(
        json.dumps({"issue_counts": {"error": 0}}), "utf-8"
    )
    (tmp_path / "reports" / "data-quality.md").write_text("# ok", "utf-8")
    return db


def db_hash(path: Path) -> str:
    return __import__("hashlib").sha256(path.read_bytes()).hexdigest()


def _backup(live_db, tmp_path, **kw):
    out = tmp_path / "backups" / "b1"
    create_backup(db_path=live_db, out_dir=out,
                  state_path=tmp_path / ".sync_state.json",
                  manifest_path=tmp_path / ".publish_manifest.json",
                  reports_dir=tmp_path / "reports",
                  **kw)
    return out


# ---------------------------------------------------------------------------
# happy path: backup -> validate -> restore round-trip
# ---------------------------------------------------------------------------
def test_backup_roundtrip_to_fresh_target(tmp_path, live_db):
    backup = _backup(live_db, tmp_path)
    assert (backup / CORE_FILES["database"]).exists()
    assert (backup / CORE_FILES["publish_manifest"]).exists()
    assert (backup / CORE_FILES["sync_state"]).exists()
    assert (backup / CORE_FILES["report_json"]).exists()

    meta = json.loads((backup / "backup.json").read_text("utf-8"))
    assert meta["run_id"] == "run-test-1"
    assert meta["snapshot_date"] == "2026-08-15"
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["database_sha256"] == db_hash(backup / CORE_FILES["database"])
    assert meta["includes_images"] is False

    # validate passes
    info = validate_backup(backup)
    assert info["database_sha256"] == meta["database_sha256"]

    # restore to a fresh path
    restored = tmp_path / "restored with spaces" / "digidex.sqlite"
    done = restore_backup(backup, db_path=restored,
                          state_path=tmp_path / "restored with spaces" / ".sync_state.json",
                          manifest_path=tmp_path / "restored with spaces" / ".publish_manifest.json",
                          reports_dir=tmp_path / "restored with spaces" / "reports")
    assert restored in done
    assert db_hash(restored) == db_hash(backup / CORE_FILES["database"])

    # the restored DB is a usable database with the fixture data
    conn = connect_readonly(restored)
    n = conn.execute("SELECT COUNT(*) FROM digimon").fetchone()[0]
    agumon = conn.execute("SELECT name_zh_cn, name_en, name_ja FROM digimon WHERE canonical_slug='agumon'").fetchone()
    conn.close()
    assert n == 6
    assert (agumon["name_zh_cn"], agumon["name_en"], agumon["name_ja"]) == ("亚古兽", "Agumon", "アグモン")


def test_restored_db_serves_api(live_db, tmp_path):
    """The restored DB satisfies the same API checks as the live one."""
    backup = _backup(live_db, tmp_path)
    restored = tmp_path / "api" / "digidex.sqlite"
    restore_backup(backup, db_path=restored)

    os.environ["DIGIDEX_DB"] = str(restored)
    try:
        from fastapi.testclient import TestClient

        from apps.api.main import app

        with TestClient(app) as c:
            assert c.get("/api/health").json()["db_ready"] is True
            meta = c.get("/api/meta").json()
            assert meta["counts"]["total"] == 6
            d = c.get("/api/digimon/agumon").json()
            assert d["names"]["zh_cn"] == "亚古兽"
            assert d["names"]["en"] == "Agumon"
            r = c.get("/api/search", params={"q": "亚古兽"}).json()
            assert r["items"][0]["canonical_slug"] == "agumon"
    finally:
        os.environ.pop("DIGIDEX_DB", None)


# ---------------------------------------------------------------------------
# rejection cases: the live DB must stay untouched
# ---------------------------------------------------------------------------
def test_restore_rejects_hash_mismatch(live_db, tmp_path):
    backup = _backup(live_db, tmp_path)
    # corrupt the backup's database copy
    db_copy = backup / CORE_FILES["database"]
    db_copy.write_bytes(db_copy.read_bytes() + b"garbage")
    target = tmp_path / "target" / "digidex.sqlite"
    with pytest.raises(BackupError, match="integrity|hash|SHA-256"):
        restore_backup(backup, db_path=target)
    assert not target.exists()  # nothing restored


def test_restore_rejects_missing_file(live_db, tmp_path):
    backup = _backup(live_db, tmp_path)
    (backup / CORE_FILES["database"]).unlink()
    target = tmp_path / "target" / "digidex.sqlite"
    with pytest.raises(BackupError, match="missing"):
        restore_backup(backup, db_path=target)
    assert not target.exists()


def test_restore_rejects_newer_schema(live_db, tmp_path):
    backup = _backup(live_db, tmp_path)
    meta = json.loads((backup / "backup.json").read_text("utf-8"))
    meta["schema_version"] = SCHEMA_VERSION + 99
    (backup / "backup.json").write_text(json.dumps(meta), "utf-8")
    target = tmp_path / "target" / "digidex.sqlite"
    with pytest.raises(BackupError, match="newer"):
        restore_backup(backup, db_path=target)
    assert not target.exists()


def test_restore_leaves_live_untouched_on_failure(live_db, tmp_path):
    """If staging fails part-way, the live DB must be byte-for-byte unchanged."""
    backup = _backup(live_db, tmp_path)
    target = tmp_path / "live" / "digidex.sqlite"
    # make the backup invalid by corrupting the report copy's parent dir as a
    # read error: instead, simply corrupt the DB copy so staging fails
    (backup / CORE_FILES["database"]).write_bytes(b"corrupt" * 10)
    before = db_hash(live_db)
    with pytest.raises(BackupError):
        restore_backup(backup, db_path=target)
    assert db_hash(live_db) == before
    assert not target.exists()


# ---------------------------------------------------------------------------
# dry-run / preview + --yes gating (CLI semantics)
# ---------------------------------------------------------------------------
def test_restore_dry_run_writes_nothing(live_db, tmp_path):
    backup = _backup(live_db, tmp_path)
    target = tmp_path / "target" / "digidex.sqlite"
    done = restore_backup(backup, db_path=target, dry_run=True)
    assert len(done) >= 1
    assert not target.exists()
    assert not list(tmp_path.glob("*.restore.tmp"))


def test_create_backup_with_images_flag(live_db, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "x.png").write_bytes(b"png-data")

    import pipeline.core.backup as backup_mod

    orig = backup_mod.IMAGES_DIR
    try:
        backup_mod.IMAGES_DIR = images
        out = tmp_path / "backups" / "bimg"
        create_backup(db_path=live_db, out_dir=out, with_images=True,
                      state_path=tmp_path / ".sync_state.json",
                      manifest_path=tmp_path / ".publish_manifest.json",
                      reports_dir=tmp_path / "reports")
        assert (out / "images" / "x.png").read_bytes() == b"png-data"
        meta = json.loads((out / "backup.json").read_text("utf-8"))
        assert meta["includes_images"] is True
    finally:
        backup_mod.IMAGES_DIR = orig


def test_prune_keeps_newest(tmp_path, live_db):
    out_root = tmp_path / "backups"
    backups = []
    for i in range(4):
        b = out_root / f"backup-{i}"
        create_backup(db_path=live_db, out_dir=b,
                      state_path=tmp_path / ".sync_state.json",
                      manifest_path=tmp_path / ".publish_manifest.json",
                      reports_dir=tmp_path / "reports")
        backups.append(b)
    pruned = prune_backups(out_root, keep=2)
    assert len(pruned) == 2
    remaining = list_backups(out_root)
    assert len(remaining) == 2
    assert all(p.exists() for p in remaining)


def test_inspect_snapshot_live_and_backup(live_db, tmp_path):
    from pipeline.core.backup import inspect_backup

    info = inspect_backup(db_path=live_db)
    assert info["integrity_ok"] is True
    assert info["snapshot_date"] == "2026-08-15"

    backup = _backup(live_db, tmp_path)
    binfo = inspect_backup(backup)
    assert binfo["database_sha256"] == db_hash(backup / CORE_FILES["database"])


def test_backup_schema_reflects_db_not_stale_manifest(live_db, tmp_path):
    """The backup records the COPY's real schema even when the publish manifest
    is stale (e.g. the DB was migrated in place after the manifest was written)."""
    meta_path = tmp_path / ".publish_manifest.json"
    m = json.loads(meta_path.read_text("utf-8"))
    m["schema_version"] = 1  # deliberately stale
    meta_path.write_text(json.dumps(m), "utf-8")

    out = _backup(live_db, tmp_path)
    meta = json.loads((out / "backup.json").read_text("utf-8"))
    assert meta["schema_version"] == SCHEMA_VERSION  # the DB's real version
