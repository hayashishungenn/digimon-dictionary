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
    """The restored DB satisfies the same API checks as the live one, and the
    runtime records (state/manifest/reports) land BESIDE the target — never the
    global data/ dir (review finding: default paths must not clobber the live
    dataset's runtime files)."""
    backup = _backup(live_db, tmp_path)
    restored = tmp_path / "api" / "digidex.sqlite"
    restore_backup(backup, db_path=restored)
    # runtime records were restored next to the target, not into data/
    assert (tmp_path / "api" / ".sync_state.json").exists()
    assert (tmp_path / "api" / ".publish_manifest.json").exists()
    assert (tmp_path / "api" / "reports" / "data-quality.json").exists()

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
    with pytest.raises(BackupError, match="integrity|hash|SHA-256|size"):
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


def test_restore_brings_back_images(live_db, tmp_path):
    """P2-06: a backup made with --with-images must restore the image cache
    beside the target DB, with matching file hashes."""
    images = tmp_path / "images"
    images.mkdir()
    (images / "a.png").write_bytes(b"img-a")
    (images / "thumbs").mkdir()
    (images / "thumbs" / "a.png").write_bytes(b"thumb-a")

    import pipeline.core.backup as backup_mod

    orig = backup_mod.IMAGES_DIR
    try:
        backup_mod.IMAGES_DIR = images
        out = tmp_path / "backups" / "with_img"
        create_backup(db_path=live_db, out_dir=out, with_images=True,
                      state_path=tmp_path / ".sync_state.json",
                      manifest_path=tmp_path / ".publish_manifest.json",
                      reports_dir=tmp_path / "reports")
    finally:
        backup_mod.IMAGES_DIR = orig
    assert (out / "images" / "a.png").read_bytes() == b"img-a"
    meta = json.loads((out / "backup.json").read_text("utf-8"))
    assert meta["includes_images"] is True

    restored = tmp_path / "restored" / "digidex.sqlite"
    restore_backup(out, db_path=restored)
    img_target = tmp_path / "restored" / "images"
    assert (img_target / "a.png").read_bytes() == b"img-a"
    assert (img_target / "thumbs" / "a.png").read_bytes() == b"thumb-a"


def test_restore_rolls_back_on_mid_commit_failure(live_db, tmp_path, monkeypatch):
    """P1-05: if a commit-phase os.replace fails part-way, every live file —
    including the already-replaced database — must return to the original
    snapshot (DB + state/manifest/reports stay from one version)."""
    import os as _os
    import shutil

    backup = _backup(live_db, tmp_path)
    live_dir = tmp_path / "live"
    live_dir.mkdir()
    db_target = live_dir / "digidex.sqlite"
    shutil.copy2(live_db, db_target)  # the current live DB
    state_target = live_dir / ".sync_state.json"
    state_target.write_text("ORIGINAL-STATE", "utf-8")

    real_replace = _os.replace
    failed_once = {"n": 0}

    def failing_replace(src, dst):
        # fail only the FIRST replace onto the state target (the commit); the
        # rollback restore of the original also targets it and must succeed
        if str(dst) == str(state_target) and failed_once["n"] == 0:
            failed_once["n"] += 1
            raise OSError("simulated mid-commit failure")
        return real_replace(src, dst)

    monkeypatch.setattr(_os, "replace", failing_replace)

    with pytest.raises(OSError):
        restore_backup(backup, db_path=db_target, state_path=state_target)

    # the DB was committed first, then rolled back to the original bytes
    assert db_hash(db_target) == db_hash(live_db)
    # the state file that was never committed stays untouched
    assert state_target.read_text("utf-8") == "ORIGINAL-STATE"
    # no rollback/temp files left behind
    assert not list(live_dir.glob("*.rollback"))
    assert not list(live_dir.glob("*.restore.tmp"))


