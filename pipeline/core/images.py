"""Unified image-cache path resolution (P0-1).

DB contract: ``digimon_image.local_path`` and ``digimon.thumbnail`` hold ONLY
cache-root-relative paths (e.g. ``"digi_00001_ab12cd34.png"``,
``"thumbs/digi_00001.png"``) or NULL. They are never absolute, never
``data/images/...``, never ``..``.

This module is the single authority on the image cache root and the only place
that maps stored values <-> absolute filesystem paths. Everything reads/writes
through it: ``scripts/download_images.py``, ``pipeline/merge/store.py``,
``apps/api/main.py`` (serving), ``apps/api/queries.py`` (sanitization) and
``scripts/migrate_image_paths.py`` (migration).

Cache root rules: DIGIDEX_IMAGES_DIR env wins; else ``<db-parent>/images/``
(e.g. default DB ``data/digidex.sqlite`` -> ``data/images/``).
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from urllib.parse import urlparse

_P_DRIVE = re.compile(r"^[A-Za-z]:")
_P_LEGACY = re.compile(r"(?i)(?:^|[/\\])data[/\\]images[/\\](.+)$")


def image_cache_root(db_path: str | Path | None = None) -> Path:
    """Resolve the image cache root for a database.

    DIGIDEX_IMAGES_DIR always wins; otherwise ``<db-parent>/images/`` (default
    DB ``data/digidex.sqlite`` -> ``data/images/``).
    """
    env = os.environ.get("DIGIDEX_IMAGES_DIR")
    if env:
        return Path(env)
    if db_path is None:
        from .config import DB_PATH

        db_path = DB_PATH
    return Path(db_path).parent / "images"


def thumbs_dir(cache_root: Path) -> Path:
    """The derived-thumbnail sub-directory inside a cache root."""
    return cache_root / "thumbs"


def db_path_from_conn(conn) -> Path | None:
    """``PRAGMA database_list`` -> the main DB file path (used when a writer
    only knows its connection, e.g. CanonicalStore). None otherwise."""
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except Exception:  # noqa: BLE001  (any sqlite/locking error -> undetermined)
        return None
    for r in rows:
        try:
            if isinstance(r, (dict,)):
                name, file = r.get("name"), r.get("file")
            elif hasattr(r, "keys"):
                name, file = r["name"], r["file"]
            else:
                name, file = r[1], r[2]
        except (IndexError, KeyError, TypeError):
            continue
        if file and str(name) == "main" and str(file) != ":memory:":
            return Path(file)
    return None


def cache_root_for(db_path: str | Path | None = None, *, conn=None) -> Path:
    """image_cache_root(db_path or db_path_from_conn(conn)); raises if neither."""
    if db_path is None and conn is not None:
        db_path = db_path_from_conn(conn)
    if db_path is None:
        raise ValueError("cache_root_for needs a db_path (or a connection with a DB file)")
    return image_cache_root(db_path)


def is_bad_stored_path(value: str) -> bool:
    """True when a stored path violates the image-path contract (or leaks a
    filesystem path): drive letter, UNC, OS-absolute, any ``..`` component, or a
    leading ``data/images/``. Platform-independent — does NOT rely on
    ``Path.is_absolute``, so a ``C:\\...`` string is caught on POSIX CI too."""
    if not value:
        return False
    if value.startswith(("/", "\\")):
        return True
    if _P_DRIVE.match(value):
        return True
    parts = value.replace("\\", "/").split("/")
    if ".." in parts:
        return True
    if parts[0] == "data" and len(parts) > 1 and parts[1] == "images":
        return True
    return False


def rebase_legacy(stored: str) -> str | None:
    """Return a cache-root-relative value for `stored`, or None if unlocatable.

    Maps the legacy absolute form ``<...>/data/images/<tail>`` (e.g. the old
    checkout ``C:\\...\\Digimon_Dictionary\\data\\images\\digi_00010_...png``)
    to ``<tail>``; a clean relative value is returned normalized with '/'
    separators. Absolute-but-other (UNC/drive-outside/no data/images marker)
    and anything with a ``..`` component -> None."""
    if not stored:
        return None
    s = stored.strip().replace("\\", "/")
    m = _P_LEGACY.search(s)
    if m and m.group(1):
        return m.group(1)
    if is_bad_stored_path(stored):
        return None
    return s


def main_rel(digimon_id: int, url: str) -> str:
    """Collision-proof, cache-root-relative main-image filename (P0-1):
    ``digi_<id:05d>_<sha8(url)><suffix>`` (forward slashes, no root)."""
    fname = (urlparse(url).path or "").rstrip("/").rsplit("/", 1)[-1]
    suffix = Path(fname).suffix.lower() or ".img"
    if len(suffix) > 6 or not suffix[1:].isalnum():
        suffix = ".img"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"digi_{digimon_id:05d}_{digest}{suffix}"


def thumb_rel(digimon_id: int) -> str:
    """Cache-root-relative thumbnail filename: ``thumbs/digi_<id:05d>.png``."""
    return f"thumbs/digi_{digimon_id:05d}.png"


def is_within(root: Path, candidate: Path) -> bool:
    """True when `candidate` resolves to a path strictly inside `root`.

    Uses os.path.realpath + normcase + prefix compare and strips the Windows
    ``\\\\?\\`` extended-length prefix — do NOT use ``root in candidate.parents``
    after ``.resolve()`` here, because on Windows ``.resolve()`` can return a
    ``\\\\?\\C:\\...``-prefixed value that breaks Path equality (P0-1)."""
    root_s = _canon_path(root)
    cand_s = _canon_path(candidate)
    if root_s == cand_s:
        return True
    return cand_s.startswith(root_s.rstrip("\\/") + os.sep)


def _canon_path(p: Path | str) -> str:
    """Canonical string form for containment comparisons: realpath + normpath,
    Windows extended-length ``\\\\?\\`` prefix stripped, normcase applied."""
    s = os.path.realpath(os.path.normpath(os.fspath(p)))
    if os.name == "nt" and s.startswith("\\\\?\\"):
        s = s[4:]
    return os.path.normcase(s)


def to_cache_relative(cache_root: Path, path: Path) -> str:
    """Absolute `path` -> cache-root-relative '/' string (raises when outside)."""
    if not is_within(cache_root, path):
        raise ValueError(f"{path} is outside the image cache root {cache_root}")
    root = os.path.realpath(os.path.normpath(os.fspath(cache_root)))
    cand = os.path.realpath(os.path.normpath(os.fspath(path)))
    rel = os.path.relpath(cand, root)
    return rel.replace("\\", "/")


def resolve_cached_path(cache_root: Path, stored: str | None) -> Path | None:
    """Map a stored value to an absolute Path under `cache_root`.

    Returns None on NULL/empty, traversal, or any value that cannot be located
    under the cache root (including legacy absolute paths without a
    ``data/images/`` marker). Existence is NOT checked — callers test
    ``.is_file()`` themselves (the API before serving; the migration before
    marking a row downloaded).
    """
    if not stored:
        return None
    rel = rebase_legacy(stored)
    if rel is None or is_bad_stored_path(rel):
        return None
    candidate = Path(cache_root) / rel
    if not is_within(cache_root, candidate):
        return None
    return candidate