"""sync-data: full data pipeline entrypoint.

FETCH -> RAW SNAPSHOT -> PARSE -> NORMALIZE -> ENTITY MATCHING -> MERGE
       -> VALIDATION -> REPORTS -> DATABASE

Fail-safe design (T1):
- Every run writes into a temporary *candidate* SQLite database
  (`<db>.candidate.sqlite`); the live `data/digidex.sqlite` is never modified
  in place.
- The candidate is published to the live DB with a single atomic ``os.replace``
  only after (a) every required source fetched successfully and completely,
  (b) validation reports no errors, and (c) all SQLite connections are closed.
- Any fetch / parse / match / merge / validation failure leaves the live
  database byte-for-byte unchanged and exits non-zero.
- ``--partial-ok`` (running a source subset) builds a partial candidate +
  report but does NOT publish it unless ``--publish-partial`` is given.

Usage:
    uv run python scripts/sync_data.py [--sources dapi,official,wikimon,digimons_net]
                                       [--force] [--skip-validation] [--partial-ok]
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pipeline.core.config import DB_PATH, REPORTS_DIR
from pipeline.core.lock import SyncLockError, sync_lock
from pipeline.core.manifest import build_manifest, manifest_path_for, write_manifest
from pipeline.core.request import Fetcher
from pipeline.core.schema import (
    SCHEMA_VERSION,
    checkpoint_and_close,
    cleanup_db_files,
    cleanup_sidecars,
    connect,
    connect_readonly,
    create_schema,
    verify_integrity,
)
from pipeline.core.sync_state import SyncState
from pipeline.matching.matcher import Matcher
from pipeline.merge.resolver import EvolutionResolver
from pipeline.merge.store import CanonicalStore

logger = logging.getLogger("sync_data")

ALL_SOURCES = ["dapi", "official", "wikimon", "digimons_net", "digidb"]

# Order matters for entity matching: dapi (backbone, en names) -> digimons_net
# (adds ja/zh names) -> official (official en names often use dub forms, so
# they resolve by ja once digimons_net has seeded it) -> wikimon -> digidb.
INGEST_ORDER = ["dapi", "digimons_net", "official", "wikimon", "digidb"]


def make_fetcher(cache_dir: Path | None = None, force: bool = False) -> Fetcher:
    return Fetcher(
        rate_per_second=1.0,
        max_concurrency=2,
        cache_dir=cache_dir,
        force=force,
    )


def load_source(name: str):
    if name == "dapi":
        from pipeline.sources.dapi import DapiAdapter

        return DapiAdapter()
    if name == "official":
        from pipeline.sources.official import OfficialAdapter

        return OfficialAdapter()
    if name == "wikimon":
        from pipeline.sources.wikimon import WikimonAdapter

        return WikimonAdapter()
    if name == "digimons_net":
        from pipeline.sources.digimons_net import DigimonsNetAdapter

        return DigimonsNetAdapter()
    if name == "digidb":
        from pipeline.sources.digidb import DigiDbAdapter

        return DigiDbAdapter()
    raise ValueError(f"unknown source: {name}")


def _resolve_db_path() -> Path:
    """The DB to build/publish. DIGIDEX_DB lets tests target a fixture path."""
    return Path(os.environ.get("DIGIDEX_DB", str(DB_PATH)))


def _load_fan_aliases(conn) -> None:
    """Register curated Chinese fan abbreviations (spec §7 / §35)."""
    import json

    from pipeline.core.config import ROOT

    path = ROOT / "pipeline" / "sources" / "manual_aliases.json"
    if not path.exists():
        return
    data = json.loads(path.read_text("utf-8"))
    by_slug = {r["canonical_slug"]: r["id"] for r in conn.execute("SELECT id, canonical_slug FROM digimon")}
    added = 0
    for item in data.get("aliases", []):
        digimon_id = by_slug.get(item["canonical_slug"])
        if digimon_id is None:
            continue
        cur = conn.execute(
            """INSERT OR IGNORE INTO digimon_alias
               (digimon_id, alias, language, alias_type, source, verified)
               VALUES(?,?,?,?,?,?)""",
            [digimon_id, item["alias"], "zh_cn", "fan_translation", "manual", 0],
        )
        added += cur.rowcount
    if added:
        logger.info("registered %d fan aliases", added)
    conn.commit()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _sha256(path: Path) -> str | None:
    """SHA-256 of a file (None when unreadable/absent) — used by the manifest."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _count_existing(db_path: Path) -> int:
    """Digimon count in the live DB (0 if it does not exist / is unreadable)."""
    if not db_path.exists():
        return 0
    try:
        conn = connect_readonly(db_path)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM digimon").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def _clear_http_cache(cache_dir: Path, parent: Path) -> bool:
    """Delete only the repo-internal HTTP cache under `parent`.

    ``--force`` must never remove an arbitrary/unvalidated path (T1.6): we
    resolve the cache dir and refuse to touch anything outside the data dir.
    """
    if not cache_dir.exists():
        return True
    try:
        resolved = cache_dir.resolve()
        parent_resolved = parent.resolve()
    except OSError:
        logger.error("force: cannot resolve cache path %s; refusing to remove", cache_dir)
        return False
    if not str(resolved).startswith(str(parent_resolved) + os.sep):
        logger.error("force: refusing to remove cache dir outside %s: %s", parent, cache_dir)
        return False
    shutil.rmtree(cache_dir)
    logger.info("force: cleared HTTP cache %s", cache_dir)
    return True


