"""SQL query layer for the DigiDex API.

All reads go through SQLite (read-only). The frontend is never allowed to
reach into the pipeline tables directly.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


def _escape_like(text: str) -> str:
    """Escape LIKE wildcards so user input is never a full-table wildcard (T5.5)."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


# --------------------------------------------------------------------------
# list + filter
# --------------------------------------------------------------------------
LIST_COLUMNS = """
    d.id, d.canonical_slug, d.name_zh_cn, d.name_en, d.name_ja,
    d.name_zh_cn_status, d.level, d.attribute, d.x_antibody,
    d.is_official_reference, d.is_extended, d.main_image, d.thumbnail,
    d.first_appearance_date, d.updated_at
"""

# Full column set for detail pages (everything the UI can show).
FULL_COLUMNS = LIST_COLUMNS + """
    , d.name_zh_cn_source, d.name_zh_cn_verified, d.name_zh_hk, d.name_zh_tw,
    d.name_en_dub, d.name_romanized, d.level_raw, d.attribute_raw, d.level_2,
    d.first_appearance_title, d.first_appearance_medium,
    d.profile_zh_cn, d.profile_en, d.profile_ja,
    d.profile_source, d.profile_source_url, d.profile_verified,
    d.name_origin, d.dapi_id, d.wikimon_title, d.official_slug,
    d.digimons_net_slug, d.digidb_id, d.content_hash, d.source_last_updated
"""


