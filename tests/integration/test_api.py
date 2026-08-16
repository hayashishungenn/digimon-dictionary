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


def test_by_ids_returns_requested_order(client, fixture_db):
    """The favorites endpoint returns list items in the requested id order,
    drops ids that don't exist, and is never shadowed by /digimon/{ident}."""
    _path, conn = fixture_db
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM digimon WHERE canonical_slug IN ('agumon','gabumon','wargreymon') ORDER BY id"
    )]
    # request in a non-id order to prove ordering follows the request
    ordered = [ids[2], ids[0], ids[1]]
    r = client.get("/api/digimon/by-id", params={"ids": ",".join(map(str, ordered))})
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["id"] for i in items] == ordered
    # nonexistent ids are dropped, not an error
    r2 = client.get("/api/digimon/by-id", params={"ids": "99999,1"})
    assert r2.status_code == 200
    assert [i["id"] for i in r2.json()["items"]] == [1]
    # "by-id" must not be captured by the /digimon/{ident} detail route
    assert client.get("/api/digimon/by-id").status_code == 422  # missing query param
    assert client.get("/api/digimon/by-id", params={"ids": "abc"}).json()["items"] == []


def test_by_ids_unicode_digits_are_ignored_not_500(client):
    """P2-04: tokens like '²' pass str.isdigit() but int() rejects them — the
    endpoint must ignore non-ASCII digits instead of returning a 500."""
    r = client.get("/api/digimon/by-id", params={"ids": "²"})
    assert r.status_code == 200
    assert r.json()["items"] == []
    # mixed input: valid ids kept, unicode/empty/negative tokens ignored
    r2 = client.get("/api/digimon/by-id", params={"ids": "1,²,2,,−3"})
    assert r2.status_code == 200
    assert [i["id"] for i in r2.json()["items"]] == [1, 2]


def test_queries_are_observable(client, caplog):
    """Every API request records SQL count + elapsed for the DB session (S1-3)."""
    import logging

    with caplog.at_level(logging.INFO, logger="apps.api.main"):
        assert client.get("/api/search", params={"q": "亚古兽"}).status_code == 200
        assert client.get("/api/digimon/agumon").status_code == 200
    sessions = [
        r.getMessage() for r in caplog.records
        if r.name == "apps.api.main" and "api db session" in r.getMessage()
    ]
    assert len(sessions) == 2
    for line in sessions:
        assert "SQL in" in line  # e.g. "api db session: 3 SQL in 1.2 ms"


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


def test_search_detail_lookup_is_batched(fixture_db):
    """P2-05: search must batch the detail lookup — the SQL count must not grow
    ~1 per extra result (a limit=100 search used to run 100 extra queries)."""
    from apps.api import queries

    _path, conn = fixture_db

    def count_for(limit):
        c = {"n": 0}
        conn.set_trace_callback(lambda _sql: c.__setitem__("n", c["n"] + 1))
        try:
            items = queries.search_digimon(conn, "a", limit=limit)
        finally:
            conn.set_trace_callback(None)
        return c["n"], len(items)

    n_small, k_small = count_for(1)
    n_large, k_large = count_for(6)
    assert k_small >= 1 and k_large >= k_small
    # the batched lookup is ONE query regardless of limit — widening the result
    # window must not add a query per extra row.
    assert n_large - n_small <= 2


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
    # depth > 3 rejected (le=3, P0-1: no depth=4 explosion)
    assert client.get("/api/digimon/agumon/evolution", params={"depth": 4}).status_code == 422
    assert client.get("/api/digimon/agumon/evolution", params={"depth": 5}).status_code == 422
    # non-integer depth rejected
    assert client.get("/api/digimon/agumon/evolution", params={"depth": "x"}).status_code == 422
    # depth=2 returns a neighbourhood with edges; every edge node is present
    g = client.get("/api/digimon/agumon/evolution", params={"depth": 2}).json()
    assert g["center"] is not None
    assert len(g["edges"]) >= 1
    for e in g["edges"]:
        # JSON serializes dict keys to strings; the frontend indexes with String()
        assert str(e["from"]) in g["nodes"] and str(e["to"]) in g["nodes"]


