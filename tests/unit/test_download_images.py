"""T8 tests: image download fail-safety with a mock fetcher.

Covers HTTP 200/404/429/timeout, content-type policy, truncated files, host
policy, duplicate basenames, atomic writes (no .tmp leftovers), and the
non-zero exit code when any download fails.
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


OK = FetchResult(url="https://digi-api.com/a.png", status_code=200,
                 content=make_png(), content_type="image/png")


def test_ok_image_downloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/a.png")])
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/a.png": OK}))
    assert (done, refused, failed) == (1, 0, 0)
    row = _image_rows(db)[0]
    assert row["download_status"] == "downloaded"
    assert row["local_path"] and Path(row["local_path"]).exists()
    assert row["sha256"] == dl.sha256_of(make_png())
    # no .tmp leftovers
    assert not list((tmp_path / "images").glob("*.tmp"))


def test_404_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/404.png")])
    not_found = FetchResult(url="https://digi-api.com/404.png", status_code=404,
                            content=b"", content_type="text/html")
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/404.png": not_found}))
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"
    assert not (tmp_path / "images").exists() or not list((tmp_path / "images").glob("*.tmp"))


def test_429_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/429.png")])
    busy = FetchResult(url="https://digi-api.com/429.png", status_code=429,
                       content=b"", content_type="image/png")
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/429.png": busy}))
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"


def test_timeout_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/slow.png")])
    done, refused, failed = dl.download_all(
        db, fetcher=FakeFetcher({"https://digi-api.com/slow.png": TimeoutError("timed out")})
    )
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"


def test_wrong_content_type_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/html.png")])
    html = FetchResult(url="https://digi-api.com/html.png", status_code=200,
                       content=make_png(), content_type="text/html")
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/html.png": html}))
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"


def test_truncated_image_marks_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    _setup_db(db, [(1, "https://digi-api.com/trunc.png")])
    trunc = FetchResult(url="https://digi-api.com/trunc.png", status_code=200,
                        content=b"\x89PNG\r\n\x1a\n", content_type="image/png")  # too short
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/trunc.png": trunc}))
    assert failed == 1 and done == 0
    assert _image_rows(db)[0]["download_status"] == "failed"
    # nothing half-written on disk
    assert not list((tmp_path / "images").glob("*")) or not list((tmp_path / "images").rglob("*.tmp"))


def test_forbidden_host_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    # digimon.net official images must never be downloaded (docs/sources.md)
    _setup_db(db, [(1, "https://digimon.net/cimages/digimon/agumon.jpg")])
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({}))
    assert done == 0 and refused == 1
    assert _image_rows(db)[0]["download_status"] == "failed"


def test_duplicate_basename_does_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    _setup_db(db, [
        (1, "https://digi-api.com/a.png"),
        (1, "https://digi-api.com/sub/a.png"),  # same basename, different URL
    ])
    fetcher = FakeFetcher({
        "https://digi-api.com/a.png": FetchResult("https://digi-api.com/a.png", 200, make_png(32, 32), "image/png"),
        "https://digi-api.com/sub/a.png": FetchResult("https://digi-api.com/sub/a.png", 200, make_png(64, 64), "image/png"),
    })
    done, refused, failed = dl.download_all(db, fetcher=fetcher)
    assert (done, refused, failed) == (2, 0, 0)
    rows = _image_rows(db)
    paths = {r["local_path"] for r in rows}
    assert len(paths) == 2  # distinct files despite identical basenames


def test_rerun_skips_complete_and_retries_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    db = tmp_path / "db.sqlite"
    _setup_db(db, [
        (1, "https://digi-api.com/ok.png"),
        (2, "https://digi-api.com/bad.png"),
    ])
    bad = FetchResult("https://digi-api.com/bad.png", 500, b"", "text/html")
    ok = FetchResult("https://digi-api.com/ok.png", 200, make_png(), "image/png")
    done, refused, failed = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/ok.png": ok, "https://digi-api.com/bad.png": bad}))
    assert (done, refused, failed) == (1, 0, 1)
    # ok.png is now 'downloaded' and skipped on the next run; bad.png is retried
    fixed = FetchResult("https://digi-api.com/bad.png", 200, make_png(), "image/png")
    done2, refused2, failed2 = dl.download_all(db, fetcher=FakeFetcher({"https://digi-api.com/bad.png": fixed}))
    assert (done2, refused2, failed2) == (1, 0, 0)


def test_main_exit_code(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(dl, "DB_PATH", tmp_path / "db.sqlite")
    _setup_db(tmp_path / "db.sqlite", [(1, "https://digimon.net/x.jpg")])  # forbidden -> failure
    assert dl.main([]) != 0