def list_digimon(
    conn: sqlite3.Connection,
    *,
    level: str | None = None,
    attribute: str | None = None,
    type_name: str | None = None,
    field: str | None = None,
    group: str | None = None,
    x_antibody: bool | None = None,
    official: str | None = None,  # 'official' | 'extended' | 'all'
    sort: str = "name",
    order: str = "asc",
    limit: int = 60,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    joins: list[str] = []

    if level:
        where.append("d.level = ?")
        params.append(level)
    if attribute:
        where.append("d.attribute = ?")
        params.append(attribute)
    if type_name:
        joins.append(
            "JOIN digimon_type dt ON dt.digimon_id = d.id "
            "JOIN type t ON t.id = dt.type_id"
        )
        where.append("t.name = ?")
        params.append(type_name)
    if field:
        joins.append(
            "JOIN digimon_field df ON df.digimon_id = d.id "
            "JOIN field f ON f.id = df.field_id"
        )
        where.append("f.name = ?")
        params.append(field)
    if group:
        joins.append(
            "JOIN digimon_group dg ON dg.digimon_id = d.id "
            "JOIN grp g ON g.id = dg.group_id"
        )
        where.append("g.name = ?")
        params.append(group)
    if x_antibody is not None:
        where.append("d.x_antibody = ?")
        params.append(1 if x_antibody else 0)
    if official == "official":
        where.append("d.is_official_reference = 1")
    elif official == "extended":
        where.append("d.is_extended = 1 AND d.is_official_reference = 0")

    sort_map = {
        "name": "d.name_en COLLATE NOCASE",
        "zh": "d.name_zh_cn COLLATE NOCASE",
        "id": "d.id",
        "debut": "d.first_appearance_date IS NULL, d.first_appearance_date",
        "recent": "d.updated_at",
        "level": "d.level",
    }
    order_sql = "ASC" if order.lower() != "desc" else "DESC"
    sort_col = sort_map.get(sort, sort_map["name"])

    join_sql = "\n".join(joins)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"""
        SELECT DISTINCT {LIST_COLUMNS}
        FROM digimon d
        {join_sql}
        {where_sql}
        ORDER BY {sort_col} {order_sql}
        LIMIT ? OFFSET ?
    """
    rows = conn.execute(sql, [*params, limit, offset]).fetchall()
    return [dict(r) for r in rows]


def count_digimon(
    conn: sqlite3.Connection,
    *,
    level: str | None = None,
    attribute: str | None = None,
    type_name: str | None = None,
    field: str | None = None,
    group: str | None = None,
    x_antibody: bool | None = None,
    official: str | None = None,
) -> int:
    """Mirror of list_digimon's WHERE clause, returning a count."""
    where: list[str] = []
    params: list[Any] = []
    joins: list[str] = []
    if level:
        where.append("d.level = ?")
        params.append(level)
    if attribute:
        where.append("d.attribute = ?")
        params.append(attribute)
    if type_name:
        joins.append("JOIN digimon_type dt ON dt.digimon_id = d.id JOIN type t ON t.id = dt.type_id")
        where.append("t.name = ?")
        params.append(type_name)
    if field:
        joins.append("JOIN digimon_field df ON df.digimon_id = d.id JOIN field f ON f.id = df.field_id")
        where.append("f.name = ?")
        params.append(field)
    if group:
        joins.append("JOIN digimon_group dg ON dg.digimon_id = d.id JOIN grp g ON g.id = dg.group_id")
        where.append("g.name = ?")
        params.append(group)
    if x_antibody is not None:
        where.append("d.x_antibody = ?")
        params.append(1 if x_antibody else 0)
    if official == "official":
        where.append("d.is_official_reference = 1")
    elif official == "extended":
        where.append("d.is_extended = 1 AND d.is_official_reference = 0")
    join_sql = "\n".join(joins)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = f"SELECT COUNT(DISTINCT d.id) FROM digimon d {join_sql} {where_sql}"
    row = conn.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


def list_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[dict[str, Any]]:
    """List items for a specific set of digimon ids (used by the favorites page).

    Only the ids that exist are returned; ordering follows the requested order
    so the UI can present favorites in the order the user saved them.
    """
    if not ids:
        return []
    sql = (
        f"SELECT {LIST_COLUMNS} FROM digimon d WHERE d.id IN "
        f"({','.join('?' * len(ids))})"
    )
    rows = conn.execute(sql, list(ids)).fetchall()
    by_id = {r["id"]: dict(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


# --------------------------------------------------------------------------
# detail
# --------------------------------------------------------------------------
def get_digimon(conn: sqlite3.Connection, ident: str | int) -> dict[str, Any] | None:
    # ASCII-only decimal ids: str.isdigit() accepts ²/³/٤ etc. which int() then
    # rejects with a 500 — treat any non-ASCII-decimal ident as a slug lookup
    # (same rule as /api/digimon/by-id, P2-04).
    if isinstance(ident, int) or re.fullmatch(r"[0-9]+", ident):
        row = conn.execute(
            f"SELECT {LIST_COLUMNS} FROM digimon d WHERE d.id = ?", [int(ident)]
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT {LIST_COLUMNS} FROM digimon d WHERE d.canonical_slug = ?", [ident]
        ).fetchone()
    return _row(row)


def get_digimon_full(conn: sqlite3.Connection, digimon_id: int) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT {FULL_COLUMNS} FROM digimon d WHERE d.id = ?", [digimon_id]
    ).fetchone()
    if row is None:
        raise ValueError(f"digimon id {digimon_id} not found")
    base = dict(row)
    base["types"] = [
        dict(r)
        for r in conn.execute(
            """SELECT t.name, t.name_zh, t.name_ja, dt.is_primary, dt.source
               FROM digimon_type dt JOIN type t ON t.id = dt.type_id
               WHERE dt.digimon_id = ? ORDER BY dt.is_primary DESC""",
            [digimon_id],
        )
    ]
    base["fields"] = [
        dict(r)
        for r in conn.execute(
            """SELECT f.name, f.name_zh FROM digimon_field df
               JOIN field f ON f.id = df.field_id
               WHERE df.digimon_id = ? ORDER BY f.name""",
            [digimon_id],
        )
    ]
    base["groups"] = [
        dict(r)
        for r in conn.execute(
            """SELECT g.name, g.name_zh FROM digimon_group dg
               JOIN grp g ON g.id = dg.group_id
               WHERE dg.digimon_id = ? ORDER BY g.name""",
            [digimon_id],
        )
    ]
    base["skills"] = get_skills(conn, digimon_id)
    base["aliases"] = get_aliases(conn, digimon_id)
    base["game_stats"] = get_game_stats(conn, digimon_id)
    base["images"] = [
        dict(r)
        for r in conn.execute(
            """SELECT image_type, remote_url, local_path, download_status, width, height,
                      transparent, sha256, content_type, fetched_at, failure_reason
               FROM digimon_image WHERE digimon_id = ? ORDER BY id""",
            [digimon_id],
        )
    ]
    # P0-1: never leak a server filesystem path. Contract says local_path is
    # cache-root-relative or NULL; anything else (absolute/UNC/..) is nulled.
    from pipeline.core.images import is_bad_stored_path

    for img in base["images"]:
        if img.get("local_path") and is_bad_stored_path(img["local_path"]):
            img["local_path"] = None
    base["evolution"] = get_evolution(conn, digimon_id, depth=1)
    base["relations"] = get_relations(conn, digimon_id)
    base["profile"] = {
        "zh_cn": base.pop("profile_zh_cn", None),
        "en": base.pop("profile_en", None),
        "ja": base.pop("profile_ja", None),
        "source": base.pop("profile_source", None),
        "source_url": base.pop("profile_source_url", None),
        "verified": bool(base.pop("profile_verified", 0)),
    }
    base["first_appearance"] = {
        "title": base.pop("first_appearance_title", None),
        "date": base.pop("first_appearance_date", None),
        "medium": base.pop("first_appearance_medium", None),
    }
    base["names"] = {
        "zh_cn": base.pop("name_zh_cn", None),
        "zh_cn_status": base.pop("name_zh_cn_status", None),
        "zh_hk": base.pop("name_zh_hk", None),
        "zh_tw": base.pop("name_zh_tw", None),
        "en": base.pop("name_en", None),
        "en_dub": base.pop("name_en_dub", None),
        "ja": base.pop("name_ja", None),
        "romanized": base.pop("name_romanized", None),
    }
    base["source"] = get_provenance(conn, "digimon", digimon_id)
    base["conflicts"] = [
        dict(r)
        for r in conn.execute(
            """SELECT field, source_a, value_a, source_b, value_b, chosen_value,
                      chosen_source, review_status, resolution
               FROM data_conflict WHERE entity_type = 'digimon' AND entity_id = ?
               ORDER BY field""",
            [digimon_id],
        )
    ]
    return base


def get_aliases(conn: sqlite3.Connection, digimon_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            """SELECT alias, language, region, alias_type, source, verified
               FROM digimon_alias WHERE digimon_id = ? ORDER BY verified DESC, id""",
            [digimon_id],
        )
    ]


def get_skills(conn: sqlite3.Connection, digimon_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            """SELECT s.id, s.name_zh_cn, s.name_en, s.name_ja,
                      s.description_zh_cn, s.description_en, s.description_ja,
                      ds.skill_type, ds.is_signature, ds.sort_order
               FROM digimon_skill ds JOIN skill s ON s.id = ds.skill_id
               WHERE ds.digimon_id = ? ORDER BY ds.sort_order, ds.is_signature DESC""",
            [digimon_id],
        )
    ]


