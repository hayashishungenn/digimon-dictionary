"""SQL query layer for the DigiDex API.

All reads go through SQLite (read-only). The frontend is never allowed to
reach into the pipeline tables directly.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any


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
    d.name_en_dub, d.name_romanized, d.level_raw, d.attribute_raw,
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


# --------------------------------------------------------------------------
# detail
# --------------------------------------------------------------------------
def get_digimon(conn: sqlite3.Connection, ident: str | int) -> dict[str, Any] | None:
    if isinstance(ident, int) or ident.isdigit():
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
    base["images"] = [
        dict(r)
        for r in conn.execute(
            """SELECT image_type, remote_url, local_path, download_status, width, height,
                      transparent, sha256
               FROM digimon_image WHERE digimon_id = ? ORDER BY id""",
            [digimon_id],
        )
    ]
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


def get_evolution(conn: sqlite3.Connection, digimon_id: int, depth: int = 1) -> dict[str, Any]:
    """Return the local evolution neighbourhood up to `depth` hops.

    shape: {"nodes": [...], "edges": [...], "center": id}
    """
    nodes: dict[int, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    frontier = {digimon_id}
    visited: set[int] = set()
    for _ in range(depth):
        if not frontier:
            break
        visited |= frontier
        ids = list(frontier)
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"""SELECT e.id, e.from_digimon_id, e.to_digimon_id, e.evolution_type,
                       e.condition, e.is_primary_line, e.source
                FROM evolution_edge e
                WHERE e.from_digimon_id IN ({placeholders}) OR e.to_digimon_id IN ({placeholders})""",
            [*ids, *ids],
        ).fetchall()
        next_frontier: set[int] = set()
        for e in rows:
            edge = {
                "id": e["id"],
                "from": e["from_digimon_id"],
                "to": e["to_digimon_id"],
                "evolution_type": e["evolution_type"],
                "condition": e["condition"],
                "is_primary_line": bool(e["is_primary_line"]),
                "source": e["source"],
            }
            if (e["from_digimon_id"], e["to_digimon_id"], e["evolution_type"]) not in {
                (x["from"], x["to"], x["evolution_type"]) for x in edges
            }:
                edges.append(edge)
            for node_id in (e["from_digimon_id"], e["to_digimon_id"]):
                if node_id not in visited and node_id not in next_frontier and node_id != digimon_id:
                    next_frontier.add(node_id)
        frontier = next_frontier
    for node_id in {x["from"] for x in edges} | {x["to"] for x in edges} | {digimon_id}:
        n = conn.execute(
            "SELECT id, canonical_slug, name_zh_cn, name_en, name_ja, level, main_image FROM digimon WHERE id = ?",
            [node_id],
        ).fetchone()
        if n:
            nodes[node_id] = dict(n)
    return {"center": digimon_id, "nodes": nodes, "edges": edges}


def get_relations(conn: sqlite3.Connection, digimon_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT r.relation_type, r.source, r.note, d2.id AS to_id, d2.canonical_slug,
                  d2.name_zh_cn, d2.name_en
           FROM digimon_relation r JOIN digimon d2 ON d2.id = r.to_digimon_id
           WHERE r.from_digimon_id = ? ORDER BY r.relation_type""",
        [digimon_id],
    ).fetchall()
    out = [dict(r) for r in rows]
    # also include reverse relations (things pointing to this digimon)
    rev = conn.execute(
        """SELECT r.relation_type, r.source, r.note, d1.id AS to_id, d1.canonical_slug,
                  d1.name_zh_cn, d1.name_en
           FROM digimon_relation r JOIN digimon d1 ON d1.id = r.from_digimon_id
           WHERE r.to_digimon_id = ? AND r.from_digimon_id != ?""",
        [digimon_id, digimon_id],
    ).fetchall()
    out.extend(dict(r) for r in rev)
    return out


def get_provenance(conn: sqlite3.Connection, entity_type: str, entity_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in conn.execute(
            """SELECT field, source, source_url, retrieved_at, confidence
               FROM provenance WHERE entity_type = ? AND entity_id = ?
               ORDER BY field""",
            [entity_type, entity_id],
        )
    ]


# --------------------------------------------------------------------------
# search (FTS5)
# --------------------------------------------------------------------------
def search_digimon(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int = 30,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """FTS5-backed multilingual search with alias expansion.

    Falls back to a LIKE scan when FTS5 yields nothing (very short queries).
    """
    q = query.strip()
    if not q:
        return []
    # FTS5 tokenization handles CJK poorly without trigram tokenizer, so we run
    # BOTH an FTS5 phrase search and a LIKE scan, then union.
    rows = []
    seen: set[int] = set()
    fts_phrase = q.replace('"', ' ')
    try:
        fts_rows = conn.execute(
            """SELECT d.id FROM digimon_fts f JOIN digimon d ON d.id = f.rowid
               WHERE digimon_fts MATCH ? ORDER BY bm25(digimon_fts) LIMIT ?""",
            [fts_phrase, limit * 3],
        ).fetchall()
        for r in fts_rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                rows.append(r["id"])
    except sqlite3.OperationalError:
        pass  # malformed FTS query — fall through to LIKE

    like = f"%{q}%"
    like_rows = conn.execute(
        """SELECT id FROM digimon
           WHERE name_zh_cn LIKE ? COLLATE NOCASE
              OR name_en LIKE ? COLLATE NOCASE
              OR name_ja LIKE ? COLLATE NOCASE
              OR name_romanized LIKE ? COLLATE NOCASE
           ORDER BY CASE WHEN name_zh_cn = ? OR name_en = ? OR name_ja = ? THEN 0 ELSE 1 END
           LIMIT ?""",
        [like, like, like, like, q, q, q, limit * 2],
    ).fetchall()
    for r in like_rows:
        if r["id"] not in seen:
            seen.add(r["id"])
            rows.append(r["id"])

    # alias search
    alias_rows = conn.execute(
        """SELECT DISTINCT a.digimon_id FROM digimon_alias a
           WHERE a.alias LIKE ? COLLATE NOCASE LIMIT ?""",
        [like, limit * 2],
    ).fetchall()
    for r in alias_rows:
        if r["digimon_id"] not in seen:
            seen.add(r["digimon_id"])
            rows.append(r["digimon_id"])

    if not rows:
        return []
    out = []
    for digimon_id in rows[: limit * 2]:
        d = get_digimon(conn, digimon_id)
        if d:
            out.append(d)
    return out


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
