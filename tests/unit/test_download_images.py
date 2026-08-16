"""T8 tests: image download fail-safety with a mock fetcher.

Covers HTTP 200/404/429/timeout, content-type policy, truncated files, host
policy, duplicate basenames, atomic writes (no .tmp leftovers), and the
non-zero exit code when any download fails.

P0-1: every stored ``local_path`` is a cache-root-RELATIVE value (never
absolute); reads resolve against the cache root.
"""
from __future__ import annotations

import sqlite3
import struct
from pathlib import Path

import scripts.download_images as dl
from pipeline.core.request import FetchResult
from pipeline.core.schema import connect, create_schema


def make_png(w: int = 32, h: int = 32) -> bytes:
    """A byte sequence that passes the PNG header/dimension check."""
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"


class FakeFetcher:
    """url -> FetchResult or exception; close() is a no-op."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.closed = False

    def get(self, url: str, **kwargs):
        resp = self.responses[url]
        if isinstance(resp, Exception):
            raise resp
        return resp

    def close(self):
        self.closed = True


def _setup_db(path: Path, rows: list[tuple[int, str]]) -> sqlite3.Connection:
    """Create a DB with digimon_image rows: [(digimon_id, url), ...]."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    seen: set[int] = set()
    for did, url in rows:
        if did not in seen:
            conn.execute("INSERT INTO digimon(id, canonical_slug) VALUES(?, ?)", [did, f"d{did}"])
            seen.add(did)
        conn.execute(
            "INSERT INTO digimon_image(digimon_id, image_type, remote_url, download_status) VALUES(?,?,?,?)",
            [did, "main_image", url, "pending"],
        )
    conn.commit()
    conn.close()
    return connect(path)


