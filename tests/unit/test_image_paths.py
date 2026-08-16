"""P0-1 tests: the unified image-path resolver (pipeline/core/images.py).

The DB contract: `local_path` / `digimon.thumbnail` hold ONLY cache-root
relative paths or NULL. These tests cover the resolver's platform-independent
path classification, legacy-absolute rebasing, containment/traversal rejection,
and the cache-root derivation rules.
"""
from __future__ import annotations

import os

import pytest

from pipeline.core import images
from pipeline.core.config import DB_PATH, IMAGES_DIR


# ---------------------------------------------------------------------------
# image_cache_root
# ---------------------------------------------------------------------------
def test_cache_root_default_matches_config(monkeypatch):
    monkeypatch.delenv("DIGIDEX_IMAGES_DIR", raising=False)
    assert images.image_cache_root(DB_PATH) == IMAGES_DIR


def test_cache_root_from_db_parent(tmp_path):
    db = tmp_path / "sub" / "db.sqlite"
    assert images.image_cache_root(db) == tmp_path / "sub" / "images"


def test_cache_root_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("DIGIDEX_IMAGES_DIR", str(tmp_path / "elsewhere"))
    assert images.image_cache_root(DB_PATH) == tmp_path / "elsewhere"


def test_db_path_from_conn(tmp_path):
    import sqlite3

    conn = sqlite3.connect(tmp_path / "x.sqlite")
    try:
        assert images.db_path_from_conn(conn) == (tmp_path / "x.sqlite")
    finally:
        conn.close()


def test_cache_root_for_requires_source():
    with pytest.raises(ValueError):
        images.cache_root_for()


# ---------------------------------------------------------------------------
# is_bad_stored_path — platform-independent
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    [
        r"C:\Users\old\Digimon_Dictionary\data\images\digi_00001_Agumon.png",  # drive
        "C:rel.png",  # drive-relative
        r"D:\x\y.png",  # another drive
        r"\\server\share\x.png",  # UNC
        "//server/share/x.png",  # UNC posix form
        "/abs/x.png",  # os-absolute
        "../x.png",  # traversal
        "a/../../x.png",
        r"..\..\x.png",
        "data/images/x.png",  # forbidden prefix
        r"data\images\x.png",
        "C:\\Windows\\evil.png",
    ],
)
def test_bad_stored_path(value):
    assert images.is_bad_stored_path(value) is True


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "digi_00001_Agumon.png",
        "digi_00001_ab12cd34.png",
        "thumbs/digi_00001.png",
        r"thumbs\digi_00001.png",
        "thumbs/digi_00001.png/",  # trailing slash tolerated (not a leak)
    ],
)
def test_good_stored_path(value):
    assert images.is_bad_stored_path(value) is False


# ---------------------------------------------------------------------------
# rebase_legacy
# ---------------------------------------------------------------------------
def test_rebase_legacy_old_checkout_absolute():
    stored = r"C:\Users\Hayas\Github\Digimon_Dictionary\data\images\digi_00010_Death_Meramon_(C'mon_Digimon_Version).png"
    assert images.rebase_legacy(stored) == "digi_00010_Death_Meramon_(C'mon_Digimon_Version).png"


def test_rebase_legacy_posix_and_thumbs():
    assert images.rebase_legacy("/Users/me/data/images/thumbs/x.png") == "thumbs/x.png"
    assert images.rebase_legacy("data/images/digi_00001_x.png") == "digi_00001_x.png"


def test_rebase_legacy_unlocatable_and_clean():
    assert images.rebase_legacy(r"C:\Windows\evil.png") is None
    assert images.rebase_legacy(r"\\server\share\x.png") is None
    assert images.rebase_legacy("../escape.png") is None
    assert images.rebase_legacy("thumbs\\digi_00001.png") == "thumbs/digi_00001.png"
    assert images.rebase_legacy("digi_00001_x.png") == "digi_00001_x.png"
    assert images.rebase_legacy("") is None
    assert images.rebase_legacy(None) is None


