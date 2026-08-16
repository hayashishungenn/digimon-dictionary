"""P0-1 API tests: image serving under the relative-path contract.

Covers: relative local_path served 200; path traversal rejected (never serves
the escaped file); no absolute filesystem path leaks in API responses; and the
"copy DB + image cache to a fresh directory" acceptance (the migration's output
is portable — DIGIDEX_DB + DIGIDEX_IMAGES_DIR point at the copies and images
still serve).
"""
from __future__ import annotations

import shutil
import sqlite3
import struct
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import scripts.migrate_image_paths as migrate
from pipeline.core.schema import connect, create_schema

LEGACY = r"C:\Users\old\Github\Digimon_Dictionary\data\images"


def _png(w: int = 32, h: int = 32) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"


def _client():
    from apps.api.main import app

    return TestClient(app)


def _agumon_id(path: Path) -> int:
    conn = connect(path)
    try:
        return conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """A fixture DB + cache root with RELATIVE main/thumbnail rows."""
    from tests.conftest import build_fixture_db

    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    did = _agumon_id(db)
    cache = tmp_path / "images"
    (cache / "thumbs").mkdir(parents=True)
    (cache / "agumon.png").write_bytes(_png(32, 32))
    (cache / "thumbs" / f"digi_{did:05d}.png").write_bytes(_png(16, 16))
    conn.execute("DELETE FROM digimon_image WHERE digimon_id=?", [did])
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status, content_type)
           VALUES(?, 'main_image', 'https://x/a.png', 'agumon.png', 'downloaded', 'image/png')""",
        [did],
    )
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status, content_type)
           VALUES(?, 'thumbnail', 'https://x/t.png', ?, 'downloaded', 'image/png')""",
        [did, f"thumbs/digi_{did:05d}.png"],
    )
    conn.execute("UPDATE digimon SET thumbnail=? WHERE id=?", [f"thumbs/digi_{did:05d}.png", did])
    conn.commit()
    conn.close()
    monkeypatch.setenv("DIGIDEX_DB", str(db))
    monkeypatch.setenv("DIGIDEX_IMAGES_DIR", str(cache))
    return db, cache


def test_relative_path_served(env):
    _db, _cache = env
    with _client() as c:
        r = c.get("/api/images/agumon/main_image")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")
        assert r.content == _png(32, 32)
        t = c.get("/api/images/agumon/thumbnail")
        assert t.status_code == 200
        assert t.headers["content-type"].startswith("image/")


def test_traversal_never_serves(env):
    db, _cache = env
    # plant a real file at the escape target, then point local_path at it
    secret = Path(db).parent.parent / "secret.png"
    secret.write_bytes(_png(64, 64))
    did = _agumon_id(db)
    conn = connect(db)
    conn.execute(
        "UPDATE digimon_image SET local_path='..\\\\..\\\\secret.png' "
        "WHERE digimon_id=? AND image_type='main_image'",
        [did],
    )
    conn.commit()
    conn.close()
    with _client() as c:
        r = c.get("/api/images/agumon/main_image")
        assert r.status_code != 200  # never serves the escaped file
        assert r.status_code in (302, 307, 404)
        assert r.content != _png(64, 64)


def test_no_absolute_path_leaks(env):
    db, _cache = env
    did = _agumon_id(db)
    conn = connect(db)
    conn.execute(
        "UPDATE digimon_image SET local_path=? WHERE digimon_id=? AND image_type='main_image'",
        [rf"{LEGACY}\digi_00001_Agumon.png", did],
    )
    conn.commit()
    conn.close()
    with _client() as c:
        body = c.get("/api/digimon/agumon").json()
        raw = c.get("/api/digimon/agumon").text
    assert "C:\\" not in raw and "C:/" not in raw
    for img in body["images"]:
        lp = img["local_path"]
        assert lp is None or not lp.startswith(("/", "\\"))


def test_copy_to_fresh_dir_serves(tmp_path, monkeypatch):
    """Migration output is portable: DB + image cache copied to a fresh dir,
    DIGIDEX_DB + DIGIDEX_IMAGES_DIR point at the copies, images still serve."""
    legacy_db = tmp_path / "legacy.sqlite"
    legacy_cache = tmp_path / "images"
    (legacy_cache / "thumbs").mkdir(parents=True)
    (legacy_cache / "digi_00001_Agumon.png").write_bytes(_png(32, 32))
    (legacy_cache / "thumbs" / "digi_00001.png").write_bytes(_png(16, 16))
    conn = sqlite3.connect(legacy_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    conn.execute("INSERT INTO digimon(id, canonical_slug) VALUES(1, 'agumon')")
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status)
           VALUES(1, 'main_image', 'https://x/a.png', ?, 'downloaded')""",
        [rf"{LEGACY}\digi_00001_Agumon.png"],
    )
    conn.commit()
    conn.close()

    rc = migrate.main(["--db", str(legacy_db), "--backup-dir", str(tmp_path / "bk")])
    assert rc == 0

    fresh = tmp_path / "fresh"
    fresh.mkdir()
    shutil.copy2(legacy_db, fresh / "digidex.sqlite")
    shutil.copytree(legacy_cache, fresh / "images")

    monkeypatch.setenv("DIGIDEX_DB", str(fresh / "digidex.sqlite"))
    monkeypatch.setenv("DIGIDEX_IMAGES_DIR", str(fresh / "images"))
    with _client() as c:
        r = c.get("/api/images/agumon/main_image")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")
        t = c.get("/api/images/agumon/thumbnail")
        assert t.status_code == 200
        assert t.headers["content-type"].startswith("image/")