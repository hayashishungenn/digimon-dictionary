"""Unit tests for the SQLite schema creation and enum mappings."""
from __future__ import annotations

import sqlite3

from pipeline.core import schema
from pipeline.core.enums import (
    Attribute,
    Level,
    parse_attribute,
    parse_level,
)

EXPECTED_TABLES = {
    "digimon",
    "digimon_alias",
    "type",
    "digimon_type",
    "field",
    "digimon_field",
    "grp",
    "digimon_group",
    "skill",
    "skill_alias",
    "digimon_skill",
    "evolution_edge",
    "digimon_relation",
    "digimon_image",
    "provenance",
    "data_conflict",
    "manual_review_queue",
    "game",
    "game_digimon_stats",
    "game_skill",
    "snapshot",
    "source_sync",
    "digimon_fts",
}


def test_create_schema(tmp_path):
    conn = schema.connect(tmp_path / "t.sqlite")
    schema.create_schema(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= tables, EXPECTED_TABLES - tables
    conn.close()


def test_level_mapping():
    assert parse_level("child") == Level.CHILD
    assert parse_level("rookie") == Level.CHILD
    assert parse_level("adult") == Level.ADULT
    assert parse_level("champion") == Level.ADULT
    assert parse_level("perfect") == Level.PERFECT
    assert parse_level("ultimate") == Level.ULTIMATE  # ja terminology
    assert parse_level("mega") == Level.ULTIMATE
    assert parse_level("fresh") == Level.BABY_I
    assert parse_level("in training") == Level.BABY_II
    assert parse_level("成长期") == Level.CHILD
    assert parse_level("究极体") == Level.ULTIMATE
    assert parse_level("armor") == Level.ARMOR
    assert parse_level("hybrid") == Level.HYBRID
    assert parse_level(None) == Level.UNKNOWN
    assert parse_level("totally-made-up") == Level.UNKNOWN


def test_attribute_mapping():
    assert parse_attribute("vaccine") == Attribute.VACCINE
    assert parse_attribute("data") == Attribute.DATA
    assert parse_attribute("virus") == Attribute.VIRUS
    assert parse_attribute("no attribute") == Attribute.UNKNOWN
    assert parse_attribute("疫苗种") == Attribute.VACCINE
    assert parse_attribute(None) == Attribute.UNKNOWN


def test_level_zh_labels():
    assert Level.CHILD.label_zh == "成长期"
    assert Level.ULTIMATE.label_zh == "究极体"
    assert Level.BABY_I.label_zh == "幼年期Ⅰ"


def test_attribute_zh_labels():
    assert Attribute.VACCINE.label_zh == "疫苗种"
    assert Attribute.UNKNOWN.label_zh == "不明"
