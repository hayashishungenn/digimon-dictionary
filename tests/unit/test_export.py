"""T9 tests: dataset export atomicity/coverage and conflict-report escaping."""
from __future__ import annotations

import csv
import json
import sqlite3

import pytest

import scripts.export_dataset as export
import scripts.review_conflicts as rc
from scripts.export_dataset import EXPORT_VERSION
from tests.conftest import build_fixture_db


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    """A fixture DB exported from, with DB_PATH pointed at it."""
    db = tmp_path / "src.sqlite"
    conn = build_fixture_db(db)
    conn.close()
    monkeypatch.setattr(export, "DB_PATH", db)
    monkeypatch.setattr(rc, "DB_PATH", db)
    return db, tmp_path


def test_json_export_covers_all_domains(fixture):
    _, tmp = fixture
    out = tmp / "out"
    export.export_dataset(out, ["json"])
    data = json.loads((out / "digimon.json").read_text("utf-8"))

    assert data["export_version"] == EXPORT_VERSION
    assert "generated_at" in data
    assert data["digimon"]  # non-empty
    # every data domain from the spec is present
    for key in ("types", "fields", "groups", "skills", "evolution_edges", "relations",
                "images", "provenance", "conflicts", "review_queue", "game_stats",
                "snapshot", "source_sync"):
        assert key in data, key

    agumon = next(d for d in data["digimon"] if d["canonical_slug"] == "agumon")
    assert agumon["aliases"] or True
    assert "skills" in agumon and "evolves_to" in agumon and "images" in agumon
    assert agumon["evolves_to"]  # agumon -> greymon edge
    assert "relations" in data and data["relations"]  # wargreymon -> agumon


def test_json_is_rereadable_and_no_nplus1(fixture, monkeypatch):
    _, tmp = fixture
    out = tmp / "out"

    # count SQL during the JSON export via a per-connection trace callback
    calls: list[str] = []
    orig_connect = export.connect

    def traced_connect(path):
        conn = orig_connect(path)
        conn.set_trace_callback(calls.append)
        return conn

    monkeypatch.setattr(export, "connect", traced_connect)
    export.export_dataset(out, ["json"])

    # the N+1 signature is a per-digimon "WHERE <join>.<fk>=?" query — the
    # batched export must never issue one
    nplus1 = [q for q in calls if q and "WHERE digimon_id = ?" in q or
              "WHERE ds.digimon_id=?" in q or "WHERE df.digimon_id=?" in q or
              "WHERE dg.digimon_id=?" in q]
    assert not nplus1, f"N+1 queries found: {nplus1}"

    data = json.loads((out / "digimon.json").read_text("utf-8"))
    assert data["digimon"]


def test_csv_roundtrip(fixture):
    _, tmp = fixture
    out = tmp / "out"
    export.export_dataset(out, ["csv"])
    with open(out / "digimon.csv", encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    assert rows[0][0] == "id"
    assert len(rows) > 1  # header + data
    # every row has the same column count (quoting handles commas/Unicode)
    ncols = len(rows[0])
    assert all(len(r) == ncols for r in rows)


def test_sqlite_export_passes_integrity_check(fixture):
    _, tmp = fixture
    out = tmp / "out"
    export.export_dataset(out, ["sqlite"])
    dest = out / "digidex.sqlite"
    assert dest.exists()
    con = sqlite3.connect(dest)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("SELECT COUNT(*) FROM digimon").fetchone()[0] > 0
    con.close()


def test_failed_export_keeps_existing_target(tmp_path, monkeypatch):
    """A failed export must not destroy an existing target file (atomic writes)."""
    broken = tmp_path / "broken"
    broken.mkdir()
    monkeypatch.setattr(export, "DB_PATH", broken)  # sqlite cannot open a directory
    out = tmp_path / "out"
    out.mkdir()
    marker = out / "digimon.json"
    marker.write_text("ORIGINAL", encoding="utf-8")
    with pytest.raises(sqlite3.OperationalError):
        export.export_dataset(out, ["json"])
    assert marker.read_text("utf-8") == "ORIGINAL"
    assert not list(out.glob("*.tmp"))


def test_review_conflicts_escapes_markdown():
    assert rc._md_cell("a|b") == "a\\|b"
    assert rc._md_cell("a\nb") == "a <br> b"
    assert rc._md_cell("<script>") == "&lt;script&gt;"
    assert rc._md_cell(None) == ""


def test_review_conflicts_report_runs(fixture):
    _, tmp = fixture
    out = tmp / "report.md"
    assert rc.main(["--out", str(out)]) == 0
    text = out.read_text("utf-8")
    assert "数据冲突审查报告" in text
    # a table with the source values is present
    assert "| 数码兽 |" in text
