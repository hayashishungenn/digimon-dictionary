"""Unit tests for the publish manifest (S0-1)."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from pipeline.core.manifest import (
    build_manifest,
    consistency_report,
    manifest_path_for,
    read_manifest,
    stamp_db_hash,
    write_manifest,
)
from pipeline.core.schema import create_schema


def test_manifest_path_lives_next_to_db(tmp_path):
    db = tmp_path / "some dir with spaces" / "digidex.sqlite"
    assert manifest_path_for(db) == tmp_path / "some dir with spaces" / ".publish_manifest.json"


def test_write_read_roundtrip(tmp_path):
    path = tmp_path / ".publish_manifest.json"
    manifest = build_manifest(
        run_id="20260815T000000000000-abc",
        snapshot_date="2026-08-15",
        sources=["dapi", "wikimon"],
        db_sha256="a" * 64,
        report_sha256="b" * 64,
        schema_version=7,
        image_stage="ok",
        is_incremental_baseline=True,
        state_committed=True,
    )
    write_manifest(manifest, path)
    loaded = read_manifest(path)
    assert loaded == manifest
    # atomic write leaves no temp file behind
    assert not (tmp_path / ".publish_manifest.json.tmp").exists()


def test_read_missing_or_corrupt_returns_none(tmp_path):
    path = tmp_path / ".publish_manifest.json"
    assert read_manifest(path) is None  # absent
    path.write_text("{not json", "utf-8")
    assert read_manifest(path) is None  # unparseable
    path.write_text(json.dumps([1, 2, 3]), "utf-8")  # not a dict
    assert read_manifest(path) is None


def test_build_manifest_shape():
    m = build_manifest(
        run_id="r1", snapshot_date="2026-08-15", sources=["dapi"],
        db_sha256="abc", report_sha256=None, schema_version=7,
        image_stage="pending", is_incremental_baseline=False,
        state_committed=False, notes="partial",
    )
    assert m["run_id"] == "r1"
    assert m["snapshot_date"] == "2026-08-15"
    assert m["schema_version"] == 7
    assert m["sources"] == ["dapi"]
    assert m["database_sha256"] == "abc"
    assert m["report_sha256"] is None
    assert m["image_stage"] == "pending"
    assert m["is_incremental_baseline"] is False
    assert m["state_committed"] is False
    assert m["notes"] == "partial"


def _setup(tmp_path) -> tuple:
    """A DB file + manifest + report describing it. Uses a DELETE-journal
    connection so every write lands in the main .sqlite file (schema.connect is
    WAL — a byte-hash test must checkpoint, so we avoid it here)."""
    db = tmp_path / "digidex.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA foreign_keys = ON")
    create_schema(conn)
    conn.execute("INSERT INTO digimon(id, canonical_slug) VALUES(1, 'x')")
    conn.commit()
    conn.close()
    db_sha = hashlib.sha256(db.read_bytes()).hexdigest()
    report = tmp_path / "reports" / "data-quality.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({"db_sha256": db_sha, "issues": []}), "utf-8")
    manifest = build_manifest(
        run_id="r1", snapshot_date="2026-08-15", sources=["dapi"],
        db_sha256=db_sha, report_sha256=hashlib.sha256(report.read_bytes()).hexdigest(),
        schema_version=8, image_stage="pending", is_incremental_baseline=False,
        state_committed=True,
    )
    write_manifest(manifest, manifest_path_for(db))
    return db, db_sha


def test_stamp_db_hash_refreshes_manifest_and_report(tmp_path):
    """P0-2: after the DB bytes change, stamp_db_hash re-stamps the report's
    db_sha256 and updates both manifest hashes atomically."""
    db, _old_sha = _setup(tmp_path)
    report = tmp_path / "reports" / "data-quality.json"

    # simulate a post-publish change to the DB (e.g. image stage)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("UPDATE digimon SET name_en='changed' WHERE id=1")
    conn.commit()
    conn.close()
    new_sha = hashlib.sha256(db.read_bytes()).hexdigest()
    assert new_sha != _old_sha

    stamp_db_hash(db)
    report_sha = hashlib.sha256(report.read_bytes()).hexdigest()
    manifest = read_manifest(manifest_path_for(db))
    assert manifest["database_sha256"] == new_sha
    assert manifest["report_sha256"] == report_sha
    assert json.loads(report.read_text("utf-8"))["db_sha256"] == new_sha
    # no temp files left
    assert not (tmp_path / ".publish_manifest.json.tmp").exists()
    assert not (report.parent / "data-quality.json.tmp").exists()


def test_stamp_db_hash_noop_without_manifest(tmp_path):
    db = tmp_path / "digidex.sqlite"
    db.write_bytes(b"x")
    assert stamp_db_hash(db) is None


def test_consistency_report_detects_mismatch(tmp_path):
    """P0-2: consistency_report tells diagnose when db/manifest/report diverge."""
    db, db_sha = _setup(tmp_path)
    cons = consistency_report(db)
    assert cons["manifest_present"] is True
    assert cons["database_sha256_matches_db"] is True
    assert cons["report_sha256_matches_report"] is True
    assert cons["report_db_sha256_matches_db"] is True

    # mutate the DB after the fact -> only the manifest/report side is stale
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("UPDATE digimon SET name_en='changed' WHERE id=1")
    conn.commit()
    conn.close()
    cons = consistency_report(db)
    assert cons["database_sha256_matches_db"] is False
    assert cons["report_db_sha256_matches_db"] is False
