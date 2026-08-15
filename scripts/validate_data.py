"""validate-data: run data-quality checks and write reports.

Usage:
    uv run python scripts/validate_data.py [--json PATH] [--reports-dir DIR]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pipeline.core.config import DB_PATH
from pipeline.validation.validator import run_and_write


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_path", type=Path, default=None)
    ap.add_argument("--reports-dir", dest="reports_dir", type=Path, default=None,
                    help="directory for data-quality.json/.md (default: data/reports)")
    args = ap.parse_args(argv)

    report = run_and_write(DB_PATH, reports_dir=args.reports_dir)
    if args.json_path:
        args.json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
    ic = report["issue_counts"]
    print(f"issues: {ic['error']} errors / {ic['warning']} warnings / {ic['info']} info")
    target = args.reports_dir or (DB_PATH.parent / "reports")
    print(f"reports written: {target / 'data-quality.json'}, {target / 'data-quality.md'}")
    return 1 if ic["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