def _image_rows(path: Path):
    conn = connect(path)
    try:
        return conn.execute(
            "SELECT id, digimon_id, remote_url, download_status, local_path, sha256 FROM digimon_image ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _cache_root(tmp_path) -> Path:
    return tmp_path / "images"


OK = FetchResult(url="https://digi-api.com/a.png", status_code=200,
                 content=make_png(), content_type="image/png")


def test_ok_image_downloaded(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/a.png")])
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/a.png": OK}),
                                            cache_root=cache_root)
    assert (done, refused, failed) == (1, 0, 0)
    row = _image_rows(db)[0]
    assert row["download_status"] == "downloaded"
    lp = row["local_path"]
    assert lp and not lp.startswith(("/", "\\")) and ":" not in lp[:2]  # relative, no drive
    assert (cache_root / lp).exists()
    assert row["sha256"] == dl.sha256_of(make_png())
    # no .tmp leftovers
    assert not list(cache_root.glob("*.tmp"))


def test_404_marks_failed(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/404.png")])
    not_found = FetchResult(url="https://digi-api.com/404.png", status_code=404,
                            content=b"", content_type="text/html")
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/404.png": not_found}),
                                            cache_root=cache_root)
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"
    assert not cache_root.exists() or not list(cache_root.glob("*.tmp"))


def test_429_marks_failed(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/429.png")])
    busy = FetchResult(url="https://digi-api.com/429.png", status_code=429,
                       content=b"", content_type="image/png")
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/429.png": busy}),
                                            cache_root=cache_root)
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"


def test_timeout_marks_failed(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/slow.png")])
    done, refused, failed = dl.download_all(
        db, fetcher=FakeFetcher({"https://digi-api.com/slow.png": TimeoutError("timed out")}),
        cache_root=cache_root,
    )
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"


def test_wrong_content_type_marks_failed(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/html.png")])
    html = FetchResult(url="https://digi-api.com/html.png", status_code=200,
                       content=make_png(), content_type="text/html")
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/html.png": html}),
                                            cache_root=cache_root)
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"


def test_truncated_image_marks_failed(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/trunc.png")])
    trunc = FetchResult(url="https://digi-api.com/trunc.png", status_code=200,
                        content=b"\x89PNG\r\n\x1a\n", content_type="image/png")  # too short
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/trunc.png": trunc}),
                                            cache_root=cache_root)
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"
    # nothing half-written on disk
    assert not cache_root.exists() or not list(cache_root.rglob("*.tmp"))


def test_forbidden_host_refused(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    # digimon.net official images must never be downloaded (docs/sources.md)
    _setup_db(db, [(1, "https://digimon.net/cimages/digimon/agumon.jpg")])
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({}), cache_root=cache_root)
    assert done == 0 and refused == 1
    assert _image_rows(db)[0]["download_status"] == "failed"


def test_duplicate_basename_does_not_collide(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _setup_db(db, [
        (1, "https://digi-api.com/a.png"),
        (1, "https://digi-api.com/sub/a.png"),  # same basename, different URL
    ])
    fetcher = FakeFetcher({
        "https://digi-api.com/a.png": FetchResult("https://digi-api.com/a.png", 200, make_png(32, 32), "image/png"),
        "https://digi-api.com/sub/a.png": FetchResult("https://digi-api.com/sub/a.png", 200, make_png(64, 64), "image/png"),
    })
    done, refused, failed = dl.download_all(db, fetcher=fetcher, cache_root=cache_root)
    assert (done, refused, failed) == (2, 0, 0)
    rows = _image_rows(db)
    paths = {r["local_path"] for r in rows}
    assert len(paths) == 2  # distinct files despite identical basenames
    assert all((cache_root / p).exists() for p in paths)


def test_rerun_skips_complete_and_retries_failed(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _setup_db(db, [
        (1, "https://digi-api.com/ok.png"),
        (2, "https://digi-api.com/bad.png"),
    ])
    bad = FetchResult("https://digi-api.com/bad.png", 500, b"", "text/html")
    ok = FetchResult("https://digi-api.com/ok.png", 200, make_png(), "image/png")
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/ok.png": ok, "https://digi-api.com/bad.png": bad}), cache_root=cache_root)
    assert (done, refused, failed) == (1, 0, 1)
    # ok.png is now 'downloaded' and skipped on the next run; bad.png is retried
    fixed = FetchResult("https://digi-api.com/bad.png", 200, make_png(), "image/png")
    done2, refused2, failed2 = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/bad.png": fixed}), cache_root=cache_root)
    assert (done2, refused2, failed2) == (1, 0, 0)


def test_main_exit_code(tmp_path, monkeypatch):
    monkeypatch.delenv("DIGIDEX_DB", raising=False)  # main() honors DIGIDEX_DB
    monkeypatch.setattr(dl, "DB_PATH", tmp_path / "db.sqlite")
    _setup_db(tmp_path / "db.sqlite", [(1, "https://digimon.net/x.jpg")])  # forbidden -> failure
    assert dl.main([]) != 0


# ---------------------------------------------------------------------------
# P0-3: metadata backfill + local thumbnail derivation
# ---------------------------------------------------------------------------
def real_png(w: int = 200, h: int = 150) -> bytes:
    """A genuinely decodable PNG (Pillow can open it) for thumbnail tests."""
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _downloaded_main_db(path: Path, digimon_id: int, png: bytes, fname: str) -> None:
    """A main-image row whose local file exists and whose local_path is
    CACHE-ROOT-RELATIVE (P0-1 contract)."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    img_dir = path.parent / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / fname).write_bytes(png)
    conn.execute("INSERT INTO digimon(id, canonical_slug) VALUES(?,?)", [digimon_id, f"d{digimon_id}"])
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status)
           VALUES(?, 'main_image', 'https://digi-api.com/x.png', ?, 'downloaded')""",
        [digimon_id, fname.replace("\\", "/")],
    )
    conn.commit()
    conn.close()


def test_thumbnail_derivation(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    _downloaded_main_db(db, 1, real_png(200, 150), "main.png")

    derived, failed = dl.ensure_thumbnails(connect(db), cache_root=cache_root)
    assert derived == 1 and failed == 0

    conn = connect(db)
    row = conn.execute("SELECT * FROM digimon_image WHERE digimon_id=1 AND image_type='thumbnail'").fetchone()
    assert row["download_status"] == "downloaded"
    assert row["width"] <= 128 and row["height"] <= 128
    assert row["content_type"] == "image/png"
    assert row["sha256"]
    assert row["local_path"] == "thumbs/digi_00001.png"  # relative contract
    assert (cache_root / row["local_path"]).exists()
    # digimon.thumbnail points at the same relative cache path
    d = conn.execute("SELECT thumbnail FROM digimon WHERE id=1").fetchone()
    assert d["thumbnail"] == row["local_path"]
    conn.close()


def test_thumbnail_failure_recorded(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    # corrupt source file that Pillow cannot decode
    _downloaded_main_db(db, 1, b"this is not an image at all", "main.png")

    derived, failed = dl.ensure_thumbnails(connect(db), cache_root=cache_root)
    assert derived == 0 and failed == 1
    conn = connect(db)
    row = conn.execute("SELECT * FROM digimon_image WHERE digimon_id=1 AND image_type='thumbnail'").fetchone()
    assert row["download_status"] == "failed"
    assert row["failure_reason"]
    conn.close()


def test_backfill_metadata(tmp_path):
    cache_root = _cache_root(tmp_path)
    db = tmp_path / "db.sqlite"
    png = real_png(64, 48)
    _downloaded_main_db(db, 1, png, "main.png")
    n = dl.backfill_metadata(connect(db), cache_root=cache_root)
    assert n == 1
    conn = connect(db)
    row = conn.execute("SELECT * FROM digimon_image WHERE digimon_id=1").fetchone()
    assert row["width"] == 64 and row["height"] == 48
    assert row["sha256"] == dl.sha256_of(png)
    assert row["content_type"] == "image/png"
    assert row["fetched_at"]
    conn.close()