#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

# ─── How to run ───
# 1. Install uv (if not installed):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
# 2. Run directly (no venv, no pip install needed):
#      uv run scripts/self_check.py --all
# 3. Or make executable and run:
#      chmod +x scripts/self_check.py && ./scripts/self_check.py --all
# ──────────────────

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None and os.name == "nt":
        resolved = shutil.which(f"{name}.cmd")
    if resolved is None:
        raise RuntimeError(f"required executable not found: {name}")
    return resolved


def run_step(name: str, command: list[str], cwd: Path) -> bool:
    print(f"\n=== {name} ===")
    print("$", " ".join(command))
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    try:
        result = subprocess.run(command, cwd=cwd, check=False, env=environment)
    except OSError as error:
        print(f"ERROR: {error}")
        return False
    if result.returncode == 0:
        print(f"PASS: {name}")
        return True
    print(f"FAIL: {name} (exit {result.returncode})")
    return False


def run_diagnose_step(name: str, command: list[str], cwd: Path) -> bool:
    print(f"\n=== {name} ===")
    print("$", " ".join(command))
    environment = os.environ.copy()
    environment.pop("VIRTUAL_ENV", None)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            env=environment,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        print(f"ERROR: {error}")
        return False
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    if result.returncode != 0:
        print(f"FAIL: {name} (exit {result.returncode})")
        return False
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        print(f"FAIL: {name} (invalid JSON: {error})")
        return False
    if not isinstance(report, dict):
        print(f"FAIL: {name} (JSON root is not an object)")
        return False
    consistency = report.get("manifest_consistency")
    if not isinstance(consistency, dict):
        print(f"FAIL: {name} (manifest consistency is missing)")
        return False
    required = {
        "quality_report_matches_db": report.get("quality_report_matches_db"),
        "database_sha256_matches_db": consistency.get("database_sha256_matches_db"),
        "report_sha256_matches_report": consistency.get("report_sha256_matches_report"),
        "report_db_sha256_matches_db": consistency.get("report_db_sha256_matches_db"),
    }
    failures = [key for key, value in required.items() if value is not True]
    if failures:
        print(f"FAIL: {name} (consistency checks failed: {', '.join(failures)})")
        return False
    print(f"PASS: {name}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DigiDex local quality checks")
    parser.add_argument("--all", action="store_true", help="also run fixture and real-DB browser E2E")
    parser.add_argument("--e2e", action="store_true", help="also run fixture browser E2E")
    parser.add_argument("--realdb", action="store_true", help="also run real-DB browser E2E")
    parser.add_argument("--python-only", action="store_true", help="run only Python checks")
    parser.add_argument("--web-only", action="store_true", help="run only Web checks")
    args = parser.parse_args()
    if args.python_only and args.web_only:
        parser.error("--python-only and --web-only cannot be used together")

    root = Path(__file__).resolve().parents[1]
    web_root = root / "apps" / "web"
    uv = executable("uv") if not args.web_only else ""
    npm = executable("npm") if not args.python_only else ""
    checks: list[tuple[str, list[str], Path]] = []

    if not args.web_only:
        checks.extend(
            [
                ("ruff", [uv, "run", "ruff", "check", "."], root),
                ("pytest", [uv, "run", "python", "-m", "pytest", "-q", "--disable-warnings"], root),
                ("diagnose", [uv, "run", "python", "scripts/diagnose.py", "--json"], root),
            ]
        )
    if not args.python_only:
        checks.extend(
            [
                ("web check", [npm, "run", "check"], web_root),
                ("web unit", [npm, "run", "test"], web_root),
                ("web build", [npm, "run", "build"], web_root),
            ]
        )
        if args.all or args.e2e:
            checks.append(("fixture E2E", [npm, "run", "test:e2e"], web_root))
        if args.all or args.realdb:
            checks.append(("real DB E2E", [npm, "run", "test:e2e:realdb"], web_root))

    failures = [
        name
        for name, command, cwd in checks
        if not (
            run_diagnose_step(name, command, cwd)
            if name == "diagnose"
            else run_step(name, command, cwd)
        )
    ]
    if failures:
        print("\nSELF_CHECK FAILED:", ", ".join(failures))
        return 1
    print(f"\nSELF_CHECK PASSED: {len(checks)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