# Evolution graph bounds (P0-1): the API only ever returns a budgeted
# neighbourhood, never an unbounded full graph. depth is validated at the API
# layer to 1..3; these budgets cap the worst case so a hub digimon cannot blow
# up the response or the renderer.
EVOLUTION_MAX_DEPTH = 3
EVOLUTION_NODE_BUDGET = 500
EVOLUTION_EDGE_BUDGET = 2500

_NODE_COLUMNS = "id, canonical_slug, name_zh_cn, name_en, name_ja, level, main_image"


def get_evolution(conn: sqlite3.Connection, digimon_id: int, depth: int = 1) -> dict[str, Any]:
    """Return the local evolution neighbourhood up to `depth` hops.

    Bounded BFS: traversal expands breadth-first from the center so the closest
    relationships are always returned first. Node/edge budgets cap the worst
    case; when a budget is hit the traversal stops and ``truncated`` is true,
    with explicit counts so the UI can tell the user part of the graph was
    dropped (never a silent omission, never an unrenderable full graph).

    shape::
        {"center": id, "depth": n, "nodes": {...}, "edges": [...],
         "node_count": n, "edge_count": n, "truncated": bool,
         "dropped_edges": n}   # unique edges encountered but not included
    """
    depth = max(1, min(int(depth), EVOLUTION_MAX_DEPTH))
    edges: list[dict[str, Any]] = []
    seen_edges: set[tuple[int, int, str]] = set()
    node_ids: set[int] = {digimon_id}
    visited: set[int] = {digimon_id}
    frontier: set[int] = {digimon_id}
    truncated = False
    dropped_edges = 0
    traversed = 0

    while frontier and traversed < depth and not truncated:
        ids = sorted(frontier)
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"""SELECT e.id, e.from_digimon_id, e.to_digimon_id, e.evolution_type,
                       e.condition, e.is_primary_line, e.source
                FROM evolution_edge e
                WHERE e.from_digimon_id IN ({placeholders}) OR e.to_digimon_id IN ({placeholders})
                ORDER BY e.id""",  # stable order -> reproducible graph
            [*ids, *ids],
        ).fetchall()
        next_frontier: set[int] = set()
        for e in rows:
            key = (e["from_digimon_id"], e["to_digimon_id"], e["evolution_type"])
            if key in seen_edges:
                continue
            seen_edges.add(key)
            new_nodes = [nid for nid in (e["from_digimon_id"], e["to_digimon_id"]) if nid not in visited]
            if len(edges) >= EVOLUTION_EDGE_BUDGET or (
                new_nodes and len(node_ids) >= EVOLUTION_NODE_BUDGET
            ):
                truncated = True
                dropped_edges += 1
                continue
            edges.append(
                {
                    "id": e["id"],
                    "from": e["from_digimon_id"],
                    "to": e["to_digimon_id"],
                    "evolution_type": e["evolution_type"],
                    "condition": e["condition"],
                    "is_primary_line": bool(e["is_primary_line"]),
                    "source": e["source"],
                }
            )
            for nid in new_nodes:
                visited.add(nid)
                node_ids.add(nid)
                next_frontier.add(nid)
        traversed += 1
        frontier = next_frontier

    # batch-load node metadata in one query (no per-node N+1)
    nodes: dict[int, dict[str, Any]] = {}
    if node_ids:
        node_list = sorted(node_ids)
        placeholders = ",".join("?" * len(node_list))
        nodes = {
            r["id"]: dict(r)
            for r in conn.execute(
                f"SELECT {_NODE_COLUMNS} FROM digimon WHERE id IN ({placeholders})",
                node_list,
            ).fetchall()
        }
    # an edge is only kept when both endpoints resolved; any missing node (e.g.
    # a deleted entity) would break the graph, so drop such edges explicitly.
    kept: list[dict[str, Any]] = []
    for e in edges:
        if e["from"] in nodes and e["to"] in nodes:
            kept.append(e)
    return {
        "center": digimon_id,
        "depth": traversed,
        "nodes": nodes,
        "edges": kept,
        "node_count": len(nodes),
        "edge_count": len(kept),
        "truncated": truncated,
        "dropped_edges": dropped_edges + (len(edges) - len(kept)),
    }


