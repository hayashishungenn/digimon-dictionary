"""inspect-snapshot: show the current snapshot / backup status at a glance.

Reads the publish manifest, the live database, and the quality report to
answer "what dataset is this, when, from which run, and is it healthy?" —
without touching anything. Pass a backup directory to inspect a backup instead.

Never prints tokens, cookies, environment variables, or `.env` (S1-4).

Usage:
    uv run python scripts/inspect_snapshot.py [--path BACKUP_DIR] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.core.backup import BackupError, inspect_backup


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Inspect the current DigiDex snapshot")
    ap.add_argument("--path", type=str, default=None,
                    help="inspect a backup directory instead of the live database")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args(argv)

    try:
        info = inspect_backup(Path(args.path) if args.path else None)
    except (BackupError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    label = f"backup: {args.path}" if args.path else f"live:    {info.get('path')}"
    print(f"source:      {label}")
    print(f"exists:      {info.get('exists') if 'exists' in info else True}")
    if "exists" in info and not info["exists"]:
        print("(database not synced yet — run scripts/sync_data.py)")
        return 0
    print(f"integrity:   {'ok' if info.get('integrity_ok') else 'FAILED'}")
    print(f"snapshot:    {info.get('snapshot_date')}  (run_id: {info.get('run_id')})")
    print(f"database:    {info.get('database_sha256')}  {info.get('database_size')} bytes")
    print(f"schema:      v{info.get('schema_version')}")
    print(f"image stage: {info.get('image_stage') or 'unknown'}")
    print(f"baseline:    {info.get('is_incremental_baseline')}")
    print(f"state:       committed={info.get('state_committed')}")
    sources = info.get("sources")
    if sources:
        print(f"sources:     {', '.join(sources)}")
    print(f"report:      {'present' if info.get('report_exists') else 'missing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
