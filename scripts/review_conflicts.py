"""review-conflicts: generate a human-readable data-conflict review report.

Conflicts are real cross-source disagreements (e.g. digi-api says attribute
"Data" while the official Reference Book says "Vaccine"). They are recorded in
`data_conflict` rather than silently resolved; this script summarizes them for
manual review.

Usage:
    uv run python scripts/review_conflicts.py [--out docs/data-conflicts.md]
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.core.config import DB_PATH
from pipeline.core.schema import connect


def main(argv: list[str] | None = None) -> int:
    ROOT = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "data-conflicts.md")
    args = ap.parse_args(argv)

    conn = connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM data_conflict").fetchone()[0]
    by_field = conn.execute("SELECT field, COUNT(*) c FROM data_conflict GROUP BY field ORDER BY c DESC").fetchall()

    lines = ["# 数据冲突审查报告", "", f"> 共 {total} 条跨源数据冲突（已记录未静默）。生成时间随运行更新。", ""]
    lines.append("## 按字段统计")
    for r in by_field:
        lines.append(f"- **{r['field']}**：{r['c']} 条")
    lines.append("")

    lines.append("## 冲突明细（按数码兽）")
    lines.append("")
    rows = conn.execute(
        """SELECT c.field, c.value_a, c.value_b, c.source_a, c.source_b,
                  COALESCE(d.name_zh_cn, d.name_en, d.canonical_slug) AS display,
                  d.canonical_slug
           FROM data_conflict c
           LEFT JOIN digimon d ON d.id = c.entity_id
           ORDER BY d.canonical_slug, c.field"""
    ).fetchall()
    lines.append("| 数码兽 | 字段 | 来源A 值 | 来源B 值 |")
    lines.append("|---|---|---|---|")
    for r in rows:
        slug = r["canonical_slug"] or "?"
        display = r["display"] or slug
        lines.append(f"| [{display}](/digimon/{slug}) | {r['field']} | {r['source_a']}={r['value_a']} | {r['source_b']}={r['value_b']} |")
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- `perfect` vs `ultimate`：digi-api 与官方对同一数码兽的等级分类不同（完全体 vs 究极体）。")
    lines.append("- `data/vaccine/free` 等属性分歧同理。这些是真实分歧，已保留双方来源值，未静默取其一。")
    lines.append("- 处理方式：人工核对后在 `data_conflict.resolution` 记录裁决，或交由后续权威来源覆盖。")

    args.out.write_text("\n".join(lines), "utf-8")
    print(f"conflict report -> {args.out} ({total} conflicts)")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
