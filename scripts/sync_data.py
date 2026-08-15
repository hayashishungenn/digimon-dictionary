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
import logging
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pipeline.core.config import DB_PATH, REPORTS_DIR
from pipeline.core.lock import SyncLockError, sync_lock
from pipeline.core.request import Fetcher
from pipeline.core.schema import (
    checkpoint_and_close,
    cleanup_db_files,
    cleanup_sidecars,
    connect,
    connect_readonly,
    create_schema,
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
                       failures: dict[str, Exception]) -> None:
    """Record every source's real status for this run in the `source_sync` table."""
    finished = _now()
    for name, records in records_by_source.items():
        st = source_stats.get(name, {})
        digest = st.get("payload_hash") or _records_hash(records)
        conn.execute(
            """INSERT OR REPLACE INTO source_sync
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
            """INSERT OR REPLACE INTO source_sync
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
              failures: dict[str, Exception] | None = None) -> None:
    """MATCH + MERGE + edges + relations + game stats + snapshot on `conn`.

    `conn` is a candidate database; every destructive step is safe because the
    live DB is never touched.
    """
    matcher = Matcher()
    order = [s for s in ["dapi", "digimons_net", "official", "wikimon"] if s in records_by_source]
    for name in order:
        for rec in records_by_source[name]:
            matcher.add(rec)
    logger.info("entities: %d (review: %d)", len(matcher.entities), len(matcher.review_queue))

    conn.execute("DELETE FROM digimon")
    conn.commit()
    store = CanonicalStore(conn)
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
    logger.info("snapshot: %s", snap)
    conn.commit()

    # per-source sync status is queryable in the candidate (T4.1)
    _write_source_sync(conn, run_id or "?", records_by_source, source_stats or {}, failures or {})


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
                  sources: list[str]) -> None:
    """Record per-source hashes/counts ONLY after a successful publish.

    The stored hash covers the full normalized payload, so "unchanged" can only
    mean the source content is genuinely identical (T4.2 / T4.3).
    """
    for name, records in records_by_source.items():
        digest = _records_hash(records)
        state.set(name, content_hash=digest, payload_hash=digest,
                  last_seen_at=_now(), records=len(records))
    state.set("sync_data", sources=sources)


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

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"-{os.getpid():x}"
    # only persist raw snapshots for the real loader (tests inject fake adapters)
    persist_raw = loader is None
    try:
        with sync_lock(db_path.parent / ".sync.lock"):
            return _run_locked(args, sources, db_path, candidate, cache_dir,
                               state, loader or load_source, reports_dir or REPORTS_DIR,
                               run_id, persist_raw)
    except SyncLockError as exc:
        logger.error("%s", exc)
        return 1


def _run_locked(args, sources: list[str], db_path: Path, candidate: Path,
                cache_dir: Path, state: SyncState, loader, reports_dir: Path,
                run_id: str, persist_raw: bool) -> int:
    # --- guard: running a source subset that EXCLUDES a previously-ingested
    # source would wipe that source's derived rows from the published DB.
    existing = _count_existing(db_path)
    prev_sources = state.get("sync_data").get("sources", [])
    dropped = [s for s in prev_sources if s not in sources]
    if existing > 0 and dropped and not args.partial_ok:
        logger.error(
            "Database has %d digimon and was last synced with sources %s; "
            "this run drops %s, which would wipe their derived data. "
            "Re-run including them, or pass --partial-ok to build a partial "
            "candidate (still not published without --publish-partial).",
            existing, prev_sources, dropped,
        )
        return 1

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
                              run_id=run_id, source_stats=source_stats, failures=failures)
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
                return 0

        _build_db(conn, records_by_source, sources, partial=partial,
                  run_id=run_id, source_stats=source_stats, failures=failures)

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
        # then atomically replace the live DB.
        checkpoint_and_close(conn)
        conn = None
        _publish(candidate, db_path)

        _update_state(state, records_by_source, sources)
        state.save()
        logger.info("snapshot published to %s", db_path)

        # optional images (only after a successful publish)
        if args.images:
            from scripts.download_images import download_all

            download_all(db_path)
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
