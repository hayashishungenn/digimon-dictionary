"""Related-form inference (spec §42).

Derives variant relationships from canonical_slug conventions without inventing
data: a slug like `wargreymon-x-antibody` declares itself a variant of base
`wargreymon`; `agumon-black` of `agumon`; `imperialdramon-fighter-mode` of
`imperialdramon`. Relations are only written when the base entity actually
exists (never fabricated), and never to itself.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

# slug suffix -> relation type (longest-match-first so e.g. "-x-antibody" wins
# over a bare "-x")
SUFFIX_RULES: list[tuple[str, str]] = [
    ("-x-antibody", "x_antibody"),
    ("-x", "x_antibody"),
    ("-black", "black_variant"),
    ("-2006", "variant"),
    ("-2006-anime-version", "variant"),
    ("-anime-version", "variant"),
    ("-deva", "variant"),
    ("-dub", "variant"),
    ("-fighter-mode", "mode_change"),
    ("-dragon-mode", "mode_change"),
    ("-paladin-mode", "mode_change"),
    ("-crimson-mode", "mode_change"),
    ("-burst-mode", "mode_change"),
    ("-blast-mode", "mode_change"),
    ("-falldown-mode", "mode_change"),
    ("-satan-mode", "mode_change"),
    ("-shadow-lord-mode", "mode_change"),
    ("-sleep-mode", "mode_change"),
    ("-rage-mode", "mode_change"),
    ("-leopard-mode", "mode_change"),
    ("-ruin-mode", "mode_change"),
    ("-sagittarius-mode", "mode_change"),
    ("-valdur-arm", "mode_change"),
    ("-mode", "mode_change"),
]

# slug prefix -> relation type
PREFIX_RULES: list[tuple[str, str]] = [
    ("black-", "black_variant"),
]


def infer_relations(conn: sqlite3.Connection) -> int:
    """Add variant relations for every digimon whose slug derives from an
    existing base. Returns relations added."""
    import re

    by_slug: dict[str, int] = {}
    by_norm: dict[str, int] = {}
    for r in conn.execute("SELECT id, canonical_slug FROM digimon"):
        by_slug[r["canonical_slug"]] = r["id"]
        norm = re.sub(r"[^a-z0-9]", "", r["canonical_slug"])
        by_norm.setdefault(norm, r["id"])

    added = 0
    for slug, did in by_slug.items():
        base = _base_slug(slug)
        if base is None:
            continue
        base_id = by_slug.get(base)
        if base_id is None:
            # tolerate hyphen/case drift (e.g. base "war-greymon" vs entity
            # slug "wargreymon" from a source that omitted the space)
            base_id = by_norm.get(re.sub(r"[^a-z0-9]", "", base))
        if base_id is None or base_id == did:
            continue
        rel_type = _relation_type(slug)
        if rel_type is None:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO digimon_relation
               (from_digimon_id, to_digimon_id, relation_type, source, note)
               VALUES(?,?,?,?,?)""",
            [did, base_id, rel_type, "inferred", f"variant of {base}"],
        )
        added += 1
    conn.commit()
    logger.info("inferred %d related-form relations", added)
    return added


def _base_slug(slug: str) -> str | None:
    for prefix, _ in PREFIX_RULES:
        if slug.startswith(prefix) and len(slug) > len(prefix):
            return slug[len(prefix):]
    for suffix, _ in SUFFIX_RULES:
        if slug.endswith(suffix) and len(slug) > len(suffix):
            return slug[: -len(suffix)]
    return None


def _relation_type(slug: str) -> str | None:
    for prefix, rt in PREFIX_RULES:
        if slug.startswith(prefix):
            return rt
    for suffix, rt in SUFFIX_RULES:
        if slug.endswith(suffix):
            return rt
    return None
