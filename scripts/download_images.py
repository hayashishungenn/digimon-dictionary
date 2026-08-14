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

from pipeline.core.config import DB_PATH, IMAGES_DIR
from pipeline.core.request import Fetcher
from pipeline.core.schema import connect

logger = logging.getLogger("download_images")

# Only these hosts may be fetched (digimon.net official art is off-limits per
# docs/sources.md — the adapter never stores official image URLs, and this is a
# safety net on top).
ALLOWED_IMAGE_HOSTS = ("digi-api.com", "wikimon.net")

# image/* content types we will accept and write to disk.
_ALLOWED_CONTENT_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp")


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


def _local_path(digimon_id: int, url: str) -> Path:
    """Collision-proof local filename: digimon id + short URL hash + extension."""
    from urllib.parse import urlparse

    fname = Path(urlparse(url).path).name
    suffix = Path(fname).suffix.lower() or ".img"
    if len(suffix) > 6 or not suffix[1:].isalnum():
        suffix = ".img"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return IMAGES_DIR / f"digi_{digimon_id:05d}_{digest}{suffix}"


def download_all(db_path: Path, *, limit: int | None = None, force: bool = False,
                 fetcher: Fetcher | None = None) -> tuple[int, int, int]:
    """Download pending images. Returns (done, refused_by_policy, failed)."""
    conn = connect(db_path)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
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
            cache_dir=DB_PATH.parent / ".http_cache",
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

        local = _local_path(row["digimon_id"], url)
        if local.exists() and not force:
            # existing file — only trust it if it is a valid, non-empty image
            if local.stat().st_size > 0 and _image_dimensions(local.read_bytes()) is not None:
                conn.execute(
                    "UPDATE digimon_image SET local_path=?, download_status='downloaded' WHERE id=?",
                    [str(local), row["id"]],
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
                [str(local), sha256_of(result.content), row["id"]],
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
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    done, refused, failed = download_all(DB_PATH, limit=args.limit, force=args.force)
    logger.info("done: %d images cached under data/images/", done)
    if failed or refused:
        logger.error("image download finished with %d failed and %d refused (policy)", failed, refused)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
