"""S1-4 tests: the diagnose script is read-only, structured, and never leaks
environment secrets."""
from __future__ import annotations

import json
import os

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
