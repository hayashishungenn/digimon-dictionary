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
    "sync_run",
    "field_coverage",
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


# ---------------------------------------------------------------------------
# schema versioning / migrations (T2)
# ---------------------------------------------------------------------------
def test_fresh_schema_stamps_version(tmp_path):
    conn = schema.connect(tmp_path / "fresh.sqlite")
    schema.create_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
    # new data_conflict columns exist
    cols = {r[1] for r in conn.execute("PRAGMA table_info(data_conflict)")}
    assert {"source_id_a", "source_id_b", "chosen_value", "chosen_source", "candidates", "review_status"} <= cols
    # no synthetic placeholder snapshot row
    assert conn.execute("SELECT COUNT(*) FROM snapshot").fetchone()[0] == 0
    conn.close()


def test_create_schema_is_idempotent(tmp_path):
    conn = schema.connect(tmp_path / "idem.sqlite")
    schema.create_schema(conn)
    schema.create_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= tables
    conn.close()


def test_migration_upgrades_old_db_without_data_loss(tmp_path):
    """A pre-versioning DB (user_version=0) with duplicate aliases and the old
    placeholder snapshot row must upgrade in place: data preserved, aliases
    deduped, placeholder removed, version stamped."""
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    # old-style minimal schema (what a v0 DB looked like)
    conn.executescript(
        """
        CREATE TABLE digimon (
            id INTEGER PRIMARY KEY, canonical_slug TEXT NOT NULL UNIQUE,
            name_zh_cn TEXT, name_zh_cn_source TEXT, name_zh_cn_status TEXT,
            name_zh_cn_verified INTEGER DEFAULT 0, name_zh_hk TEXT, name_zh_tw TEXT,
            name_en TEXT, name_en_dub TEXT, name_ja TEXT, name_romanized TEXT,
            level TEXT, level_raw TEXT, level_2 TEXT, attribute TEXT, attribute_raw TEXT,
            x_antibody INTEGER DEFAULT 0, is_official_reference INTEGER DEFAULT 0,
            is_extended INTEGER DEFAULT 1, first_appearance_title TEXT,
            first_appearance_date TEXT, first_appearance_medium TEXT,
            main_image TEXT, thumbnail TEXT, profile_zh_cn TEXT, profile_en TEXT,
            profile_ja TEXT, profile_source TEXT, profile_source_url TEXT,
            profile_verified INTEGER DEFAULT 0, name_origin TEXT, dapi_id INTEGER,
            wikimon_title TEXT, official_slug TEXT, digimons_net_slug TEXT,
            digidb_id INTEGER, content_hash TEXT, source_last_updated TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE digimon_alias (
            id INTEGER PRIMARY KEY, digimon_id INTEGER, alias TEXT, language TEXT,
            region TEXT, alias_type TEXT, source TEXT, verified INTEGER DEFAULT 0
        );
        CREATE TABLE snapshot (
            id INTEGER PRIMARY KEY, snapshot_date TEXT, official_count INTEGER,
            extended_count INTEGER, total_count INTEGER, source_last_updated TEXT, notes TEXT
        );
        CREATE TABLE data_conflict (
            id INTEGER PRIMARY KEY, entity_type TEXT NOT NULL, entity_id INTEGER,
            field TEXT NOT NULL, source_a TEXT, value_a TEXT, source_b TEXT, value_b TEXT,
            resolution TEXT, resolved INTEGER DEFAULT 0, created_at TEXT
        );
        """
    )
    conn.execute("INSERT INTO digimon(id, canonical_slug, name_en, level, level_raw, is_official_reference) VALUES(1,'agumon','Agumon','child','Child',1)")
    conn.execute(
        """INSERT INTO digimon_alias(id, digimon_id, alias, language, alias_type, source, verified)
           VALUES(1,1,'Agu','en','official','dapi',0),
                 (2,1,'Agu','en','dub','wikimon',1),
                 (3,1,'亚古兽','zh_cn','official','official',0)"""
    )
    conn.execute("INSERT INTO snapshot(id, snapshot_date) VALUES(1, '2026-01-01 00:00:00')")  # legacy placeholder
    # two conflicts for the SAME entity/field — the v2 unique index must not
    # abort the migration (P1-03)
    conn.execute(
        """INSERT INTO data_conflict(entity_type, entity_id, field, source_a, value_a, source_b, value_b)
           VALUES('digimon',1,'level','dapi','child','official','adult'),
                 ('digimon',1,'level','dapi','child','wikimon','unknown')"""
    )
    conn.commit()
    conn.close()

    conn = schema.connect(db)
    schema.create_schema(conn)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
    # no data lost
    assert conn.execute("SELECT name_en FROM digimon WHERE id=1").fetchone()[0] == "Agumon"
    # duplicate aliases deduped (Agu en kept once) AND their provenance merged:
    # the kept row carries both sources and the max verified flag (P1-03)
    assert conn.execute("SELECT COUNT(*) FROM digimon_alias WHERE digimon_id=1 AND language='en'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM digimon_alias WHERE digimon_id=1 AND language='zh_cn'").fetchone()[0] == 1
    kept = conn.execute(
        "SELECT source, alias_type, verified FROM digimon_alias WHERE digimon_id=1 AND language='en'"
    ).fetchone()
    assert "dapi" in kept["source"] and "wikimon" in kept["source"]
    assert kept["verified"] == 1
    # placeholder snapshot row removed, real rows kept
    assert conn.execute("SELECT COUNT(*) FROM snapshot").fetchone()[0] == 0
    # duplicate conflicts deduped to one (the newest) + new columns populated
    assert conn.execute("SELECT COUNT(*) FROM data_conflict WHERE field='level'").fetchone()[0] == 1
    cols = {r[1] for r in conn.execute("PRAGMA table_info(data_conflict)")}
    assert "candidates" in cols and "review_status" in cols
    # unique indexes in place
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_alias_unique'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name='idx_conflict_entity_field'").fetchone()[0] == 1
    conn.close()


