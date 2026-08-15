"""diagnose: read-only local health summary for DigiDex.

Prints the Python/Node/uv/npm versions, the database path + snapshot +
counts + image status, and the most recent sync run — everything a user needs
to know "is my local install current and healthy?" without hunting logs.

SECURITY (S1-4): this script NEVER prints tokens, cookies, environment
variables, or anything from `.env`. It only reads explicit facts from the DB,
the publish manifest, and a fixed set of version commands.
"""
from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

from pipeline.core.config import DB_PATH, IMAGES_DIR
from pipeline.core.manifest import manifest_path_for, read_manifest


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else "?"
    except (OSError, subprocess.SubprocessError):
        return "(not found)"


def _db_info(db: Path) -> dict:
    if not db.exists():
        return {"exists": False}
    info: dict = {"exists": True, "size_bytes": db.stat().st_size}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        info["schema_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
        info["integrity_ok"] = conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        snap = conn.execute(
            "SELECT snapshot_date, official_count, extended_count, total_count "
            "FROM snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if snap:
            info["snapshot_date"] = snap["snapshot_date"]
            info["counts"] = {
                "official": snap["official_count"], "extended": snap["extended_count"],
                "total": snap["total_count"],
            }
        img = conn.execute(
            "SELECT download_status, COUNT(*) c FROM digimon_image GROUP BY download_status"
        ).fetchall()
        info["images_by_status"] = {r["download_status"]: r["c"] for r in img}
        img_missing = conn.execute(
            "SELECT COUNT(*) FROM digimon WHERE main_image IS NULL OR TRIM(main_image)=''"
        ).fetchone()[0]
        info["digimon_without_main_image"] = img_missing
        run = conn.execute(
            "SELECT run_id, status, sources, snapshot_date, started_at, finished_at "
            "FROM sync_run ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if run:
            info["last_sync"] = dict(run)
        conn.close()
    except sqlite3.Error as exc:
        info["error"] = str(exc)
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DigiDex local health summary (read-only)")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    ap.add_argument("--db", type=str, default=str(DB_PATH),
                    help="database to inspect (default: data/digidex.sqlite)")
    args = ap.parse_args(argv)

    db_path = Path(args.db)
    manifest = read_manifest(manifest_path_for(db_path)) or {}
    db = _db_info(db_path)

    report = {
        "versions": {
            "python": _run([sys.executable, "--version"]),
            "uv": _run(["uv", "--version"]),
            "node": _run(["node", "--version"]),
            "npm": _run(["npm", "--version"]),
            "platform": platform.platform(),
        },
        "database": {
            "path": str(db_path),
            "exists": db.get("exists"),
            "size_bytes": db.get("size_bytes"),
            "schema_version": db.get("schema_version"),
            "integrity_ok": db.get("integrity_ok"),
            "snapshot_date": db.get("snapshot_date"),
            "counts": db.get("counts"),
            "images_by_status": db.get("images_by_status"),
            "digimon_without_main_image": db.get("digimon_without_main_image"),
        },
        "last_sync": db.get("last_sync"),
        "publish_manifest": {
            "run_id": manifest.get("run_id"),
            "snapshot_date": manifest.get("snapshot_date"),
            "image_stage": manifest.get("image_stage"),
            "state_committed": manifest.get("state_committed"),
            "is_incremental_baseline": manifest.get("is_incremental_baseline"),
        },
        "image_cache_dir": str(IMAGES_DIR),
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    v = report["versions"]
    print(f"versions:  python {v['python']}  uv {v['uv']}  node {v['node']}  npm {v['npm']}")
    d = report["database"]
    print(f"database:  {d['path']}  exists={d['exists']}  size={d['size_bytes']} bytes")
    if not d["exists"]:
        print("  (not synced yet — run: uv run python scripts/sync_data.py)")
        return 0
    print(f"  schema v{d['schema_version']}  integrity={'ok' if d['integrity_ok'] else 'FAILED'}")
    if d.get("snapshot_date"):
        c = d["counts"] or {}
        print(f"  snapshot {d['snapshot_date']}  total={c.get('total')} "
              f"official={c.get('official')} extended={c.get('extended')}")
    if d.get("images_by_status"):
        print(f"  images: {json.dumps(d['images_by_status'], ensure_ascii=False)}  "
              f"without_main_image={d['digimon_without_main_image']}")
    ls = report["last_sync"]
    if ls:
        print(f"last sync: run {ls['run_id']} status={ls['status']} sources={ls['sources']} "
              f"snapshot={ls.get('snapshot_date')} started={ls.get('started_at')} finished={ls.get('finished_at')}")
    m = report["publish_manifest"]
    if m["run_id"]:
        print(f"manifest:  run {m['run_id']} snapshot={m['snapshot_date']} "
              f"image_stage={m['image_stage']} state_committed={m['state_committed']} "
              f"baseline={m['is_incremental_baseline']}")
    else:
        print("manifest:  (none — run a publish to create one)")
    print(f"images:    {report['image_cache_dir']} (local cache, not committed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
