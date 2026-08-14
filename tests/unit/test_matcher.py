"""Unit tests for entity matching (Matcher) and slug generation."""
from __future__ import annotations

from pipeline.core.models import SourceDigimon, SourceName
from pipeline.matching.matcher import Matcher, slug_for_names


def _dapi(name: str, dapi_id: int) -> SourceDigimon:
    return SourceDigimon(
        source="dapi",
        source_id=str(dapi_id),
        names=[SourceName(name, "en", status="community", source="dapi")],
        extra={"source_url": f"https://digi-api.com/api/v1/digimon/{dapi_id}"},
    )


def _official(slug: str, en: str, zh: str, ja: str | None = None) -> SourceDigimon:
    names = [
        SourceName(en, "en", status="official", source="official"),
        SourceName(zh, "zh_cn", status="official", source="official"),
    ]
    if ja:
        names.append(SourceName(ja, "ja", status="official", source="official"))
    return SourceDigimon(
        source="official",
        source_id=slug,
        names=names,
        extra={},
    )


def _wikimon(title: str, ja: str | None = None, zh: str | None = None) -> SourceDigimon:
    names = [SourceName(title, "en", status="community", source="wikimon")]
    if ja:
        names.append(SourceName(ja, "ja", status="official", source="wikimon"))
    if zh:
        names.append(SourceName(zh, "zh_cn", status="community", source="wikimon"))
    return SourceDigimon(source="wikimon", source_id=title, names=names, extra={})


def test_slug_for_names():
    assert slug_for_names({"en": "Agumon"}) == "agumon"
    assert slug_for_names({"en": "Agumon (Black)"}) == "agumon-black"
    assert slug_for_names({"en": "Agumon (X-Antibody)"}) == "agumon-x-antibody"
    assert slug_for_names({"en": "Agumon (2006 Anime Version)"}) == "agumon-2006"
    # Japanese-only name -> stable hash fallback, never "unknown"
    s = slug_for_names({"ja": "オメガモン"})
    assert s.startswith("digimon-") and s != "unknown"
    assert slug_for_names({"ja": "オメガモン"}) == s  # deterministic


def test_zh_name_is_not_slug_base():
    # Chinese names must never become the canonical slug.
    s = slug_for_names({"en": "WarGreymon", "zh_cn": "战斗暴龙兽"})
    assert s == "wargreymon"


def test_matcher_merges_across_sources_by_en_name():
    m = Matcher()
    m.add(_dapi("Agumon", 1))
    m.add(_dapi("Greymon", 8))
    # official Agumon should merge into the existing dapi Agumon entity
    slug = m.add(_official("agumon", "Agumon", "亚古兽"))
    assert slug == "agumon"
    assert len(m.entities["agumon"].records) == 2
    # official names (zh) now attached to the same entity
    assert m.entities["agumon"].records[1].names[1].value == "亚古兽"


def test_matcher_matches_by_japanese_name():
    m = Matcher()
    m.add(_dapi("Omegamon", 55))
    # official overlay adds the Japanese name to the index
    m.add(_official("omegamon", "Omegamon", "奥米加兽", ja="オメガモン"))
    # a wikimon record with a different English title but same ja name matches
    slug = m.add(_wikimon("Omnimon", ja="オメガモン"))
    assert slug == "omegamon"


def test_matcher_creates_new_entity_for_unknown():
    m = Matcher()
    m.add(_dapi("Agumon", 1))
    slug = m.add(_wikimon("Fancymon", ja="ファンシーモン"))
    assert slug == "fancymon"
    assert len(m.entities) == 2


def test_matcher_external_id_linking():
    m = Matcher()
    m.add(_dapi("Agumon", 1))
    # a second dapi record pointing at same id resolves by external id
    slug = m.add(_dapi("Agumon", 1))
    assert slug == "agumon"


def test_digimons_ja_not_used_for_matching():
    """digimons' katakana column has errors (Styracomon listed with Stingmon's
    スティングモン). Its ja is display-only (matchable=False), so it can never
    hijack entity matching — Stingmon and Styracomon stay correctly separate."""
    m = Matcher()
    m.add(_dapi("Stingmon", 336))
    # digimons styracomon: ja (スティングモン) is non-matchable
    m.add(
        SourceDigimon(
            source="digimons_net", source_id="styracomon",
            names=[
                SourceName("刺盾角蜥兽", "zh_cn", status="community", source="digimons_net"),
                SourceName("Styracomon", "en", status="community", source="digimons_net"),
                SourceName("スティングモン", "ja", status="community", source="digimons_net", matchable=False),
            ],
            extra={},
        )
    )
    # digimons stingmon: en must land on the dapi stingmon entity
    slug = m.add(
        SourceDigimon(
            source="digimons_net", source_id="stingmon",
            names=[
                SourceName("刺钉兽", "zh_cn", status="community", source="digimons_net"),
                SourceName("Stingmon", "en", status="community", source="digimons_net"),
                SourceName("スティングモン", "ja", status="community", source="digimons_net", matchable=False),
            ],
            extra={},
        )
    )
    assert slug == "stingmon"
    assert len(m.entities) == 2  # stingmon + styracomon, no duplicates
    # digimons ja still carried on the entity for display
    slugs = {s for r in m.entities["stingmon"].records for s in
             [n.value for n in r.names if n.language == "ja"]}
    assert "スティングモン" in slugs


def test_zh_simplified_matches_traditional_name():
    """§33 简繁: a record carrying only the traditional form 亞古獸 must merge
    into the entity seeded with the simplified form 亚古兽."""
    m = Matcher()
    m.add(_official("agumon", "Agumon", "亚古兽"))
    rec = SourceDigimon(
        source="wikimon", source_id="Agumon",
        names=[SourceName("亞古獸", "zh_cn", status="community", source="wikimon")],
        extra={},
    )
    slug = m.add(rec)
    assert slug == "agumon"
    assert len(m.entities["agumon"].records) == 2


def test_ambiguous_name_creates_reviewed_entity_not_silent_merge():
    """Two entities share the same Chinese name 亚古兽 (Agumon base vs the 2006
    form). A record carrying only that name is ambiguous — it must NOT merge to
    either candidate, and its entity must be flagged for review."""
    m = Matcher()
    m.seed_entity("agumon", _official("agumon", "Agumon", "亚古兽"))
    m.seed_entity("agumon-2006", _wikimon("Agumon (2006 Anime Version)", zh="亚古兽"))
    assert len(m.entities) == 2

    rec = SourceDigimon(
        source="digimons_net", source_id="agumon-2006x",
        names=[SourceName("亚古兽", "zh_cn", status="community", source="digimons_net")],
        extra={},
    )
    slug = m.add(rec)
    assert slug not in ("agumon", "agumon-2006")  # never merged to the first candidate
    assert m.entities[slug].needs_review is True
    assert m.entities[slug].review_reason
    assert any(q["reason"] == "ambiguous_name" for q in m.review_queue)


def test_slug_collision_is_deterministic_and_cjk_fallback_stable():
    # non-latin-only names fall back to a stable hash slug, never 'unknown'
    a = slug_for_names({"ja": "オメガモン"})
    b = slug_for_names({"ja": "オメガモン"})
    assert a == b and a.startswith("digimon-")
    # X-Antibody / Black / 2006 suffixes map to stable tokens
    assert slug_for_names({"en": "Agumon (X-Antibody)"}) == "agumon-x-antibody"
    assert slug_for_names({"en": "Agumon (Black)"}) == "agumon-black"
    assert slug_for_names({"en": "Agumon (2006 Anime Version)"}) == "agumon-2006"