def _records_hash(records: list) -> str:
    """Full normalized-payload hash (T4.2): any field change forces a re-merge."""
    from pipeline.core.models import records_payload_hash

    return records_payload_hash(records)


def _fetch_sources(sources: list[str], fetcher: Fetcher, force: bool,
                   state: SyncState, loader, persist_raw: bool = True,
                   ) -> tuple[dict[str, list], dict[str, Exception], dict[str, dict]]:
    """Fetch each requested source.

    Returns ``(records_by_source, failures, source_stats)``. ``source_stats``
    holds per-source started_at / payload_hash / raw_completeness / parsed /
    failed so a ``source_sync`` row can be written. Any exception (including a
    source that now returns empty after previously yielding data) is a hard
    failure: the caller must abort without publishing.
    """
    records_by_source: dict[str, list] = {}
    failures: dict[str, Exception] = {}
    source_stats: dict[str, dict] = {}
    for name in INGEST_ORDER:
        if name not in sources:
            continue
        logger.info("=== fetching source: %s ===", name)
        started = _now()
        try:
            adapter = loader(name)
            records = adapter.fetch(fetcher, force=force)
            prev = state.previous_records(name)
            if not records and prev > 0:
                raise RuntimeError(
                    f"source {name} returned empty but previously had {prev} records "
                    f"(possible site change / failed pagination)"
                )
            records_by_source[name] = records
            if persist_raw:
                try:
                    from pipeline.sources.base import save_records

                    save_records(name, records)
                except OSError as exc:  # raw retention must not kill the sync
                    logger.warning("could not persist raw records for %s: %s", name, exc)
            source_stats[name] = {
                "started_at": started,
                "payload_hash": _records_hash(records),
                "raw_completeness": True,
                "parsed": len(records),
                "failed": 0,
            }
            logger.info("%s: %d records (hash %s)", name, len(records), source_stats[name]["payload_hash"])
        except Exception as exc:  # noqa: BLE001
            failures[name] = exc
            source_stats[name] = {"started_at": started, "raw_completeness": False,
                                  "parsed": 0, "failed": 1}
            logger.error("source %s failed: %s", name, exc)
    return records_by_source, failures, source_stats


def _load_from_raw(sources: list[str]) -> tuple[dict[str, list], dict[str, Exception], dict[str, dict]]:
    """Rebuild candidate input from persisted raw records (offline, T4.6).

    Uses data/raw/<source>/records.json written by a previous real sync, so a
    candidate can be reproduced without re-visiting the network.
    """
    from pipeline.sources.base import load_records

    records_by_source: dict[str, list] = {}
    failures: dict[str, Exception] = {}
    source_stats: dict[str, dict] = {}
    for name in INGEST_ORDER:
        if name not in sources:
            continue
        records = load_records(name)
        if not records:
            failures[name] = RuntimeError(f"no persisted raw records for '{name}' (run a real sync first)")
            source_stats[name] = {"started_at": None, "raw_completeness": False, "parsed": 0, "failed": 1}
            logger.error("from-raw: no records for %s", name)
            continue
        records_by_source[name] = records
        source_stats[name] = {
            "started_at": None,
            "payload_hash": _records_hash(records),
            "raw_completeness": True,
            "parsed": len(records),
            "failed": 0,
        }
        logger.info("from-raw: %s -> %d records", name, len(records))
    return records_by_source, failures, source_stats


