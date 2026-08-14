"""SQLite database schema for the canonical Digimon database.

Design decisions (per product spec docs/product-spec.md):
- digimon.canonical_slug is the stable internal identity; external ids
  (dapi_id, wikimon_title, ...) are stored as separate columns, never PKs.
- Evolution is a directed many-to-many graph via `evolution_edge`.
- Types/fields/groups/skills are normalized into lookup + join tables.
- Per-field provenance is stored in `provenance`.
- A FTS5 virtual table backs multilingual search.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema versioning / migrations
#
# Every sync/export that opens a DB runs create_schema(), which creates the
# base tables (idempotent) and then applies MIGRATIONS for any version ahead of
# the DB's `PRAGMA user_version`. Migrations are additive and never drop or
# destroy data — an old DB is upgraded in place, so existing rows survive.
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 2


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Legacy v0 -> v1: tables predate version tracking.

    Adds `digimon.level_2` for very old DBs and removes the synthetic
    placeholder snapshot row (id=1 with NULL counts) that create_schema used to
    insert — the snapshot table should only ever hold real snapshots.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(digimon)")}
    if "level_2" not in cols:
        conn.execute("ALTER TABLE digimon ADD COLUMN level_2 TEXT")
    conn.execute(
        """DELETE FROM snapshot
           WHERE id = 1 AND total_count IS NULL
             AND official_count IS NULL AND extended_count IS NULL"""
    )


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """v1 -> v2: audit-grade conflicts + dedup guarantees.

    Extends `data_conflict` to record the real source *id* of every candidate,
    the chosen value/source, all candidates as JSON, and a review status.
    Also dedups `digimon_alias` and adds unique indexes so re-running merge
    cannot insert duplicate aliases/conflicts.
    """
    cols = {r[1] for r in conn.execute("PRAGMA table_info(data_conflict)")}
    for col, ddl in (
        ("source_id_a", "ALTER TABLE data_conflict ADD COLUMN source_id_a TEXT"),
        ("source_id_b", "ALTER TABLE data_conflict ADD COLUMN source_id_b TEXT"),
        ("chosen_value", "ALTER TABLE data_conflict ADD COLUMN chosen_value TEXT"),
        ("chosen_source", "ALTER TABLE data_conflict ADD COLUMN chosen_source TEXT"),
        ("candidates", "ALTER TABLE data_conflict ADD COLUMN candidates TEXT"),
        ("review_status", "ALTER TABLE data_conflict ADD COLUMN review_status TEXT NOT NULL DEFAULT 'auto'"),
        ("resolved_at", "ALTER TABLE data_conflict ADD COLUMN resolved_at TEXT"),
    ):
        if col not in cols:
            conn.execute(ddl)
    # dedup aliases (keep the lowest id) before enforcing uniqueness
    conn.execute(
        """DELETE FROM digimon_alias WHERE id NOT IN (
             SELECT MIN(id) FROM digimon_alias
             GROUP BY digimon_id, alias, language
           )"""
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_alias_unique "
        "ON digimon_alias(digimon_id, alias, language)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_conflict_entity_field "
        "ON data_conflict(entity_type, entity_id, field)"
    )


MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    1: _migrate_v1,
    2: _migrate_v2,
}


def _apply_migrations(conn: sqlite3.Connection) -> None:
    ver = int(conn.execute("PRAGMA user_version").fetchone()[0])
    for v in range(ver + 1, SCHEMA_VERSION + 1):
        mig = MIGRATIONS.get(v)
        if mig is not None:
            mig(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

SCHEMA_DDL: list[str] = [
    # ---- core entity -----------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS digimon (
        id                      INTEGER PRIMARY KEY,
        canonical_slug          TEXT    NOT NULL UNIQUE,
        -- names
        name_zh_cn              TEXT,
        name_zh_cn_source       TEXT,
        name_zh_cn_status       TEXT,   -- official|official_game|official_anime|community|transliteration|unverified
        name_zh_cn_verified     INTEGER NOT NULL DEFAULT 0,
        name_zh_hk              TEXT,
        name_zh_tw              TEXT,
        name_en                 TEXT,
        name_en_dub             TEXT,
        name_ja                 TEXT,
        name_romanized          TEXT,
        -- world-view attributes (canonical enums; raw preserved alongside)
        level                   TEXT,
        level_raw               TEXT,
        level_2                 TEXT,               -- secondary tag (e.g. "Xros Wars")
        attribute               TEXT,
        attribute_raw           TEXT,
        x_antibody              INTEGER NOT NULL DEFAULT 0,
        -- flags
        is_official_reference   INTEGER NOT NULL DEFAULT 0,
        is_extended             INTEGER NOT NULL DEFAULT 1,
        -- debut
        first_appearance_title  TEXT,
        first_appearance_date   TEXT,
        first_appearance_medium TEXT,
        -- images (best-known remote URLs; local cache in digimon_image)
        main_image              TEXT,
        thumbnail               TEXT,
        -- profiles
        profile_zh_cn           TEXT,
        profile_en              TEXT,
        profile_ja              TEXT,
        profile_source          TEXT,
        profile_source_url      TEXT,
        profile_verified        INTEGER NOT NULL DEFAULT 0,
        -- name origin
        name_origin             TEXT,
        -- external ids (never primary keys)
        dapi_id                 INTEGER,
        wikimon_title           TEXT,
        official_slug           TEXT,
        digimons_net_slug       TEXT,
        digidb_id               INTEGER,
        -- lifecycle / provenance
        content_hash            TEXT,
        source_last_updated     TEXT,
        created_at              TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at              TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_digimon_level ON digimon(level);
    CREATE INDEX IF NOT EXISTS idx_digimon_attribute ON digimon(attribute);
    CREATE INDEX IF NOT EXISTS idx_digimon_official ON digimon(is_official_reference, is_extended);
    CREATE INDEX IF NOT EXISTS idx_digimon_zh ON digimon(name_zh_cn);
    CREATE INDEX IF NOT EXISTS idx_digimon_en ON digimon(name_en);
    CREATE INDEX IF NOT EXISTS idx_digimon_ja ON digimon(name_ja);
    CREATE INDEX IF NOT EXISTS idx_digimon_dapi ON digimon(dapi_id);
    CREATE INDEX IF NOT EXISTS idx_digimon_wikimon ON digimon(wikimon_title);
    """,
    # ---- aliases ---------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS digimon_alias (
        id          INTEGER PRIMARY KEY,
        digimon_id  INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        alias       TEXT    NOT NULL,
        language    TEXT,               -- zh_cn|zh_hk|zh_tw|en|ja|other
        region      TEXT,               -- cn|hk|tw|jp|na|int|other
        alias_type  TEXT    NOT NULL,   -- official|dub|romanization|old_translation|fan_translation|game_translation|anime_translation|alternative_spelling
        source      TEXT,
        verified    INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_alias_alias ON digimon_alias(alias);
    CREATE INDEX IF NOT EXISTS idx_alias_digimon ON digimon_alias(digimon_id);
    """,
    # ---- type (lookup + join) --------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS type (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,   -- canonical (English)
        name_zh     TEXT,
        name_ja     TEXT,
        notes       TEXT
    );
    CREATE TABLE IF NOT EXISTS digimon_type (
        digimon_id  INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        type_id     INTEGER NOT NULL REFERENCES type(id) ON DELETE CASCADE,
        is_primary  INTEGER NOT NULL DEFAULT 0,
        source      TEXT,
        PRIMARY KEY (digimon_id, type_id)
    );
    """,
    # ---- field (适应领域, many-to-many) ---------------------------------
    """
    CREATE TABLE IF NOT EXISTS field (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,
        name_zh     TEXT,
        name_ja     TEXT,
        notes       TEXT
    );
    CREATE TABLE IF NOT EXISTS digimon_field (
        digimon_id  INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        field_id    INTEGER NOT NULL REFERENCES field(id) ON DELETE CASCADE,
        source      TEXT,
        PRIMARY KEY (digimon_id, field_id)
    );
    """,
    # ---- group (组织, many-to-many) --------------------------------------
    """
    CREATE TABLE IF NOT EXISTS grp (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,
        name_zh     TEXT,
        description TEXT,
        source      TEXT
    );
    CREATE TABLE IF NOT EXISTS digimon_group (
        digimon_id  INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        group_id    INTEGER NOT NULL REFERENCES grp(id) ON DELETE CASCADE,
        source      TEXT,
        note        TEXT,
        PRIMARY KEY (digimon_id, group_id)
    );
    """,
    # ---- skills -----------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS skill (
        id              INTEGER PRIMARY KEY,
        match_key       TEXT,              -- normalized dedup key (name_en || name_ja)
        name_zh_cn      TEXT,
        name_en         TEXT,
        name_ja         TEXT,
        description_zh_cn TEXT,
        description_en  TEXT,
        description_ja  TEXT,
        source          TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_skill_match ON skill(match_key);
    CREATE TABLE IF NOT EXISTS skill_alias (
        id          INTEGER PRIMARY KEY,
        skill_id    INTEGER NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
        alias       TEXT    NOT NULL,
        language    TEXT,
        alias_type  TEXT,
        source      TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_skill_alias ON skill_alias(alias);
    CREATE TABLE IF NOT EXISTS digimon_skill (
        digimon_id  INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        skill_id    INTEGER NOT NULL REFERENCES skill(id) ON DELETE CASCADE,
        skill_type  TEXT    NOT NULL DEFAULT 'special_move',  -- special_move|signature_move|attack|ability|other
        is_signature INTEGER NOT NULL DEFAULT 0,
        source      TEXT,
        sort_order  INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (digimon_id, skill_id)
    );
    """,
    # ---- evolution graph (directed many-to-many) -------------------------
    """
    CREATE TABLE IF NOT EXISTS evolution_edge (
        id              INTEGER PRIMARY KEY,
        from_digimon_id INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        to_digimon_id   INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        evolution_type  TEXT    NOT NULL DEFAULT 'normal',
        condition       TEXT,
        source          TEXT,
        confidence      TEXT    NOT NULL DEFAULT 'high',  -- high|medium|low
        is_primary_line INTEGER NOT NULL DEFAULT 0,
        UNIQUE (from_digimon_id, to_digimon_id, evolution_type, source)
    );
    CREATE INDEX IF NOT EXISTS idx_edge_from ON evolution_edge(from_digimon_id);
    CREATE INDEX IF NOT EXISTS idx_edge_to ON evolution_edge(to_digimon_id);
    """,
    # ---- related forms (非进化关联) --------------------------------------
    """
    CREATE TABLE IF NOT EXISTS digimon_relation (
        id              INTEGER PRIMARY KEY,
        from_digimon_id INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        to_digimon_id   INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        relation_type   TEXT    NOT NULL,   -- variant|x_antibody|mode_change|black_variant|same_species|fusion_component|counterpart|related
        source          TEXT,
        note            TEXT,
        UNIQUE (from_digimon_id, to_digimon_id, relation_type)
    );
    """,
    # ---- images -----------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS digimon_image (
        id              INTEGER PRIMARY KEY,
        digimon_id      INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        image_type      TEXT    NOT NULL,   -- main_image|thumbnail|official_art|reference_art|sprite|card_art|anime_art|game_model
        remote_url      TEXT,
        source_page     TEXT,
        local_path      TEXT,
        width           INTEGER,
        height          INTEGER,
        transparent     INTEGER,
        sha256          TEXT,
        copyright_source TEXT,
        license_note    TEXT,
        download_status TEXT NOT NULL DEFAULT 'pending',  -- pending|downloaded|missing|failed
        fetched_at      TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_image_digimon ON digimon_image(digimon_id);
    """,
    # ---- provenance / conflicts / review ---------------------------------
    """
    CREATE TABLE IF NOT EXISTS provenance (
        id          INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL,          -- digimon|field|skill|edge|relation|image
        entity_id   INTEGER NOT NULL,
        field       TEXT NOT NULL,
        source      TEXT,
        source_url  TEXT,
        retrieved_at TEXT,
        confidence  TEXT,
        value_hash  TEXT,
        UNIQUE (entity_type, entity_id, field, source)
    );
    CREATE INDEX IF NOT EXISTS idx_prov_entity ON provenance(entity_type, entity_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS data_conflict (
        id            INTEGER PRIMARY KEY,
        entity_type   TEXT NOT NULL,
        entity_id     INTEGER,
        field         TEXT NOT NULL,
        source_a      TEXT,
        source_id_a   TEXT,              -- source-local id of value_a's record
        value_a       TEXT,
        source_b      TEXT,
        source_id_b   TEXT,              -- source-local id of value_b's record
        value_b       TEXT,
        chosen_value  TEXT,              -- canonical value selected by priority
        chosen_source TEXT,
        candidates    TEXT,              -- JSON: [{value, source, source_id}, ...]
        review_status TEXT NOT NULL DEFAULT 'auto',  -- auto|review|resolved|wontfix
        resolution    TEXT,              -- selection reason / how it was chosen
        resolved      INTEGER NOT NULL DEFAULT 0,
        created_at    TEXT NOT NULL DEFAULT (datetime('now')),
        resolved_at   TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS manual_review_queue (
        id          INTEGER PRIMARY KEY,
        entity_type TEXT NOT NULL,
        entity_id   INTEGER,
        reason      TEXT NOT NULL,
        detail      TEXT,                    -- JSON payload
        status      TEXT NOT NULL DEFAULT 'open',  -- open|resolved|wontfix
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        resolved_at TEXT
    );
    """,
    # ---- game stats (独立于世界观) ---------------------------------------
    """
    CREATE TABLE IF NOT EXISTS game (
        id          INTEGER PRIMARY KEY,
        name        TEXT NOT NULL UNIQUE,
        short_name  TEXT,
        platform    TEXT,
        notes       TEXT
    );
    CREATE TABLE IF NOT EXISTS game_digimon_stats (
        id          INTEGER PRIMARY KEY,
        game_id     INTEGER NOT NULL REFERENCES game(id) ON DELETE CASCADE,
        digimon_id  INTEGER NOT NULL REFERENCES digimon(id) ON DELETE CASCADE,
        hp          INTEGER,
        sp          INTEGER,
        atk         INTEGER,
        def         INTEGER,
        int         INTEGER,
        spd         INTEGER,
        memory      INTEGER,
        slots       INTEGER,
        extras      TEXT,                     -- JSON for game-specific fields
        source      TEXT,
        UNIQUE (game_id, digimon_id)
    );
    -- Game-specific skills, explicitly separated from canonical world-view
    -- skills (spec §17): a game's "skill" (with game-local effect text/values)
    -- is a different concept from the canonical special-move entity.
    CREATE TABLE IF NOT EXISTS game_skill (
        id          INTEGER PRIMARY KEY,
        game_id     INTEGER NOT NULL REFERENCES game(id) ON DELETE CASCADE,
        skill_id    INTEGER REFERENCES skill(id),   -- canonical link when identifiable
        digimon_id  INTEGER REFERENCES digimon(id),
        name        TEXT NOT NULL,                  -- game-local skill name
        description TEXT,
        effect      TEXT,                           -- game-specific effect
        power       INTEGER,
        element     TEXT,
        source      TEXT,
        UNIQUE (game_id, name, digimon_id)
    );
    """,
    # ---- dataset snapshot / source sync ----------------------------------
    """
    CREATE TABLE IF NOT EXISTS snapshot (
        id                  INTEGER PRIMARY KEY,
        snapshot_date       TEXT NOT NULL,
        official_count      INTEGER,
        extended_count      INTEGER,
        total_count         INTEGER,
        source_last_updated TEXT,
        notes               TEXT
    );
    CREATE TABLE IF NOT EXISTS source_sync (
        source             TEXT PRIMARY KEY,   -- dapi|wikimon|official|digimons_net|digidb|manual
        source_updated_at  TEXT,
        last_seen_at       TEXT,
        content_hash       TEXT,
        records            INTEGER,
        status             TEXT
    );
    """,
    # ---- FTS5 search index ------------------------------------------------
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS digimon_fts USING fts5(
        canonical_slug,
        name_zh_cn,
        name_en,
        name_ja,
        name_romanized,
        name_en_dub,
        aliases,
        content='',
        tokenize='unicode61'
    );
    """,
]


def create_schema(conn: sqlite3.Connection) -> None:
    """Create the base tables (if missing) and apply any pending migrations.

    Migrations run from the DB's current `PRAGMA user_version` up to
    SCHEMA_VERSION. Existing databases are upgraded in place without data loss;
    a fresh database runs every migration (each is a no-op on a new schema).
    """
    for ddl in SCHEMA_DDL:
        conn.executescript(ddl)
    _apply_migrations(conn)
    conn.commit()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with sane pragmas for read/write."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection in read-only mode (for the API)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def checkpoint_and_close(conn: sqlite3.Connection) -> None:
    """Fold any WAL content into the main DB file and close the connection.

    Used before an atomic replace so the .sqlite file alone is complete and
    self-contained (the WAL/SHM sidecar files become removable).
    """
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.Error:
        pass  # not a WAL database (or already checkpointed); the file is still valid
    conn.close()


def cleanup_db_files(path: str | Path) -> None:
    """Remove a SQLite database and its WAL/SHM sidecars if they exist.

    Used to dispose of candidate databases and to guarantee no temp files leak.
    """
    p = Path(path)
    for suffix in ("", "-wal", "-shm", "-journal"):
        sidecar = Path(f"{p}{suffix}")
        try:
            if sidecar.exists():
                sidecar.unlink()
        except OSError:
            pass


def cleanup_sidecars(path: str | Path) -> None:
    """Remove only the WAL/SHM/journal sidecars of a SQLite file.

    Leaves the main `.sqlite` file in place (e.g. a kept partial candidate),
    ensuring no sidecar temp files leak.
    """
    p = Path(path)
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{p}{suffix}")
        try:
            if sidecar.exists():
                sidecar.unlink()
        except OSError:
            pass
