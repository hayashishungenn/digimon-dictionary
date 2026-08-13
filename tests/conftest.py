"""Shared pytest fixtures: build a small canonical DB from in-memory records."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pipeline.core.models import MatchedEntity, SourceDigimon, SourceName, SourceSkill
from pipeline.core.schema import connect, create_schema
from pipeline.matching.matcher import slug_for_names
from pipeline.merge.store import CanonicalStore


def _mk(slug: str, en: str, ja: str, zh: str, *, level="child", attribute="vaccine",
        types=("Reptile",), fields=("Dragon's Roar",), groups=(), dapi_id=None,
        xab=False, skills=(), profile_en=None, profile_ja=None) -> SourceDigimon:
    rec = SourceDigimon(
        source="dapi",
        source_id=str(dapi_id) if dapi_id else slug,
        names=[
            SourceName(en, "en", status="community", source="dapi"),
            SourceName(zh, "zh_cn", status="official", source="official"),
            SourceName(ja, "ja", status="official", source="wikimon"),
        ],
        level_raw=level,
        attribute_raw=attribute,
        types=list(types),
        fields=list(fields),
        groups=list(groups),
        x_antibody=xab,
        is_official=True,
        skills=[SourceSkill(names={"en": s}, skill_type="special_move", source="dapi") for s in skills],
        extra={"source_url": "https://digi-api.com/api/v1/digimon/1"},
    )
    if profile_en:
        rec.profile["en"] = profile_en
    if profile_ja:
        rec.profile["ja"] = profile_ja
    return rec


def build_fixture_db(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    create_schema(conn)

    agumon = _mk("agumon", "Agumon", "アグモン", "亚古兽", dapi_id=1, skills=["Baby Flame", "Pepper Breath"],
                 profile_en="A Reptile Digimon.", profile_ja="爬虫類型デジモン。")
    koromon = _mk("koromon", "Koromon", "コロモン", "滚球兽", level="baby_ii",
                  types=("Lesser",), dapi_id=2, profile_en="A small Digimon.")
    greymon = _mk("greymon", "Greymon", "グレイモン", "暴龙兽", level="adult",
                  types=("Dinosaur",), fields=("Nature Spirits", "Metal Empire"),
                  dapi_id=3, skills=["Mega Flame"], profile_en="A giant dinosaur.")
    wargreymon = _mk("wargreymon", "WarGreymon", "ウォーグレイモン", "战斗暴龙兽",
                     level="ultimate", types=("Dragon Man",), fields=("Dragon's Roar",),
                     groups=("Royal Knights",), dapi_id=4, skills=["Gaia Force"],
                     profile_en="The ultimate dragon warrior.")
    gabumon = _mk("gabumon", "Gabumon", "ガブモン", "加布兽", dapi_id=5, skills=["Blue Blaster"])
    agumon_x = _mk("agumon-x-antibody", "Agumon (X-Antibody)", "アグモン（X抗体）", "亚古兽X抗体",
                   dapi_id=6, xab=True, skills=["Baby Flame"])

    store = CanonicalStore(conn)
    for rec in (agumon, koromon, greymon, wargreymon, gabumon, agumon_x):
        slug = slug_for_names({n.language: n.value for n in rec.names})
        entity = MatchedEntity(canonical_slug=slug, records=[rec])
        store.upsert_entity(entity)

    # evolution edges: koromon -> agumon -> greymon -> wargreymon, gabumon -> wargreymon
    ids = {r["canonical_slug"]: r["id"] for r in conn.execute("SELECT id, canonical_slug FROM digimon")}
    for f, t in [("koromon", "agumon"), ("agumon", "greymon"), ("greymon", "wargreymon"),
                 ("gabumon", "wargreymon"), ("agumon", "agumon-x-antibody")]:
        store.add_edge(ids[f], ids[t], evolution_type="normal", source="dapi")
    store.add_relation(ids["wargreymon"], ids["agumon"], "same_species", source="wikimon", note="Greymon family")
    store.rebuild_fts()
    store.write_snapshot(notes="test fixture")
    conn.commit()
    return conn


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "fixture.sqlite"
    conn = build_fixture_db(path)
    yield path, conn
    conn.close()
