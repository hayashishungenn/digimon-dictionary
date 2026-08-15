"""Unit tests for the publish manifest (S0-1)."""
from __future__ import annotations

import json

from pipeline.core.manifest import (
    build_manifest,
    manifest_path_for,
    read_manifest,
    write_manifest,
)


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
