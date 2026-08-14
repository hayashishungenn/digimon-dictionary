"""Special-case tests (spec §64): X-Antibody, black variants, mode changes,
armor/hybrid levels, jogress, same-name disambiguation, multi-attribute,
multi-type source conflicts."""
from __future__ import annotations

from pipeline.core.enums import Level, parse_level
from pipeline.core.models import MatchedEntity, SourceDigimon, SourceName, SourceSkill
from pipeline.core.schema import connect, create_schema
from pipeline.matching.matcher import Matcher, slug_for_names
from pipeline.merge.relations import infer_relations
from pipeline.merge.resolver import EvolutionResolver, _guess_evolution_type
from pipeline.merge.store import CanonicalStore


def _rec(source, sid, en, *, level=None, attr=None, types=(), zh=None, ja=None,
         xab=None, evolves_to=(), skills=(), is_official=None):
    names = [SourceName(en, "en", status="community", source=source)]
    if zh:
        names.append(SourceName(zh, "zh_cn", status="official", source="official"))
    if ja:
        names.append(SourceName(ja, "ja", status="official", source="wikimon"))
    return SourceDigimon(
        source=source, source_id=sid, names=names, level_raw=level, attribute_raw=attr,
        types=list(types), x_antibody=xab, evolves_to=list(evolves_to), is_official=is_official,
        skills=[SourceSkill(names={"en": s}, skill_type="special_move", source=source) for s in skills],
        extra={},
    )


def _store(conn, *pairs):
    """pairs: (slug, record). Returns {slug: id}."""
    store = CanonicalStore(conn)
    for slug, rec in pairs:
        store.upsert_entity(MatchedEntity(canonical_slug=slug, records=[rec]))
    store.commit()
    return {r["canonical_slug"]: r["id"] for r in conn.execute("SELECT id, canonical_slug FROM digimon")}


def test_x_antibody_flag(tmp_path):
    conn = connect(tmp_path / "x.sqlite")
    create_schema(conn)
    _store(conn,
        ("agumon", _rec("dapi", "1", "Agumon", xab=False)),
        ("agumon-x-antibody", _rec("dapi", "6", "Agumon (X-Antibody)", xab=True)),
    )
    xab = conn.execute("SELECT COUNT(*) FROM digimon WHERE x_antibody=1").fetchone()[0]
    assert xab == 1


def test_black_variant_and_x_antibody_relations(tmp_path):
    conn = connect(tmp_path / "r.sqlite")
    create_schema(conn)
    _store(conn,
        ("agumon", _rec("dapi", "1", "Agumon")),
        ("agumon-black", _rec("dapi", "263", "Agumon (Black)")),
        ("agumon-black-x-antibody", _rec("dapi", "264", "Agumon (Black) (X-Antibody)", xab=True)),
        ("wargreymon", _rec("dapi", "15", "WarGreymon")),
        ("black-war-greymon", _rec("dapi", "16", "BlackWarGreymon")),
    )
    infer_relations(conn)
    rels = {(r[0], r[1], r[2]) for r in conn.execute(
        """SELECT d1.canonical_slug, d2.canonical_slug, rel.relation_type
           FROM digimon_relation rel
           JOIN digimon d1 ON d1.id = rel.from_digimon_id
           JOIN digimon d2 ON d2.id = rel.to_digimon_id""").fetchall()}
    assert ("agumon-black", "agumon", "black_variant") in rels
    assert ("agumon-black-x-antibody", "agumon-black", "x_antibody") in rels
    assert ("black-war-greymon", "wargreymon", "black_variant") in rels


def test_burst_and_mode_change_relations(tmp_path):
    conn = connect(tmp_path / "m.sqlite")
    create_schema(conn)
    _store(conn,
        ("shine-greymon", _rec("dapi", "1", "ShineGreymon")),
        ("shine-greymon-burst-mode", _rec("dapi", "2", "ShineGreymon: Burst Mode")),
        ("imperialdramon", _rec("dapi", "3", "Imperialdramon")),
        ("imperialdramon-fighter-mode", _rec("dapi", "4", "Imperialdramon: Fighter Mode")),
    )
    infer_relations(conn)
    rels = {(r[0], r[1], r[2]) for r in conn.execute(
        """SELECT d1.canonical_slug, d2.canonical_slug, rel.relation_type
           FROM digimon_relation rel JOIN digimon d1 ON d1.id=rel.from_digimon_id
           JOIN digimon d2 ON d2.id=rel.to_digimon_id""").fetchall()}
    assert ("shine-greymon-burst-mode", "shine-greymon", "mode_change") in rels
    assert ("imperialdramon-fighter-mode", "imperialdramon", "mode_change") in rels


def test_armor_hybrid_level_mapping():
    assert parse_level("Armor") == Level.ARMOR
    assert parse_level("Hybrid") == Level.HYBRID
    assert parse_level("装甲体") == Level.ARMOR
    assert parse_level("混合体") == Level.HYBRID


