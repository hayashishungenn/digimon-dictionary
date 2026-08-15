"""backup-local: create a timestamped local backup of the canonical database.

Copies the database, sync state, publish manifest, quality reports, and
(optionally) the image cache into ``data/backups/backup-<ts>/`` with a
``backup.json`` describing the backup (S0-2). The copied database is
validated before the backup is recorded; ``--keep N`` prunes the oldest
backups beyond the newest N.

Usage:
    uv run python scripts/backup_local.py [--with-images] [--out DIR]
                                          [--keep N] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys

from pipeline.core.backup import (
    BACKUP_MANIFEST,
    create_backup,
    inspect_backup,
    list_backups,
)
from pipeline.core.config import BACKUP_DIR, DB_PATH


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Create a local DigiDex backup")
    ap.add_argument("--with-images", action="store_true",
                    help="also copy the local image cache (data/images/, gitignored)")
    ap.add_argument("--out", type=str, default=None,
                    help="backup directory (default: data/backups/backup-<timestamp>)")
    ap.add_argument("--keep", type=int, default=None,
                    help="prune to the newest N backups after this one (0 = delete all old)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be backed up without writing anything")
    args = ap.parse_args(argv)

    if args.dry_run:
        print(f"[dry-run] would back up: {DB_PATH}")
        print(f"[dry-run] backup root:    {BACKUP_DIR}")
        if args.with_images:
            print("[dry-run] would also copy data/images/ (local cache, not committed)")
        print(f"[dry-run] would write:     {BACKUP_DIR}/backup-<timestamp>/")
        return 0

    try:
        out = create_backup(db_path=DB_PATH, out_dir=args.out,
                            with_images=args.with_images, keep=args.keep)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: backup failed: {exc}", file=sys.stderr)
        return 1

    info = inspect_backup(out)
    print(f"backup created:  {out}")
    print(f"  backup.json:   {out / BACKUP_MANIFEST}")
    print(f"  snapshot date: {info.get('snapshot_date')}")
    print(f"  run_id:        {info.get('run_id')}")
    print(f"  db sha256:     {info.get('database_sha256')}")
    print(f"  db size:       {info.get('database_size')} bytes")
    print(f"  schema v:      {info.get('schema_version')}")
    print(f"  images:        {'yes' if (out / 'images').exists() else 'no'}")
    print(f"  integrity:     {'ok' if info.get('integrity_ok') else 'FAILED'}")
    existing = list_backups()
    print(f"  backups now:   {len(existing)} (newest first: {[p.name for p in existing[:5]]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
