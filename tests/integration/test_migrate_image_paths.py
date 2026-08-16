"""P0-1 tests: scripts/migrate_image_paths.py.

The migration rewrites legacy absolute ``local_path`` values to the
cache-root-relative contract (hashing filenames), never marks a missing file
downloaded, preserves ``remote_url``, auto-backs-up first, backfills thumbnail
metadata, and is idempotent.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import scripts.migrate_image_paths as migrate
from pipeline.core.images import is_bad_stored_path, main_rel
from pipeline.core.schema import connect, create_schema

LEGACY_ROOT = r"C:\Users\old\Github\Digimon_Dictionary\data\images"


def _real_png(w: int = 200, h: int = 150) -> bytes:
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _make_db(path: Path, cache_root: Path, main_rows: list[dict],
             main_files: dict[str, bytes] | None = None,
             thumb_files: dict[str, bytes] | None = None) -> None:
    """Build a schema-v8 DB with digimon + digimon_image rows and cache files."""
    assert main_rows, "need at least one row"
    conn = _sqlite(path)
    create_schema(conn)
    for row in main_rows:
        did = row["digimon_id"]
        conn.execute("INSERT OR IGNORE INTO digimon(id, canonical_slug) VALUES(?, ?)",
                     [did, f"d{did}"])
        conn.execute(
            """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status)
               VALUES(?, 'main_image', ?, ?, ?)""",
            [did, row.get("remote_url"), row.get("local_path"), row.get("download_status", "downloaded")],
        )
    conn.commit()
    conn.close()

    for name, data in (main_files or {}).items():
        (cache_root / name).parent.mkdir(parents=True, exist_ok=True)
        (cache_root / name).write_bytes(data)
    for name, data in (thumb_files or {}).items():
        (cache_root / name).parent.mkdir(parents=True, exist_ok=True)
        (cache_root / name).write_bytes(data)


def _image_rows(path: Path):
    conn = connect(path)
    try:
        return conn.execute(
            """SELECT id, digimon_id, image_type, remote_url, local_path, download_status, failure_reason
               FROM digimon_image ORDER BY id"""
        ).fetchall()
    finally:
        conn.close()


def _thumb_row(path: Path, digimon_id: int):
    conn = connect(path)
    try:
        return conn.execute(
            "SELECT * FROM digimon_image WHERE digimon_id=? AND image_type='thumbnail'",
            [digimon_id],
        ).fetchone()
    finally:
        conn.close()


def _digimon_thumbnail(path: Path, digimon_id: int):
    conn = connect(path)
    try:
        return conn.execute("SELECT thumbnail FROM digimon WHERE id=?", [digimon_id]).fetchone()[0]
    finally:
        conn.close()


def _forbidden_count(path: Path) -> int:
    bad = 0
    for r in _image_rows(path):
        if r["local_path"] and is_bad_stored_path(r["local_path"]):
            bad += 1
    conn = connect(path)
    try:
        for (t,) in conn.execute(
            "SELECT thumbnail FROM digimon WHERE thumbnail IS NOT NULL AND TRIM(thumbnail) != ''"
        ).fetchall():
            if is_bad_stored_path(t):
                bad += 1
    finally:
        conn.close()
    return bad


def _migrate(tmp_path, db: Path, cache_root: Path, dry_run: bool = False):
    backup = tmp_path / "backups"
    args = ["--db", str(db), "--backup-dir", str(backup)]
    if dry_run:
        args.append("--dry-run")
    return migrate.main(args)


# ---------------------------------------------------------------------------
def test_legacy_absolute_migrates_relative_and_renames(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    url = "https://digi-api.com/images/digimon/w/Agumon.png"
    _make_db(
        db, cache_root,
        [{"digimon_id": 1, "remote_url": url,
          "local_path": rf"{LEGACY_ROOT}\digi_00001_Agumon.png"}],
        main_files={"digi_00001_Agumon.png": b"png"},
    )
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    row = _image_rows(db)[0]
    target = main_rel(1, url)
    assert row["local_path"] == target  # relative + hash-based
    assert row["download_status"] == "downloaded"
    assert not (cache_root / "digi_00001_Agumon.png").exists()  # renamed
    assert (cache_root / target).exists()
    assert _forbidden_count(db) == 0


def test_missing_file_becomes_failed_keeps_remote_url(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    url = "https://digi-api.com/x/gone.png"
    _make_db(db, cache_root,
             [{"digimon_id": 1, "remote_url": url,
               "local_path": rf"{LEGACY_ROOT}\digi_00001_Gone.png"}])
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    row = _image_rows(db)[0]
    assert row["local_path"] is None
    assert row["download_status"] == "failed"
    assert "missing" in (row["failure_reason"] or "")
    assert row["remote_url"] == url  # never touched


def test_already_relative_kept(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    url = "https://digi-api.com/x/b.png"
    target = main_rel(2, url)
    _make_db(db, cache_root,
             [{"digimon_id": 2, "remote_url": url, "local_path": target}],
             main_files={target: b"png"})
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    row = _image_rows(db)[0]
    assert row["local_path"] == target
    assert row["download_status"] == "downloaded"


def test_relative_missing_becomes_failed(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    _make_db(db, cache_root,
             [{"digimon_id": 3, "remote_url": "https://x/c.png",
               "local_path": "digi_00003_missing.png"}])
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    row = _image_rows(db)[0]
    assert row["local_path"] is None and row["download_status"] == "failed"


def test_pending_with_existing_file_becomes_downloaded(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    url = "https://digi-api.com/x/d.png"
    _make_db(db, cache_root,
             [{"digimon_id": 4, "remote_url": url,
               "local_path": rf"{LEGACY_ROOT}\digi_00004_D.png",
               "download_status": "pending"}],
             main_files={"digi_00004_D.png": b"png"})
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    row = _image_rows(db)[0]
    assert row["download_status"] == "downloaded"
    assert row["local_path"] == main_rel(4, url)


def test_thumbnail_metadata_backfilled(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    url = "https://digi-api.com/x/Agumon.png"
    png = _real_png()
    _make_db(
        db, cache_root,
        [{"digimon_id": 1, "remote_url": url,
          "local_path": rf"{LEGACY_ROOT}\digi_00001_Agumon.png"}],
        main_files={"digi_00001_Agumon.png": png},
        thumb_files={"thumbs/digi_00001.png": _real_png(64, 48)},
    )
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    thumb = _thumb_row(db, 1)
    assert thumb is not None
    assert thumb["local_path"] == "thumbs/digi_00001.png"
    assert thumb["download_status"] == "downloaded"
    assert thumb["width"] == 64 and thumb["height"] == 48
    assert _digimon_thumbnail(db, 1) == "thumbs/digi_00001.png"
    assert _forbidden_count(db) == 0


def test_mixed_db_no_forbidden_paths_remain(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    _make_db(
        db, cache_root,
        [
            {"digimon_id": 1, "remote_url": "https://x/a.png",
             "local_path": rf"{LEGACY_ROOT}\digi_00001_A.png"},
            {"digimon_id": 2, "remote_url": "https://x/b.png",
             "local_path": "digi_00002_missing.png"},  # relative, file absent
            {"digimon_id": 3, "remote_url": r"C:\Windows\evil.png",
             "local_path": r"C:\Windows\evil.png"},  # unlocatable
        ],
        main_files={"digi_00001_A.png": b"png"},
    )
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    assert _forbidden_count(db) == 0
    statuses = {r["digimon_id"]: r["download_status"]
                for r in _image_rows(db) if r["image_type"] == "main_image"}
    assert statuses[1] == "downloaded"
    assert statuses[2] == "failed"
    assert statuses[3] == "failed"


def test_idempotent(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    url = "https://digi-api.com/x/a.png"
    _make_db(db, cache_root,
             [{"digimon_id": 1, "remote_url": url,
               "local_path": rf"{LEGACY_ROOT}\digi_00001_A.png"}],
             main_files={"digi_00001_A.png": b"png"},
             thumb_files={"thumbs/digi_00001.png": _real_png(64, 48)})
    assert _migrate(tmp_path, db, cache_root) == 0
    first = [tuple(r) for r in _image_rows(db)]
    files_first = sorted(p.name for p in cache_root.iterdir() if p.is_file())
    assert _migrate(tmp_path, db, cache_root) == 0
    assert [tuple(r) for r in _image_rows(db)] == first
    files_second = sorted(p.name for p in cache_root.iterdir() if p.is_file())
    assert files_first == files_second


def test_integrity_failure_exits_1(tmp_path, monkeypatch):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    _make_db(db, cache_root,
             [{"digimon_id": 1, "remote_url": "https://x/a.png",
               "local_path": rf"{LEGACY_ROOT}\digi_00001_A.png"}],
             main_files={"digi_00001_A.png": b"png"})
    monkeypatch.setattr(migrate, "verify_integrity", lambda db: False)
    assert _migrate(tmp_path, db, cache_root) == 1
    assert _image_rows(db)[0]["local_path"] is not None  # untouched


def test_backup_failure_exits_1_and_changes_nothing(tmp_path, monkeypatch):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    _make_db(db, cache_root,
             [{"digimon_id": 1, "remote_url": "https://x/a.png",
               "local_path": rf"{LEGACY_ROOT}\digi_00001_A.png"}],
             main_files={"digi_00001_A.png": b"png"})
    before = _image_rows(db)[0]["local_path"]

    def boom(**kwargs):
        raise RuntimeError("no backup dir")

    monkeypatch.setattr(migrate, "create_backup", boom)
    assert _migrate(tmp_path, db, cache_root) == 1
    assert _image_rows(db)[0]["local_path"] == before  # unchanged


def test_cache_root_absent_all_absolute_become_failed(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"  # no files on disk
    _make_db(db, cache_root,
             [{"digimon_id": 1, "remote_url": "https://x/a.png",
               "local_path": rf"{LEGACY_ROOT}\digi_00001_A.png"},
              {"digimon_id": 2, "remote_url": "https://x/b.png",
               "local_path": rf"{LEGACY_ROOT}\digi_00002_B.png"}])
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    rows = _image_rows(db)
    assert all(r["download_status"] == "failed" for r in rows)
    assert all(r["local_path"] is None for r in rows)


def test_dry_run_changes_nothing(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    _make_db(db, cache_root,
             [{"digimon_id": 1, "remote_url": "https://x/a.png",
               "local_path": rf"{LEGACY_ROOT}\digi_00001_A.png"}],
             main_files={"digi_00001_A.png": b"png"})
    before = _image_rows(db)[0]["local_path"]
    rc = _migrate(tmp_path, db, cache_root, dry_run=True)
    assert rc == 0
    assert _image_rows(db)[0]["local_path"] == before
    assert (cache_root / "digi_00001_A.png").exists()  # no rename
    assert not (tmp_path / "backups").exists()  # no backup written


def test_unlocatable_absolute_becomes_failed(tmp_path):
    db = tmp_path / "digidex.sqlite"
    cache_root = tmp_path / "images"
    _make_db(db, cache_root,
             [{"digimon_id": 1, "remote_url": "https://x/a.png",
               "local_path": r"C:\Windows\system32\evil.png"}])
    rc = _migrate(tmp_path, db, cache_root)
    assert rc == 0
    row = _image_rows(db)[0]
    assert row["local_path"] is None and row["download_status"] == "failed"
    assert "unlocatable" in (row["failure_reason"] or "")