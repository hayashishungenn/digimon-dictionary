"""export-dataset: export the canonical DB to JSON / CSV / SQLite.

Usage:
    uv run python scripts/export_dataset.py [--formats json,csv,sqlite] [--out exports]
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path

from pipeline.core.config import DB_PATH, EXPORTS_DIR
from pipeline.core.schema import connect


def _read_all(conn: sqlite3.Connection, table: str) -> list[dict]:
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    except sqlite3.Error:
        return []
    rows = conn.execute(f"SELECT * FROM {table}").fetchall()
    return [dict(zip(cols, r, strict=False)) for r in rows]


def export_dataset(out_dir: Path, formats: list[str]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(DB_PATH)

    # --- JSON: nested digimon with relationships ---------------------------
    if "json" in formats:
        digimon = []
        rows = conn.execute("SELECT * FROM digimon ORDER BY id").fetchall()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(digimon)")]
        for row in rows:
            d = dict(zip(cols, row, strict=False))
            d["aliases"] = [r[0] for r in conn.execute(
                "SELECT alias FROM digimon_alias WHERE digimon_id=?", [d["id"]])]
            d["skills"] = [r[0] for r in conn.execute(
                """SELECT s.name_en FROM digimon_skill ds JOIN skill s ON s.id=ds.skill_id
                   WHERE ds.digimon_id=?""", [d["id"]])]
            d["fields"] = [r[0] for r in conn.execute(
                """SELECT f.name FROM digimon_field df JOIN field f ON f.id=df.field_id
                   WHERE df.digimon_id=?""", [d["id"]])]
            d["groups"] = [r[0] for r in conn.execute(
                """SELECT g.name FROM digimon_group dg JOIN grp g ON g.id=dg.group_id
                   WHERE dg.digimon_id=?""", [d["id"]])]
            d["evolves_to"] = [r[0] for r in conn.execute(
                """SELECT d2.canonical_slug FROM evolution_edge e
                   JOIN digimon d2 ON d2.id=e.to_digimon_id WHERE e.from_digimon_id=?""", [d["id"]])]
            d["evolves_from"] = [r[0] for r in conn.execute(
                """SELECT d1.canonical_slug FROM evolution_edge e
                   JOIN digimon d1 ON d1.id=e.from_digimon_id WHERE e.to_digimon_id=?""", [d["id"]])]
            digimon.append(d)

        payload = {
            "export_version": 1,
            "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
            "digimon": digimon,
            "types": _read_all(conn, "type"),
            "fields": _read_all(conn, "field"),
            "groups": _read_all(conn, "grp"),
            "skills": _read_all(conn, "skill"),
            "evolution_edges": _read_all(conn, "evolution_edge"),
        }
        (out_dir / "digimon.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")

    # --- CSV: flat tables --------------------------------------------------
    if "csv" in formats:
        flat = conn.execute(
            """SELECT id, canonical_slug, name_zh_cn, name_en, name_ja, name_romanized,
                      level, attribute, x_antibody, is_official_reference, is_extended,
                      first_appearance_title, main_image
               FROM digimon ORDER BY id"""
        ).fetchall()
        cols = ["id", "canonical_slug", "name_zh_cn", "name_en", "name_ja", "name_romanized",
                "level", "attribute", "x_antibody", "is_official_reference", "is_extended",
                "first_appearance_title", "main_image"]
        with open(out_dir / "digimon.csv", "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(flat)
        # evolution edges csv
        with open(out_dir / "evolution_edges.csv", "w", newline="", encoding="utf-8-sig") as fh:
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

    # --- SQLite copy -------------------------------------------------------
    if "sqlite" in formats:
        dest = out_dir / "digidex.sqlite"
        if dest.exists():
            dest.unlink()
        src = sqlite3.connect(DB_PATH)
        dst = sqlite3.connect(dest)
        src.backup(dst)
        dst.close()
        src.close()

    conn.close()
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