def test_migration_backs_up_populated_db(tmp_path):
    """P1-03: migrating a POPULATED legacy DB copies the file aside first; a
    fresh (empty) DB does not get a backup sidecar."""
    from pipeline.core.schema import create_schema

    # populated legacy DB (v0, full enough old schema, has a digimon row)
    db = tmp_path / "populated.sqlite"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """CREATE TABLE digimon (
            id INTEGER PRIMARY KEY, canonical_slug TEXT NOT NULL UNIQUE,
            name_zh_cn TEXT, name_zh_cn_source TEXT, name_zh_cn_status TEXT,
            name_zh_cn_verified INTEGER DEFAULT 0, name_zh_hk TEXT, name_zh_tw TEXT,
            name_en TEXT, name_en_dub TEXT, name_ja TEXT, name_romanized TEXT,
            level TEXT, level_raw TEXT, level_2 TEXT, attribute TEXT, attribute_raw TEXT,
            x_antibody INTEGER DEFAULT 0, is_official_reference INTEGER DEFAULT 0,
            is_extended INTEGER DEFAULT 1, first_appearance_title TEXT,
            first_appearance_date TEXT, first_appearance_medium TEXT,
            main_image TEXT, thumbnail TEXT, profile_zh_cn TEXT, profile_en TEXT,
            profile_ja TEXT, profile_source TEXT, profile_source_url TEXT,
            profile_verified INTEGER DEFAULT 0, name_origin TEXT, dapi_id INTEGER,
            wikimon_title TEXT, official_slug TEXT, digimons_net_slug TEXT,
            digidb_id INTEGER, content_hash TEXT, source_last_updated TEXT,
            created_at TEXT, updated_at TEXT
        );
        CREATE TABLE digimon_alias (
            id INTEGER PRIMARY KEY, digimon_id INTEGER, alias TEXT, language TEXT,
            region TEXT, alias_type TEXT, source TEXT, verified INTEGER DEFAULT 0
        );"""
    )
    conn.execute("INSERT INTO digimon(id, canonical_slug, name_en) VALUES(1,'agumon','Agumon')")
    conn.commit()
    conn.close()

    conn = schema.connect(db)
    create_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
    conn.close()
    backup = tmp_path / "populated.sqlite.pre-migrate-v0.sqlite"
    assert backup.exists(), "migrating a populated DB must leave a pre-migration copy"

    # a fresh (empty) DB must NOT leave a sidecar
    empty = tmp_path / "empty.sqlite"
    conn = schema.connect(empty)
    create_schema(conn)
    conn.close()
    assert not (tmp_path / "empty.sqlite.pre-migrate-v0.sqlite").exists()
    assert not (tmp_path / "empty.sqlite.pre-migrate-v8.sqlite").exists()


