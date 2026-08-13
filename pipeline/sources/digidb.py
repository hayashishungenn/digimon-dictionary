"""digidb.io adapter — game statistics (Cyber Sleuth / Hacker's Memory).

digidb.io currently returns 403 to bots and only provides game stats, which the
canonical world-view DB intentionally keeps separate (spec §10). This adapter is
a placeholder that can load the community-scraped dataset from a local JSON
file (data/raw/digidb/digidb.json) when provided; the live site is not scraped.

Game stats are written to the `game` / `game_digimon_stats` tables, never into
the canonical `digimon` fields.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pipeline.core.config import RAW_SOURCES
from pipeline.core.models import SourceDigimon, SourceName

logger = logging.getLogger(__name__)

DIGIDB_JSON = RAW_SOURCES["digidb"] / "digidb.json"


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
            rec = SourceDigimon(
                source="digidb",
                source_id=str(row.get("no", name)),
                names=[SourceName(str(name), "en", status="community", source="digidb")],
                extra={"stats": {k: row.get(k) for k in
                                 ("hp", "sp", "atk", "def", "int", "spd", "memory", "slots", "stage", "type", "attribute")}},
            )
            records.append(rec)
        logger.info("digidb: %d records from local dataset", len(records))
        return records
