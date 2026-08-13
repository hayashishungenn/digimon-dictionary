"""Integration test: matcher -> store -> resolver -> validator, end to end
with synthetic records (no network)."""
from __future__ import annotations

from pipeline.core.models import SourceDigimon, SourceName
from pipeline.core.schema import connect, create_schema
from pipeline.matching.matcher import Matcher
from pipeline.merge.resolver import EvolutionResolver
from pipeline.merge.store import CanonicalStore
from pipeline.validation.validator import validate


def _rec(source, sid, en, *, level=None, attr=None, zh=None, ja=None, is_official=None,
         evolves_to=(), skills=()):
    names = [SourceName(en, "en", status="community", source=source)]
    if zh:
        names.append(SourceName(zh, "zh_cn", status="official", source="official"))
    if ja:
        names.append(SourceName(ja, "ja", status="official", source="wikimon"))
    from pipeline.core.models import SourceSkill

    return SourceDigimon(
        source=source, source_id=sid, names=names, level_raw=level, attribute_raw=attr,
        is_official=is_official, evolves_to=list(evolves_to),
        skills=[SourceSkill(names={"en": s}, skill_type="special_move", source=source) for s in skills],
        extra={},
    )


def test_full_pipeline(tmp_path):
    conn = connect(tmp_path / "full.sqlite")
    create_schema(conn)

    # dapi backbone: Agumon(id1), Greymon(id8), WarGreymon(id9), Koromon(id2)
    dapi = [
        _rec("dapi", "1", "Agumon", level="Child", attr="Vaccine", skills=["Baby Flame"]),
        _rec("dapi", "2", "Koromon", level="Baby II", attr="None"),
        _rec("dapi", "8", "Greymon", level="Adult", attr="Vaccine", evolves_to=["9"]),
        _rec("dapi", "9", "WarGreymon", level="Ultimate", attr="Vaccine"),
    ]
    # official overlay adds zh/ja names + official status
    official = [
        _rec("official", "agumon", "Agumon", zh="亚古兽", ja="アグモン", is_official=True),
        _rec("official", "greymon", "Greymon", zh="暴龙兽", ja="グレイモン", is_official=True),
        _rec("official", "wargreymon", "WarGreymon", zh="战斗暴龙兽", ja="ウォーグレイモン", is_official=True),
        _rec("official", "koromon", "Koromon", zh="滚球兽", ja="コロモン", is_official=True),
    ]

    m = Matcher()
    for r in dapi + official:
        m.add(r)

    store = CanonicalStore(conn)
    for e in m.entities.values():
        store.upsert_entity(e)
    store.commit()

    # edges
    res = EvolutionResolver(conn)
    for e in m.entities.values():
        res.add_edges_for_entity(e)
    store.commit()
    store.rebuild_fts()
    store.write_snapshot(notes="integration")
    conn.commit()

    # ---- assertions ----
    rows = conn.execute("SELECT canonical_slug, name_zh_cn, name_ja, level, is_official_reference FROM digimon").fetchall()
    by_slug = {r["canonical_slug"]: r for r in rows}
    assert len(by_slug) == 4
    assert by_slug["agumon"]["name_zh_cn"] == "亚古兽"
    assert by_slug["agumon"]["name_ja"] == "アグモン"
    assert by_slug["agumon"]["level"] == "child"
    assert by_slug["agumon"]["is_official_reference"] == 1
    assert by_slug["wargreymon"]["name_zh_cn"] == "战斗暴龙兽"

    # evolution edge greymon -> wargreymon resolved via dapi id
    n_edges = conn.execute("SELECT COUNT(*) FROM evolution_edge").fetchone()[0]
    assert n_edges >= 1
    pair = conn.execute(
        """SELECT d1.canonical_slug, d2.canonical_slug FROM evolution_edge e
           JOIN digimon d1 ON d1.id=e.from_digimon_id
           JOIN digimon d2 ON d2.id=e.to_digimon_id"""
    ).fetchall()
    assert ("greymon", "wargreymon") in {(r[0], r[1]) for r in pair}

    # skills present
    n_skills = conn.execute("SELECT COUNT(*) FROM digimon_skill").fetchone()[0]
    assert n_skills == 1

    # validator runs without errors
    report = validate(conn)
    assert report["issue_counts"]["error"] == 0
    assert report["coverage"]["zh_cn"]["present"] == 4
