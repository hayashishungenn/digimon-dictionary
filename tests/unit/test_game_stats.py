"""Unit tests for game-stats import (digidb → game_digimon_stats)."""
from __future__ import annotations

import sqlite3

from pipeline.core.models import SourceDigimon, SourceName
from pipeline.core.schema import connect, create_schema
from pipeline.matching.matcher import Matcher
from pipeline.merge.store import CanonicalStore
from pipeline.sources.digidb import import_game_stats


def _dapi(name: str, dapi_id: int) -> SourceDigimon:
    return SourceDigimon(
        source="dapi", source_id=str(dapi_id),
        names=[SourceName(name, "en", status="community", source="dapi")], extra={},
    )


def _digidb(no: str, name: str, hp: int) -> SourceDigimon:
    return SourceDigimon(
        source="digidb", source_id=no,
        names=[SourceName(name, "en", status="community", source="digidb")],
        extra={"game": "Digimon Story: Cyber Sleuth", "game_short": "cyber-sleuth",
               "game_stats": {"hp": hp, "sp": 100, "atk": 50, "def": 40, "int": 30, "spd": 60,
                              "memory": 14, "equip slots": 2, "stage": "Child", "element": "Neutral"}},
    )


def test_import_game_stats(tmp_path):
    conn = connect(tmp_path / "g.sqlite")
    create_schema(conn)

    m = Matcher()
    for rec in (_dapi("Agumon", 1), _dapi("Greymon", 8), _dapi("NoSuchmon", 999)):
        m.add(rec)
    store = CanonicalStore(conn)
    for e in m.entities.values():
        store.upsert_entity(e)
    store.commit()

    digidb = [
        _digidb("1", "Agumon", 590),
        _digidb("2", "Greymon", 720),
        _digidb("3", "DoesNotExist", 500),  # no match -> skipped
    ]
    written = import_game_stats(conn, digidb)

    assert written == 2
    game = conn.execute("SELECT id, name, short_name FROM game").fetchone()
    assert game["name"] == "Digimon Story: Cyber Sleuth"
    agumon_id = conn.execute("SELECT id FROM digimon WHERE canonical_slug='agumon'").fetchone()["id"]
    stats = conn.execute(
        "SELECT hp, sp, memory, slots FROM game_digimon_stats WHERE digimon_id=?",
        [agumon_id],
    ).fetchone()
    assert stats["hp"] == 590
    assert stats["memory"] == 14
    # world-view digimon fields are untouched by game stats
    row = conn.execute("SELECT level, attribute FROM digimon WHERE id=?", [agumon_id]).fetchone()
    assert row["level"] == "unknown"  # digidb stage (Child) never became world-view level


def test_import_game_stats_no_records(tmp_path):
    conn = connect(tmp_path / "g2.sqlite")
    create_schema(conn)
    assert import_game_stats(conn, []) == 0
