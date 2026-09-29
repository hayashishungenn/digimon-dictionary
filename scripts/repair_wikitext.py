"""repair-wikitext: clean raw wikitext residue out of user-visible short fields.

`digimon_alias.alias` and `skill.name_*` / `skill.description_*` were written
verbatim, while `profile` and `name_origin` already went through the P1-2 safety
net — so a language comment (`<!--Simplified Chinese--> 黑暗巨龙兽`), a trailing
template (`AeroVeedramon{{DD|a|earov-dramon}}`), a self-closing ref
(`<ref name=DRA/>`) and a truncated template (`シュ{{FGM`) all reached the DB and
were served straight into the search index (`digimon_fts.aliases` included).

The pipeline now cleans those same fields on write (``_plain`` in
``pipeline/merge/store.py``), so a re-sync stays clean; this script repairs a
database that was built before that.

Nothing is dropped silently: every changed value queues a ``manual_review_queue``
item holding the original text, and an alias that collapses onto an existing row
has its provenance (source / alias_type / verified) merged into the kept row —
the same rule ``_migrate_v2`` uses.

Usage:
    uv run python scripts/repair_wikitext.py [--dry-run] [--no-backup] [--show N]

Exit code is 0 even when nothing needed repair.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from typing import Any

from pipeline.core.backup import create_backup
from pipeline.core.config import DB_PATH
from pipeline.merge.store import CanonicalStore, _plain

# Every user-visible short field that used to be written verbatim.
# (table, id column, entity_type for the review queue, [value columns])
TARGETS = [
    ("digimon_alias", "id", "digimon", ["alias"]),
    # The `digimon` name columns are user-visible AND feed `digimon_fts`, so
    # `<!--Traditional Chinese--> 黑暗巨龍獸` was searchable verbatim. These are
    # plain data columns (rows are matched by canonical_slug), so rewriting them
    # cannot affect merge identity.
    ("digimon", "id", "digimon", ["name_zh_cn", "name_zh_tw", "name_zh_hk",
                                  "name_en", "name_en_dub", "name_ja",
                                  "name_romanized"]),
    ("skill", "id", "skill", ["name_zh_cn", "name_en", "name_ja",
                              "description_zh_cn", "description_en", "description_ja"]),
]

# Deliberately NOT repaired, and why — a repair run should not silently widen:
#   type.name / field.name / grp.name  — these ARE the merge lookup keys
#     (`_ensure_type` matches on `name`), so rewriting one would make the next
#     sync insert a duplicate row instead of matching it (2 rows affected).
#   evolution_edge.condition (3282)    — raw wikitext, but the field is a
#     relationship's condition text, not a name; needs its own decision.
#   skill.match_key (11)               — derived join key; changing it changes
#     skill identity/deduplication.
#   digimon_image.remote_url/source_page (4+4) — `{{!}}` inside an image URL
#     encodes a `|`; "fixing" it breaks the image path.
#   manual_review_queue.detail (224)   — the review queue's whole purpose is to
#     preserve the original text.


_ALIAS_COLUMNS = ("digimon_id", "alias", "language", "region", "alias_type", "source", "verified")


def _queue(conn: sqlite3.Connection, entity_type: str, entity_id: int | None,
           field: str, original: str) -> None:
    conn.execute(
        """INSERT INTO manual_review_queue(entity_type, entity_id, reason, detail, run_id)
           VALUES(?,?,?,?,?)""",
        [entity_type, entity_id,
         f"{field} contained unresolved wikitext (repaired)",
         json.dumps({"field": field, "original": original[:300]}, ensure_ascii=False),
         None],
    )


def _repair_aliases(conn: sqlite3.Connection, dry: bool, show: int) -> dict[str, int]:
    """Aliases need delete-then-reinsert: the unique index
    (digimon_id, alias, language) rejects a plain UPDATE when two rows collapse
    onto the same value, and a collision must merge provenance, not abort."""
    rows = conn.execute(
        "SELECT id, %s FROM digimon_alias ORDER BY id" % ", ".join(_ALIAS_COLUMNS)
    ).fetchall()
    plan = [(r, _plain(r["alias"])) for r in rows if _plain(r["alias"]) != r["alias"]]
    stat = {"changed": 0, "dropped": 0, "merged": 0}
    printed = 0
    for row, new in plan:
        if show and printed < show:
            print("  alias  %-9s %r -> %r"
                  % ("drop" if not new else "rewrite", row["alias"][:70], new))
            printed += 1
        if dry:
            continue
        conn.execute("DELETE FROM digimon_alias WHERE id = ?", [row["id"]])
        _queue(conn, "digimon", row["digimon_id"], "alias", row["alias"])
        stat["dropped" if not new else "changed"] += 1
        if not new:
            continue
        hit = conn.execute(
            "SELECT id, source, alias_type, verified FROM digimon_alias "
            "WHERE digimon_id = ? AND alias = ? AND language IS ?",
            [row["digimon_id"], new, row["language"]],
        ).fetchone()
        if hit:
            # Same (digimon_id, alias, language) already exists: keep that row and
            # fold this one's provenance in, so nothing is lost to the dedupe.
            sources = [s for s in (hit["source"], row["source"]) if s]
            conn.execute(
                "UPDATE digimon_alias SET source=?, alias_type=?, verified=? WHERE id=?",
                [",".join(dict.fromkeys(sources)) or None,
                 hit["alias_type"] or row["alias_type"],
                 max(hit["verified"] or 0, row["verified"] or 0),
                 hit["id"]],
            )
            stat["merged"] += 1
            continue
        conn.execute(
            "INSERT INTO digimon_alias(%s) VALUES(%s)"
            % (", ".join(_ALIAS_COLUMNS), ",".join("?" * len(_ALIAS_COLUMNS))),
            [row[c] if c != "alias" else new for c in _ALIAS_COLUMNS],
        )
    return stat


def _repair_table(conn: sqlite3.Connection, table: str, id_col: str, entity_type: str,
                  columns: list[str], dry: bool, show: int) -> dict[str, int]:
    stat: dict[str, int] = {"changed": 0, "emptied": 0}
    printed = 0
    for col in columns:
        rows = conn.execute(
            "SELECT %s AS id, %s AS v FROM %s WHERE %s IS NOT NULL AND %s <> ''"
            % (id_col, col, table, col, col)
        ).fetchall()
        for row in rows:
            new: Any = _plain(row["v"])
            if new == row["v"]:
                continue
            if show and printed < show:
                print("  %-8s %-18s #%-6s %r -> %r"
                      % (table, col, row["id"], row["v"][:70], new))
                printed += 1
            if dry:
                continue
            conn.execute("UPDATE %s SET %s = ? WHERE %s = ?" % (table, col, id_col),
                         [new, row["id"]])
            _queue(conn, entity_type, row["id"], col, row["v"])
            stat["changed" if new else "emptied"] += 1
    return stat


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Repair wikitext residue in the canonical DB")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would change without writing (no backup either)")
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the pre-repair backup (not recommended)")
    ap.add_argument("--show", type=int, default=10,
                    help="print this many before/after pairs (0 = silent)")
    args = ap.parse_args(argv)

    if not args.dry_run and not args.no_backup:
        out = create_backup(db_path=DB_PATH)
        print("[backup] %s" % out)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        alias_stat = _repair_aliases(conn, args.dry_run, args.show)
        per_table: dict[str, dict[str, int]] = {}
        for table, id_col, entity_type, columns in TARGETS:
            if table == "digimon_alias":
                continue
            per_table[table] = _repair_table(conn, table, id_col, entity_type, columns,
                                            args.dry_run, args.show)
        if not args.dry_run:
            # aliases and the digimon name columns feed digimon_fts.aliases /
            # digimon_fts.*, so the index has to be rebuilt or the web app keeps
            # serving the pre-repair text.
            CanonicalStore(conn).rebuild_fts()
            conn.commit()
        label = "dry-run" if args.dry_run else "done"
        print("[%s] alias: %d rewritten, %d dropped, %d merged"
              % (label, alias_stat["changed"], alias_stat["dropped"], alias_stat["merged"]))
        for table in sorted(per_table):
            s = per_table[table]
            print("[%s] %s: %d rewritten, %d emptied" % (label, table, s["changed"], s["emptied"]))
        if not args.dry_run:
            left = _residue_count(conn)
            print("[verify] rows still carrying markup: %d" % left)
            return 1 if left else 0
        return 0
    finally:
        conn.close()


def _residue_count(conn: sqlite3.Connection) -> int:
    """Re-scan with the same cleaner: 0 means the repair really took."""
    left = 0
    for table, id_col, _entity, columns in TARGETS:
        for col in columns:
            for (v,) in conn.execute(
                    "SELECT %s FROM %s WHERE %s IS NOT NULL AND %s <> ''"
                    % (col, table, col, col)):
                if _plain(v) != v:
                    left += 1
    return left


if __name__ == "__main__":
    raise SystemExit(main())