def get_relations(conn: sqlite3.Connection, digimon_id: int) -> list[dict[str, Any]]:
    """Relations in both directions with explicit direction/from_id/to_id.

    ``to_id`` stays the *other* digimon for backward compatibility with earlier
    clients; ``direction`` ('out'|'in') and the explicit ``from_id``/``to_id``
    let a client present the graph without guessing (T5.8).
    """
    out: list[dict[str, Any]] = []
    rows = conn.execute(
        """SELECT r.relation_type, r.source, r.note, d2.id AS to_id, d2.canonical_slug,
                  d2.name_zh_cn, d2.name_en
           FROM digimon_relation r JOIN digimon d2 ON d2.id = r.to_digimon_id
           WHERE r.from_digimon_id = ? ORDER BY r.relation_type""",
        [digimon_id],
    ).fetchall()
    for r in rows:
        item = dict(r)
        item["direction"] = "out"
        item["from_id"] = digimon_id
        out.append(item)
    # also include reverse relations (things pointing to this digimon)
    rev = conn.execute(
        """SELECT r.relation_type, r.source, r.note, d1.id AS other_id, d1.canonical_slug,
                  d1.name_zh_cn, d1.name_en
           FROM digimon_relation r JOIN digimon d1 ON d1.id = r.from_digimon_id
           WHERE r.to_digimon_id = ? AND r.from_digimon_id != ?""",
        [digimon_id, digimon_id],
    ).fetchall()
    for r in rev:
        item = dict(r)
        item["direction"] = "in"
        item["from_id"] = item.pop("other_id")
        item["to_id"] = digimon_id
        out.append(item)
    return out


