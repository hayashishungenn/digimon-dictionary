"""DigiDex FastAPI application.

Serves the canonical Digimon database to the SvelteKit frontend.
Database access is read-only via SQLite.
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from pipeline.core.config import DB_PATH
from pipeline.core.enums import Attribute, Level
from pipeline.core.schema import connect_readonly

from . import queries

# Resolve DB path: allow override via DIGIDEX_DB env var (tests use a fixture).
# This file is at <root>/apps/api/main.py -> parents[2] is the repo root.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "digidex.sqlite"


def _db_path() -> Path:
    return Path(os.environ.get("DIGIDEX_DB", str(DEFAULT_DB_PATH)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_ready = _db_path().exists()
    yield


app = FastAPI(title="DigiDex API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local dev; tighten before deployment
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db() -> Any:
    db = _db_path()
    if not db.exists():
        raise HTTPException(503, "Dataset not synced yet. Run `uv run python scripts/sync_data.py`.")
    return connect_readonly(db)


# --------------------------------------------------------------------------
# meta
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "db_ready": _db_path().exists(),
        "db_path": str(_db_path()),
    }


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    conn = _db()
    try:
        return {
            "snapshot": queries.get_snapshot(conn),
            "counts": queries.get_counts(conn),
            "levels": [
                {"value": lv.value, "label_zh": lv.label_zh, "label_en": lv.label_en}
                for lv in Level
            ],
            "attributes": [
                {"value": a.value, "label_zh": a.label_zh, "label_en": a.label_en}
                for a in Attribute
            ],
            "types": queries.list_types(conn),
            "fields": queries.list_fields(conn),
            "groups": queries.list_groups(conn),
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------
# digimon list / detail
# --------------------------------------------------------------------------
@app.get("/api/digimon")
def list_digimon(
    level: str | None = None,
    attribute: str | None = None,
    type: str | None = Query(default=None, alias="type"),
    field: str | None = None,
    group: str | None = None,
    x_antibody: bool | None = None,
    official: str | None = Query(default="all", pattern="^(all|official|extended)$"),
    sort: str = Query(default="name", pattern="^(name|zh|id|debut|recent|level)$"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
    limit: int = Query(default=60, ge=1, le=300),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    conn = _db()
    try:
        items = queries.list_digimon(
            conn,
            level=level,
            attribute=attribute,
            type_name=type,
            field=field,
            group=group,
            x_antibody=x_antibody,
            official=official if official != "all" else None,
            sort=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
        total = queries.count_digimon(
            conn,
            level=level,
            attribute=attribute,
            type_name=type,
            field=field,
            group=group,
            x_antibody=x_antibody,
            official=official if official != "all" else None,
        )
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


@app.get("/api/digimon/{ident}")
def digimon_detail(ident: str) -> dict[str, Any]:
    conn = _db()
    try:
        base = queries.get_digimon(conn, ident)
        if not base:
            raise HTTPException(404, f"Unknown digimon: {ident}")
        return queries.get_digimon_full(conn, base["id"])
    finally:
        conn.close()


# --------------------------------------------------------------------------
# search
# --------------------------------------------------------------------------
@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    conn = _db()
    try:
        items = queries.search_digimon(conn, q, limit=limit)
        return {"query": q, "items": items, "count": len(items)}
    finally:
        conn.close()


# --------------------------------------------------------------------------
# sub-resources
# --------------------------------------------------------------------------
@app.get("/api/digimon/{ident}/evolution")
def digimon_evolution(ident: str, depth: int = Query(default=1, ge=1, le=4)) -> dict[str, Any]:
    conn = _db()
    try:
        base = queries.get_digimon(conn, ident)
        if not base:
            raise HTTPException(404, f"Unknown digimon: {ident}")
        return queries.get_evolution(conn, base["id"], depth=depth)
    finally:
        conn.close()


@app.get("/api/digimon/{ident}/skills")
def digimon_skills(ident: str) -> list[dict[str, Any]]:
    conn = _db()
    try:
        base = queries.get_digimon(conn, ident)
        if not base:
            raise HTTPException(404, f"Unknown digimon: {ident}")
        return queries.get_skills(conn, base["id"])
    finally:
        conn.close()


@app.get("/api/digimon/{ident}/aliases")
def digimon_aliases(ident: str) -> list[dict[str, Any]]:
    conn = _db()
    try:
        base = queries.get_digimon(conn, ident)
        if not base:
            raise HTTPException(404, f"Unknown digimon: {ident}")
        return queries.get_aliases(conn, base["id"])
    finally:
        conn.close()


@app.get("/api/digimon/{ident}/relations")
def digimon_relations(ident: str) -> list[dict[str, Any]]:
    conn = _db()
    try:
        base = queries.get_digimon(conn, ident)
        if not base:
            raise HTTPException(404, f"Unknown digimon: {ident}")
        return queries.get_relations(conn, base["id"])
    finally:
        conn.close()


@app.get("/api/groups/{group_name}")
def group_detail(group_name: str) -> dict[str, Any]:
    conn = _db()
    try:
        members = queries.group_members(conn, group_name)
        if not members:
            raise HTTPException(404, f"Unknown group: {group_name}")
        return {"name": group_name, "members": members, "count": len(members)}
    finally:
        conn.close()
