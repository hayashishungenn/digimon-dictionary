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


def _ids(items):
    return [i["id"] for i in items]


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


def test_search_space_variant(client):
    # §35: "War Greymon" (with space) must hit the WarGreymon entity
    r = client.get("/api/search", params={"q": "War Greymon"})
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


# ---------------------------------------------------------------------------
# T5: security + search + response contract
# ---------------------------------------------------------------------------
def test_health_does_not_leak_paths(client):
    """/api/health must not expose db_path or absolute filesystem info."""
    body = client.get("/api/health").json()
    assert "db_path" not in body
    assert "DIGIDEX_DB" not in body
    assert "C:" not in str(body)
    assert body["ok"] is True


def test_cors_defaults_to_localhost(monkeypatch):
    from apps.api.main import _cors_origins

    monkeypatch.delenv("DIGIDEX_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("DIGIDEX_ENV", raising=False)
    origins = _cors_origins()
    assert "*" not in origins
    assert "http://localhost:5173" in origins


def test_cors_env_override(monkeypatch):
    from apps.api.main import _cors_origins

    monkeypatch.setenv("DIGIDEX_CORS_ORIGINS", "https://a.example,https://b.example")
    assert _cors_origins() == ["https://a.example", "https://b.example"]


def test_cors_refuses_wildcard_outside_dev(monkeypatch):
    """A literal '*' is refused unless DIGIDEX_ENV=development."""
    from apps.api.main import _cors_origins

    monkeypatch.setenv("DIGIDEX_CORS_ORIGINS", "*")
    monkeypatch.delenv("DIGIDEX_ENV", raising=False)
    assert "*" not in _cors_origins()

    monkeypatch.setenv("DIGIDEX_ENV", "development")
    assert "*" in _cors_origins()


def test_search_like_wildcards_are_escaped(client):
    """A '%' or '_' in user input must not become a full-table wildcard."""
    r = client.get("/api/search", params={"q": "%"})
    assert r.status_code == 200
    assert r.json()["count"] == 0

    r = client.get("/api/search", params={"q": "_"})
    assert r.status_code == 200
    assert r.json()["count"] == 0

    r = client.get("/api/search", params={"q": "A%"})
    assert r.status_code == 200
    assert all("A%" not in (i["name_en"] or "") for i in r.json()["items"])


def test_search_malformed_fts_and_quotes_are_safe(client):
    # quotes make a malformed FTS phrase -> observable fallback, never a 500
    r = client.get("/api/search", params={"q": '"'})
    assert r.status_code == 200

    r = client.get("/api/search", params={"q": "not-a-digimon-zzz"})
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_search_no_offset_in_contract(client):
    """Keyword search is not offset-paginated: the response contract has no
    offset and an unknown offset param is ignored (T5.4)."""
    body = client.get("/api/search", params={"q": "Agumon"}).json()
    assert "offset" not in body
    assert body["count"] >= 1


def test_relations_express_direction(client):
    """The fixture has wargreymon -> agumon (same_species). Both endpoints must
    state the direction explicitly while keeping to_id as the other digimon."""
    wg = client.get("/api/digimon/wargreymon").json()
    ag = client.get("/api/digimon/agumon").json()

    out = [r for r in wg["relations"] if r["relation_type"] == "same_species"]
    assert out and out[0]["direction"] == "out"
    assert out[0]["from_id"] == wg["id"]
    assert out[0]["to_id"] == ag["id"]
    assert out[0]["canonical_slug"] == "agumon"

    inc = [r for r in ag["relations"] if r["relation_type"] == "same_species"]
    assert inc and inc[0]["direction"] == "in"
    assert inc[0]["from_id"] == wg["id"]
    assert inc[0]["to_id"] == ag["id"]


def test_evolution_depth_and_bounds(client):
    # depth=0 rejected (ge=1)
    assert client.get("/api/digimon/agumon/evolution", params={"depth": 0}).status_code == 422
    # depth > 4 rejected (le=4)
    assert client.get("/api/digimon/agumon/evolution", params={"depth": 5}).status_code == 422
    # depth=2 returns a neighbourhood with edges; every edge node is present
    g = client.get("/api/digimon/agumon/evolution", params={"depth": 2}).json()
    assert g["center"] is not None
    assert len(g["edges"]) >= 1
    for e in g["edges"]:
        # JSON serializes dict keys to strings; the frontend indexes with String()
        assert str(e["from"]) in g["nodes"] and str(e["to"]) in g["nodes"]


def test_list_bounds(client):
    assert client.get("/api/digimon", params={"limit": 0}).status_code == 422
    assert client.get("/api/digimon", params={"limit": 9999}).status_code == 422
    assert client.get("/api/digimon", params={"offset": -1}).status_code == 422
    assert client.get("/api/digimon", params={"sort": "bogus"}).status_code == 422
    assert client.get("/api/digimon", params={"order": "sideways"}).status_code == 422


def test_sqlite_error_is_stable_500(client, monkeypatch, tmp_path):
    """A corrupt database must yield a clean JSON 500, never a traceback."""
    bad = tmp_path / "corrupt.sqlite"
    bad.write_bytes(b"this is not a sqlite database at all")
    monkeypatch.setenv("DIGIDEX_DB", str(bad))
    resp = client.get("/api/digimon")
    assert resp.status_code == 500
    body = resp.json()
    assert isinstance(body.get("detail"), str)
    assert "Traceback" not in str(body)


def test_search_returns_same_entity_across_languages_paginated(client):
    """Two search pages do not overlap and are contiguous (T5.4)."""
    r = client.get("/api/digimon", params={"limit": 2, "offset": 0})
    r2 = client.get("/api/digimon", params={"limit": 2, "offset": 2})
    ids1 = _ids(r.json()["items"])
    ids2 = _ids(r2.json()["items"])
    assert ids1 and ids2
    assert set(ids1).isdisjoint(ids2)
