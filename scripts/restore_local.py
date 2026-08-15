"""restore-local: restore the canonical database from a local backup.

Validates the backup (manifest + file presence + DB SHA-256 + SQLite
integrity + schema compatibility), stages every target to a temp file, then
atomically replaces the live paths — a failed restore leaves the live
database unchanged (S0-2).

The live DB is never overwritten without ``--yes`` (or ``--dry-run`` to
preview). ``--target`` lets tests / unusual layouts restore elsewhere.

Usage:
    uv run python scripts/restore_local.py <backup_dir> [--yes] [--dry-run]
                                           [--target data/digidex.sqlite]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline.core.backup import BackupError, inspect_backup, restore_backup
from pipeline.core.config import DB_PATH


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Restore DigiDex from a local backup")
    ap.add_argument("backup_dir", type=str, help="path to the backup directory to restore")
    ap.add_argument("--yes", action="store_true",
                    help="confirm overwriting the existing live database")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate + preview what would be restored, write nothing")
    ap.add_argument("--target", type=str, default=str(DB_PATH),
                    help="target database path (default: data/digidex.sqlite)")
    args = ap.parse_args(argv)

    backup_dir = Path(args.backup_dir)
    if not backup_dir.is_dir():
        print(f"ERROR: not a directory: {backup_dir}", file=sys.stderr)
        return 1

    # validate first — a bad backup is rejected even for --dry-run
    try:
        info = inspect_backup(backup_dir)
    except (BackupError, ValueError) as exc:
        print(f"ERROR: backup invalid: {exc}", file=sys.stderr)
        return 1

    target = Path(args.target)
    if target.exists() and not (args.yes or args.dry_run):
        print(
            f"ERROR: {target} already exists. Restoring would overwrite it. "
            f"Pass --yes to confirm, or --dry-run to preview.",
            file=sys.stderr,
        )
        return 1

    print(f"backup:      {backup_dir}")
    print(f"  snapshot:  {info.get('snapshot_date')}  run_id: {info.get('run_id')}")
    print(f"  db sha256: {info.get('database_sha256')}")
    print(f"  schema v:  {info.get('schema_version')}  images: {'yes' if (backup_dir / 'images').exists() else 'no'}")
    if args.dry_run:
        would = restore_backup(backup_dir, db_path=target, dry_run=True)
        print("[dry-run] would restore:")
        for p in would:
            print(f"  -> {p}")
        return 0

    # runtime records (sync state, manifest, reports) live beside the DB, so
    # when --target relocates the DB the other files follow it.
    state_path = target.parent / ".sync_state.json"
    manifest_path = target.parent / ".publish_manifest.json"
    reports_dir = target.parent / "reports"
    try:
        restored = restore_backup(
            backup_dir, db_path=target, state_path=state_path,
            manifest_path=manifest_path, reports_dir=reports_dir,
        )
    except (BackupError, OSError) as exc:
        print(f"ERROR: restore failed; live database unchanged: {exc}", file=sys.stderr)
        return 1

    print("restored:")
    for p in restored:
        print(f"  -> {p}")
    print("post-restore checks: run `uv run python scripts/inspect_snapshot.py`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
