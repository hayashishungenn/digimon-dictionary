"""review-queue: filter, inspect, resolve, export, and audit manual review items.

Turns `manual_review_queue` into an actionable local workflow (S1-1): find an
entity's open items, see the original candidate/wikitext, mark items
resolved/wontfix with an explanation, and export without deleting anything.

Categories (derived from the item reason):
  external_target  — an evolution/relation edge references a target outside the
                     current dataset (not a match bug)
  matching_failure — an entity could not be safely matched/merged
  conflict         — real cross-source disagreement source priority couldn't settle
  wikitext         — a user-visible field still carries raw wikitext (original here)
  other            — e.g. unmatched game records

Usage:
    uv run python scripts/review_queue.py stats
    uv run python scripts/review_queue.py list [--status open] [--entity-type edge]
        [--category external_target] [--q TERM] [--limit 50] [--json]
    uv run python scripts/review_queue.py show <id>
    uv run python scripts/review_queue.py resolve <id> --status wontfix --note "..."
    uv run python scripts/review_queue.py export --status open --format csv --out queue.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from apps.api import queries
from pipeline.core.config import DB_PATH
from pipeline.core.schema import connect_readonly


def _conn() -> sqlite3.Connection:
    db = Path(os.environ.get("DIGIDEX_DB", str(DB_PATH)))
    if not db.exists():
        print(f"ERROR: database not found: {db} (run scripts/sync_data.py)", file=sys.stderr)
        raise SystemExit(1)
    return connect_readonly(db)


def _short(s: str | None, n: int = 70) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _print_table(rows: list[dict]) -> None:
    if not rows:
        print("(no matching review items)")
        return
    headers = ["id", "entity_type", "entity_id", "category", "status", "reason"]
    widths = {h: len(h) for h in headers}
    for r in rows:
        vals = {h: str(r.get(h) or "") for h in headers}
        for h in headers:
            widths[h] = max(widths[h], len(vals[h]))
    print("  ".join(h.ljust(widths[h]) for h in headers))
    print("  ".join("-" * widths[h] for h in headers))
    for r in rows:
        vals = {h: str(r.get(h) or "") for h in headers}
        # reason column gets some slack
        print("  ".join(vals[h].ljust(widths[h]) for h in headers))
        if r.get("note"):
            print(f"    note: {r['note']}")
        if r.get("detail"):
            print(f"    detail: {json.dumps(r['detail'], ensure_ascii=False)[:120]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DigiDex manual review workflow")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_stats = sub.add_parser("stats", help="open-item counts by status/entity/category")
    p_stats.add_argument("--json", action="store_true")

    p_list = sub.add_parser("list", help="list review items")
    p_list.add_argument("--status", default="open", choices=["open", "resolved", "wontfix"])
    p_list.add_argument("--entity-type", default=None)
    p_list.add_argument("--category", default=None,
                        choices=["external_target", "matching_failure", "conflict", "wikitext", "other"])
    p_list.add_argument("--q", default=None, help="substring in reason/detail")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="show one item in full (incl. original candidate)")
    p_show.add_argument("id", type=int)

    p_res = sub.add_parser("resolve", help="mark an item resolved/wontfix with a note")
    p_res.add_argument("id", type=int)
    p_res.add_argument("--status", required=True, choices=["resolved", "wontfix"])
    p_res.add_argument("--note", required=True, help="explanation (wontfix ≠ fact verified)")

    p_exp = sub.add_parser("export", help="export items as JSON or CSV (never deletes)")
    p_exp.add_argument("--status", default="open", choices=["open", "resolved", "wontfix"])
    p_exp.add_argument("--entity-type", default=None)
    p_exp.add_argument("--format", default="csv", choices=["csv", "json"])
    p_exp.add_argument("--out", required=True)

    args = ap.parse_args(argv)
    conn = _conn()

    if args.cmd == "stats":
        stats = queries.review_stats(conn)
        if args.json:
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        else:
            print(f"open:      {stats['open']}")
            print(f"by_status: {json.dumps(stats['by_status'], ensure_ascii=False)}")
            print(f"by_entity: {json.dumps(stats['by_entity'], ensure_ascii=False)}")
            print(f"by_category: {json.dumps(stats['by_category'], ensure_ascii=False)}")
        conn.close()
        return 0

    if args.cmd == "list":
        items = queries.list_review_items(
            conn, status=args.status, entity_type=args.entity_type, q=args.q,
            category=args.category, limit=args.limit,
        )
        if args.json:
            print(json.dumps(items, ensure_ascii=False, indent=2))
        else:
            _print_table(items)
        conn.close()
        return 0

    if args.cmd == "show":
        target = None
        for st in ("open", "resolved", "wontfix"):
            target = next((i for i in queries.list_review_items(conn, status=st) if i["id"] == args.id), None)
            if target:
                break
        if target is None:
            print(f"ERROR: no review item #{args.id}", file=sys.stderr)
            conn.close()
            return 1
        print(json.dumps(target, ensure_ascii=False, indent=2))
        conn.close()
        return 0

    if args.cmd == "resolve":
        # resolution must go through a writable connection
        conn.close()
        from pipeline.core.schema import connect

        conn = connect(Path(os.environ.get("DIGIDEX_DB", str(DB_PATH))))
        try:
            row = queries.resolve_review_item(conn, args.id, status=args.status, note=args.note)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            conn.close()
            return 1
        if row is None:
            print(f"ERROR: no open review item #{args.id}", file=sys.stderr)
            conn.close()
            return 1
        print(f"#{row['id']} [{row['entity_type']}] -> {row['status']}  note={row['note']}")
        conn.close()
        return 0

    if args.cmd == "export":
        items = queries.list_review_items(
            conn, status=args.status, entity_type=args.entity_type, limit=10000,
        )
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "json":
            out.write_text(json.dumps(items, ensure_ascii=False, indent=2), "utf-8")
        else:
            import csv as _csv

            with out.open("w", encoding="utf-8", newline="") as f:
                w = _csv.writer(f)
                w.writerow(["id", "entity_type", "entity_id", "category", "status", "reason",
                            "detail", "created_at", "resolved_at", "run_id", "note"])
                for it in items:
                    w.writerow([it["id"], it["entity_type"], it["entity_id"], it["category"],
                                it["status"], it["reason"],
                                json.dumps(it["detail"], ensure_ascii=False),
                                it["created_at"], it["resolved_at"], it["run_id"], it["note"]])
        print(f"exported {len(items)} items -> {out}")
        conn.close()
        return 0

    conn.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
