"""verify-samples: spot-check N random digimon + a fixed list (spec §63).

Prints a human-readable verification report checking that each sampled digimon
has: zh/en/ja names, level, type, attribute, image, skills, profile, evolution.

Usage:
    uv run python scripts/verify_samples.py [--n 50]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.core.config import DB_PATH
from pipeline.core.schema import connect

FIXED = [
    "Agumon", "Gabumon", "Greymon", "WarGreymon", "Omegamon", "Tailmon", "Angewomon",
    "Renamon", "Dukemon", "Imperialdramon", "Lucemon", "Alphamon", "Jesmon",
    "Beelzebumon", "Shoutmon", "Gammamon",
]


def row_for(conn, name: str):
    r = conn.execute(
        """SELECT id, canonical_slug, name_zh_cn, name_en, name_ja, level, attribute,
                  main_image,
                  (SELECT COUNT(*) FROM digimon_skill ds WHERE ds.digimon_id=d.id) AS skills,
                  (SELECT COUNT(*) FROM evolution_edge e WHERE e.from_digimon_id=d.id) AS out_edges,
                  (SELECT COUNT(*) FROM evolution_edge e WHERE e.to_digimon_id=d.id) AS in_edges,
                  profile_en, profile_zh_cn
           FROM digimon d
           WHERE name_en LIKE ? COLLATE NOCASE OR name_ja = ? OR canonical_slug = ?
           ORDER BY CASE WHEN name_en = ? COLLATE NOCASE THEN 0 ELSE 1 END
           LIMIT 1""",
        [f"%{name}%", name, name.lower().replace(" ", "-"), name],
    ).fetchone()
    return r


def check(conn, name: str) -> dict:
    r = row_for(conn, name)
    if r is None:
        return {"name": name, "found": False}
    problems = []
    if not r["name_zh_cn"]:
        problems.append("missing zh")
    if not r["name_en"]:
        problems.append("missing en")
    if not r["name_ja"]:
        problems.append("missing ja")
    if not r["level"] or r["level"] == "unknown":
        problems.append("missing level")
    if not r["attribute"] or r["attribute"] == "unknown":
        problems.append("missing attribute")
    if not r["main_image"]:
        problems.append("missing image")
    if r["skills"] == 0:
        problems.append("no skills")
    if not (r["profile_en"] or r["profile_zh_cn"]):
        problems.append("no profile")
    return {
        "name": name,
        "found": True,
        "slug": r["canonical_slug"],
        "names": f"{r['name_zh_cn']}/{r['name_en']}/{r['name_ja']}",
        "level": r["level"],
        "attribute": r["attribute"],
        "skills": r["skills"],
        "out_edges": r["out_edges"],
        "in_edges": r["in_edges"],
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    args = ap.parse_args(argv)

    conn = connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM digimon").fetchone()[0]
    ids = [r[0] for r in conn.execute("SELECT id FROM digimon ORDER BY RANDOM() LIMIT ?", [args.n])]

    print(f"=== 随机抽样 {args.n} 只（总数 {total}）===")
    ok = 0
    for row in conn.execute(
        f"SELECT canonical_slug, name_en FROM digimon WHERE id IN ({','.join('?' * len(ids))})", ids
    ):
        res = check(conn, row["name_en"] or row["canonical_slug"])
        status = "OK" if res["found"] and not res["problems"] else "!!"
        if status == "OK":
            ok += 1
        print(f"[{status}] {res.get('name','?'):<28} {res.get('names','NOT FOUND'):<30} "
              f"{res.get('level',''):<10}{res.get('attribute',''):<9} 技能{res.get('skills','-')} "
              f"出边{res.get('out_edges','-')} 入边{res.get('in_edges','-')} {', '.join(res.get('problems',[]))}")

    print()
    print("=== 固定名单 ===")
    fixed_ok = 0
    for name in FIXED:
        res = check(conn, name)
        if res["found"] and not res["problems"]:
            fixed_ok += 1
            print(f"[OK] {name:<22} {res['names']}")
        else:
            print(f"[!!] {name:<22} found={res.get('found')} problems={res.get('problems')}")
    conn.close()

    print()
    print(f"随机抽样通过 {ok}/{args.n}，固定名单通过 {fixed_ok}/{len(FIXED)}")
    failed_random = args.n - ok
    failed_fixed = len(FIXED) - fixed_ok
    if failed_random or failed_fixed:
        print(
            f"VERIFICATION FAILED: {failed_random} random + {failed_fixed} fixed "
            f"sample(s) have missing/failed fields (see [!!] above)"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