def test_every_migration_version_preserves_data(tmp_path):
    """P1-03: opening a populated DB at EACH historical schema version (0..7)
    and running create_schema must migrate to the current version WITHOUT
    losing any existing rows — every migration is additive/idempotent."""
    from pipeline.core.schema import create_schema

    for start_ver in range(0, schema.SCHEMA_VERSION):
        db = tmp_path / f"v{start_ver}.sqlite"
        conn = schema.connect(db)
        create_schema(conn)  # current-schema base
        conn.execute(
            "INSERT INTO digimon(canonical_slug, name_en, name_ja, name_zh_cn) "
            "VALUES('agumon','Agumon','アグモン','亚古兽')"
        )
        conn.execute("INSERT INTO digimon_alias(digimon_id, alias, language, alias_type) VALUES(1,'Agu','en','official')")
        conn.execute(
            "INSERT INTO data_conflict(entity_type, entity_id, field, source_a, value_a, source_b, value_b) "
            "VALUES('digimon',1,'level','a','x','b','y')"
        )
        conn.execute(
            "INSERT INTO snapshot(snapshot_date, official_count, extended_count, total_count) "
            "VALUES('2026-01-01',1,0,1)"
        )
        conn.execute("INSERT INTO manual_review_queue(entity_type, reason) VALUES('digimon','needs review')")
        conn.execute(f"PRAGMA user_version = {start_ver}")
        conn.commit()
        counts_before = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("digimon", "digimon_alias", "data_conflict", "snapshot", "manual_review_queue")
        }
        conn.close()

        conn = schema.connect(db)
        create_schema(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == schema.SCHEMA_VERSION
        for table, n in counts_before.items():
            after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert after == n, f"{table} lost rows migrating v{start_ver}->{schema.SCHEMA_VERSION}"
        conn.close()


def test_verify_integrity(tmp_path):
    """verify_integrity accepts a valid DB, rejects missing/corrupt files (S0-1)."""
    from pipeline.core.schema import create_schema

    db = tmp_path / "digidex.sqlite"
    conn = schema.connect(db)
    create_schema(conn)
    conn.close()
    assert schema.verify_integrity(db) is True

    # a non-database file is rejected
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"this is not a sqlite database" * 10)
    assert schema.verify_integrity(junk) is False

    # a missing file is rejected (not an exception)
    assert schema.verify_integrity(tmp_path / "absent.sqlite") is False


def test_checkpoint_detects_busy_wal(tmp_path):
    """P2-08: a WAL checkpoint with a busy writer must return False, never a
    silent success (a busy checkpoint can leave frames unflushed)."""
    import sqlite3 as _sqlite3

    db = tmp_path / "d.sqlite"
    conn = schema.connect(db)
    schema.create_schema(conn)
    conn.commit()

    # hold the WAL busy from a second connection with an open write transaction
    other = _sqlite3.connect(db)
    other.execute("PRAGMA journal_mode=WAL")
    other.execute("BEGIN IMMEDIATE")
    other.execute("INSERT INTO snapshot(snapshot_date) VALUES('x')")

    assert schema.checkpoint_and_close(conn) is False  # busy=1 -> failure
    other.rollback()
    other.close()

    # once the writer releases, a fresh checkpoint succeeds
    conn2 = schema.connect(db)
    assert schema.checkpoint_and_close(conn2) is True