# ---------------------------------------------------------------------------
# P1-1: conflicts / manual review are backed up, restored, and hash-validated
# ---------------------------------------------------------------------------
def test_conflicts_and_manual_review_backed_up_and_restored(live_db, tmp_path):
    conflicts = tmp_path / "data_conflicts.json"
    conflicts.write_text(json.dumps({"conflicts": 1}), "utf-8")
    manual_review = tmp_path / "manual_review_queue.json"
    manual_review.write_text(json.dumps({"open": 3}), "utf-8")
    out = tmp_path / "backups" / "bcr"
    create_backup(
        db_path=live_db, out_dir=out,
        state_path=tmp_path / ".sync_state.json",
        manifest_path=tmp_path / ".publish_manifest.json",
        reports_dir=tmp_path / "reports",
        conflicts_path=conflicts, manual_review_path=manual_review,
    )
    # both are copied into the backup with per-file sha256 recorded
    assert (out / "data_conflicts.json").read_text("utf-8") == json.dumps({"conflicts": 1})
    assert (out / "manual_review_queue.json").read_text("utf-8") == json.dumps({"open": 3})
    meta = json.loads((out / "backup.json").read_text("utf-8"))
    assert meta["files"]["conflicts"]["path"] == "data_conflicts.json"
    assert meta["files"]["conflicts"]["sha256"]
    assert meta["files"]["manual_review"]["sha256"]
    assert "conflicts" not in meta["missing_files"]

    validate_backup(out)  # passes

    # restore to a fresh target -> both land BESIDE the restored DB
    restored = tmp_path / "restored" / "digidex.sqlite"
    restore_backup(out, db_path=restored)
    assert (tmp_path / "restored" / "data_conflicts.json").read_text("utf-8") == json.dumps({"conflicts": 1})
    assert (tmp_path / "restored" / "manual_review_queue.json").read_text("utf-8") == json.dumps({"open": 3})


@pytest.mark.parametrize("role", ["sync_state", "report_json", "conflicts", "manual_review"])
def test_validate_detects_tampered_non_db_file(live_db, tmp_path, role):
    """P1-1: a modified state/report/conflict/review file in a backup is caught
    by the per-file SHA-256 check (size is kept identical so hash is the gate)."""
    conflicts = tmp_path / "data_conflicts.json"
    conflicts.write_text("{}", "utf-8")
    manual_review = tmp_path / "manual_review_queue.json"
    manual_review.write_text("{}", "utf-8")
    out = tmp_path / "backups" / "b"
    create_backup(
        db_path=live_db, out_dir=out,
        state_path=tmp_path / ".sync_state.json",
        manifest_path=tmp_path / ".publish_manifest.json",
        reports_dir=tmp_path / "reports",
        conflicts_path=conflicts, manual_review_path=manual_review,
    )
    p = out / CORE_FILES[role]
    original = p.read_bytes()
    p.write_bytes(original[:-1] + bytes([original[-1] ^ 0xFF]))  # same size, different byte
    with pytest.raises(BackupError, match="SHA-256"):
        validate_backup(out)


def test_custom_out_keep_does_not_prune_default_root(tmp_path, live_db):
    """P1-1: --keep prunes only the backup root that owns --out, never the
    default data/backups root."""
    default_root = tmp_path / "default-backups"
    custom_root = tmp_path / "custom-backups"
    for i in range(2):
        create_backup(
            db_path=live_db, out_dir=default_root / f"backup-{i}",
            state_path=tmp_path / ".sync_state.json",
            manifest_path=tmp_path / ".publish_manifest.json",
            reports_dir=tmp_path / "reports",
        )
        create_backup(
            db_path=live_db, out_dir=custom_root / f"backup-{i}",
            state_path=tmp_path / ".sync_state.json",
            manifest_path=tmp_path / ".publish_manifest.json",
            reports_dir=tmp_path / "reports",
        )
    # custom-root backup with keep=1 -> prunes only the custom root
    create_backup(
        db_path=live_db, out_dir=custom_root / "backup-x",
        state_path=tmp_path / ".sync_state.json",
        manifest_path=tmp_path / ".publish_manifest.json",
        reports_dir=tmp_path / "reports",
        keep=1,
    )
    assert list_backups(custom_root) == [custom_root / "backup-x"]
    assert len(list_backups(default_root)) == 2  # default root untouched


