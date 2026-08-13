"""sync-data: full data pipeline entrypoint.

FETCH -> RAW SNAPSHOT -> PARSE -> NORMALIZE -> ENTITY MATCHING -> MERGE
       -> VALIDATION -> REPORTS -> DATABASE

Usage:
    uv run python scripts/sync_data.py [--sources dapi,official,wikimon,digimons_net]
                                       [--force] [--skip-validation]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure the repo root is importable regardless of cwd.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.core.config import DB_PATH
from pipeline.core.request import Fetcher
from pipeline.core.schema import connect, create_schema
from pipeline.core.sync_state import SyncState
from pipeline.matching.matcher import Matcher
from pipeline.merge.resolver import EvolutionResolver
from pipeline.merge.store import CanonicalStore

logger = logging.getLogger("sync_data")

ALL_SOURCES = ["dapi", "official", "wikimon", "digimons_net", "digidb"]


def make_fetcher(cache_dir: Path | None = None) -> Fetcher:
    return Fetcher(
        rate_per_second=1.0,
        max_concurrency=2,
        cache_dir=cache_dir,
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="DigiDex data sync pipeline")
    ap.add_argument(
        "--sources",
        default="dapi,official,digimons_net",
        help="comma-separated sources (default: dapi,official,digimons_net)",
    )
    ap.add_argument("--force", action="store_true", help="bypass HTTP cache, re-fetch")
    ap.add_argument("--skip-validation", action="store_true")
    ap.add_argument("--partial-ok", action="store_true",
                    help="allow a source subset against an already-populated database")
    ap.add_argument("--images", action="store_true", help="also download images after sync")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    missing = [s for s in sources if s not in ALL_SOURCES]
    if missing:
        logger.error("unknown sources: %s", missing)
        return 1

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # --force: ignore the HTTP cache entirely (fetch fresh from sources)
    if args.force:
        cache_dir = DB_PATH.parent / ".http_cache"
        if cache_dir.exists():
            import shutil

            shutil.rmtree(cache_dir)
            logger.info("force: cleared HTTP cache %s", cache_dir)
    conn = connect(DB_PATH)
    create_schema(conn)
    # conflicts are regenerated from scratch each run (data_conflict)
    conn.execute("DELETE FROM data_conflict")
    conn.commit()
    state = SyncState()
    try:
        # Guard: running a source subset that EXCLUDES a previously-ingested
        # source silently wipes that source's derived rows (groups/skills/
        # aliases/images) for re-written entities. Refuse unless --partial-ok.
        existing = conn.execute("SELECT COUNT(*) FROM digimon").fetchone()[0]
        prev_sources = state.get("sync_data").get("sources", [])
        dropped = [s for s in prev_sources if s not in sources]
        if existing > 0 and dropped and not args.partial_ok:
            logger.error(
                "Database has %d digimon and was last synced with sources %s; "
                "this run drops %s, which would wipe their derived data. "
                "Re-run including them, or pass --partial-ok to override.",
                existing, prev_sources, dropped,
            )
            return 1
        fetcher = make_fetcher(cache_dir=DB_PATH.parent / ".http_cache")

        matcher = Matcher()
        # 1. fetch all records. Ingest order matters for entity matching:
        #    dapi (backbone, en names) -> digimons_net (adds ja/zh names, so the
        #    dapi entities can be matched by ja/zh later) -> official (official
        #    en names often use dub forms like "Omnimon"/"Gatomon", so they are
        #    resolved by their ja name once digimons_net has seeded it)
        #    -> wikimon -> digidb.
        records_by_source: dict[str, list] = {}
        for name in ["dapi", "digimons_net", "official", "wikimon", "digidb"]:
            if name not in sources:
                continue
            logger.info("=== fetching source: %s ===", name)
            try:
                adapter = load_source(name)
                records = adapter.fetch(fetcher, force=args.force)
                logger.info("%s: %d records", name, len(records))
                records_by_source[name] = records
            except ImportError as exc:
                logger.warning("source %s not implemented yet: %s", name, exc)
            except Exception as exc:  # noqa: BLE001
                logger.error("source %s failed: %s", name, exc)

        # 2. entity matching (same order as ingestion)
        order = [s for s in ["dapi", "digimons_net", "official", "wikimon", "digidb"] if s in records_by_source]
        for name in order:
            for rec in records_by_source[name]:
                matcher.add(rec)
        logger.info("entities: %d (review: %d)", len(matcher.entities), len(matcher.review_queue))

        # 3. merge entities -> DB
        store = CanonicalStore(conn)
        for slug, entity in matcher.entities.items():
            store.upsert_entity(entity)
        store.commit()
        logger.info("digimon rows written")

        # 4. resolve evolution edges + relations
        resolver = EvolutionResolver(conn)
        edge_count = 0
        rel_count = 0
        for slug, entity in matcher.entities.items():
            edge_count += resolver.add_edges_for_entity(entity)
            rel_count += resolver.add_relations_for_entity(entity)
        conn.commit()
        logger.info("evolution edges: %d, relations: %d", edge_count, rel_count)

        # 5. write review queue + conflicts
        for item in matcher.review_queue:
            store.queue_review("digimon", None, item["reason"], item)
        store.commit()

        # 6. finalize
        store.rebuild_fts()
        snap = store.write_snapshot(notes=f"sources={args.sources}")
        logger.info("snapshot: %s", snap)
        state.set("sync_data", sources=sources)
        state.save()
        fetcher.close()

        # 7. validation
        if not args.skip_validation:
            from pipeline.validation.validator import run_and_write

            report = run_and_write(DB_PATH)
            ic = report["issue_counts"]
            logger.info(
                "validation: %d errors, %d warnings, %d info",
                ic["error"], ic["warning"], ic["info"],
            )
            logger.info("reports -> %s", "data/reports/data-quality.{json,md}")

        # 8. optional images
        if args.images:
            from scripts.download_images import download_all

            download_all(DB_PATH)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
