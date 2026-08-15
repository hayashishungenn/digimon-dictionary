"""S1-1 integration tests: manual review workflow (API + CLI + migration).

Builds a fixture DB with a representative review queue (external_target /
matching_failure / conflict / wikitext / other), then exercises the API
list/filter/stats/export/resolve surfaces and the review_queue CLI. Also
verifies the v7 -> v8 migration adds note + run_id without losing rows.
"""
from __future__ import annotations

import csv
import os

import pytest

from apps.api import queries
from pipeline.core.schema import connect
from tests.conftest import build_fixture_db


def _review_items(conn) -> None:
    """Insert one representative item per category (as the pipeline would)."""
    conn.execute(
        """INSERT INTO manual_review_queue(entity_type, entity_id, reason, detail, run_id)
           VALUES('edge', NULL, 'unresolved evolution target(s) for agumon',
                  '{"canonical_slug":"agumon","unresolved":[{"source":"wikimon","source_id":"X","ref":"[[FooMon]]"}]}',
                  'run-a')"""
    )
    conn.execute(
        """INSERT INTO manual_review_queue(entity_type, entity_id, reason, detail, run_id)
           VALUES('relation', NULL, 'unresolved relation target(s) for gabumon',
                  '{"canonical_slug":"gabumon","unresolved":[{"source":"dapi","ref":"BarMon"}]}', 'run-a')"""
    )
    conn.execute(
        """INSERT INTO manual_review_queue(entity_type, entity_id, reason, detail, run_id)
           VALUES('digimon', NULL, 'ambiguous exact name needs review',
                  '{"canonical_slug":"agumon-2006","record_sources":["dapi","wikimon"]}', 'run-a')"""
    )
    conn.execute(
        """INSERT INTO manual_review_queue(entity_type, entity_id, reason, detail, run_id)
           VALUES('digimon', NULL, 'level conflict cannot be resolved by source priority',
                  '{"field":"level","candidates":[{"value":"adult","source":"dapi"},{"value":"perfect","source":"wikimon"}]}',
                  'run-a')"""
    )
    conn.execute(
        """INSERT INTO manual_review_queue(entity_type, entity_id, reason, detail, run_id)
           VALUES('digimon', NULL, 'name_origin contains unresolved wikitext (P1-2)',
                  '{"canonical_slug":"agumon","field":"name_origin","value":"{{ETY|Foo}} [[bar]]"}', 'run-a')"""
    )
    conn.execute(
        """INSERT INTO manual_review_queue(entity_type, entity_id, reason, detail, run_id)
           VALUES('game', NULL, 'unmatched Cyber Sleuth record',
                  '{"name":"SomeMon","digidb_id":999}', 'run-a')"""
    )
    conn.commit()


@pytest.fixture
def review_db(tmp_path):
    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    _review_items(conn)
    conn.close()
    return db


@pytest.fixture
def env_db(monkeypatch, review_db):
    monkeypatch.setenv("DIGIDEX_DB", str(review_db))
    return review_db


def _api_client(db):
    os.environ["DIGIDEX_DB"] = str(db)
    from fastapi.testclient import TestClient

    from apps.api.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# query layer: categories / filters / stats / resolve
# ---------------------------------------------------------------------------
def test_review_categories_are_derived(review_db):
    conn = connect(review_db)
    items = queries.list_review_items(conn)
    conn.close()
    by_id = {i["reason"]: i["category"] for i in items}
    assert by_id["unresolved evolution target(s) for agumon"] == "external_target"
    assert by_id["unresolved relation target(s) for gabumon"] == "external_target"
    assert by_id["ambiguous exact name needs review"] == "matching_failure"
    assert by_id["level conflict cannot be resolved by source priority"] == "conflict"
    assert by_id["name_origin contains unresolved wikitext (P1-2)"] == "wikitext"
    assert by_id["unmatched Cyber Sleuth record"] == "other"
    # detail is decoded JSON, run_id is present
    edge = next(i for i in items if i["category"] == "external_target" and i["entity_type"] == "edge")
    assert edge["detail"]["unresolved"][0]["source"] == "wikimon"
    assert edge["run_id"] == "run-a"


def test_review_filters(review_db):
    conn = connect(review_db)
    assert len(queries.list_review_items(conn, entity_type="edge")) == 1
    assert len(queries.list_review_items(conn, category="external_target")) == 2
    assert len(queries.list_review_items(conn, q="wikitext")) == 1
    assert queries.count_review_items(conn, category="conflict") == 1
    assert queries.count_review_items(conn, q="FooMon") == 1  # detail search
    conn.close()


def test_review_stats(review_db):
    conn = connect(review_db)
    stats = queries.review_stats(conn)
    conn.close()
    assert stats["open"] == 6
    assert stats["by_category"]["external_target"] == 2
    assert stats["by_category"]["matching_failure"] == 1
    assert stats["by_entity"]["digimon"] == 3


