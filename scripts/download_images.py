"""download-images: download remote digimon art into the local cache.

Images are cached under data/images/ (gitignored). We never re-distribute
third-party artwork; this script is for personal offline use only (spec §26/§57).

Usage:
    uv run python scripts/download_images.py [--limit N] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path

from pipeline.core.config import DB_PATH, IMAGES_DIR
from pipeline.core.schema import connect

logger = logging.getLogger("download_images")


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download_all(db_path: Path, *, limit: int | None = None, force: bool = False) -> int:
    conn = connect(db_path)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT id, digimon_id, remote_url, local_path FROM digimon_image "
        "WHERE download_status != 'downloaded'"
    ).fetchall()
    if limit:
        rows = rows[:limit]

    import httpx

    client = httpx.Client(follow_redirects=True, timeout=20, headers={"User-Agent": "DigiDex/0.1 (personal cache)"})
    done = 0
    for row in rows:
        url = row["remote_url"]
        if not url:
            continue
        fname = Path(url.split("/")[-1].split("?")[0])
        # keep a stable, collision-free local name
        local = IMAGES_DIR / f"digi_{row['digimon_id']:05d}_{fname.name}"
        if local.exists() and not force:
            conn.execute(
                "UPDATE digimon_image SET local_path=?, download_status='downloaded' WHERE id=?",
                [str(local), row["id"]],
            )
            done += 1
            continue
        try:
            resp = client.get(url)
            if resp.status_code != 200 or not resp.content:
                conn.execute("UPDATE digimon_image SET download_status='failed' WHERE id=?", [row["id"]])
                continue
            local.write_bytes(resp.content)
            conn.execute(
                "UPDATE digimon_image SET local_path=?, sha256=?, download_status='downloaded' WHERE id=?",
                [str(local), sha256_of(resp.content), row["id"]],
            )
            done += 1
            if done % 50 == 0:
                logger.info("downloaded %d images", done)
        except Exception as exc:  # noqa: BLE001
            logger.warning("image download failed %s: %s", url, exc)
            conn.execute("UPDATE digimon_image SET download_status='failed' WHERE id=?", [row["id"]])
    conn.commit()
    conn.close()
    client.close()
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    n = download_all(DB_PATH, limit=args.limit, force=args.force)
    logger.info("done: %d images cached under data/images/", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
