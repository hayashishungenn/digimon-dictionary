"""migrate-image-paths: rewrite image paths to the cache-root-relative contract.

P0-1: ``digimon_image.local_path`` and ``digimon.thumbnail`` must hold ONLY
cache-root-relative paths (e.g. ``digi_00001_ab12cd34.png``,
``thumbs/digi_00001.png``) or NULL — never absolute checkout paths.

This migration:
- verifies DB integrity first and creates a full backup (DB + image cache)
  before touching anything (there is NO --no-backup escape hatch);
- relocates legacy ``<...>/data/images/<file>`` absolute paths BY FILENAME
  against the resolved cache root, renaming main files to the canonical
  hash-based name ``digi_<id>_<sha8>.<ext>``;
- never marks a non-existent file downloaded and never touches ``remote_url``;
- backfills thumbnail metadata from the existing ``thumbs/digi_<id>.png``
  cache (no network, no re-derivation) and ``digimon.thumbnail``;
- is idempotent (a second run is a no-op).

Usage:
    uv run python scripts/migrate_image_paths.py [--db PATH] [--dry-run]
console script: migrate-image-paths
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

from pipeline.core.backup import create_backup
from pipeline.core.config import DB_PATH
from pipeline.core.images import (
    image_cache_root,
    is_bad_stored_path,
    is_within,
    main_rel,
    rebase_legacy,
)
from pipeline.core.lock import db_lock_path, sync_lock
from pipeline.core.manifest import manifest_path_for, read_manifest, write_manifest
from pipeline.core.schema import checkpoint_and_close, connect, create_schema, verify_integrity

logger = logging.getLogger("migrate-image-paths")

FAIL_MISSING = "local file missing after path migration"
FAIL_UNLOCATABLE = "unlocatable path"


def _restamp_hashes(db_path: Path) -> None:
    """Refresh manifest + report hashes after the migration changed the DB
    bytes (self-contained; P0-2 moves this to manifest.stamp_db_hash). Best
    effort — a failure only warns so a successful migration is not aborted."""
    manifest_path = manifest_path_for(db_path)
    manifest = read_manifest(manifest_path)
    if manifest is None:
        return
    db_sha = hashlib.sha256(db_path.read_bytes()).hexdigest()
    report_json = db_path.parent / "reports" / "data-quality.json"
    try:
        if report_json.exists():
            report = json.loads(report_json.read_text("utf-8"))
            report["db_sha256"] = db_sha
            tmp = report_json.with_name(report_json.name + ".tmp")
            tmp.write_text(json.dumps(report, indent=2, ensure_ascii=False), "utf-8")
            os.replace(tmp, report_json)
            manifest["report_sha256"] = hashlib.sha256(report_json.read_bytes()).hexdigest()
        manifest["database_sha256"] = db_sha
        write_manifest(manifest, manifest_path)
    except OSError as exc:
        logger.warning("could not refresh manifest/report hashes after migration: %s", exc)


def _canonical_name(digimon_id: int, remote_url: str | None, current_rel: str) -> str:
    """The on-disk canonical (hash-based) cache-root-relative name for a main
    image, fallbacking to the current relative name when no URL is available."""
    return main_rel(digimon_id, remote_url or current_rel)


def was_absolute(stored: str) -> bool:
    """True when the stored value itself violates the relative contract."""
    return bool(is_bad_stored_path(stored))


def _run(db_path: Path, *, dry_run: bool = False, backup_dir: Path | None = None) -> int:
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}", file=sys.stderr)
        return 1

    # fold WAL so the later backup copy is complete and the DB is self-contained
    conn = connect(db_path)
    try:
        create_schema(conn)  # no-op at v8; migrates an older DB safely
    finally:
        conn.close()
    if not checkpoint_and_close(connect(db_path)):
        print("ERROR: could not checkpoint the database before migration", file=sys.stderr)
        return 1
    if not verify_integrity(db_path):
        print("ERROR: database failed PRAGMA integrity_check; refusing to migrate", file=sys.stderr)
        return 1

    cache_root = image_cache_root(db_path)

    created_backup: Path | None = None
    if not dry_run:
        try:
            created_backup = create_backup(db_path=db_path, with_images=True,
                                           images_dir=cache_root, out_dir=backup_dir)
            print(f"backed up to: {created_backup}")
        except Exception as exc:  # noqa: BLE001  (any BackupError/implicit IO)
            print(f"ERROR: backup failed — not migrating: {exc}", file=sys.stderr)
            return 1

    stats = {
        "migrated": 0, "renamed_files": 0, "already_relative_ok": 0,
        "missing_relative": 0, "missing": 0, "unlocatable": 0, "touched": 0,
    }

    try:
        with sync_lock(db_lock_path(db_path)):
            if dry_run:
                conn = connect(db_path)
            else:
                conn = connect(db_path)
            try:
                rows = conn.execute(
                    """SELECT id, digimon_id, image_type, remote_url, local_path, download_status
                       FROM digimon_image ORDER BY id"""
                ).fetchall()
                for row in rows:
                    row_id, digimon_id, image_type = row["id"], row["digimon_id"], row["image_type"]
                    remote_url, stored = row["remote_url"], row["local_path"]
                    if not stored:
                        continue  # already NULL — untouched

                    rel = rebase_legacy(stored)
                    if rel is None or is_bad_stored_path(rel):
                        stats["unlocatable"] += 1
                        if not dry_run:
                            conn.execute(
                                "UPDATE digimon_image SET local_path=NULL, download_status='failed', "
                                "failure_reason=? WHERE id=?",
                                [FAIL_UNLOCATABLE, row_id],
                            )
                        continue

                    candidate = cache_root / rel
                    if not is_within(cache_root, candidate):
                        stats["unlocatable"] += 1
                        if not dry_run:
                            conn.execute(
                                "UPDATE digimon_image SET local_path=NULL, download_status='failed', "
                                "failure_reason=? WHERE id=?",
                                [FAIL_UNLOCATABLE, row_id],
                            )
                        continue

                    file_exists = candidate.is_file()
                    abs_was = was_absolute(stored)
                    if image_type == "main_image":
                        if file_exists:
                            new_rel = _canonical_name(digimon_id, remote_url, rel)
                            if new_rel != rel and (cache_root / new_rel).exists():
                                new_rel = rel  # collision — keep the existing file name
                            if new_rel != rel:
                                stats["renamed_files"] += 1
                                if not dry_run:
                                    os.replace(candidate, cache_root / new_rel)
                            if abs_was:
                                stats["migrated"] += 1
                            else:
                                stats["already_relative_ok"] += 1
                            if not dry_run:
                                conn.execute(
                                    "UPDATE digimon_image SET local_path=?, download_status='downloaded', "
                                    "failure_reason=NULL WHERE id=?",
                                    [new_rel, row_id],
                                )
                        else:
                            if abs_was:
                                stats["missing"] += 1
                            else:
                                stats["missing_relative"] += 1
                            if not dry_run:
                                conn.execute(
                                    "UPDATE digimon_image SET local_path=NULL, download_status='failed', "
                                    "failure_reason=? WHERE id=?",
                                    [FAIL_MISSING, row_id],
                                )
                    else:
                        # thumbnail rows: normalize to relative; never 'downloaded'
                        # when the local file is gone.
                        new_rel = to_posix(rel)
                        if file_exists:
                            if abs_was:
                                stats["migrated"] += 1
                            else:
                                stats["already_relative_ok"] += 1
                            if not dry_run:
                                conn.execute(
                                    "UPDATE digimon_image SET local_path=?, download_status='downloaded', "
                                    "failure_reason=NULL WHERE id=?",
                                    [new_rel, row_id],
                                )
                        else:
                            stats["missing_relative" if not abs_was else "missing"] += 1
                            if not dry_run:
                                conn.execute(
                                    "UPDATE digimon_image SET local_path=NULL, download_status='failed', "
                                    "failure_reason=? WHERE id=?",
                                    [FAIL_MISSING, row_id],
                                )
                    stats["touched"] += 1
            finally:
                if not dry_run:
                    conn.commit()
                conn.close()

            if not dry_run:
                # thumbnail metadata + digimon.thumbnail from the existing
                # thumbs/ cache (no network; existing files are reused).
                from scripts.download_images import backfill_metadata, ensure_thumbnails

                conn = connect(db_path)
                try:
                    derived, thumb_failed = ensure_thumbnails(conn, cache_root=cache_root)
                    enriched = backfill_metadata(conn, cache_root=cache_root)
                finally:
                    conn.close()
                if not checkpoint_and_close(connect(db_path)):
                    print("WARNING: final WAL checkpoint failed; hashes may be stale", file=sys.stderr)
                stats["thumbnails_created"] = derived
                stats["thumbnail_failures"] = thumb_failed
                stats["metadata_enriched"] = enriched
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: migration write phase failed: {exc}", file=sys.stderr)
        return 1

    # post-migration verification + report
    remaining_bad = _count_bad_paths(db_path)
    print("\nmigrate-image-paths report")
    print(f"  digimon_image rows touched        : {stats['touched']}")
    print(f"  migrated (abs -> relative)        : {stats['migrated']}")
    print(f"  renamed to hash filename          : {stats['renamed_files']}")
    print(f"  already-relative, file present    : {stats['already_relative_ok']}")
    print(f"  missing file  -> failed           : {stats['missing']}")
    print(f"  missing relative file -> failed   : {stats['missing_relative']}")
    print(f"  unlocatable    -> failed          : {stats['unlocatable']}")
    if not dry_run:
        print(f"  thumbnail rows created/updated    : {stats.get('thumbnails_created', 0)}")
        print(f"  thumbnail failures               : {stats.get('thumbnail_failures', 0)}")
        print(f"  main-image metadata enriched     : {stats.get('metadata_enriched', 0)}")
    print(f"  forbidden paths remaining         : {remaining_bad}")
    if created_backup is not None:
        print(f"  backed up at                      : {created_backup}")
    if dry_run:
        print("\nDRY RUN — no files or database changed; backup skipped.")
        return 0

    failed_rows = _count_failed_rows(db_path)
    if failed_rows:
        print(f"\nWARNING: {failed_rows} rows marked failed — "
              "re-run scripts/download_images.py to retry.")
    if remaining_bad:
        print(f"\nERROR: {remaining_bad} forbidden (absolute/..) paths remain.", file=sys.stderr)
        return 1
    if not dry_run:
        _restamp_hashes(db_path)
    print("\nmigration complete.")
    return 0


def to_posix(rel: str) -> str:
    return rel.replace("\\", "/")


def _count_bad_paths(db_path: Path) -> int:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        bad = 0
        for (p,) in con.execute(
            "SELECT local_path FROM digimon_image WHERE local_path IS NOT NULL"
        ).fetchall():
            if is_bad_stored_path(p):
                bad += 1
        for (t,) in con.execute(
            "SELECT thumbnail FROM digimon WHERE thumbnail IS NOT NULL AND TRIM(thumbnail) != ''"
        ).fetchall():
            if is_bad_stored_path(t):
                bad += 1
        return bad
    finally:
        con.close()


def _count_failed_rows(db_path: Path) -> int:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM digimon_image WHERE download_status='failed'"
        ).fetchone()[0]
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rewrite image paths to the relative contract (P0-1)")
    ap.add_argument("--db", type=Path, default=None)
    ap.add_argument("--backup-dir", type=Path, default=None,
                    help="backup location (default: data/backups/backup-<ts>)")
    ap.add_argument("--dry-run", action="store_true", help="report only; no backup, no writes")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    db_path = args.db or Path(os.environ.get("DIGIDEX_DB", str(DB_PATH)))
    return _run(db_path, dry_run=args.dry_run, backup_dir=args.backup_dir)


if __name__ == "__main__":
    raise SystemExit(main())