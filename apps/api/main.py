"""DigiDex FastAPI application.

Serves the canonical Digimon database to the SvelteKit frontend.
Database access is read-only via SQLite.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from pipeline.core.enums import Attribute, Level
from pipeline.core.schema import connect_readonly

from . import queries

logger = logging.getLogger(__name__)

# Resolve DB path: allow override via DIGIDEX_DB env var (tests use a fixture).
# This file is at <root>/apps/api/main.py -> parents[2] is the repo root.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "digidex.sqlite"

# Local development origins. Never a permanent wildcard — see _cors_origins().
DEFAULT_CORS_ORIGINS = ["http://localhost:5173", "http://localhost:4173"]


def _db_path() -> Path:
    return Path(os.environ.get("DIGIDEX_DB", str(DEFAULT_DB_PATH)))


def _cors_origins() -> list[str]:
    """CORS allow-list from DIGIDEX_CORS_ORIGINS (comma-separated).

    - Unset: explicit localhost dev origins (no wildcard).
    - Set: use exactly those origins.
    - A literal "*" is refused unless DIGIDEX_ENV=development — the default
      posture never allows arbitrary origins (T5.2).
    """
    env = os.environ.get("DIGIDEX_ENV", "").lower()
    raw = os.environ.get("DIGIDEX_CORS_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if "*" in origins and env != "development":
        logger.warning(
            "DIGIDEX_CORS_ORIGINS contains '*' but DIGIDEX_ENV is not 'development'; "
            "refusing wildcard CORS"
        )
        return list(DEFAULT_CORS_ORIGINS)
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_ready = _db_path().exists()
    yield


app = FastAPI(title="DigiDex API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _db() -> Any:
    db = _db_path()
    if not db.exists():
        raise HTTPException(503, "Dataset not synced yet. Run `uv run python scripts/sync_data.py`.")
    return connect_readonly(db)


def _thumb_servable(item: dict[str, Any]) -> str | None:
    """Turn the stored local thumbnail path into a servable API path.

    ``digimon.thumbnail`` holds the local cache path (data/images/thumbs/...);
    the API exposes it as ``/api/images/<id>/thumbnail`` so the frontend can
    load it without knowing the filesystem. Returns None when no thumbnail was
    derived (the UI then falls back to the main image / placeholder)."""
    if item.get("thumbnail"):
        return f"/api/images/{item['id']}/thumbnail"
    return None


# image types the /api/images/{ident}/{kind} endpoint serves.
_IMAGE_KINDS = {"main_image", "thumbnail"}


# Stable error responses: never leak absolute paths or SQLite internals (T5.10).
@app.exception_handler(sqlite3.Error)
async def _sqlite_error_handler(request, exc):
    logger.warning("sqlite error on %s: %s", request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "database query failed"})


@app.exception_handler(Exception)
async def _generic_error_handler(request, exc):
    logger.warning("unhandled error on %s: %r", request.url.path, exc)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


# --------------------------------------------------------------------------
# meta
# --------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    # Deliberately no db_path / absolute filesystem info (T5.1).
    return {
        "ok": True,
        "db_ready": _db_path().exists(),
        "service": "digidex-api",
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
        for it in items:
            it["thumbnail"] = _thumb_servable(it)
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        conn.close()


@app.get("/api/digimon/by-id")
def digimon_by_ids(ids: str = Query(..., description="comma-separated digimon ids")) -> dict[str, Any]:
    """List items for a specific set of ids (UI favorites page, S0/S1).

    Returns only ids that exist, in the requested order. Keeps the favorites
    page from fetching full details for a whole list (UI-P0-1). Registered
    before ``/api/digimon/{ident}`` so ``by-id`` is not captured as an ident.
    """
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    conn = _db()
    try:
        items = queries.list_by_ids(conn, id_list[:500])
        for it in items:
            it["thumbnail"] = _thumb_servable(it)
        return {"items": items}
    finally:
        conn.close()


@app.get("/api/digimon/{ident}")
def digimon_detail(ident: str) -> dict[str, Any]:
    conn = _db()
    try:
        base = queries.get_digimon(conn, ident)
        if not base:
            raise HTTPException(404, f"Unknown digimon: {ident}")
        detail = queries.get_digimon_full(conn, base["id"])
        detail["thumbnail"] = _thumb_servable(detail)
        return detail
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
        for it in items:
            it["thumbnail"] = _thumb_servable(it)
        return {"query": q, "items": items, "count": len(items)}
    finally:
        conn.close()


# --------------------------------------------------------------------------
# sub-resources
# --------------------------------------------------------------------------
@app.get("/api/digimon/{ident}/evolution")
def digimon_evolution(ident: str, depth: int = Query(default=1, ge=1, le=3)) -> dict[str, Any]:
    """Local evolution neighbourhood. depth is bounded to 1..3 (P0-1): the
    server rejects anything outside that range so a request can never ask the
    traversal to blow up. Large graphs are additionally budgeted server-side
    and marked ``truncated`` — never returned in full."""
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
        for m in members:
            m["thumbnail"] = _thumb_servable(m)
        return {"name": group_name, "members": members, "count": len(members)}
    finally:
        conn.close()


# --------------------------------------------------------------------------
# images (P0-3): serve the local cached main/thumbnail art.
# --------------------------------------------------------------------------
@app.get("/api/images/{ident}/{kind}")
def digimon_image(ident: str, kind: str):
    """Serve a digimon's cached image.

    ``kind`` is ``main_image`` or ``thumbnail``. The local cache under
    data/images/ is served when present; otherwise the request redirects to the
    source URL (the browser loads it); a digimon with no image at all returns
    404, and the frontend renders a placeholder with its data/source status.
    """
    if kind not in _IMAGE_KINDS:
        raise HTTPException(400, "kind must be main_image or thumbnail")
    from pathlib import Path as _Path

    from pipeline.core.config import IMAGES_DIR

    conn = _db()
    try:
        base = queries.get_digimon(conn, ident)
        if not base:
            raise HTTPException(404, f"Unknown digimon: {ident}")
        digimon_id = base["id"]
        row = conn.execute(
            """SELECT remote_url, local_path, download_status, content_type
               FROM digimon_image WHERE digimon_id=? AND image_type=?
               ORDER BY id LIMIT 1""",
            [digimon_id, kind],
        ).fetchone()
        if row is None:
            # no image of the requested type — fall back to the main art
            row = conn.execute(
                """SELECT remote_url, local_path, download_status, content_type
                   FROM digimon_image WHERE digimon_id=? AND image_type='main_image'
                   ORDER BY id LIMIT 1""",
                [digimon_id],
            ).fetchone()
            if row is None:
                raise HTTPException(404, "no image for this digimon")
        local = row["local_path"]
        if local:
            path = _Path(local).resolve()
            # only ever serve files inside the local image cache
            cache_root = IMAGES_DIR.resolve()
            if path.is_file() and cache_root in path.parents:
                media = row["content_type"] or "image/png"
                return FileResponse(path, media_type=media)
        if row["remote_url"]:
            # local cache missing (e.g. not yet downloaded) — load the source URL
            return RedirectResponse(row["remote_url"])
        raise HTTPException(404, "image not available")
    finally:
        conn.close()
