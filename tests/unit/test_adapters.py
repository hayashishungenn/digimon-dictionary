"""Unit tests for source adapters (official list, wikimon S2 parsing)."""
from __future__ import annotations

from pipeline.sources.official import parse_list_rows
from pipeline.sources.wikimon import WikimonAdapter
from pipeline.sources.wikitext import extract_template, parse_ol_field

S2_FIXTURE = """{{FArticle|162}}{{S2
|drbentry={{DRBEntry|772|773|2a=Zubamon}}
|kan=アグモン
|dub=Augumon
|ol={{CHI}} 亞古獸{{DD|a}}<br>{{ZHO}} 亚古兽{{DD|a}}<br>{{KOR}} 아구몬{{DD|a}} — ''Agumon''
|image=Agumon.jpg
|l1=Child
|a1=Vaccine
|t1=Reptile
|f1=Deep Savers
|f2=Dragon's Roar
|g1=Agumon-species
|s1=Agumon (2006 Anime Version)
|s2=Agumon (Black)
|s3=Agumon (X-Antibody)
|pn=DRB
|pe=A Reptile Digimon... ({{AT|Baby Flame}}).
|pj=爬虫類型デジモン。{{ATK|ベビーフレイム}}。
|ety=May come from {{ETY|Agu}}.
|yd=1997
}}

==Evolves From==
* '''[[Koromon]]'''
* [[Digimon Card Game Colors and Levels#Red Lv.2 Digimon|Any Red Lv.2 Digimon from the ''Digimon Card Game'']]

==Evolves To==
* '''[[Greymon]]''' (with or without the Crest)
* [[Agumon (X-Antibody)]] (with or without the X-Antibody)
* [[Digimon Card Game Colors and Levels#Blue Lv.3 Digimon|Any Blue Lv.3 Digimon from the ''Digimon Card Game'']]
"""


def test_official_list_rows():
    payload = {
        "next": 96,
        "rows": [
            {"directory_name": "agumon", "name": "Agumon", "level": "Rookie",
             "level_2": None, "icon_20th": 0, "icon_new": 0, "relate_word6": None},
            {"directory_name": "alphamon", "name": "Alphamon", "level": "Ultimate",
             "level_2": None, "icon_20th": 0, "icon_new": 0, "relate_word6": "〇"},
        ],
    }
    rows = parse_list_rows(payload, "en")
    assert len(rows) == 2
    assert rows[0].name == "Agumon"
    assert rows[0].x_antibody is False
    assert rows[1].x_antibody is True


def test_wikimon_parse_page(tmp_path):
    ad = WikimonAdapter()
    rec = ad._parse_page("Agumon", S2_FIXTURE)
    assert rec is not None
    names = {n.language: n.value for n in rec.names}
    assert names["ja"] == "アグモン"
    assert names["en"] == "Agumon"
    assert names["en_dub"] == "Augumon"
    assert names["zh_cn"] == "亚古兽"
    assert names["zh_tw"] == "亞古獸"
    assert rec.level_raw == "Child"
    assert rec.attribute_raw == "Vaccine"
    assert "Reptile" in rec.types
    assert "Deep Savers" in rec.fields and "Dragon's Roar" in rec.fields
    assert rec.groups == ["Agumon-species"]
    assert rec.is_official is True  # drbentry present
    assert rec.extra["drb_entry"] == "772"
    assert "Agumon (2006 Anime Version)" in [r["name"] for r in rec.extra["related"]]
    assert rec.profile["en"]
    assert rec.profile["ja"]
    assert rec.name_origin
    # special moves extracted from {{AT}} in profiles
    sm = [s.names.get("en") or s.names.get("ja") for s in rec.skills]
    assert "Baby Flame" in sm or "ベビーフレイム" in sm
    # evolution: junk card-game lines filtered, real ones kept
    assert "Koromon" in rec.evolves_from
    assert len(rec.evolves_from) == 1  # junk removed
    assert "Greymon" in rec.evolves_to
    assert "Agumon (X-Antibody)" in rec.evolves_to
    assert len(rec.evolves_to) == 2  # junk removed
    # primary line marked
    assert "Greymon" in rec.extra.get("primary_to", [])
    # condition captured
    assert rec.conditions.get("to:Greymon") == "with or without the Crest"


def test_wikimon_redirect_skipped():
    ad = WikimonAdapter()
    assert ad._parse_page("MudFrigimon", "#redirect [[Tuchidarumon]]") is None


def test_wikimon_non_digimon_skipped():
    ad = WikimonAdapter()
    assert ad._parse_page("List of Digimon", "just some text without an S2 infobox") is None


def test_extract_template_roundtrip():
    params, _ = extract_template(S2_FIXTURE, "S2")
    pd = dict(params)
    assert pd["kan"] == "アグモン"
    assert "DRBEntry" in pd["drbentry"]
    assert parse_ol_field(pd["ol"])["zh_cn"] == "亚古兽"


def test_dapi_pagination_ignores_broken_totalPages():
    """digi-api reports totalPages=1 even when a 2nd page exists (its known bug).
    The adapter must paginate until rows run short, not trust totalPages."""
    from pipeline.sources.dapi import DapiAdapter

    pages = {
        0: {"content": [{"id": i, "name": f"D{i}"} for i in range(1, 1001)],
            "pageable": {"totalElements": 1488, "totalPages": 1}},
        1: {"content": [{"id": i, "name": f"D{i}"} for i in range(1001, 1489)],
            "pageable": {"totalElements": 1488, "totalPages": 1}},
    }

    class FakeFetcher:
        def get_json(self, url, params=None):
            return pages[params["page"]]

    ids = DapiAdapter()._fetch_all_ids(FakeFetcher())
    assert len(ids) == 1488