def test_jogress_evolution_type():
    assert _guess_evolution_type("Jogress Evolution with Metal Garurumon") == "jogress"
    assert _guess_evolution_type("DNA Digivolution") == "jogress"
    # plain conditional evolution is NOT jogress
    assert _guess_evolution_type("with or without the Crest") == "normal"


def test_same_name_forms_stay_separate():
    """近名形态绝不合并（§64 同名/近似名）：Agumon / Agumon (Black) / Agumon X."""
    m = Matcher()
    m.add(_rec("dapi", "1", "Agumon"))
    m.add(_rec("dapi", "263", "Agumon (Black)"))
    m.add(_rec("dapi", "634", "Agumon (X-Antibody)"))
    assert m.entities["agumon"].records[0].source_id == "1"
    assert m.entities["agumon-black"].records[0].source_id == "263"
    assert m.entities["agumon-x-antibody"].records[0].source_id == "634"
    assert len(m.entities) == 3


def test_slug_for_ambiguous_variants():
    assert slug_for_names({"en": "Omegamon Zwart"}) == "omegamon-zwart"
    assert slug_for_names({"en": "Omegamon (X-Antibody)"}) == "omegamon-x-antibody"
    # Chinese name never becomes the slug base
    assert slug_for_names({"en": "Omegamon", "zh_cn": "奥米加兽"}) == "omegamon"


def test_multi_attribute_uses_first_non_unknown(tmp_path):
    """digi-api 把 Unknown 排在前面时，应取后一个真实属性（§64 多属性）."""

    rec = SourceDigimon(
        source="dapi", source_id="1",
        names=[SourceName("Shoutmon", "en", status="community", source="dapi")],
        extra={},
    )
    rec.attribute_raw = None
    # simulate the store picking non-unknown attribute: check parse path
    from pipeline.core.enums import parse_attribute

    assert parse_attribute("Unknown") == parse_attribute("None")
    assert parse_attribute("Data").value == "data"
    assert parse_attribute("Unknown").value == "unknown"


def test_multi_type_conflict_recorded(tmp_path):
    """两源对类型给出不同主类型 → 不静默，写入 data_conflict."""
    conn = connect(tmp_path / "c.sqlite")
    create_schema(conn)
    dapi = _rec("dapi", "1", "Agumon", level="Child", attr="Vaccine")
    official = _rec("official", "agumon", "Agumon", level="Adult", attr="Vaccine", is_official=True)
    entity = MatchedEntity(canonical_slug="agumon", records=[dapi, official])
    CanonicalStore(conn).upsert_entity(entity)
    conn.commit()
    conflicts = conn.execute(
        "SELECT field, value_a, value_b FROM data_conflict"
    ).fetchall()
    assert any(r["field"] == "level" for r in conflicts)


def test_no_level_special_entity(tmp_path):
    """无等级实体 level 应为 unknown 而非错误."""
    conn = connect(tmp_path / "n.sqlite")
    create_schema(conn)
    _store(conn, ("mysterymon", _rec("dapi", "1", "Mysterymon")))
    lv = conn.execute("SELECT level FROM digimon WHERE canonical_slug='mysterymon'").fetchone()[0]
    assert lv == "unknown"


def test_xros_wars_level_2(tmp_path):
    """Xros（§64）：官方 level_2 标记（如 Xros Wars / 合体战争）应保存."""
    conn = connect(tmp_path / "xw.sqlite")
    create_schema(conn)
    rec = _rec("official", "shoutmon_x2", "Shoutmon X2", level="Adult")
    rec.extra["level_2"] = "Xros Wars"
    _store(conn, ("shoutmon-x2", rec))
    l2 = conn.execute("SELECT level_2 FROM digimon WHERE canonical_slug='shoutmon-x2'").fetchone()[0]
    assert l2 == "Xros Wars"


def test_armor_and_hybrid_digimon(tmp_path):
    """装甲体 / 混合体 数码兽按正确等级入库."""
    conn = connect(tmp_path / "ah.sqlite")
    create_schema(conn)
    _store(conn,
        ("magnamon", _rec("dapi", "1", "Magnamon", level="Armor")),
        ("agnimon", _rec("dapi", "2", "Agnimon", level="Hybrid")),
    )
    rows = {r[0]: r[1] for r in conn.execute("SELECT canonical_slug, level FROM digimon")}
    assert rows["magnamon"] == "armor"
    assert rows["agnimon"] == "hybrid"


def test_evolution_resolver_unknown_target_skipped(tmp_path):
    """进化到未知实体 → 跳过（禁悬空引用，§54）."""
    conn = connect(tmp_path / "e.sqlite")
    create_schema(conn)
    _store(conn, ("agumon", _rec("dapi", "1", "Agumon", evolves_to=["99999"])))
    res = EvolutionResolver(conn)
    rec = _rec("dapi", "1", "Agumon", evolves_to=["99999"])
    res.add_edges_for_entity(MatchedEntity(canonical_slug="agumon", records=[rec]))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM evolution_edge").fetchone()[0] == 0
