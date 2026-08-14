"""Unit tests for the canonical store (merge) and evolution resolver."""
from __future__ import annotations

import pytest

from pipeline.core.models import MatchedEntity, SourceDigimon, SourceName, SourceSkill
from pipeline.core.schema import connect, create_schema
from pipeline.merge.resolver import EvolutionResolver, _guess_evolution_type
from pipeline.merge.store import CanonicalStore


def _rec(source: str, sid: str, en: str, *, level=None, attr=None, types=(), fields=(),
         groups=(), skills=(), is_official=None, zh=None, ja=None,
         evolves_from=(), evolves_to=()) -> SourceDigimon:
    names = [SourceName(en, "en", status="community", source=source)]
    if zh:
        names.append(SourceName(zh, "zh_cn", status="official", source="official"))
    if ja:
        names.append(SourceName(ja, "ja", status="official", source="wikimon"))
    return SourceDigimon(
        source=source, source_id=sid, names=names, level_raw=level, attribute_raw=attr,
        types=list(types), fields=list(fields), groups=list(groups),
        is_official=is_official, evolves_from=list(evolves_from), evolves_to=list(evolves_to),
        skills=[SourceSkill(names={"en": s}, skill_type="special_move", source=source) for s in skills],
        extra={},
    )


@pytest.fixture
def store_conn(tmp_path):
    conn = connect(tmp_path / "s.sqlite")
    create_schema(conn)
    return conn


def _upsert(conn, slug, rec):
    e = MatchedEntity(canonical_slug=slug, records=[rec])
    CanonicalStore(conn).upsert_entity(e)
    conn.commit()


def test_upsert_and_names(store_conn):
    rec = _rec("dapi", "1", "Agumon", level="Child", attr="Vaccine", types=["Reptile"],
               zh="亚古兽", ja="アグモン", is_official=True)
    _upsert(store_conn, "agumon", rec)
    row = store_conn.execute("SELECT * FROM digimon WHERE canonical_slug='agumon'").fetchone()
    assert row["name_en"] == "Agumon"
    assert row["name_zh_cn"] == "亚古兽"
    assert row["name_ja"] == "アグモン"
    assert row["level"] == "child"
    assert row["attribute"] == "vaccine"
    assert row["is_official_reference"] == 1


def test_merge_two_sources_enrich(store_conn):
    dapi = _rec("dapi", "1", "Agumon", level="Child", types=["Reptile"])
    official = _rec("official", "agumon", "Agumon", zh="亚古兽", ja="アグモン", is_official=True)
    entity = MatchedEntity(canonical_slug="agumon", records=[dapi, official])
    CanonicalStore(store_conn).upsert_entity(entity)
    store_conn.commit()
    row = store_conn.execute("SELECT * FROM digimon WHERE canonical_slug='agumon'").fetchone()
    # dapi provides level; official provides zh/ja names + official flag
    assert row["level"] == "child"
    assert row["name_zh_cn"] == "亚古兽"
    assert row["name_ja"] == "アグモン"
    assert row["is_official_reference"] == 1


def test_skills_dedup_across_sources(store_conn):
    a = _rec("dapi", "1", "Agumon", skills=["Baby Flame"])
    b = _rec("wikimon", "Agumon", "Agumon", skills=["Baby Flame"])
    entity = MatchedEntity(canonical_slug="agumon", records=[a, b])
    CanonicalStore(store_conn).upsert_entity(entity)
    store_conn.commit()
    n = store_conn.execute("SELECT COUNT(*) FROM skill").fetchone()[0]
    assert n == 1
    links = store_conn.execute("SELECT COUNT(*) FROM digimon_skill").fetchone()[0]
    assert links == 1


