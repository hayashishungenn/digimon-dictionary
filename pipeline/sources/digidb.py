"""digidb.io adapter — game statistics (Digimon Story: Cyber Sleuth / Hacker's Memory).

digidb.io returns 403 to bots; this adapter loads the community-scraped dataset
from data/raw/digidb/digidb.json (GitHub mirror of the Cyber Sleuth roster).

IMPORTANT (spec §10): game numbers live in `game_digimon_stats`, never blended
into the canonical world-view `digimon` fields. The adapter therefore emits a
SourceDigimon carrying ONLY the English name (for entity matching) plus a
`game_stats` payload; a separate step writes the stats table after merge.

digidb naming quirk: its `type` column is the world-view ATTRIBUTE
(Vaccine/Data/Virus/Free) and its `attribute` column is the elemental type
(Neutral/Wind/Fire/...). Neither is used as a world-view type/attribute.
"""
from __future__ import annotations

import json
import logging

from pipeline.core.config import RAW_SOURCES
from pipeline.core.models import SourceDigimon, SourceName

logger = logging.getLogger(__name__)

DIGIDB_JSON = RAW_SOURCES["digidb"] / "digidb.json"

GAME_NAME = "Digimon Story: Cyber Sleuth"

# numeric stat columns present in the dataset
_STAT_KEYS = ("hp", "sp", "atk", "def", "int", "spd", "memory", "equip slots")


class DigiDbAdapter:
    source = "digidb"

    def fetch(self, fetcher=None, force: bool = False) -> list[SourceDigimon]:
        if not DIGIDB_JSON.exists():
            logger.info("digidb: no local dataset at %s (skipping — game stats are optional)", DIGIDB_JSON)
            return []
        data = json.loads(DIGIDB_JSON.read_text("utf-8"))
        records: list[SourceDigimon] = []
        for row in data:
            name = row.get("digimon") or row.get("name")
            if not name:
                continue
            stats = {k: _int_or_none(row.get(k)) for k in _STAT_KEYS}
            stats["stage"] = row.get("stage")
            stats["element"] = row.get("attribute")  # elemental, NOT world-view attribute
            rec = SourceDigimon(
                source="digidb",
                source_id=str(row.get("no", name)),
                names=[SourceName(str(name), "en", status="community", source="digidb")],
                extra={
                    "game": GAME_NAME,
                    "game_stats": stats,
                    "game_short": "cyber-sleuth",
                },
            )
            records.append(rec)
        logger.info("digidb: %d game-stat records loaded", len(records))
        # digidb is optional; a missing local dataset is an explicit empty
        # (complete) — the pipeline's required-source rules never apply to it.
        self._report(parsed=len(records), expected=len(records), complete=True)
        return records


def _int_or_none(v):
    if v is None or v == "":
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _norm(name: str) -> str:
    """Case/space/punctuation-insensitive comparison key for name matching."""
    import re

    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


# digidb roster spellings that differ from canonical names (abbreviations,
# alternate romanizations, old dub names). Mapped to canonical_slug; entries
# whose slug is absent from the DB are silently skipped (never fabricated).
GAME_ALIAS_MAP: dict[str, str] = {
    "agumonblk": "agumon-black",
    "gabumonblk": "gabumon-black",
    "garurumonblk": "garurumon-black",
    "weregarurumonblk": "were-garurumon-black",
    "metalgarurumonblk": "metal-garurumon-black",
    "lucemonfm": "lucemon-falldown-mode",
    "lucemonsm": "lucemon-satan-mode",
    "imperialdramondm": "imperialdramon-dragon-mode",
    "imperialdramonfm": "imperialdramon-fighter-mode",
    "imperialdramonpm": "imperialdramon-paladin-mode",
    "gallantmoncm": "dukemon-crimson-mode",
    "shinegreymonbm": "shine-greymon-burst-mode",
    "beelzemonbm": "beelzebumon-blast-mode",
    "miragegaogamonbm": "mirage-gaogamon-burst-mode",
    "ravemonbm": "ravmon-burst-mode",
    "rosemonbm": "rosemon-burst-mode",
    "belphemonsm": "belphemon-sleep-mode",
    "belphemonrm": "belphemon-rage-mode",
    "kerpymonblk": "cherubimon-vice",
    "kerpymongood": "cherubimon-virtue",
    "crusadermon": "lord-knightmon",
    "chaosmonva": "chaosmon-valdur-arm",
    "leopardmonlm": "duftmon-leopard-mode",
    "sistermonbawake": "sistermon-blanc-awake",
    "sistermoncawake": "sistermon-ciel-awake",
}