def _write_source_sync(conn: sqlite3.Connection, run_id: str,
                       records_by_source: dict[str, list],
                       source_stats: dict[str, dict],
                       failures: dict[str, Exception],
                       *, partial: bool = False, note: str | None = None,
                       started_at: str | None = None,
                       snapshot_date: str | None = None) -> None:
    """Record every source's real status for this run, preserving history (P1-1).

    source_sync is keyed by (source, run_id), so each run appends new rows
    instead of overwriting — a specific version can be reconstructed and
    audited. A `sync_run` row carries the run-level metadata using the SAME
    run_id and the run's actual started_at / finished_at / snapshot_date
    (S0-1: `sync_run.started_at` must not be empty).
    """
    finished = _now()
    run_status = "failed" if failures else ("partial" if partial else "ok")
    conn.execute(
        """INSERT OR REPLACE INTO sync_run(run_id, started_at, finished_at, status, sources, note, snapshot_date)
           VALUES(?,?,?,?,?,?,?)""",
        [run_id, started_at, finished, run_status,
         ",".join(sorted(set(records_by_source) | set(failures))), note,
         snapshot_date or _now()[:10]],
    )
    for name, records in records_by_source.items():
        st = source_stats.get(name, {})
        digest = st.get("payload_hash") or _records_hash(records)
        conn.execute(
            """INSERT INTO source_sync
               (source, run_id, last_seen_at, started_at, finished_at, status,
                records, parsed_count, failed_count, raw_completeness,
                content_hash, payload_hash, error_summary)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [name, run_id, _now(), st.get("started_at"), finished, "ok",
             len(records), st.get("parsed", len(records)), st.get("failed", 0),
             1 if st.get("raw_completeness", True) else 0, digest, digest, None],
        )
    for name, exc in failures.items():
        st = source_stats.get(name, {})
        conn.execute(
            """INSERT INTO source_sync
               (source, run_id, started_at, finished_at, status,
                records, parsed_count, failed_count, raw_completeness,
                content_hash, payload_hash, error_summary)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            [name, run_id, st.get("started_at"), finished, "failed",
             0, st.get("parsed", 0), st.get("failed", 1), 0, None, None, str(exc)],
        )
    conn.commit()


def _build_db(conn: sqlite3.Connection, records_by_source: dict[str, list],
              sources: list[str], *, partial: bool, run_id: str | None = None,
              source_stats: dict[str, dict] | None = None,
              failures: dict[str, Exception] | None = None,
              started_at: str | None = None) -> str | None:
    """MATCH + MERGE + edges + relations + game stats + snapshot on `conn`.

    `conn` is a candidate database; every destructive step is safe because the
    live DB is never touched. Returns the snapshot_date the run recorded (used
    to keep sync_run / publish manifest consistent with the snapshot row).
    """
    matcher = Matcher()
    order = [s for s in ["dapi", "digimons_net", "official", "wikimon"] if s in records_by_source]
    for name in order:
        for rec in records_by_source[name]:
            matcher.add(rec)
    logger.info("entities: %d (review: %d)", len(matcher.entities), len(matcher.review_queue))

    conn.execute("DELETE FROM digimon")
    conn.commit()
    store = CanonicalStore(conn, run_id=run_id or "?")
    for _slug, entity in matcher.entities.items():
        store.upsert_entity(entity)
    store.commit()
    logger.info("digimon rows written")

    conn.execute("DELETE FROM evolution_edge")
    conn.execute("DELETE FROM digimon_relation")
    conn.commit()
    resolver = EvolutionResolver(conn)
    edge_count = 0
    rel_count = 0
    unknown_edges = 0
    self_edges = 0
    unknown_rels = 0
    for slug, entity in matcher.entities.items():
        edge_stats = resolver.add_edges_for_entity(entity)
        edge_count += edge_stats["edges"]
        if edge_stats["unknown"]:
            unknown_edges += len(edge_stats["unknown"])
            store.queue_review(
                "edge", None, f"unresolved evolution target(s) for {slug}",
                {"canonical_slug": slug,
                 "unresolved": [{"source": s, "source_id": sid, "ref": r}
                                for s, sid, r in edge_stats["unknown"]]},
            )
        if edge_stats["self"]:
            self_edges += len(edge_stats["self"])
            store.queue_review(
                "edge", None, f"self-evolution reference(s) for {slug}",
                {"canonical_slug": slug,
                 "self": [{"source": s, "source_id": sid, "ref": r}
                          for s, sid, r in edge_stats["self"]]},
            )
        rel_stats = resolver.add_relations_for_entity(entity)
        rel_count += rel_stats["relations"]
        if rel_stats["unknown"]:
            unknown_rels += len(rel_stats["unknown"])
            store.queue_review(
                "relation", None, f"unresolved relation target(s) for {slug}",
                {"canonical_slug": slug,
                 "unresolved": [{"source": s, "source_id": sid, "ref": r}
                                for s, sid, r in rel_stats["unknown"]]},
            )
    conn.commit()
    logger.info(
        "evolution edges: %d, relations: %d (unresolved: %d edge + %d relation targets, %d self-edges)",
        edge_count, rel_count, unknown_edges, unknown_rels, self_edges,
    )

    from pipeline.merge.relations import infer_relations

    rel_inferred = infer_relations(conn)
    if rel_inferred:
        logger.info("inferred related-form relations: %d", rel_inferred)

    _load_fan_aliases(conn)

    if "digidb" in records_by_source:
        from pipeline.sources.digidb import import_game_stats

        import_game_stats(conn, records_by_source["digidb"])
        logger.info("game stats imported (game: cyber-sleuth)")

    for item in matcher.review_queue:
        store.queue_review("digimon", None, item["reason"], item)
    # entities created from ambiguous names are never silently confirmed
    for slug, entity in matcher.entities.items():
        if entity.needs_review:
            store.queue_review(
                "digimon", None, entity.review_reason or "needs review",
                {"canonical_slug": slug,
                 "record_sources": [r.source for r in entity.records if r]},
            )
    store.commit()

    store.rebuild_fts()
    notes = f"sources={','.join(sources)}"
    if partial:
        notes += " partial=true"
    snap = store.write_snapshot(notes=notes)
    snap_date = conn.execute(
        "SELECT snapshot_date FROM snapshot ORDER BY id DESC LIMIT 1"
    ).fetchone()["snapshot_date"]
    logger.info("snapshot: %s (date %s)", snap, snap_date)
    conn.commit()

    # per-source sync status is queryable in the candidate (T4.1); history is
    # preserved per (source, run_id) with a sync_run row (P1-1). sync_run uses
    # the run's real started_at and the snapshot's date (S0-1).
    _write_source_sync(conn, run_id or "?", records_by_source, source_stats or {},
                       failures or {}, partial=partial,
                       note=f"build of sources={sources}",
                       started_at=started_at, snapshot_date=snap_date)
    return snap_date


