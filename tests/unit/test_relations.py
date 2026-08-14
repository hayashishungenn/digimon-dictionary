"""Unit tests for related-form inference (spec §42)."""
from __future__ import annotations

from pipeline.core.models import MatchedEntity, SourceDigimon, SourceName
from pipeline.core.schema import connect, create_schema
from pipeline.merge.relations import _base_slug, _relation_type, infer_relations
from pipeline.merge.store import CanonicalStore


def _rec(slug: str, en: str) -> SourceDigimon:
    return SourceDigimon(
        source="dapi", source_id=slug,
        names=[SourceName(en, "en", status="community", source="dapi")], extra={},
    )


def _setup_conn(tmp_path):
    conn = connect(tmp_path / "r.sqlite")
    create_schema(conn)
    store = CanonicalStore(conn)
    for slug, en in [
        ("agumon", "Agumon"),
        ("agumon-black", "Agumon (Black)"),
        ("agumon-x-antibody", "Agumon (X-Antibody)"),
        ("war-greymon", "WarGreymon"),  # real DB convention (space-derived slug)
        ("black-war-greymon", "BlackWarGreymon"),
        ("war-greymon-x-antibody", "WarGreymon (X-Antibody)"),
        ("imperialdramon", "Imperialdramon"),
        ("imperialdramon-fighter-mode", "Imperialdramon: Fighter Mode"),
        ("solo-slug-no-base", "SoloSlugNoBase"),
    ]:
        store.upsert_entity(MatchedEntity(canonical_slug=slug, records=[_rec(slug, en)]))
    store.commit()
    return conn


def test_base_slug_rules():
    assert _base_slug("agumon-black") == "agumon"
    assert _base_slug("agumon-x-antibody") == "agumon"
    assert _base_slug("war-greymon-x-antibody") == "war-greymon"
    assert _base_slug("black-war-greymon") == "war-greymon"
    assert _base_slug("imperialdramon-fighter-mode") == "imperialdramon"
    assert _base_slug("plain") is None


def test_relation_type_rules():
    assert _relation_type("agumon-black") == "black_variant"
    assert _relation_type("agumon-x-antibody") == "x_antibody"
    assert _relation_type("imperialdramon-fighter-mode") == "mode_change"


def test_infer_relations(tmp_path):
    conn = _setup_conn(tmp_path)
    added = infer_relations(conn)
    rows = conn.execute(
        """SELECT d1.canonical_slug AS f, d2.canonical_slug AS t, r.relation_type
           FROM digimon_relation r
           JOIN digimon d1 ON d1.id = r.from_digimon_id
           JOIN digimon d2 ON d2.id = r.to_digimon_id"""
    ).fetchall()
    pairs = {(r["f"], r["t"], r["relation_type"]) for r in rows}

    assert ("agumon-black", "agumon", "black_variant") in pairs
    assert ("agumon-x-antibody", "agumon", "x_antibody") in pairs
    assert ("black-war-greymon", "war-greymon", "black_variant") in pairs
    assert ("war-greymon-x-antibody", "war-greymon", "x_antibody") in pairs
    assert ("imperialdramon-fighter-mode", "imperialdramon", "mode_change") in pairs
    # no relation for a slug whose base doesn't exist
    assert not any(r["f"] == "solo-slug-no-base" for r in rows)
    # never self-relation
    assert not any(r["f"] == r["t"] for r in rows)
    assert added == len(rows)
