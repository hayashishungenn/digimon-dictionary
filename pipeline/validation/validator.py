"""Data quality validation & coverage reports (product spec §49–§54).

All checks run against the built database and produce a structured report
written to data/reports/data-quality.json and data/reports/data-quality.md.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pipeline.core.config import REPORTS_DIR
from pipeline.core.schema import connect

# Fixed digimon that must be spot-verified in every report (spec §63).
FIXED_SAMPLE = [
    "Agumon",
    "Gabumon",
    "Greymon",
    "WarGreymon",
    "Omegamon",
    "Tailmon",
    "Angewomon",
    "Renamon",
    "Dukemon",
    "Imperialdramon",
    "Lucemon",
    "Alphamon",
    "Jesmon",
    "Beelzebumon",
    "Shoutmon",
    "Gammamon",
]


def validate(conn: sqlite3.Connection) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []

    def issue(level: str, check: str, message: str, **extra: Any) -> None:
        issues.append({"level": level, "check": check, "message": message, **extra})

    # --- digimon integrity ------------------------------------------------
    dup_slug = conn.execute(
        """SELECT canonical_slug, COUNT(*) c FROM digimon GROUP BY canonical_slug HAVING c > 1"""
    ).fetchall()
    for r in dup_slug:
        issue("error", "duplicate_canonical_slug", f"slug '{r['canonical_slug']}' appears {r['c']}x")

    dup_dapi = conn.execute(
        """SELECT dapi_id, COUNT(*) c FROM digimon WHERE dapi_id IS NOT NULL
           GROUP BY dapi_id HAVING c > 1"""
    ).fetchall()
    for r in dup_dapi:
        issue("error", "duplicate_external_id", f"dapi_id {r['dapi_id']} appears {r['c']}x")

    for col, label in (
        ("name_zh_cn", "Chinese"),
        ("name_en", "English"),
        ("name_ja", "Japanese"),
    ):
        n = conn.execute(f"SELECT COUNT(*) FROM digimon WHERE {col} IS NULL OR TRIM({col})=''").fetchone()[0]
        if n:
            issue("warning", f"missing_{col}", f"{n} digimon missing {label} name")

    for col, label in (("level", "level"), ("attribute", "attribute")):
        n = conn.execute(f"SELECT COUNT(*) FROM digimon WHERE {col} IS NULL OR {col}='unknown'").fetchone()[0]
        if n:
            issue("info", f"missing_{col}", f"{n} digimon missing/unknown {label}")

    # --- evolution graph integrity -----------------------------------------
    bad_from = conn.execute(
        """SELECT COUNT(*) FROM evolution_edge e
           LEFT JOIN digimon d ON d.id = e.from_digimon_id
           WHERE d.id IS NULL"""
    ).fetchone()[0]
    if bad_from:
        issue("error", "broken_evolution_edge", f"{bad_from} edges reference missing 'from' digimon")

    bad_to = conn.execute(
        """SELECT COUNT(*) FROM evolution_edge e
           LEFT JOIN digimon d ON d.id = e.to_digimon_id
           WHERE d.id IS NULL"""
    ).fetchone()[0]
    if bad_to:
        issue("error", "broken_evolution_edge", f"{bad_to} edges reference missing 'to' digimon")

    self_edges = conn.execute(
        "SELECT COUNT(*) FROM evolution_edge WHERE from_digimon_id = to_digimon_id"
    ).fetchone()[0]
    if self_edges:
        issue("warning", "self_evolution", f"{self_edges} self-loops (may be legit for some modes)")

    dup_edges = conn.execute(
        """SELECT from_digimon_id, to_digimon_id, evolution_type, COUNT(*) c
           FROM evolution_edge GROUP BY from_digimon_id, to_digimon_id, evolution_type HAVING c > 1"""
    ).fetchall()
    for r in dup_edges:
        issue("warning", "duplicate_evolution_edge", f"edge {r[0]}->{r[1]} ({r[2]}) appears {r[3]}x")

    # --- near-duplicate entities (same ja + same zh, different en) ----------
    dup_groups = conn.execute(
        """SELECT name_ja, name_zh_cn, COUNT(*) c
           FROM digimon
           WHERE name_ja IS NOT NULL AND TRIM(name_ja) != ''
             AND name_zh_cn IS NOT NULL AND TRIM(name_zh_cn) != ''
           GROUP BY name_ja, name_zh_cn HAVING c > 1"""
    ).fetchall()
    for g in dup_groups:
        members = conn.execute(
            """SELECT canonical_slug, name_en FROM digimon
               WHERE name_ja = ? AND name_zh_cn = ? ORDER BY name_en""",
            [g["name_ja"], g["name_zh_cn"]],
        ).fetchall()
        en_set = {m["name_en"] for m in members}
        if len(en_set) > 1:  # same ja+zh but different English names → likely duplicate
            issue(
                "warning", "duplicate_entity",
                f"{g['name_ja']} / {g['name_zh_cn']} appears as {len(members)} entities: "
                f"{', '.join(m['canonical_slug'] for m in members)}",
            )

    # --- orphan references ---------------------------------------------------
    for tbl, _fk in (("digimon_skill", "skill_id"), ("digimon_alias", "digimon_id")):
        orphans = conn.execute(
            f"""SELECT COUNT(*) FROM {tbl} o LEFT JOIN digimon d ON d.id = o.digimon_id
                WHERE o.digimon_id IS NOT NULL AND d.id IS NULL"""
        ).fetchone()[0]
        if orphans:
            issue("error", "orphan_relation", f"{orphans} orphan rows in {tbl}")

    orphan_skills = conn.execute(
        """SELECT COUNT(*) FROM skill s
           LEFT JOIN digimon_skill ds ON ds.skill_id = s.id WHERE ds.skill_id IS NULL"""
    ).fetchone()[0]
    if orphan_skills:
        issue("info", "orphan_skill", f"{orphan_skills} skills not attached to any digimon")

    # --- images ---------------------------------------------------------------
    img_stats = conn.execute(
        """SELECT download_status, COUNT(*) c FROM digimon_image GROUP BY download_status"""
    ).fetchall()
    img_missing = conn.execute(
        "SELECT COUNT(*) FROM digimon WHERE main_image IS NULL OR TRIM(main_image)=''"
    ).fetchone()[0]
    img_broken = conn.execute(
        "SELECT COUNT(*) FROM digimon_image WHERE download_status = 'failed'"
    ).fetchone()[0]
    img_pending = conn.execute(
        "SELECT COUNT(*) FROM digimon_image WHERE download_status = 'pending'"
    ).fetchone()[0]
    if img_broken:
        issue("warning", "broken_image",
              f"{img_broken} image downloads failed (broken image URLs)")
    if img_pending:
        issue("info", "image_pending",
              f"{img_pending} images not yet downloaded")

    # --- coverage --------------------------------------------------------------
    def coverage(column: str) -> dict[str, int]:
        total = conn.execute("SELECT COUNT(*) FROM digimon").fetchone()[0]
        have = conn.execute(
            f"SELECT COUNT(*) FROM digimon WHERE {column} IS NOT NULL AND TRIM({column}) != ''"
        ).fetchone()[0]
        return {"total": total, "present": have, "pct": round(have / total * 100, 1) if total else 0}

    zh_status = conn.execute(
        """SELECT name_zh_cn_status, COUNT(*) c FROM digimon
           WHERE name_zh_cn IS NOT NULL GROUP BY name_zh_cn_status"""
    ).fetchall()
    zh_status_dict = {r["name_zh_cn_status"]: r["c"] for r in zh_status}

    skill_stats = {
        "digimon_with_skills": conn.execute(
            "SELECT COUNT(DISTINCT digimon_id) FROM digimon_skill"
        ).fetchone()[0],
        "total_skills": conn.execute("SELECT COUNT(*) FROM skill").fetchone()[0],
        "skills_with_zh": conn.execute(
            "SELECT COUNT(*) FROM skill WHERE name_zh_cn IS NOT NULL AND name_zh_cn != ''"
        ).fetchone()[0],
        "skills_with_en": conn.execute(
            "SELECT COUNT(*) FROM skill WHERE name_en IS NOT NULL AND name_en != ''"
        ).fetchone()[0],
        "skills_with_ja": conn.execute(
            "SELECT COUNT(*) FROM skill WHERE name_ja IS NOT NULL AND name_ja != ''"
        ).fetchone()[0],
        "skills_with_description": conn.execute(
            "SELECT COUNT(*) FROM skill WHERE description_en IS NOT NULL AND description_en != ''"
            " OR description_zh_cn IS NOT NULL AND description_zh_cn != ''"
            " OR description_ja IS NOT NULL AND description_ja != ''"
        ).fetchone()[0],
    }

    graph_stats = {
        "edges": conn.execute("SELECT COUNT(*) FROM evolution_edge").fetchone()[0],
        "digimon_with_in_edges": conn.execute(
            "SELECT COUNT(DISTINCT to_digimon_id) FROM evolution_edge"
        ).fetchone()[0],
        "digimon_with_out_edges": conn.execute(
            "SELECT COUNT(DISTINCT from_digimon_id) FROM evolution_edge"
        ).fetchone()[0],
        "cycles_supported": True,  # graph is designed to support cycles; not an error
    }

    # --- fixed sample spot-check -----------------------------------------------
    sample_report: dict[str, Any] = {}
    for name in FIXED_SAMPLE:
        row = conn.execute(
            """SELECT canonical_slug, name_zh_cn, name_en, name_ja, level, attribute,
                      (SELECT COUNT(*) FROM digimon_skill ds WHERE ds.digimon_id = d.id) AS skills,
                      (SELECT COUNT(*) FROM evolution_edge e WHERE e.from_digimon_id = d.id) AS out_edges,
                      main_image
               FROM digimon d
               WHERE name_en = ? COLLATE NOCASE OR name_ja = ? OR canonical_slug = ?
                  OR name_en LIKE ? COLLATE NOCASE
               ORDER BY CASE WHEN name_en = ? COLLATE NOCASE THEN 0 ELSE 1 END
               LIMIT 1""",
            [name, name, name.lower().replace(" ", "-"), f"%{name}%", name],
        ).fetchone()
        sample_report[name] = dict(row) if row else None

    report: dict[str, Any] = {
        "generated_at": None,  # stamped by run_and_write
        "issues": issues,
        "issue_counts": {
            "error": sum(1 for i in issues if i["level"] == "error"),
            "warning": sum(1 for i in issues if i["level"] == "warning"),
            "info": sum(1 for i in issues if i["level"] == "info"),
        },
        "coverage": {
            "zh_cn": coverage("name_zh_cn"),
            "en": coverage("name_en"),
            "ja": coverage("name_ja"),
            "zh_cn_status": zh_status_dict,
            "images": {
                "digimon_with_main_image": conn.execute(
                    "SELECT COUNT(*) FROM digimon WHERE main_image IS NOT NULL AND main_image != ''"
                ).fetchone()[0],
                "by_download_status": {r["download_status"]: r["c"] for r in img_stats},
                "missing_main_image": img_missing,
                "broken": img_broken,
                "pending": img_pending,
            },
            "profiles": {
                "zh_cn": coverage("profile_zh_cn"),
                "en": coverage("profile_en"),
                "ja": coverage("profile_ja"),
            },
            "skills": skill_stats,
        },
        "graph": graph_stats,
        "fixed_sample": sample_report,
    }
    return report


def to_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = ["# 数据质量报告", ""]
    c = report["coverage"]
    lines.append(f"- 问题：{report['issue_counts']['error']} error / "
                 f"{report['issue_counts']['warning']} warning / {report['issue_counts']['info']} info")
    lines.append(f"- 中文名覆盖率：{c['zh_cn']['present']}/{c['zh_cn']['total']} ({c['zh_cn']['pct']}%)")
    lines.append(f"- 英文名覆盖率：{c['en']['present']}/{c['en']['total']} ({c['en']['pct']}%)")
    lines.append(f"- 日文名覆盖率：{c['ja']['present']}/{c['ja']['total']} ({c['ja']['pct']}%)")
    lines.append(f"- 图片（主图存在）：{c['images']['digimon_with_main_image']}；"
                 f"缺主图：{c['images']['missing_main_image']}"
                 f"{f'；下载失败(broken)：{c['images']['broken']}' if c['images'].get('broken') else ''}"
                 f"{f'；未下载：{c['images']['pending']}' if c['images'].get('pending') else ''}")
    lines.append(f"- 技能：{c['skills']['total_skills']} 个，"
                 f"有技能数码兽 {c['skills']['digimon_with_skills']} 只")
    lines.append(f"- 进化边：{report['graph']['edges']} 条")
    lines.append("")
    if report["issues"]:
        lines.append("## 问题清单")
        for i in report["issues"]:
            lines.append(f"- **[{i['level']}]** {i['check']}: {i['message']}")
    lines.append("")
    lines.append("## 固定抽样验证")
    for name, rec in report["fixed_sample"].items():
        if rec is None:
            lines.append(f"- {name}: ❌ 未找到")
        else:
            lines.append(
                f"- {name}: {rec.get('name_zh_cn')} / {rec.get('name_en')} / {rec.get('name_ja')} "
                f"[{rec.get('level')}/{rec.get('attribute')}] 技能{rec.get('skills')} 出边{rec.get('out_edges')}"
            )
    return "\n".join(lines)


def run_and_write(db_path: Path, reports_dir: Path | None = None) -> dict[str, Any]:
    from datetime import datetime

    conn = connect(db_path)
    try:
        report = validate(conn)
    finally:
        conn.close()
    report["generated_at"] = datetime.now().isoformat(timespec="seconds")
    out_dir = reports_dir or REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data-quality.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), "utf-8"
    )
    (out_dir / "data-quality.md").write_text(to_markdown(report), "utf-8")
    return report
