"""generate-transliterations: fill digimon lacking Chinese names with phonetic
transliterations, clearly marked unverified (product spec §8 "最后手段").

This is an OPTIONAL last-resort tool: it only fills digimon with NO Chinese name
from any reliable source, converting their katakana name into Chinese characters
phonetically. Every generated name is stored with name_zh_cn_status='transliteration'
and name_zh_cn_verified=0, so it can never be mistaken for an official name.

Usage:
    uv run python scripts/generate_transliterations.py [--apply] [--out docs/transliteration-candidates.md]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.core.config import DB_PATH
from pipeline.core.schema import connect

# Standard katakana syllabary → common Chinese phonetic character.
# Covers the gojūon. Not exhaustive (rare/obsolete kana fall back to a token).
_KATAKANA = {
    "ア": "阿", "イ": "伊", "ウ": "乌", "エ": "埃", "オ": "奥",
    "カ": "卡", "キ": "基", "ク": "库", "ケ": "凯", "コ": "科",
    "サ": "萨", "シ": "西", "ス": "斯", "セ": "塞", "ソ": "索",
    "タ": "塔", "チ": "奇", "ツ": "茨", "テ": "铁", "ト": "托",
    "ナ": "纳", "ニ": "尼", "ヌ": "努", "ネ": "内", "ノ": "诺",
    "ハ": "哈", "ヒ": "希", "フ": "夫", "ヘ": "赫", "ホ": "霍",
    "マ": "玛", "ミ": "米", "ム": "姆", "メ": "梅", "モ": "莫",
    "ヤ": "雅", "ユ": "尤", "ヨ": "约",
    "ラ": "拉", "リ": "利", "ル": "鲁", "レ": "雷", "ロ": "罗",
    "ワ": "瓦", "ヲ": "沃", "ン": "恩",
    "ガ": "加", "ギ": "吉", "グ": "古", "ゲ": "盖", "ゴ": "戈",
    "ザ": "扎", "ジ": "吉", "ズ": "兹", "ゼ": "泽", "ゾ": "佐",
    "ダ": "达", "ヂ": "治", "ヅ": "兹", "デ": "德", "ド": "多",
    "バ": "巴", "ビ": "比", "ブ": "布", "ベ": "贝", "ボ": "博",
    "パ": "帕", "ピ": "皮", "プ": "普", "ペ": "佩", "ポ": "波",
    "ヴ": "武", "ァ": "阿", "ィ": "伊", "ゥ": "乌", "ェ": "埃", "ォ": "奥",
    "ッ": "", "ャ": "亚", "ュ": "尤", "ョ": "约",
    "ー": "",
}
# 小写 ぁぃぅぇぉ etc. handled via the ァ... block above (halfwidth katakana).


def katakana_to_hanzi(text: str) -> str:
    """Mechanical katakana→Chinese phonetic transliteration (lossy)."""
    out = []
    for ch in text:
        if ch in _KATAKANA:
            v = _KATAKANA[ch]
            if v:
                out.append(v)
        elif "ぁ" <= ch <= "ん":  # hiragana — not a loanword token
            return ""
        else:
            return ""  # kanji/latin/digits — not pure katakana
    return "".join(out)


def is_pure_katakana(text: str, max_len: int = 8) -> bool:
    """Only pure-katakana names up to `max_len` characters transliterate cleanly;
    longer or mixed-script names produce unusable results (spec §55)."""
    if not text or len(text) > max_len:
        return False
    return all(ch in _KATAKANA for ch in text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write generated names to the DB")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "transliteration-candidates.md")
    args = ap.parse_args(argv)

    conn = connect(DB_PATH)
    rows = conn.execute(
        """SELECT id, canonical_slug, name_en, name_ja, name_zh_cn, name_zh_cn_status
           FROM digimon
           WHERE (name_zh_cn IS NULL OR TRIM(name_zh_cn) = '')
              AND name_ja IS NOT NULL AND TRIM(name_ja) != ''"""
    ).fetchall()

    lines = ["# 中文名音译候选（自动生成 · 未验证）", "",
             "> 这些数码兽无可靠中文来源，以下为按规格 §8『最后手段』机械音译的候选名，",
             "> **全部标记 unverified（未验证），不可当作官方/社区定名**。", ""]
    applied = 0
    for r in rows:
        ja = r["name_ja"]
        if not is_pure_katakana(ja, max_len=8):
            continue  # mixed-script or too long → leave NULL (honest)
        gen = katakana_to_hanzi(ja)
        if not gen or gen == ja:
            continue  # nothing sensible generated
        lines.append(f"- [{r['name_en']}]({r['canonical_slug']}) {ja} → **{gen}**")
        if args.apply:
            conn.execute(
                """UPDATE digimon SET name_zh_cn=?, name_zh_cn_status='transliteration',
                       name_zh_cn_verified=0 WHERE id=?""",
                [gen, r["id"]],
            )
            applied += 1
    if args.apply:
        conn.commit()
        print(f"applied {applied} transliterations (unverified) to the DB")
    else:
        print(f"{len(rows)} missing-zh digimon with ja name; {len(lines)-4} candidates written "
              f"to {args.out} (dry-run — use --apply to write)")
    args.out.write_text("\n".join(lines), "utf-8")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