def test_resolve_requires_note_and_keeps_candidates(review_db):
    conn = connect(review_db)
    open_item = queries.list_review_items(conn, category="wikitext")[0]
    with pytest.raises(ValueError, match="note"):
        queries.resolve_review_item(conn, open_item["id"], status="wontfix", note="  ")
    with pytest.raises(ValueError, match="status"):
        queries.resolve_review_item(conn, open_item["id"], status="bogus", note="x")

    row = queries.resolve_review_item(conn, open_item["id"], status="wontfix", note="won't chase for now")
    assert row["status"] == "wontfix"
    assert row["note"] == "won't chase for now"
    assert row["resolved_at"] is not None
    # original candidates preserved verbatim
    after = queries.list_review_items(conn, status="wontfix")
    assert len(after) == 1
    assert after[0]["detail"]["value"] == "{{ETY|Foo}} [[bar]]"
    # already closed -> cannot re-resolve
    assert queries.resolve_review_item(conn, open_item["id"], status="resolved", note="x") is None
    conn.close()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_api_review_list_and_filters(review_db, monkeypatch):
    c = _api_client(review_db)
    body = c.get("/api/review").json()
    assert body["total"] == 6
    assert all(i["status"] == "open" for i in body["items"])
    assert {i["category"] for i in body["items"]} == {
        "external_target", "matching_failure", "conflict", "wikitext", "other",
    }
    ext = c.get("/api/review", params={"category": "external_target"}).json()
    assert ext["total"] == 2
    bad = c.get("/api/review", params={"status": "nope"})
    assert bad.status_code == 422
    stats = c.get("/api/review/stats").json()
    assert stats["open"] == 6


def test_api_review_resolve(review_db, monkeypatch):
    c = _api_client(review_db)
    item = c.get("/api/review", params={"category": "matching_failure"}).json()["items"][0]
    r = c.post(f"/api/review/{item['id']}/resolve",
               json={"status": "resolved", "note": "confirmed the 2006 variant"})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"
    # empty note refused
    r2 = c.post(f"/api/review/{item['id']}/resolve",
                json={"status": "wontfix", "note": ""})
    assert r2.status_code == 422
    # unknown id 404
    assert c.post("/api/review/999999/resolve",
                  json={"status": "wontfix", "note": "x"}).status_code == 404


def test_api_review_export_json_and_csv(review_db, monkeypatch):
    c = _api_client(review_db)
    j = c.get("/api/review/export", params={"format": "json"}).json()
    assert j["count"] == 6
    assert j["items"][0]["detail"]  # decoded detail included
    csv_resp = c.get("/api/review/export", params={"format": "csv"})
    assert csv_resp.status_code == 200
    assert csv_resp.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(csv_resp.text.splitlines()))
    assert rows[0][0] == "id"
    assert rows[0][3] == "category"
    assert len(rows) == 7  # header + 6 items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_stats_list_show_resolve_export(review_db, monkeypatch, tmp_path):
    import scripts.review_queue as rq

    monkeypatch.setenv("DIGIDEX_DB", str(review_db))
    assert rq.main(["stats"]) == 0
    assert rq.main(["list", "--category", "wikitext"]) == 0
    assert rq.main(["show", "5"]) == 0  # wikitext item
    # resolve via CLI
    assert rq.main(["resolve", "5", "--status", "resolved", "--note", "checked the original"]) == 0
    conn = connect(review_db)
    row = conn.execute("SELECT status, note FROM manual_review_queue WHERE id=5").fetchone()
    conn.close()
    assert row["status"] == "resolved" and "checked" in row["note"]
    # export csv
    out = tmp_path / "queue.csv"
    assert rq.main(["export", "--status", "resolved", "--format", "csv", "--out", str(out)]) == 0
    assert out.exists()
    data = out.read_text("utf-8")
    assert "category" in data and "resolved" in data


def test_cli_bad_resolve_returns_nonzero(review_db, monkeypatch):
    import scripts.review_queue as rq

    monkeypatch.setenv("DIGIDEX_DB", str(review_db))
    assert rq.main(["resolve", "999999", "--status", "resolved", "--note", "x"]) == 1


# ---------------------------------------------------------------------------
# migration: v7 -> v8 keeps rows and adds note/run_id
# ---------------------------------------------------------------------------
def test_migration_adds_note_and_run_id(tmp_path):
    from pipeline.core.schema import SCHEMA_VERSION as SV
    from pipeline.core.schema import create_schema

    db = tmp_path / "old.sqlite"
    conn = connect(db)
    # build a v7-schema DB by hand: apply the base DDL then set user_version=7
    create_schema(conn)
    conn.execute("PRAGMA user_version = 7")
    # simulate the v7 review table (no note/run_id) by recreating it
    conn.execute("DROP TABLE manual_review_queue")
    conn.execute(
        """CREATE TABLE manual_review_queue (
            id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id INTEGER,
            reason TEXT NOT NULL, detail TEXT, status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT (datetime('now')), resolved_at TEXT)"""
    )
    conn.execute(
        """INSERT INTO manual_review_queue(entity_type, reason) VALUES('edge', 'unresolved target')"""
    )
    conn.execute("PRAGMA user_version = 7")
    conn.commit()
    conn.close()

    # reopening runs the v8 migration
    conn = connect(db)
    create_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SV
    cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_review_queue)")}
    assert "note" in cols and "run_id" in cols
    row = conn.execute("SELECT reason FROM manual_review_queue").fetchone()
    assert row["reason"] == "unresolved target"  # data preserved
    conn.close()