def get_game_stats(conn: sqlite3.Connection, digimon_id: int) -> list[dict[str, Any]]:
    """Per-game stats, isolated from world-view data (spec §10)."""
    return [
        dict(r)
        for r in conn.execute(
            """SELECT g.name AS game, g.short_name, s.hp, s.sp, s.atk, s.def, s.int, s.spd,
                      s.memory, s.slots, s.extras, s.source
               FROM game_digimon_stats s JOIN game g ON g.id = s.game_id
               WHERE s.digimon_id = ? ORDER BY g.name""",
            [digimon_id],
        )
    ]


def get_provenance(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            """SELECT field, source, source_url, retrieved_at, confidence, run_id
               FROM provenance WHERE entity_type = ? AND entity_id = ?
               ORDER BY field""",
            [entity_type, entity_id],
        )
    ]


# --------------------------------------------------------------------------
# search (FTS5 + LIKE)
# --------------------------------------------------------------------------
def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" or "぀" <= ch <= "ヿ" for ch in text)


def search_digimon(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Multilingual search: exact name → substring (LIKE) → aliases → FTS.

    FTS5's unicode61 tokenizer splits CJK into per-character tokens, so a
    Chinese query like 亚古兽 matches ANY digimon containing 亚/古/兽 (OR
    semantics). We therefore use exact + LIKE matching for CJK queries and
    reserve FTS for Latin queries (where tokenization is helpful). Exact-name
    matches always rank first.

    User input is never treated as a SQL wildcard: `%` and `_` are escaped so
    arbitrary input cannot become a full-table scan (T5.5). The public contract
    has no pagination offset for keyword search (T5.4).
    """
    q = query.strip()
    if not q:
        return []
    # 简体/繁体/日文 查询变体：让 "亞古獸" 命中 "亚古兽"（§35 简繁转换）
    variants = _search_variants(q)
    rows: list[int] = []
    seen: set[int] = set()

    def add(id_: int) -> None:
        if id_ not in seen:
            seen.add(id_)
            rows.append(id_)

    # 1. exact name matches (any language, any variant) rank first
    exact_clause = " OR ".join(
        ["name_zh_cn = ?"] * len(variants)
        + ["name_en = ? COLLATE NOCASE"] * len(variants)
        + ["name_ja = ?"] * len(variants)
        + ["name_romanized = ? COLLATE NOCASE"] * len(variants)
        + ["name_en_dub = ? COLLATE NOCASE"] * len(variants)
    )
    exact_params = [*variants] * 5
    for r in conn.execute(
        f"SELECT id FROM digimon WHERE {exact_clause} LIMIT ?",
        [*exact_params, limit],
    ).fetchall():
        add(r["id"])

    # 1b. exact alias matches
    for v in variants:
        for r in conn.execute(
            """SELECT DISTINCT a.digimon_id FROM digimon_alias a
               WHERE a.alias = ? COLLATE NOCASE LIMIT ?""",
            [v, limit],
        ).fetchall():
            add(r["digimon_id"])

    # 2. substring (LIKE) matches across primary names (all variants), with
    #    user `%`/`_` escaped so they never act as wildcards.
    like_params: list[str] = []
    like_where: list[str] = []
    for v in variants:
        lv = f"%{_escape_like(v)}%"
        for col in ("name_zh_cn", "name_en", "name_ja", "name_romanized"):
            like_where.append(f"{col} LIKE ? ESCAPE '\\' COLLATE NOCASE")
            like_params.append(lv)
    like_rows = conn.execute(
        f"""SELECT id FROM digimon WHERE {' OR '.join(like_where)} LIMIT ?""",
        [*like_params, limit * 2],
    ).fetchall()
    for r in like_rows:
        add(r["id"])

    # 3. alias substring matches (all variants)
    alias_where = " OR ".join(["a.alias LIKE ? ESCAPE '\\' COLLATE NOCASE"] * len(variants))
    alias_params = [f"%{_escape_like(v)}%" for v in variants]
    for r in conn.execute(
        f"""SELECT DISTINCT a.digimon_id FROM digimon_alias a
            WHERE {alias_where} LIMIT ?""",
        [*alias_params, limit * 2],
    ).fetchall():
        add(r["digimon_id"])

    # 4. FTS only for Latin queries (CJK tokenization is too broad). A malformed
    #    FTS query falls back to the LIKE results above — observably, not silently.
    if not _has_cjk(q):
        try:
            fts_phrase = q.replace('"', " ")
            fts_rows = conn.execute(
                """SELECT d.id FROM digimon_fts f JOIN digimon d ON d.id = f.rowid
                   WHERE digimon_fts MATCH ? ORDER BY bm25(digimon_fts) LIMIT ?""",
                [fts_phrase, limit * 2],
            ).fetchall()
            for r in fts_rows:
                add(r["id"])
        except sqlite3.OperationalError as exc:
            logger.warning("FTS query %r failed; falling back to LIKE results: %s", q, exc)

    # P2-05: batch the detail lookup with a single WHERE id IN (...) instead of
    # one query per result (search limit=100 used to run 100 extra queries).
    return list_by_ids(conn, rows[:limit])


def _search_variants(q: str) -> list[str]:
    """Query variants for matching: original + simplified/traditional CJK +
    punctuation-stripped form (so "War Greymon" hits "WarGreymon", §35)."""
    import re as _re

    from pipeline.core import naming

    variants = [q]
    stripped = _re.sub(r"[\s\-_()（）·]+", "", q)
    if stripped and stripped != q:
        variants.append(stripped)
    if _has_cjk(q):
        for conv in (naming.to_simplified, naming.to_traditional):
            v = conv(q)
            if v not in variants:
                variants.append(v)
    return variants


# --------------------------------------------------------------------------
# meta / enums
# --------------------------------------------------------------------------
def list_types(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT id, name, name_zh, name_ja FROM type ORDER BY name")]


def list_fields(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT id, name, name_zh, name_ja FROM field ORDER BY name")]


def list_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT id, name, name_zh FROM grp ORDER BY name")]


def group_members(conn: sqlite3.Connection, group_name: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""SELECT {LIST_COLUMNS} FROM digimon d
            JOIN digimon_group dg ON dg.digimon_id = d.id
            JOIN grp g ON g.id = dg.group_id
            WHERE g.name = ? ORDER BY d.name_en""",
        [group_name],
    ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# manual review workflow (S1-1)
#
# The review queue is small (hundreds of items), so filtering + category
# derivation happen in Python after a cheap SQL row scan. `category` is a
# derived, human-meaningful label that distinguishes *why* an item is queued:
#   - external_target  : an edge/relation references a target outside the
#                        current dataset ("unresolved target") — not a match bug
#   - matching_failure : an entity could not be safely matched/merged
#   - conflict         : real cross-source disagreement that source priority
#                        could not resolve
#   - wikitext         : a user-visible field still carries raw wikitext
#                        (original preserved here, cleaned value shown in UI)
#   - other            : anything else (e.g. unmatched game records)
# --------------------------------------------------------------------------
def _review_category(reason: str | None) -> str:
    r = (reason or "").lower()
    if "wikitext" in r:
        return "wikitext"
    if "unresolved" in r or "target" in r or "not in the current" in r:
        return "external_target"
    if "ambiguous" in r or "needs review" in r or "not matched" in r:
        return "matching_failure"
    if "conflict" in r:
        return "conflict"
    return "other"


def _review_category_sql() -> str:
    """Category as a SQL CASE so filtering + count happen in the database
    (P2-03) instead of loading every row and slicing in Python."""
    return """CASE
        WHEN reason LIKE '%wikitext%' THEN 'wikitext'
        WHEN reason LIKE '%unresolved%' OR reason LIKE '%target%' THEN 'external_target'
        WHEN reason LIKE '%ambiguous%' OR reason LIKE '%needs review%' THEN 'matching_failure'
        WHEN reason LIKE '%conflict%' THEN 'conflict'
        ELSE 'other' END"""


def _review_where(status: str, entity_type: str | None, q: str | None, category: str | None = None) -> tuple[str, list[Any]]:
    where = ["status = ?"]
    params: list[Any] = [status]
    if entity_type:
        where.append("entity_type = ?")
        params.append(entity_type)
    if q:
        where.append("(reason LIKE ? ESCAPE '\\' OR detail LIKE ? ESCAPE '\\')")
        like = f"%{_escape_like(q)}%"
        params += [like, like]
    if category:
        where.append(f"({_review_category_sql()}) = ?")
        params.append(category)
    return " AND ".join(where), params


def list_review_items(
    conn: sqlite3.Connection,
    *,
    status: str = "open",
    entity_type: str | None = None,
    q: str | None = None,
    category: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where, params = _review_where(status, entity_type, q, category)
    rows = conn.execute(
        f"""SELECT id, entity_type, entity_id, reason, detail, status,
                   created_at, resolved_at, run_id, note,
                   {_review_category_sql()} AS category
            FROM manual_review_queue WHERE {where} ORDER BY id LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()
    return [
        {**dict(r), "detail": json.loads(r["detail"]) if r["detail"] else {}}
        for r in rows
    ]


def count_review_items(
    conn: sqlite3.Connection,
    *,
    status: str = "open",
    entity_type: str | None = None,
    q: str | None = None,
    category: str | None = None,
) -> int:
    where, params = _review_where(status, entity_type, q, category)
    row = conn.execute(
        f"SELECT COUNT(*) FROM manual_review_queue WHERE {where}", params
    ).fetchone()
    return int(row[0]) if row else 0


def review_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    by_status = {
        r["status"]: r["c"]
        for r in conn.execute(
            "SELECT status, COUNT(*) c FROM manual_review_queue GROUP BY status"
        )
    }
    open_rows = conn.execute(
        "SELECT entity_type, reason FROM manual_review_queue WHERE status='open'"
    ).fetchall()
    by_entity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for r in open_rows:
        by_entity[r["entity_type"]] = by_entity.get(r["entity_type"], 0) + 1
        c = _review_category(r["reason"])
        by_category[c] = by_category.get(c, 0) + 1
    return {
        "by_status": by_status,
        "by_entity": by_entity,
        "by_category": by_category,
        "open": by_status.get("open", 0),
    }


def resolve_review_item(
    conn: sqlite3.Connection,
    review_id: int,
    *,
    status: str,
    note: str,
) -> dict[str, Any] | None:
    """Mark a review item resolved/wontfix with an explanation.

    A note is required: 'wontfix' means 'won't chase this now', NOT that the
    underlying fact is verified (S1-1). The original candidates are preserved
    (never deleted). Returns the updated row, or None when the item does not
    exist or is already closed.
    """
    if status not in ("resolved", "wontfix"):
        raise ValueError("status must be 'resolved' or 'wontfix'")
    if not note or not note.strip():
        raise ValueError("a resolution note is required")
    cur = conn.execute(
        """UPDATE manual_review_queue SET status=?, note=?, resolved_at=datetime('now')
           WHERE id=? AND status='open'""",
        [status, note.strip(), review_id],
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    row = conn.execute(
        """SELECT id, entity_type, entity_id, reason, status, note, resolved_at
           FROM manual_review_queue WHERE id=?""",
        [review_id],
    ).fetchone()
    return dict(row) if row else None


def get_snapshot(conn: sqlite3.Connection) -> dict[str, Any] | None:
    return _row(
        conn.execute(
            "SELECT snapshot_date, official_count, extended_count, total_count FROM snapshot ORDER BY id DESC LIMIT 1"
        ).fetchone()
    )


def get_counts(conn: sqlite3.Connection) -> dict[str, int]:
    row = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM digimon) AS total,
             (SELECT COUNT(*) FROM digimon WHERE is_official_reference = 1) AS official,
             (SELECT COUNT(*) FROM digimon WHERE is_extended = 1 AND is_official_reference = 0) AS extended"""
    ).fetchone()
    return {"total": row["total"], "official": row["official"], "extended": row["extended"]}
