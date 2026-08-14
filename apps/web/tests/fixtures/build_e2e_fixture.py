"""Build a deterministic, hermetic fixture database for Playwright E2E.

No network, no real sync, no random data: every entity, name, alias, evolution
edge, relation, and snapshot is fixed. The E2E suite runs entirely against this
fixture so it never depends on a pre-synced `data/digidex.sqlite` (T6.7).

The fixture intentionally covers the E2E scenarios:
- Agumon with trilingual names + image + skills + a primary evolution line
- an extended entity with no image (agumon-ds) for the missing-image test
- an alias 战暴 -> wargreymon for the fan-abbreviation search test
- a snapshot row so the About page can show runtime counts
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root
sys.path.insert(0, str(ROOT))

from pipeline.core.models import MatchedEntity, SourceDigimon, SourceName, SourceSkill
from pipeline.core.schema import create_schema
from pipeline.merge.store import CanonicalStore


def _rec(slug: str, en: str, ja: str, zh: str, *, level="child", attribute="vaccine",
         types=("Reptile",), dapi_id=None, is_official=True, image=None,
         skills=(), profile_en=None, groups=()) -> SourceDigimon:
    names = [
        SourceName(en, "en", status="community", source="dapi"),
        SourceName(zh, "zh_cn", status="official", source="official"),
        SourceName(ja, "ja", status="official", source="wikimon"),
    ]
    rec = SourceDigimon(
        source="dapi", source_id=str(dapi_id or 0),
        names=names,
        level_raw=level,
        attribute_raw=attribute,
        types=list(types),
        groups=list(groups),
        is_official=is_official,
        skills=[SourceSkill(names={"en": s}, skill_type="special_move", source="dapi") for s in skills],
        extra={"source_url": "https://digi-api.com/api/v1/digimon/1"},
    )
    if image:
        rec.image_url = image
    if profile_en:
        rec.profile["en"] = profile_en
    return rec


def _digimons_net_only(slug: str, en: str, ja: str, zh: str) -> SourceDigimon:
    """An extended, image-less entity from digimons.net (missing-image test)."""
    return SourceDigimon(
        source="digimons_net", source_id=slug,
        names=[
            SourceName(zh, "zh_cn", status="community", source="digimons_net"),
            SourceName(en, "en", status="community", source="digimons_net"),
            SourceName(ja, "ja", status="community", source="digimons_net"),
        ],
        is_official=False,
        extra={"source_url": f"https://www.digimons.net/digimon/{slug}/index.html"},
    )


IMG = "https://digi-api.com/images/digimon/w/{name}.png"

ENTITIES = [
    ("koromon", _rec("koromon", "Koromon", "コロモン", "滚球兽", level="Baby II",
                     types=("Lesser",), dapi_id=2, image=IMG.format(name="Koromon"))),
    ("agumon", _rec("agumon", "Agumon", "アグモン", "亚古兽", dapi_id=1,
                    image=IMG.format(name="Agumon"),
                    skills=["Baby Flame", "Pepper Breath"],
                    profile_en="A Reptile Digimon. Its Special Move is Baby Flame.")),
    ("greymon", _rec("greymon", "Greymon", "グレイモン", "暴龙兽", level="adult",
                     types=("Dinosaur",), dapi_id=3, image=IMG.format(name="Greymon"),
                     skills=["Mega Flame"])),
    ("war-greymon", _rec("war-greymon", "WarGreymon", "ウォーグレイモン", "战斗暴龙兽",
                         level="ultimate", types=("Dragon Man",), dapi_id=4,
                         groups=("Royal Knights",), image=IMG.format(name="WarGreymon"),
                         skills=["Gaia Force"])),
    ("gabumon", _rec("gabumon", "Gabumon", "ガブモン", "加布兽", dapi_id=5,
                     image=IMG.format(name="Gabumon"))),
    ("agumon-x-antibody", _rec("agumon-x-antibody", "Agumon (X-Antibody)", "アグモン（X抗体）",
                               "亚古兽X抗体", dapi_id=6,
                               image=IMG.format(name="Agumon (X-Antibody)"))),
    ("agumon-ds", _digimons_net_only("agumon-ds", "Agumon (DS)", "アグモン", "亚古兽（DS）")),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("apps/web/tests/fixtures/e2e.sqlite"))
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    # A plain (non-WAL) connection so every write lands in the main file — the
    # fixture must be self-contained for the E2E API server (T6.7).
    conn = sqlite3.connect(args.out)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA busy_timeout = 5000")
    create_schema(conn)
    store = CanonicalStore(conn)
    for slug, rec in ENTITIES:
        store.upsert_entity(MatchedEntity(canonical_slug=slug, records=[rec]))
    store.commit()

    ids = {r["canonical_slug"]: r["id"] for r in conn.execute("SELECT id, canonical_slug FROM digimon")}
    # primary line koromon -> agumon -> greymon -> wargreymon
    for f, t in [("koromon", "agumon"), ("agumon", "greymon"), ("greymon", "war-greymon")]:
        store.add_edge(ids[f], ids[t], evolution_type="normal", source="dapi", is_primary_line=True)
    # secondary edges (not primary)
    store.add_edge(ids["gabumon"], ids["war-greymon"], evolution_type="normal", source="dapi")
    store.add_edge(ids["agumon"], ids["agumon-x-antibody"], evolution_type="normal", source="dapi")
    store.commit()
    # wargreymon -> agumon same-species relation
    store.add_relation(ids["war-greymon"], ids["agumon"], "same_species", source="wikimon", note="Greymon family")
    # fan abbreviation alias (search §35)
    conn.execute(
        """INSERT OR IGNORE INTO digimon_alias(digimon_id, alias, language, alias_type, source, verified)
           VALUES(?,?,?,?,?,?)""",
        [ids["war-greymon"], "战暴", "zh_cn", "fan_translation", "manual", 0],
    )
    store.rebuild_fts()
    store.write_snapshot(notes="e2e fixture")
    conn.commit()
    conn.close()
    print(f"E2E fixture written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