def test_evolution_resolver_edges(store_conn):
    koromon = _rec("dapi", "2", "Koromon")
    agumon = _rec("dapi", "1", "Agumon", evolves_from=["2"])
    _upsert(store_conn, "koromon", koromon)
    _upsert(store_conn, "agumon", agumon)
    res = EvolutionResolver(store_conn)
    ag_id = store_conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()["id"]
    ko_id = store_conn.execute("SELECT id FROM digimon WHERE canonical_slug='koromon'").fetchone()["id"]
    # add edges for the agumon entity
    e = MatchedEntity(canonical_slug="agumon", records=[agumon])
    res.add_edges_for_entity(e)
    store_conn.commit()
    rows = store_conn.execute("SELECT from_digimon_id, to_digimon_id FROM evolution_edge").fetchall()
    assert (ko_id, ag_id) in {(r[0], r[1]) for r in rows}


def test_evolution_resolver_skips_junk(store_conn):
    agumon = _rec("wikimon", "Agumon", "Agumon",
                  evolves_to=["Any Red Lv.2 Digimon from the Digimon Card Game"])
    _upsert(store_conn, "agumon", agumon)
    res = EvolutionResolver(store_conn)
    e = MatchedEntity(canonical_slug="agumon", records=[agumon])
    res.add_edges_for_entity(e)
    store_conn.commit()
    assert store_conn.execute("SELECT COUNT(*) FROM evolution_edge").fetchone()[0] == 0


def test_cycle_supported(store_conn):
    # A->B->A cycle must be allowed (graph is designed for cycles)
    a = _rec("dapi", "1", "A", evolves_to=["2"])
    b = _rec("dapi", "2", "B", evolves_to=["1"])
    _upsert(store_conn, "a", a)
    _upsert(store_conn, "b", b)
    res = EvolutionResolver(store_conn)
    for slug, rec in (("a", a), ("b", b)):
        res.add_edges_for_entity(MatchedEntity(canonical_slug=slug, records=[rec]))
    store_conn.commit()
    n = store_conn.execute("SELECT COUNT(*) FROM evolution_edge").fetchone()[0]
    assert n == 2  # both directions stored


def test_evolution_type_heuristic():
    # generic conditional phrases are NOT jogress (regression)
    assert _guess_evolution_type("with or without the Crest") == "normal"
    assert _guess_evolution_type("when HP is low and a friend is present") == "normal"
    assert _guess_evolution_type("") == "normal"
    # explicit signals still classify
    assert _guess_evolution_type("Jogress Evolution") == "jogress"
    assert _guess_evolution_type("DNA Digivolution") == "jogress"
    assert _guess_evolution_type("Warp Evolution") == "special"
    assert _guess_evolution_type("with the X-Antibody") == "x_evolution"


def test_fts_rebuild(store_conn):
    rec = _rec("dapi", "1", "Agumon", zh="亚古兽", ja="アグモン")
    _upsert(store_conn, "agumon", rec)
    s = CanonicalStore(store_conn)
    s.rebuild_fts()
    store_conn.commit()
    rows = store_conn.execute("SELECT rowid FROM digimon_fts WHERE digimon_fts MATCH 'Agumon'").fetchall()
    assert len(rows) == 1


def test_resolver_reports_unknown_and_self_refs(store_conn):
    """The resolver returns stats and never silently drops unresolved/self refs:
    a record evolving to an unknown id and to itself is reported, the resolvable
    edge is still written."""
    agumon = _rec("dapi", "1", "Agumon", evolves_to=["2", "3", "1"])
    greymon = _rec("dapi", "3", "Greymon")
    _upsert(store_conn, "agumon", agumon)
    _upsert(store_conn, "greymon", greymon)
    res = EvolutionResolver(store_conn)
    stats = res.add_edges_for_entity(MatchedEntity(canonical_slug="agumon", records=[agumon]))
    store_conn.commit()
    assert stats["edges"] == 1            # -> greymon (id 3) resolved
    assert len(stats["unknown"]) == 1     # id 2 not in the dataset
    assert len(stats["self"]) == 1        # id 1 is agumon itself
    assert stats["unknown"][0][2] == "2"
    # the resolved edge exists
    edges = store_conn.execute("SELECT COUNT(*) FROM evolution_edge").fetchone()[0]
    assert edges == 1
