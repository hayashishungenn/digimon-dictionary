"""Evolution-graph edge resolution.

After all digimon rows exist, we resolve every source's evolves_from /
evolves_to references (source-local ids / page titles / names) to canonical
digimon ids and write directed edges. Handles cycles naturally (the graph is
designed to support them).
"""
from __future__ import annotations

import logging
import sqlite3

from pipeline.core import naming
from pipeline.core.models import MatchedEntity

logger = logging.getLogger(__name__)

# Generic card-game / broad rule lines that add noise, not canonical edges.
_JUNK_EVO_PATTERNS = (
    "card game",
    "battle spirits",
    "any adult",
    "any child",
    "any digimon",
    "any armor",
    "also evolves from",
    "lv.",
)


def _is_junk_evo(name: str) -> bool:
    low = name.lower()
    return any(p in low for p in _JUNK_EVO_PATTERNS)


def _guess_evolution_type(condition: str | None) -> str:
    """Classify evolution type from a condition string.

    Only positive signals classify (jogress/dna/fusion/warp/armor/x-antibody/
    mode-change). Generic phrases like "with or without the Crest" or "and"
    are plain conditional evolutions → normal (never guess jogress from them).
    """
    if not condition:
        return "normal"
    low = condition.lower()
    if any(w in low for w in ("jogress", "dna", "fusion")):
        return "jogress"
    if "x-antibody" in low or "x antibody" in low:
        return "x_evolution"
    if "warp" in low:
        return "special"
    if "armor evolve" in low or "armor digivolution" in low:
        return "armor"
    if "mode change" in low or "changer" in low:
        return "mode_change"
    return "normal"


class EvolutionResolver:
    """Resolves per-source references to digimon ids using DB lookup tables."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._dapi: dict[int, int] = {}
        self._wikimon: dict[str, int] = {}
        self._official: dict[str, int] = {}
        self._names: dict[str, int] = {}
        self._by_slug: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        rows = self.conn.execute(
            """SELECT id, canonical_slug, dapi_id, wikimon_title, official_slug,
                      name_en, name_ja, name_romanized, name_zh_cn
               FROM digimon"""
        ).fetchall()
        for r in rows:
            if r["dapi_id"] is not None:
                self._dapi[int(r["dapi_id"])] = r["id"]
            if r["wikimon_title"]:
                self._wikimon[r["wikimon_title"]] = r["id"]
            if r["official_slug"]:
                self._official[r["official_slug"]] = r["id"]
            self._by_slug[r["canonical_slug"]] = r["id"]
            for col in ("name_en", "name_ja", "name_romanized", "name_zh_cn"):
                v = r[col]
                if v:
                    self._names.setdefault(naming.normalize_key(v), r["id"])

    # ------------------------------------------------------------------ API
    def resolve_source(self, source: str, ref: str) -> int | None:
        """Resolve one source-local reference to a digimon id."""
        if source == "dapi":
            return self._dapi.get(int(ref)) if ref.isdigit() else None
        if source == "official":
            return self._official.get(ref) or self._names.get(naming.normalize_key(ref))
        if source == "wikimon":
            if ref in self._wikimon:
                return self._wikimon[ref]
            return self._names.get(naming.normalize_key(ref))
        # digimons_net / digidb reference by name
        return self._names.get(naming.normalize_key(ref))

    def add_edges_for_entity(self, entity: MatchedEntity) -> int:
        """Write all evolution edges described by an entity's records."""
        added = 0
        from_id = self._by_slug.get(entity.canonical_slug)
        if from_id is None:
            return 0
        for rec in entity.records:
            for ref in rec.evolves_to:
                if _is_junk_evo(ref):
                    continue
                to_id = self.resolve_source(rec.source, ref)
                if to_id is None or to_id == from_id:
                    continue
                cond = rec.conditions.get(f"to:{ref}") or ""
                etype = _guess_evolution_type(cond) if cond else "normal"
                self.conn.execute(
                    """INSERT OR IGNORE INTO evolution_edge
                       (from_digimon_id, to_digimon_id, evolution_type, condition, source, confidence)
                       VALUES(?,?,?,?,?,?)""",
                    [from_id, to_id, etype, cond or None, rec.source, "medium"],
                )
                added += 1
            for ref in rec.evolves_from:
                if _is_junk_evo(ref):
                    continue
                to_id = self.resolve_source(rec.source, ref)
                if to_id is None or to_id == from_id:
                    continue
                cond = rec.conditions.get(f"from:{ref}") or ""
                etype = _guess_evolution_type(cond) if cond else "normal"
                self.conn.execute(
                    """INSERT OR IGNORE INTO evolution_edge
                       (from_digimon_id, to_digimon_id, evolution_type, condition, source, confidence)
                       VALUES(?,?,?,?,?,?)""",
                    [to_id, from_id, etype, cond or None, rec.source, "medium"],
                )
                added += 1
        return added

    def add_relations_for_entity(self, entity: MatchedEntity) -> int:
        """Write non-evolution relations (official 'related', wikimon variants)."""
        added = 0
        from_id = self._by_slug.get(entity.canonical_slug)
        if from_id is None:
            return 0
        for rec in entity.records:
            for rel in rec.extra.get("related", []) or []:
                target = rel.get("slug") or rel.get("name")
                if not target:
                    continue
                to_id = self.resolve_source("official" if rel.get("slug") else rec.source, target)
                if to_id is None or to_id == from_id:
                    continue
                self.conn.execute(
                    """INSERT OR IGNORE INTO digimon_relation
                       (from_digimon_id, to_digimon_id, relation_type, source, note)
                       VALUES(?,?,?,?,?)""",
                    [from_id, to_id, "related", "official", None],
                )
                added += 1
        return added
