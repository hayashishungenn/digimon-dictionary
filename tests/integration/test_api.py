"""API integration tests (FastAPI TestClient against a fixture DB)."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(fixture_db):
    from apps.api.main import app

    path, _conn = fixture_db
    os.environ["DIGIDEX_DB"] = str(path)
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["db_ready"] is True


def test_meta(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    meta = r.json()
    assert meta["counts"]["total"] == 6
    assert meta["snapshot"]["official_count"] == 6
    levels = {lv["value"] for lv in meta["levels"]}
    assert "child" in levels and "ultimate" in levels


def test_list(client):
    r = client.get("/api/digimon")
    body = r.json()
    assert body["total"] == 6
    assert len(body["items"]) == 6


def test_list_filter_level(client):
    r = client.get("/api/digimon", params={"level": "adult"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_slug"] == "greymon"


def test_list_filter_attribute(client):
    r = client.get("/api/digimon", params={"attribute": "vaccine"})
    assert r.json()["total"] == 6


def test_list_filter_group(client):
    r = client.get("/api/digimon", params={"group": "Royal Knights"})
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["canonical_slug"] == "wargreymon"


def test_list_sort_recent(client):
    # regression: sort=recent used to produce invalid SQL (DESC ASC -> 500)
    r = client.get("/api/digimon", params={"sort": "recent", "order": "desc", "limit": 3})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 3


def test_list_pagination(client):
    r1 = client.get("/api/digimon", params={"limit": 2, "offset": 0})
    r2 = client.get("/api/digimon", params={"limit": 2, "offset": 2})
    ids1 = [i["id"] for i in r1.json()["items"]]
    ids2 = [i["id"] for i in r2.json()["items"]]
    assert ids1 and ids2
    assert set(ids1).isdisjoint(ids2)  # pages do not overlap


def test_detail_by_slug(client):
    r = client.get("/api/digimon/agumon")
    assert r.status_code == 200
    d = r.json()
    assert d["names"]["zh_cn"] == "亚古兽"
    assert d["names"]["en"] == "Agumon"
    assert d["names"]["ja"] == "アグモン"
    assert d["level"] == "child"
    assert d["attribute"] == "vaccine"
    assert len(d["skills"]) == 2
    assert d["profile"]["en"] == "A Reptile Digimon."
    # evolution neighborhood
    assert d["evolution"]["center"] == d["id"]
    slugs = [n["canonical_slug"] for n in d["evolution"]["nodes"].values()]
    assert "koromon" in slugs and "greymon" in slugs


def test_detail_404(client):
    assert client.get("/api/digimon/does-not-exist").status_code == 404


def test_search_chinese(client):
    r = client.get("/api/search", params={"q": "亚古兽"})
    items = r.json()["items"]
    assert any(i["canonical_slug"] == "agumon" for i in items)


def test_search_traditional_chinese_converts(client):
    # §35: 简繁转换 — 繁体 "亞古獸" must hit the same 亚古兽 entity
    r = client.get("/api/search", params={"q": "亞古獸"})
    items = r.json()["items"]
    assert any(i["canonical_slug"] == "agumon" for i in items)


def test_search_fan_alias(client, fixture_db):
    # §35: fan abbreviation "战暴" resolves via fan_translation alias
    from pipeline.core.schema import connect as _connect

    _path, conn = fixture_db
    by_slug = {r["canonical_slug"]: r["id"] for r in conn.execute("SELECT id, canonical_slug FROM digimon")}
    conn.execute(
        """INSERT OR IGNORE INTO digimon_alias
           (digimon_id, alias, language, alias_type, source, verified)
           VALUES(?,?,?,?,?,?)""",
        [by_slug["wargreymon"], "战暴", "zh_cn", "fan_translation", "manual", 0],
    )
    conn.commit()
    r = client.get("/api/search", params={"q": "战暴"})
    assert any(i["canonical_slug"] == "wargreymon" for i in r.json()["items"])


def test_search_japanese(client):
    r = client.get("/api/search", params={"q": "アグモン"})
    items = r.json()["items"]
    assert any(i["canonical_slug"] == "agumon" for i in items)


def test_search_english_partial(client):
    r = client.get("/api/search", params={"q": "Wargre"})
    items = r.json()["items"]
    assert any(i["canonical_slug"] == "wargreymon" for i in items)


def test_search_returns_same_entity_across_languages(client):
    def find(q):
        return client.get("/api/search", params={"q": q}).json()["items"][0]["id"]

    zh = find("亚古兽")
    en = find("Agumon")
    ja = find("アグモン")
    assert zh == en == ja


def test_evolution_endpoint(client):
    r = client.get("/api/digimon/agumon/evolution", params={"depth": 2})
    assert r.status_code == 200
    g = r.json()
    assert g["center"] is not None
    assert len(g["edges"]) >= 2


def test_skills_endpoint(client):
    r = client.get("/api/digimon/agumon/skills")
    names = [s["name_en"] for s in r.json()]
    assert "Baby Flame" in names


def test_aliases_endpoint(client):
    r = client.get("/api/digimon/agumon/aliases")
    assert r.status_code == 200


def test_group_endpoint(client):
    r = client.get("/api/groups/Royal Knights")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_relations_in_detail(client):
    d = client.get("/api/digimon/wargreymon").json()
    rel_types = {rel["relation_type"] for rel in d["relations"]}
    assert "same_species" in rel_types


def test_game_stats_in_detail(client, fixture_db):
    """game stats appear in detail but never touch world-view fields."""
    from pipeline.core.models import SourceDigimon, SourceName
    from pipeline.sources.digidb import import_game_stats

    _path, conn = fixture_db
    rec = SourceDigimon(
        source="digidb", source_id="1",
        names=[SourceName("Agumon", "en", status="community", source="digidb")],
        extra={"game": "Digimon Story: Cyber Sleuth", "game_short": "cyber-sleuth",
               "game_stats": {"hp": 1030, "sp": 200, "atk": 131, "def": 100, "int": 90,
                              "spd": 95, "memory": 5, "equip slots": 2, "stage": "Rookie",
                              "element": "Neutral"}},
    )
    import_game_stats(conn, [rec])

    d = client.get("/api/digimon/agumon").json()
    assert len(d["game_stats"]) == 1
    gs = d["game_stats"][0]
    assert gs["game"] == "Digimon Story: Cyber Sleuth"
    assert gs["hp"] == 1030
    # world-view level untouched (still child from the fixture)
    assert d["level"] == "child"