def test_evolution_response_has_budget_metadata(client):
    """P0-1: the response exposes explicit depth/counts/truncation so the UI can
    tell the user when part of the graph was dropped."""
    g = client.get("/api/digimon/agumon/evolution", params={"depth": 1}).json()
    assert g["node_count"] == len(g["nodes"])
    assert g["edge_count"] == len(g["edges"])
    assert g["depth"] >= 1
    assert isinstance(g["truncated"], bool)
    assert isinstance(g["dropped_edges"], int)
    # center always present
    assert str(g["center"]) in g["nodes"]


def test_evolution_truncates_at_budget(client):
    """A pathological hub must not return an unbounded graph: when the node/edge
    budget is hit the server stops and marks the response truncated."""
    from apps.api.queries import EVOLUTION_EDGE_BUDGET, EVOLUTION_NODE_BUDGET

    g = client.get("/api/digimon/agumon/evolution", params={"depth": 3}).json()
    assert g["edge_count"] <= EVOLUTION_EDGE_BUDGET
    assert g["node_count"] <= EVOLUTION_NODE_BUDGET
    if g["truncated"]:
        assert g["dropped_edges"] > 0
        # every edge endpoint resolves to a node in the partial graph
        for e in g["edges"]:
            assert str(e["from"]) in g["nodes"] and str(e["to"]) in g["nodes"]


def test_evolution_unknown_slug_404(client):
    assert client.get("/api/digimon/does-not-exist/evolution", params={"depth": 1}).status_code == 404


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


# ---------------------------------------------------------------------------
# P0-3: image serving endpoint + first appearance + thumbnail contract
# ---------------------------------------------------------------------------
def test_image_endpoint_404_for_digimon_without_image(client, fixture_db):
    # fixture digimon have no digimon_image rows -> 404 (frontend shows placeholder)
    r = client.get("/api/images/agumon/main_image")
    assert r.status_code == 404


def test_image_endpoint_rejects_bad_kind(client):
    assert client.get("/api/images/agumon/bogus").status_code == 400


def test_image_endpoint_unknown_slug_404(client):
    assert client.get("/api/images/not-a-digimon/main_image").status_code == 404


def test_image_endpoint_serves_local_file(client, fixture_db, tmp_path, monkeypatch):
    import struct

    import pipeline.core.config as cfg

    _path, conn = fixture_db
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 32, 32) + b"\x08\x06\x00\x00\x00"
    img_dir = tmp_path / "images"
    img_dir.mkdir()
    local = img_dir / "agumon.png"
    local.write_bytes(png)
    monkeypatch.setattr(cfg, "IMAGES_DIR", img_dir)  # the API resolves cache root from config
    did = conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()["id"]
    conn.execute("DELETE FROM digimon_image WHERE digimon_id=?", [did])  # isolate from prior tests
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status, content_type)
           VALUES(?, 'main_image', 'https://digi-api.com/x.png', ?, 'downloaded', 'image/png')""",
        [did, str(local)],
    )
    conn.commit()
    r = client.get("/api/images/agumon/main_image")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == png


def test_image_endpoint_redirects_to_remote_without_local(client, fixture_db):
    _path, conn = fixture_db
    did = conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()["id"]
    conn.execute("DELETE FROM digimon_image WHERE digimon_id=?", [did])  # isolate from prior tests
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, download_status)
           VALUES(?, 'main_image', 'https://digi-api.com/images/digimon/w/Agumon.png', 'pending')""",
        [did],
    )
    conn.commit()
    r = client.get("/api/images/agumon/main_image", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "https://digi-api.com/images/digimon/w/Agumon.png"


def test_list_thumbnail_field_is_null_without_cache(client):
    # fixture has no thumbnails -> thumbnail stays null so the UI falls back
    # to the main image / placeholder instead of a dead URL
    items = client.get("/api/digimon", params={"limit": 3}).json()["items"]
    assert all("thumbnail" in it for it in items)
    assert all(it["thumbnail"] is None for it in items)


def test_first_appearance_date_returned_even_without_title(client, fixture_db):
    _path, conn = fixture_db
    did = conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()["id"]
    conn.execute("UPDATE digimon SET first_appearance_date='1997', first_appearance_title=NULL WHERE id=?", [did])
    conn.commit()
    d = client.get("/api/digimon/agumon").json()
    assert d["first_appearance"]["date"] == "1997"
    assert d["first_appearance"]["title"] is None
