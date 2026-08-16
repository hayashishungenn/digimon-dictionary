"""download-images: download remote digimon art into the local cache.

Images are cached under data/images/ (gitignored). We never re-distribute
third-party artwork; this script is for personal offline use only (spec §26/§57).

Fail-safe design (T8):
- Reuses the shared rate-limited/retrying/timeout Fetcher — never a separate
  raw httpx request.
- Only hosts on the allow-list are fetched; official digimon.net images (which
  docs/sources.md forbids downloading) are refused up front.
- Every file is written to a temp path, validated (HTTP 200, image/* content
  type, non-empty, parseable dimensions), then atomically replaced. A failure
  deletes the temp file, so a half-written file is never marked downloaded.
- Local filenames are collision-proof (digimon id + URL hash).
- Returns non-zero when any image failed or was skipped by policy.

Usage:
    uv run python scripts/download_images.py [--limit N] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import struct
from pathlib import Path

from pipeline.core.config import DB_PATH
from pipeline.core.images import (
    cache_root_for,
    image_cache_root,
    main_rel,
    resolve_cached_path,
    thumb_rel,
    thumbs_dir,
)
from pipeline.core.request import Fetcher
from pipeline.core.schema import connect

logger = logging.getLogger("download_images")

# Only these hosts may be fetched (digimon.net official art is off-limits per
# docs/sources.md — the adapter never stores official image URLs, and this is a
# safety net on top).
ALLOWED_IMAGE_HOSTS = ("digi-api.com", "wikimon.net")

# image/* content types we will accept and write to disk.
_ALLOWED_CONTENT_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp")

THUMB_MAX_EDGE = 128  # px


def _content_type(suffix: str) -> str:
    return {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".avif": "image/avif",
        ".bmp": "image/bmp",
    }.get(suffix.lower(), "application/octet-stream")


def _write_thumbnail(src: Path, dst: Path) -> None:
    """Downscale `src` into a PNG thumbnail at `dst` (best-effort, non-destructive).

    The source file is only ever read; the thumbnail is a new derived file so a
    failure can never corrupt the original artwork."""
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(src) as im:
            im.thumbnail((THUMB_MAX_EDGE, THUMB_MAX_EDGE))
            im.save(dst, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise OSError(f"thumbnail failed for {src.name}: {exc}") from exc


def _thumbnail_local(digimon_id: int) -> str:
    return thumb_rel(digimon_id)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def _content_type_allowed(content_type: str | None) -> bool:
    if not content_type:
        return False
    return content_type.split(";")[0].strip().lower() in _ALLOWED_CONTENT_TYPES


def _image_dimensions(data: bytes) -> tuple[int, int] | None:
    """Best-effort (width, height) for PNG/JPEG/GIF/WebP from their headers.

    Returns None when the bytes do not parse as one of these formats — used to
    catch truncated/corrupt downloads before they are written to disk.
    """
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
        if data[:3] == b"GIF" and len(data) >= 10:
            w, h = struct.unpack("<HH", data[6:10])
            return int(w), int(h)
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
            fmt = data[12:16]
            if fmt == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return int(w), int(h)
            if fmt == b"VP8L" and len(data) >= 25:
                bits = int.from_bytes(data[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if data[:2] == b"\xff\xd8" and len(data) >= 4:
            # JPEG: scan segments for a SOF marker
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5 : i + 9])
                    return int(w), int(h)
                length = struct.unpack(">H", data[i + 2 : i + 4])[0]
                i += 2 + length
    except (struct.error, IndexError, ValueError):
        return None
    return None


def _local_path(digimon_id: int, url: str) -> str:
    """Collision-proof, cache-root-RELATIVE filename (P0-1 contract):
    ``digi_<id:05d>_<sha8(url)><suffix>``. The DB stores this relative value;
    filesystem I/O prepends the resolved cache root."""
    return main_rel(digimon_id, url)


def backfill_metadata(conn, *, cache_root: Path | None = None) -> int:
    """Backfill width/height/sha256/content_type/fetched_at for every cached
    image from the file on disk (idempotent; used to enrich an already-downloaded
    cache). Returns the number of rows enriched."""
    cache_root = cache_root or cache_root_for(None, conn=conn)
    done = 0
    rows = conn.execute(
        "SELECT id, local_path FROM digimon_image WHERE download_status = 'downloaded'"
    ).fetchall()
    for row in rows:
        if not row["local_path"]:
            continue
        p = resolve_cached_path(cache_root, row["local_path"])
        if p is None or not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        dims = _image_dimensions(data)
        conn.execute(
            """UPDATE digimon_image SET
                 width=COALESCE(width, ?), height=COALESCE(height, ?),
                 sha256=COALESCE(sha256, ?), content_type=COALESCE(content_type, ?),
                 fetched_at=COALESCE(fetched_at, datetime('now'))
               WHERE id=?""",
            [dims[0] if dims else None, dims[1] if dims else None,
             sha256_of(data), _content_type(p.suffix), row["id"]],
        )
        done += 1
    conn.commit()
    return done


def ensure_thumbnails(conn, *, force: bool = False, cache_root: Path | None = None) -> tuple[int, int]:
    """Derive a local thumbnail for every downloaded main image (P0-3).

    Writes ``<cache_root>/thumbs/digi_<id>.png`` (a new derived cache file) and
    records an ``image_type='thumbnail'`` digimon_image row with dimensions,
    sha256, content type and fetch time. Also populates ``digimon.thumbnail``
    with the cache-root-RELATIVE path. Returns ``(derived, failed)`` — a failure
    is recorded with ``failure_reason`` so the quality report can surface it.
    """
    cache_root = cache_root or cache_root_for(None, conn=conn)
    thumbs_root = thumbs_dir(cache_root)
    thumbs_root.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        """SELECT id, digimon_id, remote_url, local_path FROM digimon_image
           WHERE image_type = 'main_image' AND download_status = 'downloaded'"""
    ).fetchall()
    derived = 0
    failed = 0
    for row in rows:
        digimon_id = row["digimon_id"]
        src = resolve_cached_path(cache_root, row["local_path"])
        if src is None or not src.is_file():
            continue  # nothing to derive from; the main file is missing
        thumb_rel_path = _thumbnail_local(digimon_id)
        dst = cache_root / thumb_rel_path
        try:
            if not dst.exists() or force:
                _write_thumbnail(src, dst)
            data = dst.read_bytes()
            dims = _image_dimensions(data)
            existing = conn.execute(
                "SELECT id FROM digimon_image WHERE digimon_id=? AND image_type='thumbnail'",
                [digimon_id],
            ).fetchone()
            thumb_meta = [
                digimon_id, thumb_rel_path, dims[0] if dims else None, dims[1] if dims else None,
                sha256_of(data), "image/png",
            ]
            if existing:
                conn.execute(
                    """UPDATE digimon_image SET local_path=?, width=?, height=?, sha256=?,
                       content_type=?, download_status='downloaded', failure_reason=NULL,
                       fetched_at=datetime('now')
                       WHERE id=?""",
                    [*thumb_meta[1:], existing["id"]],  # digimon_id not a column here
                )
            else:
                conn.execute(
                    """INSERT INTO digimon_image
                       (digimon_id, image_type, local_path, width, height, sha256,
                        content_type, download_status, fetched_at)
                       VALUES(?, 'thumbnail', ?, ?, ?, ?, ?, 'downloaded', datetime('now'))""",
                    thumb_meta,
                )
            conn.execute("UPDATE digimon SET thumbnail=? WHERE id=?", [thumb_rel_path, digimon_id])
            derived += 1
        except OSError as exc:
            failed += 1
            existing = conn.execute(
                "SELECT id FROM digimon_image WHERE digimon_id=? AND image_type='thumbnail'",
                [digimon_id],
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE digimon_image SET download_status='failed', failure_reason=?, "
                    "fetched_at=datetime('now') WHERE id=?",
                    [str(exc), existing["id"]],
                )
            else:
                conn.execute(
                    """INSERT INTO digimon_image
                       (digimon_id, image_type, local_path, download_status, failure_reason, fetched_at)
                       VALUES(?, 'thumbnail', ?, 'failed', ?, datetime('now'))""",
                    [digimon_id, thumb_rel_path, str(exc)],
                )
            logger.warning("thumbnail failed for digimon %d: %s", digimon_id, exc)
    conn.commit()
    return derived, failed


def download_all(db_path: Path, *, limit: int | None = None, force: bool = False,
                 fetcher: Fetcher | None = None, cache_root: Path | None = None) -> tuple[int, int, int]:
    """Download pending images. Returns (done, refused_by_policy, failed)."""
    cache_root = cache_root or image_cache_root(db_path)
    conn = connect(db_path)
    cache_root.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT id, digimon_id, remote_url, local_path FROM digimon_image "
        "WHERE download_status != 'downloaded'"
    ).fetchall()
    if limit:
        rows = rows[:limit]

    own_fetcher = fetcher is None
    if fetcher is None:
        fetcher = Fetcher(
            rate_per_second=1.0,
            max_concurrency=2,
            # P0-1: the fetch cache belongs with THIS db, not the module default
            cache_dir=db_path.parent / ".http_cache",
            headers={"User-Agent": "DigiDex/0.1 (personal offline cache)"},
        )
    done = 0
    refused = 0
    failed = 0
    for row in rows:
        url = row["remote_url"]
        if not url:
            continue
        if _host_of(url) not in ALLOWED_IMAGE_HOSTS:
            refused += 1
            conn.execute(
                "UPDATE digimon_image SET download_status='failed' WHERE id=?",
                [row["id"]],
            )
            logger.warning("image host not allowed (skipped): %s", url)
            continue

        local_rel = _local_path(row["digimon_id"], url)
        local = cache_root / local_rel
        if local.exists() and not force:
            # existing file — only trust it if it is a valid, non-empty image
            if local.stat().st_size > 0 and _image_dimensions(local.read_bytes()) is not None:
                conn.execute(
                    "UPDATE digimon_image SET local_path=?, download_status='downloaded' WHERE id=?",
                    [local_rel, row["id"]],
                )
                done += 1
                continue
            local.unlink()  # stale/corrupt partial file — re-download

        tmp = Path(f"{local}.tmp")
        try:
            result = fetcher.get(url)
            if result.status_code != 200:
                raise OSError(f"HTTP {result.status_code}")
            if not _content_type_allowed(result.content_type):
                raise OSError(f"unexpected content type {result.content_type}")
            if not result.content:
                raise OSError("empty body")
            if _image_dimensions(result.content) is None:
                raise OSError("unparseable/truncated image")
            tmp.write_bytes(result.content)
            os.replace(tmp, local)
            conn.execute(
                "UPDATE digimon_image SET local_path=?, sha256=?, download_status='downloaded' WHERE id=?",
                [local_rel, sha256_of(result.content), row["id"]],
            )
            done += 1
            if done % 50 == 0:
                logger.info("downloaded %d images", done)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
            logger.warning("image download failed %s: %s", url, exc)
            conn.execute("UPDATE digimon_image SET download_status='failed' WHERE id=?", [row["id"]])
    conn.commit()
    conn.close()
    if own_fetcher:
        fetcher.close()
    logger.info("images: %d done, %d refused by policy, %d failed", done, refused, failed)
    return done, refused, failed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--no-thumbnails", action="store_true",
                    help="skip local thumbnail derivation (P0-3)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    # mirror sync_data._resolve_db_path: DIGIDEX_DB wins over the module default
    db_path = Path(os.environ.get("DIGIDEX_DB", str(DB_PATH)))
    cache_root = image_cache_root(db_path)
    done, refused, failed = download_all(db_path, limit=args.limit, force=args.force,
                                         cache_root=cache_root)
    logger.info("done: %d images cached under %s", done, cache_root)

    conn = connect(db_path)
    try:
        enriched = backfill_metadata(conn, cache_root=cache_root)
        logger.info("metadata backfilled for %d cached images", enriched)
        derived = 0
        thumb_failed = 0
        if not args.no_thumbnails:
            derived, thumb_failed = ensure_thumbnails(conn, force=args.force, cache_root=cache_root)
            logger.info("thumbnails: %d derived, %d failed (%s)",
                        derived, thumb_failed, thumbs_dir(cache_root))
    finally:
        conn.close()

    if failed or refused or thumb_failed:
        logger.error(
            "image pipeline finished with %d failed, %d refused (policy) and %d thumbnail failures",
            failed, refused, thumb_failed,
        )
        return 1
    logger.info("image pipeline ok: %d main + %d thumbnails under %s", done, derived, cache_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