def import_game_stats(conn, digidb_records: list[SourceDigimon]) -> int:
    """Write digidb records into `game` + `game_digimon_stats`.

    Matches each record to a canonical digimon by English name (exact → alias →
    punctuation-insensitive normalized). Matched-by-normalization names are
    registered as game-translation aliases so they become searchable. Stats are
    UPSERTed (a re-import updates existing values; it never uses INSERT OR
    IGNORE which would keep stale numbers forever). Unmatched records are
    surfaced in the manual review queue, never just logged. Returns rows
    written.
    """
    if not digidb_records:
        return 0
    game_id = conn.execute("SELECT id FROM game WHERE short_name = 'cyber-sleuth'").fetchone()
    if game_id:
        game_id = game_id["id"]
    else:
        cur = conn.execute(
            "INSERT INTO game(name, short_name, platform, notes) VALUES(?,?,?,?)",
            [GAME_NAME, "cyber-sleuth", "PlayStation 4 / Vita", "Digimon Story: Cyber Sleuth / Hacker's Memory roster (digidb.io)"],
        )
        game_id = cur.lastrowid

    # lookup tables: exact name / alias -> id, plus normalized keys
    exact_ids: dict[str, int] = {}
    norm_ids: dict[str, int] = {}
    slug_ids: dict[str, int] = {}
    for r in conn.execute("SELECT id, canonical_slug, name_en, name_ja, name_romanized FROM digimon"):
        slug_ids[r["canonical_slug"]] = r["id"]
        if r["name_en"]:
            exact_ids.setdefault(r["name_en"].lower(), r["id"])
            norm_ids.setdefault(_norm(r["name_en"]), r["id"])
        for col in ("name_ja", "name_romanized"):
            v = r[col]
            if v:
                norm_ids.setdefault(_norm(v), r["id"])
    for r in conn.execute("SELECT a.alias, a.digimon_id FROM digimon_alias a"):
        exact_ids.setdefault(r["alias"].lower(), r["digimon_id"])
        norm_ids.setdefault(_norm(r["alias"]), r["digimon_id"])

    written = 0
    skipped = 0
    for rec in digidb_records:
        en = (rec.names[0].value if rec.names else "").strip()
        digimon_id = exact_ids.get(en.lower())
        if digimon_id is None:
            digimon_id = norm_ids.get(_norm(en))
        if digimon_id is None:
            # curated game-name mapping (abbreviations / alternate romanizations)
            target_slug = GAME_ALIAS_MAP.get(_norm(en))
            if target_slug:
                digimon_id = slug_ids.get(target_slug)
        if digimon_id is None:
            skipped += 1
            conn.execute(
                """INSERT OR IGNORE INTO manual_review_queue(entity_type, entity_id, reason, detail)
                   VALUES('game_digimon_stats', NULL, ?, ?)""",
                [f"digidb record '{en}' could not be matched to a canonical digimon",
                 json.dumps({"source": "digidb", "source_id": rec.source_id, "name": en},
                             ensure_ascii=False)],
            )
            continue

        # register the game's spelling as a searchable game-translation alias
        # when it differs from the canonical English name (e.g. "Agumon (Blk)")
        canon_en = conn.execute(
            "SELECT name_en FROM digimon WHERE id=?", [digimon_id]
        ).fetchone()
        canon = canon_en["name_en"] if canon_en else ""
        if _norm(en) and _norm(en) != _norm(canon):
            conn.execute(
                """INSERT OR IGNORE INTO digimon_alias
                   (digimon_id, alias, language, alias_type, source, verified)
                   VALUES(?,?,?,?,?,?)""",
                [digimon_id, en, "en", "game_translation", "digidb", 0],
            )

        stats = rec.extra.get("game_stats", {})
        conn.execute(
            """INSERT INTO game_digimon_stats
               (game_id, digimon_id, hp, sp, atk, def, int, spd, memory, slots, extras, source)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(game_id, digimon_id) DO UPDATE SET
                 hp=excluded.hp, sp=excluded.sp, atk=excluded.atk, def=excluded.def,
                 int=excluded.int, spd=excluded.spd, memory=excluded.memory,
                 slots=excluded.slots, extras=excluded.extras, source=excluded.source""",
            [
                game_id, digimon_id,
                stats.get("hp"), stats.get("sp"), stats.get("atk"), stats.get("def"),
                stats.get("int"), stats.get("spd"), stats.get("memory"), stats.get("equip slots"),
                json.dumps({"stage": stats.get("stage"), "element": stats.get("element")}, ensure_ascii=False),
                "digidb",
            ],
        )
        written += 1
    conn.commit()
    logger.info("digidb game stats: %d written, %d unmatched (queued for review)", written, skipped)
    return written