def test_restore_with_images_to_different_root_serves_relative_paths(live_db, tmp_path):
    """P1-1 + P0-1: a with-images backup restored to a DIFFERENT root still
    serves images — the restored DB's relative local_path resolves against the
    restored cache root."""
    import struct

    from pipeline.core.schema import connect as db_connect

    images = tmp_path / "images"
    images.mkdir()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 32, 32) + b"\x08\x06\x00\x00\x00"
    (images / "agumon.png").write_bytes(png)
    conn = db_connect(live_db)
    did = conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()[0]
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path,
           download_status, content_type) VALUES(?, 'main_image', 'https://x/a.png',
           'agumon.png', 'downloaded', 'image/png')""",
        [did],
    )
    conn.commit()
    conn.close()

    out = tmp_path / "backups" / "bimg"
    create_backup(
        db_path=live_db, out_dir=out, with_images=True, images_dir=images,
        state_path=tmp_path / ".sync_state.json",
        manifest_path=tmp_path / ".publish_manifest.json",
        reports_dir=tmp_path / "reports",
    )
    restored = tmp_path / "restored" / "digidex.sqlite"
    restore_backup(out, db_path=restored)
    assert (tmp_path / "restored" / "images" / "agumon.png").read_bytes() == png

    os.environ["DIGIDEX_DB"] = str(restored)
    os.environ["DIGIDEX_IMAGES_DIR"] = str(tmp_path / "restored" / "images")
    try:
        from fastapi.testclient import TestClient

        from apps.api.main import app

        with TestClient(app) as c:
            r = c.get("/api/images/agumon/main_image")
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("image/")
            assert r.content == png
    finally:
        os.environ.pop("DIGIDEX_DB", None)
        os.environ.pop("DIGIDEX_IMAGES_DIR", None)


def test_restore_rolls_back_including_conflicts_manual_review(live_db, tmp_path, monkeypatch):
    """P1-1: when a commit-phase replace fails on the conflicts target, the
    already-committed database AND the untouched conflict/review files all stay
    at the original snapshot."""
    import os as _os
    import shutil

    conflicts = tmp_path / "data_conflicts.json"
    conflicts.write_text("ORIG-CONFLICTS", "utf-8")
    manual_review = tmp_path / "manual_review_queue.json"
    manual_review.write_text("ORIG-REVIEW", "utf-8")
    out = tmp_path / "backups" / "bcr"
    create_backup(
        db_path=live_db, out_dir=out,
        state_path=tmp_path / ".sync_state.json",
        manifest_path=tmp_path / ".publish_manifest.json",
        reports_dir=tmp_path / "reports",
        conflicts_path=conflicts, manual_review_path=manual_review,
    )

    live_dir = tmp_path / "live"
    live_dir.mkdir()
    db_target = live_dir / "digidex.sqlite"
    shutil.copy2(live_db, db_target)
    conflicts_target = live_dir / "data_conflicts.json"
    conflicts_target.write_text("ORIG-CONFLICTS", "utf-8")
    review_target = live_dir / "manual_review_queue.json"
    review_target.write_text("ORIG-REVIEW", "utf-8")

    real_replace = _os.replace
    failed_once = {"n": 0}

    def failing_replace(src, dst):
        # fail only the FIRST replace onto the conflicts target (the commit);
        # the rollback restore of its original must succeed
        if str(dst) == str(conflicts_target) and failed_once["n"] == 0:
            failed_once["n"] += 1
            raise OSError("simulated mid-commit failure on conflicts")
        return real_replace(src, dst)

    monkeypatch.setattr(_os, "replace", failing_replace)

    with pytest.raises(OSError):
        restore_backup(out, db_path=db_target)

    # the database was committed then rolled back to the original bytes
    assert db_hash(db_target) == db_hash(live_db)
    # the conflict/review files were never committed
    assert conflicts_target.read_text("utf-8") == "ORIG-CONFLICTS"
    assert review_target.read_text("utf-8") == "ORIG-REVIEW"
    assert not list(live_dir.glob("*.rollback"))
