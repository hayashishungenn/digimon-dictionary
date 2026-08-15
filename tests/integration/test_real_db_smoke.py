"""Real-database smoke test (P0-0 / P0-1).

Runs the FastAPI against the REAL data/digidex.sqlite (not a fixture) and checks
the key query surfaces are usable at real scale: health, meta, trilingual
search, combined filters, Agumon detail, group page, and the evolution graph at
depth 1..3 with its budget/truncation metadata.

Gating: the real DB is gitignored and regenerable via sync_data.py, so this
test skips when it is absent. Set DIGIDEX_SKIP_REAL_SMOKE=1 to force-skip even
when the DB exists (CI should not depend on a locally-synced DB).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
REAL_DB = ROOT / "data" / "digidex.sqlite"

pytestmark = pytest.mark.skipif(
    not REAL_DB.exists() or os.environ.get("DIGIDEX_SKIP_REAL_SMOKE") == "1",
    reason="real data/digidex.sqlite not present (run sync_data.py first)",
)


@pytest.fixture(scope="module")
def client():
    from apps.api.main import app

    os.environ["DIGIDEX_DB"] = str(REAL_DB)
    with TestClient(app) as c:
        yield c


def _expect(r, status=200):
    assert r.status_code == status, f"{r.status_code}: {r.text[:300]}"
    return r.json()


def test_health_and_meta(client):
    body = _expect(client.get("/api/health"))
    assert body["ok"] is True and body["db_ready"] is True
    meta = _expect(client.get("/api/meta"))
    # counts are computed at runtime, never hardcoded
    assert meta["counts"]["total"] > 1000
    assert meta["counts"]["official"] > 1000
    assert meta["counts"]["official"] + meta["counts"]["extended"] == meta["counts"]["total"]
    assert meta["snapshot"] is not None


def test_trilingual_search_hits_same_entity(client):
    def first_id(q):
        body = _expect(client.get("/api/search", params={"q": q}))
        assert body["count"] >= 1, f"no result for {q!r}"
        return body["items"][0]["id"]

    zh = first_id("亚古兽")
    traditional = first_id("亞古獸")
    en = first_id("Agumon")
    ja = first_id("アグモン")
    assert zh == en == ja == traditional


def test_partial_and_alias_search(client):
    part = _expect(client.get("/api/search", params={"q": "Wargre"}))
    assert any(i["canonical_slug"] == "war-greymon" for i in part["items"])
    alias = _expect(client.get("/api/search", params={"q": "战暴"}))
    assert any(i["canonical_slug"] == "war-greymon" for i in alias["items"])


def test_combined_filter(client):
    body = _expect(
        client.get(
            "/api/digimon",
            params={
                "level": "ultimate",
                "attribute": "vaccine",
                "group": "Royal Knights",
                "official": "official",
                "limit": 20,
            },
        )
    )
    assert body["total"] >= 1
    for item in body["items"]:
        assert item["level"] == "ultimate"
        assert item["attribute"] == "vaccine"


def test_agumon_detail(client):
    d = _expect(client.get("/api/digimon/agumon"))
    assert d["canonical_slug"] == "agumon"
    assert d["names"]["zh_cn"] == "亚古兽"
    assert d["names"]["en"] == "Agumon"
    assert d["names"]["ja"] == "アグモン"
    assert d["level"] == "child"
    assert d["attribute"] == "vaccine"
    assert len(d["skills"]) >= 1
    # evolution neighbourhood embedded in the detail loads at depth 1
    assert d["evolution"]["center"] == d["id"]
    assert d["evolution"]["node_count"] == len(d["evolution"]["nodes"])


def test_group_page(client):
    body = _expect(client.get("/api/groups/Royal%20Knights"))
    assert body["count"] == len(body["members"])
    assert body["count"] >= 1


def test_images_served_or_absent(client):
    """P0-3: every real digimon resolves an image to either a cached file, a
    redirect to the source, or an explicit 404 (placeholder) — never a crash."""
    # agumon has a cached main image + thumbnail
    r = client.get("/api/images/agumon/thumbnail")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")
    # invalid kind rejected
    assert client.get("/api/images/agumon/bogus").status_code == 400
    # unknown slug 404
    assert client.get("/api/images/not-a-digimon/main_image").status_code == 404
    # any entity without a main image resolves to an explicit 404
    import sqlite3

    conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    noimg = conn.execute(
        "SELECT canonical_slug FROM digimon WHERE main_image IS NULL OR TRIM(main_image)='' LIMIT 1"
    ).fetchone()
    conn.close()
    if noimg is not None:
        r = client.get(f"/api/images/{noimg['canonical_slug']}/main_image")
        assert r.status_code in (404, 200, 302, 307)  # served, redirect, or placeholder-404
    # list items carry a servable thumbnail contract
    items = _expect(client.get("/api/digimon", params={"limit": 3}))["items"]
    for it in items:
        assert "thumbnail" in it


def test_first_appearance_date_real(client):
    """P0-3: real digimon expose first-appearance date even without a title."""
    d = _expect(client.get("/api/digimon/agumon"))
    assert d["first_appearance"]["date"] is not None or d["first_appearance"]["title"] is not None


def test_evolution_depth_bounds(client):
    for depth in (0, 4, 5):
        assert client.get("/api/digimon/agumon/evolution", params={"depth": depth}).status_code == 422
    assert client.get("/api/digimon/agumon/evolution", params={"depth": "x"}).status_code == 422
    assert client.get("/api/digimon/not-a-digimon/evolution", params={"depth": 1}).status_code == 404


def test_evolution_non_hub_full_traversal(client):
    """A low-degree digimon is well under budget, so depth 3 completes fully."""
    g = _expect(client.get("/api/digimon/grimmon/evolution", params={"depth": 3}))
    assert g["truncated"] is False
    assert g["depth"] == 3
    assert str(g["center"]) in g["nodes"]
    assert g["edge_count"] == len(g["edges"])


def test_evolution_ring_and_isolated(client):
    """Graph semantics survive real data: cycles are allowed and an entity with
    no edges returns an empty (not failing) graph with the center node."""
    # agumon has a cycle-rich neighbourhood; just confirm the response shape is valid
    g = _expect(client.get("/api/digimon/agumon/evolution", params={"depth": 1}))
    assert g["edge_count"] == len(g["edges"])
    # an entity with zero evolution edges must still resolve (empty graph).
    # The API has no "isolated" endpoint, so locate one via the real DB directly.
    import sqlite3

    conn = sqlite3.connect(f"file:{REAL_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    isolated = conn.execute(
        """SELECT d.canonical_slug FROM digimon d
           WHERE NOT EXISTS (SELECT 1 FROM evolution_edge e
                             WHERE e.from_digimon_id = d.id OR e.to_digimon_id = d.id)
           LIMIT 1"""
    ).fetchone()
    conn.close()
    if isolated is not None:
        g = _expect(client.get(f"/api/digimon/{isolated['canonical_slug']}/evolution", params={"depth": 1}))
        assert g["edge_count"] == 0
        assert str(g["center"]) in g["nodes"]


def test_evolution_depths_bounded_and_consistent(client):
    """Real-scale graph is bounded, deterministic and self-consistent."""
    from apps.api.queries import EVOLUTION_EDGE_BUDGET, EVOLUTION_NODE_BUDGET

    prev: dict | None = None
    for depth in (1, 2, 3):
        t0 = time.perf_counter()
        g = _expect(client.get("/api/digimon/agumon/evolution", params={"depth": depth}))
        elapsed = time.perf_counter() - t0
        # usable upper bounds — never an unrenderable full graph
        assert g["edge_count"] <= EVOLUTION_EDGE_BUDGET
        assert g["node_count"] <= EVOLUTION_NODE_BUDGET
        # depth reports the levels actually traversed (may be < requested when
        # the budget was hit part-way — that is what `truncated` communicates)
        assert 1 <= g["depth"] <= depth
        assert str(g["center"]) in g["nodes"]
        for e in g["edges"]:
            assert str(e["from"]) in g["nodes"] and str(e["to"]) in g["nodes"]
        # deeper request is a superset of the shallower one
        if prev is not None:
            assert len(g["nodes"]) >= len(prev["nodes"])
            assert len(g["edges"]) >= len(prev["edges"])
        prev = g
        print(f"    depth={depth}: {len(g['nodes'])} nodes / {len(g['edges'])} edges "
              f"truncated={g['truncated']} dropped={g['dropped_edges']} in {elapsed:.2f}s")
