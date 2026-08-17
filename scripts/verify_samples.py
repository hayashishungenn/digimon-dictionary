"""verify-samples: spot-check N random digimon + a fixed list (spec §63).

Each sampled digimon is checked for zh/en/ja names, level, attribute, image,
skills and profile. Absence is classified against the ``field_coverage`` audit
written at merge time (P0-2):

- ``present``            — field has a value.
- ``no_source``          — genuinely absent across all ingested sources.
- ``no_level``           — raw value(s) present but none map to a canonical enum.
- ``conflict``           — real unresolved cross-source disagreement.
- ``sync_failure``       — a source had the field but the pipeline lost it.
- (no coverage row)      — unexplained absence.

``sync_failure``/unexplained absences are hard failures and block the release
gate (exit 1). ``no_source``/``no_level``/``conflict`` are reported as visible,
documented gaps but do not block — the audit proves they are not silent drops.

The random sample is seeded (``--seed``, reproducible) and the full result is
written as JSON when ``--json`` is given, so the gate is auditable.

Usage:
    uv run python scripts/verify_samples.py [--n 50] [--seed 20260815] [--json PATH]
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
from datetime import datetime
from pathlib import Path

from pipeline.core.config import DB_PATH
from pipeline.core.schema import connect

FIXED = [
    "Agumon", "Gabumon", "Greymon", "WarGreymon", "Omegamon", "Tailmon", "Angewomon",
    "Renamon", "Dukemon", "Imperialdramon", "Lucemon", "Alphamon", "Jesmon",
    "Beelzebumon", "Shoutmon", "Gammamon",
]

# (coverage_field, label) — the fields spot-checked per sample.
FIELDS = [
    ("zh_cn", "中文名"),
    ("en", "英文名"),
    ("ja", "日文名"),
    ("level", "等级"),
    ("attribute", "属性"),
    ("image", "图片"),
    ("skills", "技能"),
    ("profile", "简介"),
]

# Coverage statuses that mean "the pipeline is missing data it should have had":
# these are real failures and must block publish.
HARD_FAIL = {"sync_failure"}
# Documented, sourced absences / pending review: reported but not a pipeline bug.
KNOWN_GAP = {"no_source", "no_level"}

# Default seed: stable across runs unless overridden, so random samples are
# reproducible (baseline date of the P0/P1 taskbook).
DEFAULT_SEED = 20260815


def _resolve_fixed(conn: sqlite3.Connection, name: str) -> int | None:
    """Resolve a fixed-list name to a digimon id (exact first, then LIKE)."""
    row = conn.execute(
        """SELECT id FROM digimon
           WHERE canonical_slug = ? COLLATE NOCASE
              OR name_en = ? COLLATE NOCASE
              OR name_ja = ?
           ORDER BY CASE WHEN canonical_slug = ? COLLATE NOCASE OR name_en = ? COLLATE NOCASE
                         THEN 0 ELSE 1 END
           LIMIT 1""",
        [name.lower().replace(" ", "-"), name, name,
         name.lower().replace(" ", "-"), name],
    ).fetchone()
    if row:
        return row["id"]
    row = conn.execute(
        "SELECT id FROM digimon WHERE name_en LIKE ? COLLATE NOCASE LIMIT 1",
        [f"%{name}%"],
    ).fetchone()
    return row["id"] if row else None


def check_digimon(conn: sqlite3.Connection, digimon_id: int) -> dict:
    """Spot-check one digimon; classify each field by the coverage audit."""
    d = conn.execute(
        """SELECT canonical_slug, name_zh_cn, name_en, name_ja, level, attribute,
                  main_image
           FROM digimon WHERE id = ?""",
        [digimon_id],
    ).fetchone()
    if d is None:
        return {"id": digimon_id, "found": False}

    cov = {r["field"]: r for r in conn.execute(
        "SELECT field, status, sources, detail FROM field_coverage WHERE digimon_id=?",
        [digimon_id],
    )}
    n_skills = conn.execute(
        "SELECT COUNT(*) FROM digimon_skill WHERE digimon_id=?", [digimon_id]
    ).fetchone()[0]
    has_profile = conn.execute(
        "SELECT profile_zh_cn IS NOT NULL AND TRIM(profile_zh_cn)!='' "
        "OR profile_en IS NOT NULL AND TRIM(profile_en)!='' "
        "OR profile_ja IS NOT NULL AND TRIM(profile_ja)!='' "
        "FROM digimon WHERE id=?", [digimon_id],
    ).fetchone()[0]

    present = {
        "zh_cn": bool(d["name_zh_cn"]),
        "en": bool(d["name_en"]),
        "ja": bool(d["name_ja"]),
        "level": bool(d["level"]) and d["level"] != "unknown",
        "attribute": bool(d["attribute"]) and d["attribute"] != "unknown",
        "image": bool(d["main_image"]),
        "skills": n_skills > 0,
        "profile": bool(has_profile),
    }

    problems: list[dict] = []
    gaps: list[dict] = []
    conflicts: list[dict] = []
    for field, label in FIELDS:
        if present[field]:
            continue
        c = cov.get(field)
        if c is None:
            problems.append({"field": field, "label": label, "status": "unexplained",
                             "detail": "no field_coverage row"})
        elif c["status"] in HARD_FAIL:
            problems.append({"field": field, "label": label, "status": c["status"],
                             "detail": c["detail"]})
        elif c["status"] == "conflict":
            conflicts.append({"field": field, "label": label, "status": "conflict",
                              "detail": c["detail"]})
        elif c["status"] in KNOWN_GAP:
            gaps.append({"field": field, "label": label, "status": c["status"],
                         "detail": c["detail"], "sources": c["sources"]})
        else:
            # present-but-absent contradiction or unknown status -> treat as failure
            problems.append({"field": field, "label": label, "status": c["status"],
                             "detail": c["detail"]})

    return {
        "id": digimon_id,
        "found": True,
        "slug": d["canonical_slug"],
        "names": f"{d['name_zh_cn']}/{d['name_en']}/{d['name_ja']}",
        "level": d["level"],
        "attribute": d["attribute"],
        "problems": problems,
        "gaps": gaps,
        "conflicts": conflicts,
    }


def _sample_category(result: dict) -> str:
    """P1-2: classify one sample by its dominant failure/gap reason.

    ``no_source`` — fields genuinely absent across ingested sources.
    ``fetch_failure`` — unexplained absence / a source had the data but it never
      reached the candidate (no coverage audit row).
    ``parse_failure`` — a source had the field but the pipeline lost it while
      parsing/normalizing (field_coverage status ``sync_failure``).
    ``match_failure`` — the sample could not be resolved to an entity at all.
    ``conflict`` — real unresolved cross-source disagreement (in review).
    ``image_missing`` — the only documented gap is the image field.
    """
    if not result["found"]:
        return "match_failure"
    if any(p["status"] == "sync_failure" for p in result["problems"]):
        return "parse_failure"
    if result["problems"]:
        return "fetch_failure"
    if result["conflicts"]:
        return "conflict"
    if any(g["field"] == "image" for g in result["gaps"]):
        return "image_missing"
    return "no_source"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--json", dest="json_path", type=Path, default=None)
    args = ap.parse_args(argv)

    conn = connect(DB_PATH)
    try:
        total = conn.execute("SELECT COUNT(*) FROM digimon").fetchone()[0]
        snap = conn.execute(
            "SELECT snapshot_date, official_count, extended_count, total_count "
            "FROM snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
        snapshot = dict(snap) if snap else None

        # seeded, reproducible random sample
        all_ids = [r[0] for r in conn.execute("SELECT id FROM digimon ORDER BY id")]
        rng = random.Random(args.seed)
        sample_ids = rng.sample(all_ids, min(args.n, len(all_ids)))

        print(f"=== 随机抽样 {len(sample_ids)} 只 / 总数 {total}（seed={args.seed}）===")
        random_results = [check_digimon(conn, i) for i in sample_ids]

        ok = sum(1 for r in random_results if r["found"] and not r["problems"])
        gap_count = sum(len(r["gaps"]) for r in random_results)
        conflict_count = sum(len(r["conflicts"]) for r in random_results)
        fail_results = [r for r in random_results if r["problems"] or not r["found"]]

        for r in random_results:
            status = "OK"
            if r["problems"]:
                status = "!!"
            elif r["conflicts"]:
                status = "??"
            elif r["gaps"]:
                status = ".."
            print(
                f"[{status}] {r.get('slug','?'):<30} {r.get('names','NOT FOUND'):<34} "
                f"{r.get('level',''):<10}{r.get('attribute',''):<9} "
                f"{('FAIL: ' + '; '.join(p['label'] for p in r['problems'])) if r['problems'] else ''}"
            )
            for p in r["problems"]:
                print(f"        FAIL {p['field']}: {p['status']} — {p['detail']}")
            for g in r["gaps"]:
                print(f"        gap  {g['field']}: {g['status']} (sources: {g['sources']})")
            for c in r["conflicts"]:
                print(f"        conf {c['field']}: {c['detail']}")

        print()
        print("=== 固定名单 ===")
        fixed_results: list[dict] = []
        fixed_fail = 0
        for name in FIXED:
            did = _resolve_fixed(conn, name)
            if did is None:
                fixed_fail += 1
                fixed_results.append({"name": name, "found": False})
                print(f"[!!] {name:<22} NOT FOUND")
                continue
            r = check_digimon(conn, did)
            r["name"] = name
            fixed_results.append(r)
            if not r["found"] or r["problems"]:
                fixed_fail += 1
                print(f"[!!] {name:<22} found={r['found']} "
                      f"problems={[p['field'] for p in r['problems']]}")
            else:
                print(f"[OK] {name:<22} {r['names']}")

        print()
        print(f"随机抽样 {ok}/{len(sample_ids)} 干净通过，"
              f"{gap_count} 项记录缺口（no_source/no_level），"
              f"{conflict_count} 项待复核冲突，"
              f"{len(fail_results)} 只存在硬性失败；固定名单 {len(FIXED) - fixed_fail}/{len(FIXED)}")

        if fail_results:
            print("HARD FAILURES (block publish):")
            for r in fail_results:
                for p in r.get("problems", []):
                    print(f"  - {r.get('slug','?')} {p['field']}: {p['status']} — {p['detail']}")
        if fixed_fail:
            print(f"FIXED SAMPLE FAILURES: {fixed_fail}")

        # P1-2: sample-level failure categories + the queue / run context so the
        # gate report is auditable against the live DB and its sync history.
        # ``manual_pending`` (items awaiting human review) is reported via
        # review_queue.open — the samples whose conflicts land there surface as
        # ``conflict``.
        def _categories(results: list[dict]) -> dict[str, int]:
            cats: dict[str, int] = {}
            for r in results:
                if r["found"] and not r["problems"] and not r["conflicts"] and not r["gaps"]:
                    continue  # fully clean
                c = _sample_category(r)
                cats[c] = cats.get(c, 0) + 1
            return cats

        latest_run = conn.execute(
            "SELECT run_id FROM sync_run ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        review_queue = conn.execute(
            "SELECT status, COUNT(*) c FROM manual_review_queue GROUP BY status"
        ).fetchall()
        review_queue_dict = {r["status"]: r["c"] for r in review_queue}
        run_sources = [
            r["source"] for r in conn.execute(
                "SELECT DISTINCT source FROM source_sync WHERE run_id = ? ORDER BY source",
                [latest_run["run_id"] if latest_run else ""],
            )
        ] if latest_run else None

        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "seed": args.seed,
            "run_id": latest_run["run_id"] if latest_run else None,
            "snapshot": snapshot,
            "sources": run_sources,
            "review_queue": {
                "open": review_queue_dict.get("open", 0),
                "resolved": review_queue_dict.get("resolved", 0),
                "wontfix": review_queue_dict.get("wontfix", 0),
            },
            "totals": {"total": total, "sampled": len(sample_ids),
                       "clean": ok, "gaps": gap_count, "conflicts": conflict_count,
                       "hard_failures": len(fail_results)},
            "failure_categories": _categories(random_results + fixed_results),
            "random_sample": random_results,
            "fixed_sample": fixed_results,
            "fixed_pass": len(FIXED) - fixed_fail,
            "fixed_total": len(FIXED),
        }
        if args.json_path:
            args.json_path.parent.mkdir(parents=True, exist_ok=True)
            args.json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
            print(f"report -> {args.json_path}")

        if fail_results or fixed_fail:
            print("VERIFICATION FAILED: hard failures or fixed-sample failures "
                  "(see above); do not publish.")
            return 1
        print("VERIFICATION PASSED: no hard failures; documented gaps are reported above.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
