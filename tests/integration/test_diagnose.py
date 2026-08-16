"""S1-4 tests: the diagnose script is read-only, structured, and never leaks
environment secrets."""
from __future__ import annotations

import json
import os
import shutil

import pytest

import scripts.diagnose as diagnose


def test_diagnose_json_reports_facts(tmp_path, capsys):
    """A fixture DB yields structured versions/database/sync facts, exit 0."""
    from tests.conftest import build_fixture_db

    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    conn.execute(
        """INSERT INTO sync_run(run_id, status, sources, snapshot_date, started_at, finished_at)
           VALUES('run-x','ok','dapi','2026-08-15','2026-08-15T00:00:00+00:00','2026-08-15T00:00:01+00:00')"""
    )
    conn.commit()
    conn.close()

    rc = diagnose.main(["--json", "--db", str(db)])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["versions"]["python"].startswith("Python")
    assert report["database"]["path"] == str(db)
    assert report["database"]["exists"] is True
    assert report["database"]["integrity_ok"] is True
    assert report["database"]["snapshot_date"]  # date is runtime, not hardcoded
    assert report["database"]["counts"]["total"] == 6
    assert report["last_sync"]["run_id"] == "run-x"
    assert report["last_sync"]["status"] == "ok"


def test_diagnose_image_path_contract(tmp_path, capsys):
    """P0-0/P0-1: diagnose counts absolute vs relative local_path, thumbnail
    rows in the DB, and populated digimon.thumbnail — proving whether the image
    path contract (relative-or-NULL) holds."""
    from tests.conftest import build_fixture_db

    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    did = conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()[0]
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status)
           VALUES(?, 'main_image', 'https://x/1.png', ?, 'downloaded')""",
        [did, r"C:\Users\old\Github\Digimon_Dictionary\data\images\digi_00001_Agumon.png"],
    )
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, remote_url, local_path, download_status)
           VALUES(?, 'main_image', 'https://x/2.png', ?, 'downloaded')""",
        [did, "digi_00002_f1e2a3.png"],
    )
    conn.execute(
        """INSERT INTO digimon_image(digimon_id, image_type, local_path, download_status)
           VALUES(?, 'thumbnail', ?, 'downloaded')""",
        [did, "thumbs/digi_00001.png"],
    )
    conn.execute("UPDATE digimon SET thumbnail=? WHERE id=?", ["thumbs/digi_00001.png", did])
    conn.commit()
    conn.close()

    rc = diagnose.main(["--json", "--db", str(db)])
    assert rc == 0
    contract = json.loads(capsys.readouterr().out)["database"]["image_path_contract"]
    assert contract["absolute_local_paths"] == 1
    assert contract["relative_local_paths"] == 2
    assert contract["thumbnails_in_db"] == 1
    assert contract["digimon_with_thumbnail"] == 1


def test_diagnose_manifest_consistency(tmp_path, capsys):
    """P0-2: diagnose reports manifest/db/report hash consistency, and flags a
    stale manifest after the DB bytes change."""
    from pipeline.core.manifest import (
        build_manifest,
        manifest_path_for,
        write_manifest,
    )
    from tests.conftest import build_fixture_db

    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    conn.close()
    report = tmp_path / "reports" / "data-quality.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(
        run_id="r9", snapshot_date="2026-08-15", sources=["dapi"],
        db_sha256="0" * 64, report_sha256="0" * 64, schema_version=8,
        image_stage="ok", is_incremental_baseline=True, state_committed=True,
    )
    write_manifest(manifest, manifest_path_for(db))
    report.write_text(json.dumps({"db_sha256": "0" * 64}), "utf-8")

    rc = diagnose.main(["--json", "--db", str(db)])
    assert rc == 0
    cons = json.loads(capsys.readouterr().out)["manifest_consistency"]
    assert cons["manifest_present"] is True
    # the fake hashes don't match the real db/report -> every check is False
    assert cons["database_sha256_matches_db"] is False
    assert cons["report_sha256_matches_report"] is False
    assert cons["report_db_sha256_matches_db"] is False
    assert cons["image_stage"] == "ok"


def test_diagnose_missing_db_is_graceful(tmp_path, capsys):
    rc = diagnose.main(["--json", "--db", str(tmp_path / "absent.sqlite")])
    assert rc == 0
    report = json.loads(capsys.readouterr().out)
    assert report["database"]["exists"] is False
    assert report["database"]["integrity_ok"] is None


def test_diagnose_never_leaks_environment(tmp_path, capsys):
    """The report must not contain any environment variable values or secrets."""
    from tests.conftest import build_fixture_db

    db = tmp_path / "digidex.sqlite"
    conn = build_fixture_db(db)
    conn.close()

    # plant a "secret" in the environment and confirm it never appears
    os.environ["DIGIDEX_SUPER_SECRET_TOKEN"] = "super-secret-value-xyz"
    os.environ["PATH"] = os.environ.get("PATH", "")  # exists on all platforms
    try:
        diagnose.main(["--json", "--db", str(db)])
        out = capsys.readouterr().out
    finally:
        os.environ.pop("DIGIDEX_SUPER_SECRET_TOKEN", None)

    assert "super-secret-value-xyz" not in out
    # env var NAMES aren't printed either (no DIGIDEX_ env values leak)
    assert "DIGIDEX_SUPER_SECRET_TOKEN" not in out
    # PATH's value is not echoed
    for part in os.environ["PATH"].split(os.pathsep):
        if part and len(part) > 3:
            assert part not in out, f"PATH segment leaked: {part}"


def test_diagnose_resolves_npm_when_installed():
    """P3: on Windows npm is a .cmd shim — _run must resolve the executable via
    shutil.which's full path and never report '(not found)' when npm exists."""
    if shutil.which("npm") is None and shutil.which("npm.cmd") is None:
        pytest.skip("npm not installed on this machine")
    version = diagnose._run(["npm", "--version"])
    assert version != "(not found)"
    assert version and version[0].isdigit()
