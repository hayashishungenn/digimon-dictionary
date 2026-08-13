"""Unit tests for the MediaWiki wikitext parser used by the Wikimon adapter."""
from __future__ import annotations

from pipeline.sources import wikitext

SAMPLE = """
{{FArticle|162}}{{S2
|drbentry={{DRBEntry|772|773|2a=Zubamon}}
|kan=アグモン
|dub=Agumon
|dub2=Augumon
|ol={{CHI}} 亞古獸{{DD|a}}<br>{{ZHO}} 亚古兽{{DD|a}}<br>{{KOR}} 아구몬{{DD|a}} — ''Agumon''
|image=Agumon.jpg
|l1=Child
|a1=Vaccine
|t1=Reptile
|t2=Dinosaur
|f1=Deep Savers
|f2=Dragon's Roar
|g1=Agumon-species
|s1=Agumon (2006 Anime Version)
|s2=Agumon (Black)
|pn=DRB
|pe=A Reptile Digimon... {{AT|Baby Flame}}.
|pj=成長した爬虫類型デジモン。{{ATK|ベビーフレイム}}。
|ety=May come from {{JP}} {{ETY|Agu}}.
|yd=1997
}}

==Evolves From==
* '''[[Koromon]]'''
* [[Gigimon]]
* [[Digimon Card Game Colors and Levels#Red Lv.2 Digimon|Any Red Lv.2 Digimon from the ''Digimon Card Game'']]

==Evolves To==
* '''[[Greymon]]''' (with or without the Crest)
* [[Agumon (X-Antibody)]] (with or without the '''[[X-Antibody]]''')
* [[Agnimon]]{{ref|''[[Digital Monster: D-Project]]''}}
* [[Digimon Card Game Colors and Levels#Blue Lv.3 Digimon|Any Blue Lv.3 Digimon from the ''Digimon Card Game'']]
"""


def test_extract_template_params():
    params, end = wikitext.extract_template(SAMPLE, "S2")
    assert params is not None
    pd = dict(params)
    assert pd["kan"] == "アグモン"
    assert pd["l1"] == "Child"
    assert pd["a1"] == "Vaccine"
    assert pd["t1"] == "Reptile"
    assert pd["f1"] == "Deep Savers"
    assert pd["s1"] == "Agumon (2006 Anime Version)"
    # nested template values survive
    assert "DRBEntry" in pd["drbentry"]


def test_parse_ol_field():
    ol = wikitext.parse_ol_field("{{CHI}} 亞古獸{{DD|a}}<br>{{ZHO}} 亚古兽{{DD|a}}<br>{{KOR}} 아구몬{{DD|a}}")
    assert ol["zh_tw"] == "亞古獸"
    assert ol["zh_cn"] == "亚古兽"
    assert ol["ko"] == "아구몬"


def test_strip_markup():
    assert wikitext.strip_markup("[[Koromon]]<ref>''X''</ref>") == "Koromon"
    assert wikitext.strip_markup("'''[[Greymon]]'''") == "Greymon"


def test_extract_wiki_section():
    ef = wikitext.extract_wiki_section(SAMPLE, "Evolves From")
    et = wikitext.extract_wiki_section(SAMPLE, "Evolves To")
    assert len(ef) == 3
    assert len(et) == 4


def test_profile_attack_extraction_pattern():
    import re

    text = "A Reptile Digimon... {{AT|Baby Flame}}."
    m = re.findall(r"\{\{\s*AT(?:K)?\s*\|([^|}]+)", text)
    assert m == ["Baby Flame"]
