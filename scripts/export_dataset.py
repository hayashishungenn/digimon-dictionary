"""export-dataset: export the canonical DB to JSON / CSV / SQLite.

Fail-safe design (T9):
- Every export writes to a temp file and is atomically replaced — a failed
  export never destroys an existing target file.
- SQLite backup goes to a temp file first; the target is replaced only after a
  successful backup, and every connection is closed with a clear boundary.
- JSON joins are batched (no per-digimon N+1 queries).
- CSV is written via the stdlib csv module, which handles commas, newlines,
  quotes, and Unicode; NULL values become empty cells.

Usage:
    uv run python scripts/export_dataset.py [--formats json,csv,sqlite] [--out exports]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from pipeline.core.config import DB_PATH, EXPORTS_DIR
from pipeline.core.schema import connect

EXPORT_VERSION = 3


def _atomic_write(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Write `text` to `path` atomically via a temp file + replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding=encoding)
    os.replace(tmp, path)


def _read_all(conn: sqlite3.Connection, table: str) -> list[dict]:
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return []
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(zip(cols, r, strict=False)) for r in rows]


def _group_rows(rows, key: str) -> dict[int, list[dict]]:
    """rows -> {key_value: [dict, ...]} preserving order."""
    out: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        out[r[key]].append(dict(r))
    return out


def _dataset_summary(conn: sqlite3.Connection) -> dict:
    """Concise dataset header so consumers know which snapshot they got (S1-3)."""
    snap = conn.execute(
        "SELECT snapshot_date, official_count, extended_count, total_count "
        "FROM snapshot ORDER BY id DESC LIMIT 1"
    ).fetchone()
    schema_version = conn.execute("PRAGMA user_version").fetchone()[0]
    return {
        "schema_version": schema_version,
        "snapshot_date": snap[0] if snap else None,
        "official_count": snap[1] if snap else None,
        "extended_count": snap[2] if snap else None,
        "total_count": snap[3] if snap else None,
    }


def _export_json(conn: sqlite3.Connection, out_dir: Path) -> None:
    """Nested digimon JSON with batched joins (no N+1) plus every data domain."""
    digimon_rows = conn.execute("SELECT * FROM digimon ORDER BY id").fetchall()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(digimon)")]

    # batch-load join tables grouped by digimon id — 5 queries, not 5 per digimon
    aliases = _group_rows(conn.execute(
        "SELECT digimon_id, alias, language, alias_type, source, verified "
        "FROM digimon_alias ORDER BY digimon_id, id"), "digimon_id")
    skills = _group_rows(conn.execute(
        """SELECT ds.digimon_id, s.id AS skill_id, s.name_en, s.name_zh_cn, s.name_ja,
                  ds.skill_type, ds.is_signature
           FROM digimon_skill ds JOIN skill s ON s.id = ds.skill_id
           ORDER BY ds.digimon_id, ds.sort_order"""), "digimon_id")
    fields = _group_rows(conn.execute(
        """SELECT df.digimon_id, f.name, f.name_zh FROM digimon_field df
           JOIN field f ON f.id = df.field_id ORDER BY df.digimon_id, f.name"""), "digimon_id")
    groups = _group_rows(conn.execute(
        """SELECT dg.digimon_id, g.name, g.name_zh FROM digimon_group dg
           JOIN grp g ON g.id = dg.group_id ORDER BY dg.digimon_id, g.name"""), "digimon_id")
    images = _group_rows(conn.execute(
        """SELECT digimon_id, image_type, remote_url, local_path, width, height,
                  transparent, sha256, download_status
           FROM digimon_image ORDER BY digimon_id, id"""), "digimon_id")
    game_stats = _group_rows(conn.execute(
        """SELECT s.digimon_id, g.short_name AS game, s.hp, s.sp, s.atk, s.def, s.int,
                  s.spd, s.memory, s.slots, s.extras
           FROM game_digimon_stats s JOIN game g ON g.id = s.game_id
           ORDER BY s.digimon_id"""), "digimon_id")

    # evolution edges as slug pairs (id -> slug map)
    slug_of = {r["id"]: r["canonical_slug"] for r in digimon_rows}
    edges = conn.execute(
        "SELECT from_digimon_id, to_digimon_id, evolution_type, condition, source, is_primary_line "
        "FROM evolution_edge ORDER BY id"
    ).fetchall()
    evolves_to: dict[int, list[str]] = defaultdict(list)
    evolves_from: dict[int, list[str]] = defaultdict(list)
    for e in edges:
        f, t = slug_of.get(e["from_digimon_id"]), slug_of.get(e["to_digimon_id"])
        if f and t:
            evolves_to[e["from_digimon_id"]].append(t)
            evolves_from[e["to_digimon_id"]].append(f)

    digimon: list[dict] = []
    for row in digimon_rows:
        d = dict(zip(cols, row, strict=False))
        did = d["id"]
        d["aliases"] = aliases.get(did, [])
        d["skills"] = skills.get(did, [])
        d["fields"] = [x["name"] for x in fields.get(did, [])]
        d["groups"] = [x["name"] for x in groups.get(did, [])]
        d["images"] = images.get(did, [])
        d["game_stats"] = game_stats.get(did, [])
        d["evolves_to"] = evolves_to.get(did, [])
        d["evolves_from"] = evolves_from.get(did, [])
        digimon.append(d)

    payload = {
        "export_version": EXPORT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": _dataset_summary(conn),
        "digimon": digimon,
        "types": _read_all(conn, "type"),
        "fields": _read_all(conn, "field"),
        "groups": _read_all(conn, "grp"),
        "skills": _read_all(conn, "skill"),
        "evolution_edges": [dict(e) for e in edges],
        "relations": _read_all(conn, "digimon_relation"),
        "images": _read_all(conn, "digimon_image"),
        "provenance": _read_all(conn, "provenance"),
        "conflicts": _read_all(conn, "data_conflict"),
        "review_queue": _read_all(conn, "manual_review_queue"),
        "game_stats": _read_all(conn, "game_digimon_stats"),
        "snapshot": _read_all(conn, "snapshot"),
        "source_sync": _read_all(conn, "source_sync"),
    }
    _atomic_write(out_dir / "digimon.json", json.dumps(payload, ensure_ascii=False, indent=1))


def _export_csv(conn: sqlite3.Connection, out_dir: Path) -> None:
    """Flat CSV digests. csv.writer handles quoting/Unicode; NULL -> empty cell.

    Includes provenance-adjacent columns (name status / source / verified) so a
    consumer can tell official from unverified without a second lookup (S1-3).
    """
    flat = conn.execute(
        """SELECT id, canonical_slug, name_zh_cn, name_en, name_ja, name_romanized,
                  name_zh_cn_status, name_zh_cn_source, level, attribute,
                  x_antibody, is_official_reference, is_extended,
                  profile_verified, first_appearance_date, main_image
           FROM digimon ORDER BY id"""
    ).fetchall()
    cols = ["id", "canonical_slug", "name_zh_cn", "name_en", "name_ja", "name_romanized",
            "name_zh_cn_status", "name_zh_cn_source", "level", "attribute",
            "x_antibody", "is_official_reference", "is_extended",
            "profile_verified", "first_appearance_date", "main_image"]

    tmp = out_dir / "digimon.csv.tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerows(flat)
    os.replace(tmp, out_dir / "digimon.csv")

    edges_tmp = out_dir / "evolution_edges.csv.tmp"
    with open(edges_tmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["from", "to", "evolution_type", "condition", "source", "is_primary_line"])
        for e in conn.execute(
            """SELECT d1.canonical_slug, d2.canonical_slug, e.evolution_type, e.condition,
                      e.source, e.is_primary_line
               FROM evolution_edge e
               JOIN digimon d1 ON d1.id=e.from_digimon_id
               JOIN digimon d2 ON d2.id=e.to_digimon_id
               ORDER BY d1.id"""
        ).fetchall():
            w.writerow(e)
    os.replace(edges_tmp, out_dir / "evolution_edges.csv")


def _export_sqlite(out_dir: Path) -> None:
    """Backup the DB to a temp file, then atomically replace the target.

    The existing target is never unlinked first: a failed backup leaves the old
    export untouched. The source connection is closed before the replace.
    """
    dest = out_dir / "digidex.sqlite"
    tmp = out_dir / "digidex.sqlite.tmp"
    if tmp.exists():
        tmp.unlink()
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, dest)


def export_dataset(out_dir: Path, formats: list[str]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(DB_PATH)
    try:
        if "json" in formats:
            _export_json(conn, out_dir)
        if "csv" in formats:
            _export_csv(conn, out_dir)
    finally:
        conn.close()
    if "sqlite" in formats:
        _export_sqlite(out_dir)
    return {"formats": formats, "dir": str(out_dir)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", default="json,csv,sqlite")
    ap.add_argument("--out", type=Path, default=EXPORTS_DIR)
    args = ap.parse_args(argv)
    result = export_dataset(args.out, [f.strip() for f in args.formats.split(",")])
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