# ---------------------------------------------------------------------------
# resolve_cached_path
# ---------------------------------------------------------------------------
def test_resolve_relative_existing(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    (root / "digi_00001_ab12cd34.png").write_bytes(b"x")
    p = images.resolve_cached_path(root, "digi_00001_ab12cd34.png")
    assert p is not None and p.is_file() and images.is_within(root, p)


def test_resolve_legacy_absolute_to_existing(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    (root / "digi_00001_Agumon.png").write_bytes(b"x")
    legacy = r"C:\Users\old\Digimon_Dictionary\data\images\digi_00001_Agumon.png"
    p = images.resolve_cached_path(root, legacy)
    assert p is not None and p.is_file()


def test_resolve_thumbs(tmp_path):
    root = tmp_path / "images"
    (root / "thumbs").mkdir(parents=True)
    (root / "thumbs" / "digi_00001.png").write_bytes(b"x")
    p = images.resolve_cached_path(root, "thumbs/digi_00001.png")
    assert p is not None and p.is_file()


@pytest.mark.parametrize(
    "stored",
    [None, "", "../outside.png", "..\\..\\secret.png", "a/../..\\x.png",
     r"C:\Windows\evil.png", r"\\server\share\x.png", "/etc/passwd"],
)
def test_resolve_rejects_traversal_and_foreign(tmp_path, stored):
    root = tmp_path / "images"
    root.mkdir()
    assert images.resolve_cached_path(root, stored) is None


def test_resolve_missing_file_returns_path_not_none(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    p = images.resolve_cached_path(root, "digi_00001_missing.png")
    assert p is not None  # existence is the CALLER's job (is_file)
    assert not p.is_file()


# ---------------------------------------------------------------------------
# to_cache_relative
# ---------------------------------------------------------------------------
def test_to_cache_relative(tmp_path):
    root = tmp_path / "images"
    f = root / "thumbs" / "digi_00001.png"
    assert images.to_cache_relative(root, f) == "thumbs/digi_00001.png"


def test_to_cache_relative_outside_raises(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    with pytest.raises(ValueError):
        images.to_cache_relative(root, tmp_path / "other" / "x.png")


# ---------------------------------------------------------------------------
# is_within / _canon_path
# ---------------------------------------------------------------------------
def test_is_within_same_root(tmp_path):
    root = tmp_path / "images"
    assert images.is_within(root, root / "a.png")
    assert images.is_within(root, root / "thumbs" / "b.png")


def test_is_within_rejects_siblings_and_escape(tmp_path):
    root = tmp_path / "images"
    assert not images.is_within(root, tmp_path / "other" / "x.png")
    assert not images.is_within(root, root / ".." / "images2" / "x.png")


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive filesystem")
def test_is_within_case_insensitive_on_windows(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    assert images.is_within(root, root / "DIGI_00001_X.PNG")


@pytest.mark.skipif(os.name != "nt", reason="Windows \\\\?\\ extended prefix")
def test_canon_path_strips_extended_prefix():
    assert images._canon_path(r"\\?\C:\Foo\Bar") == images._canon_path(r"C:\Foo\Bar")


# ---------------------------------------------------------------------------
# naming helpers
# ---------------------------------------------------------------------------
def test_main_rel_is_hash_based():
    import hashlib

    url = "https://digi-api.com/images/digimon/w/Agumon.png"
    expected = "digi_00001_" + hashlib.sha256(url.encode()).hexdigest()[:8] + ".png"
    assert images.main_rel(1, url) == expected
    assert "/" not in images.main_rel(1, url)
    assert not images.is_bad_stored_path(images.main_rel(1, url))


def test_main_rel_fallback_suffix():
    rel = images.main_rel(2, "https://x/v/no-extension")
    assert rel.startswith("digi_00002_")
    assert rel.endswith(".img")
    assert len(rel[len("digi_00002_"):].split(".")[0]) == 8  # sha8 digest


def test_thumb_rel():
    assert images.thumb_rel(1488) == "thumbs/digi_01488.png"