def _preserve_review_history(db_path: Path, conn: sqlite3.Connection) -> None:
    """Carry resolved/wontfix review items from the live DB into the candidate.

    The candidate rebuilds the queue from current data, but human decisions
    (resolved/wontfix) must persist across syncs (they are not regenerated).
    Open items are always regenerated, so only resolved/wontfix are copied.
    """
    if not db_path.exists():
        return
    try:
        old = connect_readonly(db_path)
    except sqlite3.Error:
        return
    try:
        rows = old.execute(
            """SELECT entity_type, entity_id, reason, detail, status, resolved_at
               FROM manual_review_queue
               WHERE status IN ('resolved','wontfix')"""
        ).fetchall()
        copied = 0
        for r in rows:
            cur = conn.execute(
                """INSERT OR IGNORE INTO manual_review_queue
                   (entity_type, entity_id, reason, detail, status, resolved_at)
                   VALUES(?,?,?,?,?,?)""",
                [r["entity_type"], r["entity_id"], r["reason"], r["detail"], r["status"], r["resolved_at"]],
            )
            copied += cur.rowcount
        if copied:
            conn.commit()
            logger.info("preserved %d resolved/wontfix review items", copied)
    finally:
        old.close()


def _preserve_sync_history(db_path: Path, conn: sqlite3.Connection) -> None:
    """Carry previous runs' source_sync/sync_run rows into the candidate (P1-1).

    The candidate is rebuilt from scratch each run, so without this every
    publish would start with an empty source_sync — the per-run history would
    never accumulate. Historical rows are immutable facts and are copied
    verbatim; the current run appends its own rows on top.
    """
    if not db_path.exists():
        return
    try:
        old = connect_readonly(db_path)
    except sqlite3.Error:
        return
    try:
        old_tables = {
            r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        for table, cols in (
            ("source_sync", ["source", "run_id", "source_updated_at", "last_seen_at",
                             "started_at", "finished_at", "status", "records",
                             "parsed_count", "failed_count", "raw_completeness",
                             "content_hash", "payload_hash", "error_summary"]),
            ("sync_run", ["run_id", "started_at", "finished_at", "status",
                          "sources", "note", "snapshot_date"]),
        ):
            if table not in old_tables:
                continue  # an older DB predates this table
            rows = old.execute(f"SELECT {','.join(cols)} FROM {table}").fetchall()
            if not rows:
                continue
            ph = ",".join("?" * len(cols))
            conn.executemany(
                f"INSERT OR IGNORE INTO {table}({','.join(cols)}) VALUES({ph})",
                [tuple(r[c] for c in cols) for r in rows],
            )
        conn.commit()
    finally:
        old.close()


def _publish(candidate: Path, target: Path) -> None:
    """Atomically replace the live DB with the (checkpointed) candidate.

    The caller must have closed every connection to `candidate` first
    (Windows refuses os.replace on open files).
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(candidate, target)
    # main file moved; drop any leftover -wal/-shm/-journal sidecars
    cleanup_db_files(candidate)
    logger.info("published %s (atomic replace)", target)


def _update_state(state: SyncState, records_by_source: dict[str, list],
                  sources: list[str], *, run_id: str | None = None,
                  snapshot_date: str | None = None) -> None:
    """Record per-source hashes/counts ONLY after a successful publish.

    The stored hash covers the full normalized payload, so "unchanged" can only
    mean the source content is genuinely identical (T4.2 / T4.3). Also records
    which run / snapshot produced this state so a future reconcile can confirm
    the state corresponds to the DB's latest run (S0-1).
    """
    for name, records in records_by_source.items():
        digest = _records_hash(records)
        state.set(name, content_hash=digest, payload_hash=digest,
                  last_seen_at=_now(), records=len(records))
    state.set("sync_data", sources=sources, run_id=run_id, snapshot_date=snapshot_date)


def _write_validation_report(db_path: Path, reports_dir: Path | None, skip: bool) -> dict | None:
    """Run validation on `db_path`, writing reports; return the report or None."""
    if skip:
        logger.info("validation skipped (--skip-validation)")
        return None
    from pipeline.validation.validator import run_and_write

    report = run_and_write(db_path, reports_dir=reports_dir)
    ic = report["issue_counts"]
    logger.info(
        "validation: %d errors, %d warnings, %d info",
        ic["error"], ic["warning"], ic["info"],
    )
    logger.info("reports -> %s", "data/reports/data-quality.{json,md}")
    return report


def run(argv: list[str] | None = None, *, loader=None, reports_dir: Path | None = None) -> int:
    """Full sync entrypoint. `loader` is injectable for tests (defaults to
    the real `load_source`); `reports_dir` overrides where reports are written."""
    ap = argparse.ArgumentParser(description="DigiDex data sync pipeline")
    ap.add_argument(
        "--sources",
        default="dapi,official,digimons_net",
        help="comma-separated sources (default: dapi,official,digimons_net)",
    )
    ap.add_argument("--force", action="store_true", help="clear the HTTP cache and re-fetch")
    ap.add_argument("--skip-validation", action="store_true")
    ap.add_argument("--partial-ok", action="store_true",
                    help="allow a source subset against an already-populated database "
                         "(builds a partial candidate; does NOT publish unless --publish-partial)")
    ap.add_argument("--publish-partial", action="store_true",
                    help="explicitly publish a partial (source-subset) candidate, "
                         "marking the snapshot as partial")
    ap.add_argument("--images", action="store_true", help="also download images after sync")
    ap.add_argument("--from-raw", action="store_true",
                    help="rebuild from persisted data/raw/<source>/records.json (offline, no network)")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    missing = [s for s in sources if s not in ALL_SOURCES]
    if missing:
        logger.error("unknown sources: %s", missing)
        return 1

    db_path = _resolve_db_path()
    candidate = db_path.with_name(db_path.stem + ".candidate.sqlite")
    cache_dir = db_path.parent / ".http_cache"
    state = SyncState(db_path.parent / ".sync_state.json")

    # --force: remove the repo-internal HTTP cache (validated path only).
    if args.force and not _clear_http_cache(cache_dir, db_path.parent):
        return 1

    started_at = _now()  # run-level start (sync_run.started_at, S0-1)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f") + f"-{os.getpid():x}"
    # only persist raw snapshots for the real loader (tests inject fake adapters)
    persist_raw = loader is None
    try:
        with sync_lock(db_path.parent / ".sync.lock"):
            return _run_locked(args, sources, db_path, candidate, cache_dir,
                               state, loader or load_source, reports_dir or REPORTS_DIR,
                               run_id, persist_raw, started_at)
    except SyncLockError as exc:
        logger.error("%s", exc)
        return 1


def _backfill_manifest(db_path: Path, state: SyncState, reports_dir: Path,
                       sources: list[str]) -> None:
    """Write a publish manifest for an already-current database that predates
    the manifest system (S0-1).

    Runs on the incremental no-op path so a DB published before manifests
    existed still has a durable publish record, which backup/restore rely on.
    No-op: skips when a manifest already exists.
    """
    from pipeline.core.manifest import manifest_path_for, read_manifest, write_manifest

    mpath = manifest_path_for(db_path)
    if read_manifest(mpath) is not None:
        return
    run_id = state.get("sync_data").get("run_id")
    snap_date = state.get("sync_data").get("snapshot_date")
    if not snap_date:
        try:
            conn = connect_readonly(db_path)
            try:
                row = conn.execute(
                    "SELECT snapshot_date FROM snapshot ORDER BY id DESC LIMIT 1"
                ).fetchone()
                snap_date = row["snapshot_date"] if row else _now()[:10]
            finally:
                conn.close()
        except sqlite3.Error:
            snap_date = _now()[:10]
    manifest = build_manifest(
        run_id=run_id or f"backfill-{_now()}",
        snapshot_date=snap_date,
        sources=sources or state.get("sync_data").get("sources", []),
        db_sha256=_sha256(db_path),
        report_sha256=_sha256(reports_dir / "data-quality.json"),
        schema_version=SCHEMA_VERSION,
        image_stage="unknown",
        is_incremental_baseline=True,
        state_committed=True,
        notes="backfilled (database predates manifest system)",
    )
    try:
        write_manifest(manifest, mpath)
        logger.info("backfilled publish manifest at %s", mpath)
    except OSError as exc:
        logger.warning("could not backfill publish manifest: %s", exc)


def _mark_state_committed(db_path: Path, state: SyncState) -> bool:
    """Flip a prior publish manifest's state_committed to true after recovery.

    When a run reconciles state from the database (healing a "database published
    but state not committed" split), the split-recognition record in the
    manifest must be updated so the next run no longer sees a false split. Only
    touches the manifest when its run_id matches the run the state was
    reconciled from (S0-1).
    """
    from pipeline.core.manifest import manifest_path_for, read_manifest, write_manifest

    mpath = manifest_path_for(db_path)
    manifest = read_manifest(mpath)
    run_id = state.get("sync_data").get("run_id")
    if not manifest or not run_id or manifest.get("run_id") != run_id:
        return False
    if manifest.get("state_committed"):
        return True
    manifest["state_committed"] = True
    try:
        write_manifest(manifest, mpath)
    except OSError as exc:
        logger.warning("could not mark manifest state_committed after recovery: %s", exc)
        return False
    return True


def _run_locked(args, sources: list[str], db_path: Path, candidate: Path,
                cache_dir: Path, state: SyncState, loader, reports_dir: Path,
                run_id: str, persist_raw: bool, started_at: str) -> int:
    # --- guard: running a source subset that EXCLUDES a previously-ingested
    # source would wipe that source's derived rows from the published DB.
    existing = _count_existing(db_path)
    # Recovery from "database published but state not committed" (S0-1): the
    # live DB has a real snapshot but .sync_state.json knows no source set, so
    # rebuild the incremental markers from the DB's latest successful run and
    # persist them. This is what makes a publish whose state save failed (or a
    # killed process between publish and state save) recoverable on the next run.
    if existing > 0 and not state.get("sync_data").get("sources"):
        if state.reconcile_from_db(db_path):
            try:
                state.save()
            except OSError as exc:
                logger.warning("reconciled sync state could not be persisted: %s", exc)
            if _mark_state_committed(db_path, state):
                logger.info("marked prior publish manifest as state_committed=true")
            logger.info(
                "reconciled sync state from database (previous publish may not "
                "have committed .sync_state.json)"
            )
    prev_sources = state.get("sync_data").get("sources", [])
    dropped = [s for s in prev_sources if s not in sources]
    added = [s for s in sources if s not in prev_sources]
    if existing > 0 and (added or dropped):
        # source-set change detection (P1-1): added AND removed sources are
        # both identified. Adding is safe (additive); dropping is refused
        # unless the user explicitly builds a partial candidate.
        if added:
            logger.info("source set change: adding %s (previous run used %s)", added, prev_sources)
        if dropped and not args.partial_ok:
            logger.error(
                "Database has %d digimon and was last synced with sources %s; "
                "this run drops %s, which would wipe their derived data. "
                "Re-run including them, or pass --partial-ok to build a partial "
                "candidate (still not published without --publish-partial).",
                existing, prev_sources, dropped,
            )
            return 1
        if dropped:
            logger.warning("source set change: dropping %s — building a partial candidate", dropped)

    cleanup_db_files(candidate)  # remove any stale candidate from a prior run
    conn: sqlite3.Connection | None = None
    fetcher: Fetcher | None = None
    keep_candidate = False
    try:
        conn = connect(candidate)
        create_schema(conn)
        if args.from_raw:
            records_by_source, failures, source_stats = _load_from_raw(sources)
        else:
            fetcher = make_fetcher(cache_dir=cache_dir, force=args.force)
            records_by_source, failures, source_stats = _fetch_sources(
                sources, fetcher, args.force, state, loader, persist_raw=persist_raw
            )

        if failures:
            # Hard failure: never publish. Build a best-effort inspection
            # candidate + report from whatever fetched, then exit non-zero.
            logger.error("required source(s) failed: %s", ", ".join(failures))
            if records_by_source:
                try:
                    _build_db(conn, records_by_source, sources, partial=True,
                              run_id=run_id, source_stats=source_stats,
                              failures=failures, started_at=started_at)
                    _write_validation_report(candidate, reports_dir, args.skip_validation)
                except Exception as exc:  # noqa: BLE001
                    logger.error("could not build inspection candidate: %r", exc)
            logger.error("sync FAILED; official database unchanged")
            return 1

        # Incremental no-op (T4.3): when every requested source is unchanged AND
        # the live DB already has data, there is nothing to rebuild — skip the
        # expensive merge and leave the DB untouched. Only reported when the
        # source fetch was complete and the full payload hash matches.
        partial = bool(existing > 0 and dropped)
        if existing > 0 and not partial and not args.force:
            all_unchanged = True
            for name, records in records_by_source.items():
                if state.get(name).get("content_hash") != _records_hash(records):
                    all_unchanged = False
                    break
            if all_unchanged:
                logger.info(
                    "all sources unchanged since the last successful sync; "
                    "incremental no-op (database already current)"
                )
                _backfill_manifest(db_path, state, reports_dir, sources)
                return 0

        snap_date = _build_db(conn, records_by_source, sources, partial=partial,
                              run_id=run_id, source_stats=source_stats,
                              failures=failures, started_at=started_at)

        # candidate validation is a publication gate (T1.4 / T2.10 / P0-2).
        # --skip-validation is a diagnosis/dev flag only: it must never let an
        # unvalidated candidate pass the publish gate, so the candidate is kept
        # for inspection but the live DB is left untouched and we exit non-zero.
        if args.skip_validation:
            checkpoint_and_close(conn)
            conn = None
            cleanup_sidecars(candidate)
            keep_candidate = True
            logger.error(
                "validation skipped (--skip-validation): candidate built at %s "
                "for inspection but NOT published — an unvalidated database must "
                "not be marked publishable. Live DB unchanged.",
                candidate,
            )
            return 1

        report = _write_validation_report(candidate, reports_dir, skip=False)
        if report["issue_counts"]["error"]:
            logger.error(
                "validation: %d errors; candidate NOT published (live DB unchanged)",
                report["issue_counts"]["error"],
            )
            return 1

        # preserve resolved/wontfix review history into the candidate first
        _preserve_review_history(db_path, conn)
        # preserve previous runs' source_sync/sync_run history (P1-1)
        _preserve_sync_history(db_path, conn)

        # Partial (source-subset) run: build + report but do NOT publish by
        # default. Publishing a partial snapshot requires an explicit override.
        if partial and not args.publish_partial:
            checkpoint_and_close(conn)
            conn = None
            cleanup_sidecars(candidate)
            keep_candidate = True
            logger.info(
                "partial candidate built at %s; NOT published. "
                "Re-run with --publish-partial to publish a partial snapshot.",
                candidate,
            )
            return 0

        # Publish: checkpoint WAL into the main file, close all connections,
        # then atomically replace the live DB. A failed checkpoint means the
        # candidate file may silently lack WAL content — never publish it (P1-1).
        if not checkpoint_and_close(conn):
            logger.error(
                "WAL checkpoint failed; candidate NOT published (live DB unchanged)"
            )
            conn = None
            return 1
        conn = None

        # Candidate corruption guard: the candidate must be a self-consistent
        # SQLite file before it replaces the live DB (S0-1).
        if not verify_integrity(candidate):
            logger.error(
                "candidate integrity check failed; NOT published (live DB unchanged)"
            )
            cleanup_db_files(candidate)
            return 1

        _publish(candidate, db_path)
        db_sha = _sha256(db_path)
        report_path = reports_dir / "data-quality.json"
        report_sha = _sha256(report_path) if report_path.exists() else None
        manifest_path = manifest_path_for(db_path)

        # Durable publish manifest (S0-1): written BEFORE the state file is
        # updated with state_committed=false, then rewritten to true only after
        # .sync_state.json is durably saved. If the process dies between publish
        # and state save (or state.save() fails), the next run recognizes the
        # split via state_committed=false and reconciles state from the DB.
        manifest = build_manifest(
            run_id=run_id,
            snapshot_date=snap_date,
            sources=sources,
            db_sha256=db_sha,
            report_sha256=report_sha,
            schema_version=SCHEMA_VERSION,
            image_stage="pending" if args.images else "skipped",
            is_incremental_baseline=False,
            state_committed=False,
            notes="partial" if partial else None,
        )
        try:
            write_manifest(manifest, manifest_path)
        except OSError as exc:
            logger.error(
                "database published but publish manifest could not be written (%s); "
                "next sync will reconcile state from the database", exc,
            )
            return 1

        # state.save() failing after a successful publish is the "database
        # published but state not committed" split — it must not be a silent
        # success, and it must leave a recognizable recovery path (S0-1).
        _update_state(state, records_by_source, sources,
                      run_id=run_id, snapshot_date=snap_date)
        try:
            state.save()
        except OSError as exc:
            logger.error(
                "DATABASE PUBLISHED but sync state could not be committed: %s", exc
            )
            logger.error(
                "publish manifest at %s records state_committed=false; recovery: "
                "re-run sync_data.py (it reconciles state from the database), or "
                "confirm the DB is the one you want and delete %s",
                manifest_path, state.path,
            )
            return 1
        manifest["state_committed"] = True
        manifest["is_incremental_baseline"] = not partial
        try:
            write_manifest(manifest, manifest_path)
        except OSError as exc:
            # DB + state are committed; only the manifest finalization failed.
            logger.warning("could not finalize publish manifest: %s", exc)
        logger.info("snapshot published to %s", db_path)

        # optional images (only after a successful publish). The DB is already
        # published (valid canonical data); an image-stage failure is reported
        # and the run exits non-zero so the incomplete image cache is never
        # mistaken for a fully-clean sync (P1-1). The manifest's image_stage
        # distinguishes canonical-DB success from image-cache failure (S0-1).
        if args.images:
            from scripts.download_images import backfill_metadata, download_all, ensure_thumbnails

            done, refused, failed = download_all(db_path)
            conn = connect(db_path)
            try:
                backfill_metadata(conn)
                derived, thumb_failed = ensure_thumbnails(conn, force=args.force)
            finally:
                conn.close()
            logger.info("image stage: %d images, %d thumbnails derived, %d refused by policy",
                        done, derived, refused)
            manifest["image_stage"] = "ok" if not (failed or thumb_failed) else "failed"
            try:
                write_manifest(manifest, manifest_path)
            except OSError as exc:
                logger.warning("could not record image stage in manifest: %s", exc)
            if failed or thumb_failed:
                # audit trail distinguishes a published canonical DB from an
                # incomplete image cache (S0-1).
                try:
                    run_conn = connect(db_path)
                    try:
                        run_conn.execute(
                            "UPDATE sync_run SET note = COALESCE(note,'') || '; image stage failed' "
                            "WHERE run_id = ?", [run_id],
                        )
                        run_conn.commit()
                    finally:
                        run_conn.close()
                except sqlite3.Error:
                    pass
                logger.error(
                    "image stage had %d download / %d thumbnail failures; DB published "
                    "but image cache incomplete — re-run scripts/download_images.py",
                    failed, thumb_failed,
                )
                return 1
        return 0
    except KeyboardInterrupt:
        logger.error("interrupted; official database unchanged")
        return 130
    except Exception as exc:  # noqa: BLE001
        logger.error("sync FAILED; official database unchanged: %r", exc)
        return 1
    finally:
        if fetcher is not None:
            fetcher.close()
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        if not keep_candidate:
            cleanup_db_files(candidate)


# console-script alias: `sync-data` (see pyproject.toml [project.scripts])
main = run

if __name__ == "__main__":
    raise SystemExit(run())
