"""Local backup / restore / snapshot inspection (S0-2).

A backup is a timestamped directory under ``data/backups/backup-<ts>/`` that
reproduces the canonical database *plus* the runtime records needed to audit
and restore it:

- ``digidex.sqlite``          — the published database (never modified in place;
                              restore validates + atomically replaces)
- ``.sync_state.json``        — incremental sync markers
- ``.publish_manifest.json``  — the publish manifest (S0-1)
- ``reports/data-quality.{json,md}`` — quality report for the same snapshot
- ``images/``                 — optional local image cache (never committed)

Each backup carries ``backup.json`` describing itself: created_at, run_id,
snapshot date, DB SHA-256 + size, schema version, and whether images are
included. Restore validates the backup (manifest + files + hash + SQLite
integrity + schema compatibility) BEFORE touching the live DB, writes every
file to a temp path, and only then atomically replaces — a failed restore
never leaves the live database changed (S0-2).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .config import BACKUP_DIR, IMAGES_DIR, MANUAL_REVIEW_PATH, SYNC_STATE_PATH
from .manifest import manifest_path_for, read_manifest
from .schema import SCHEMA_VERSION, connect_readonly, verify_integrity

BACKUP_MANIFEST = "backup.json"
IMAGES_SUBDIR = "images"

# Core files, keyed by logical role -> path relative to the backup root.
CORE_FILES = {
    "database": Path("digidex.sqlite"),
    "sync_state": Path(".sync_state.json"),
    "publish_manifest": Path(".publish_manifest.json"),
    "report_json": Path("reports") / "data-quality.json",
    "report_md": Path("reports") / "data-quality.md",
    "conflicts": Path("data_conflicts.json"),
    "manual_review": Path("manual_review_queue.json"),
}


class BackupError(Exception):
    """A backup/restore failed validation; the live DB is left untouched."""


def _now_ts() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S")


def _sha256(path: Path) -> str | None:
    try:
        return _hash_bytes(path.read_bytes())
    except OSError:
        return None


def _hash_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _db_snapshot_date(db_path: Path) -> str | None:
    try:
        conn = connect_readonly(db_path)
        try:
            row = conn.execute(
                "SELECT snapshot_date FROM snapshot ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row["snapshot_date"] if row else None
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def list_backups(backup_root: Path = BACKUP_DIR) -> list[Path]:
    """Existing backup directories, newest first."""
    if not backup_root.exists():
        return []
    return sorted(
        (p for p in backup_root.iterdir() if p.is_dir() and (p / BACKUP_MANIFEST).exists()),
        key=lambda p: p.name,
        reverse=True,
    )


def create_backup(
    *,
    db_path: Path,
    out_dir: Path | None = None,
    with_images: bool = False,
    state_path: Path = SYNC_STATE_PATH,
    manifest_path: Path | None = None,
    reports_dir: Path | None = None,
    conflicts_path: Path = MANUAL_REVIEW_PATH,
    keep: int | None = None,
) -> Path:
    """Create a timestamped backup directory and return its path.

    The copied database is validated (integrity + hash) before ``backup.json``
    is written, so a corrupted copy never masquerades as a valid backup.
    ``keep`` prunes the oldest backups beyond the newest ``keep`` (only ever
    inside the validated backup root).
    """
    from .config import DATA_DIR, REPORTS_DIR

    reports_dir = reports_dir or REPORTS_DIR
    manifest_path = manifest_path or manifest_path_for(db_path)
    out_dir = out_dir or BACKUP_DIR / f"backup-{_now_ts()}"

    if not db_path.exists():
        raise BackupError(f"database does not exist: {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "reports").mkdir(parents=True, exist_ok=True)

    # copy core files that exist (a missing runtime file is not a backup failure
    # for the database itself, but the backup manifest must record it).
    copied: dict[str, Path] = {}
    missing: list[str] = []
    source_of = {
        "database": db_path,
        "sync_state": state_path,
        "publish_manifest": manifest_path,
        "report_json": reports_dir / "data-quality.json",
        "report_md": reports_dir / "data-quality.md",
        "conflicts": conflicts_path,
        "manual_review": DATA_DIR / "manual_review_queue.json",
    }
    for role, src in source_of.items():
        target = out_dir / CORE_FILES[role]
        if src.exists():
            shutil.copy2(src, target)
            copied[role] = target
        else:
            missing.append(role)

    if with_images and IMAGES_DIR.exists():
        img_target = out_dir / IMAGES_SUBDIR
        if img_target.exists():
            shutil.rmtree(img_target)
        shutil.copytree(IMAGES_DIR, img_target)
        includes_images = True
    else:
        includes_images = False

    db_copy = out_dir / CORE_FILES["database"]
    if "database" not in copied or not verify_integrity(db_copy):
        # leave no half-built backup dir behind
        shutil.rmtree(out_dir, ignore_errors=True)
        raise BackupError(f"backed-up database failed integrity check: {db_copy}")

    manifest = read_manifest(manifest_path) or {}
    db_sha = _sha256(db_copy)
    # the backup's schema is the COPY'S actual schema (authoritative); the
    # publish manifest may be stale if the DB was migrated in place after the
    # manifest was written (e.g. v7 manifest, v8 DB).
    db_schema = _read_user_version(db_copy)
    backup_meta = {
        "backup_id": out_dir.name,
        "created_at": _now_ts(),
        "snapshot_date": manifest.get("snapshot_date") or _db_snapshot_date(db_copy),
        "run_id": manifest.get("run_id"),
        "sources": manifest.get("sources"),
        "database_sha256": db_sha,
        "database_size": db_copy.stat().st_size,
        "schema_version": db_schema or manifest.get("schema_version"),
        "includes_images": includes_images,
        "image_stage": manifest.get("image_stage"),
        "files": {
            role: {"size": p.stat().st_size} for role, p in copied.items()
        },
        "missing_files": missing,
    }
    (out_dir / BACKUP_MANIFEST).write_text(
        json.dumps(backup_meta, indent=2, ensure_ascii=False), "utf-8"
    )

    if keep is not None:
        pruned = prune_backups(BACKUP_DIR, keep=keep, keep_exact=out_dir)
        if pruned:
            print(f"pruned old backups: {[p.name for p in pruned]}")
    return out_dir


def _read_user_version(db_path: Path) -> int:
    try:
        conn = connect_readonly(db_path)
        try:
            return int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return 0


def prune_backups(backup_root: Path, keep: int, keep_exact: Path | None = None) -> list[Path]:
    """Delete the oldest backups beyond ``keep``; returns removed paths."""
    kept = list_backups(backup_root)
    if keep_exact is not None and keep_exact not in kept:
        kept = [keep_exact, *kept]
    remove = kept[keep:] if keep >= 0 else []
    for p in remove:
        shutil.rmtree(p, ignore_errors=True)
    return remove


def validate_backup(backup_dir: Path) -> dict:
    """Validate a backup directory; raises BackupError on any problem.

    Checks, in order: backup manifest present, every listed core file exists,
    DB SHA-256 matches the manifest, SQLite integrity passes, and the DB schema
    version is not newer than the running code can open (S0-2).
    """
    meta_path = backup_dir / BACKUP_MANIFEST
    if not meta_path.exists():
        raise BackupError(f"not a backup (missing {BACKUP_MANIFEST}): {backup_dir}")
    meta = json.loads(meta_path.read_text("utf-8"))

    for role, rel in CORE_FILES.items():
        if meta.get("files", {}).get(role) is None:
            continue  # runtime file was missing at backup time — recorded, not required
        if not (backup_dir / rel).exists():
            raise BackupError(f"backup is missing {rel} (role={role})")

    db_copy = backup_dir / CORE_FILES["database"]
    if not db_copy.exists():
        raise BackupError(f"backup is missing database: {db_copy}")

    db_sha = _sha256(db_copy)
    if meta.get("database_sha256") and db_sha != meta["database_sha256"]:
        raise BackupError(
            f"database SHA-256 mismatch: backup.json says {meta['database_sha256']}, "
            f"actual {db_sha}"
        )
    if not verify_integrity(db_copy):
        raise BackupError(f"backup database failed SQLite integrity_check: {db_copy}")

    schema_version = meta.get("schema_version") or _read_user_version(db_copy)
    if schema_version and int(schema_version) > SCHEMA_VERSION:
        raise BackupError(
            f"backup schema_version {schema_version} is newer than this build "
            f"({SCHEMA_VERSION}); refusing to restore"
        )
    return {**meta, "schema_version": int(schema_version or 0)}


def restore_backup(
    backup_dir: Path,
    *,
    db_path: Path,
    state_path: Path = SYNC_STATE_PATH,
    manifest_path: Path | None = None,
    reports_dir: Path | None = None,
    dry_run: bool = False,
) -> list[Path]:
    """Restore a validated backup onto the live paths.

    Two-phase: first validate the backup and stage every target as a ``.tmp``
    file (DB temp re-verified), then atomically replace each target. A failure
    in the staging phase leaves the live DB untouched. Returns the restored
    paths (for dry_run, the paths that *would* be restored).
    """
    from .config import REPORTS_DIR

    reports_dir = reports_dir or REPORTS_DIR
    manifest_path = manifest_path or manifest_path_for(db_path)
    info = validate_backup(backup_dir)

    targets = {
        "database": db_path,
        "sync_state": state_path,
        "publish_manifest": manifest_path,
        "report_json": reports_dir / "data-quality.json",
        "report_md": reports_dir / "data-quality.md",
    }
    staged: list[tuple[Path, Path]] = []  # (temp, target)
    try:
        for role, target in targets.items():
            rel = CORE_FILES[role]
            src = backup_dir / rel
            if not src.exists():
                continue  # runtime file was not in this backup
            target.parent.mkdir(parents=True, exist_ok=True)
            if dry_run:
                staged.append((src, target))  # nothing written
                continue
            tmp = target.with_name(target.name + ".restore.tmp")
            shutil.copy2(src, tmp)
            staged.append((tmp, target))
        # the staged DB temp must be a valid, matching database
        db_tmp = db_path.with_name(db_path.name + ".restore.tmp")
        if not dry_run and db_tmp.exists() and not _temp_db_matches(db_tmp, info):
            raise BackupError(f"staged database failed re-validation: {db_tmp}")
    except Exception:
        if not dry_run:
            _cleanup_temps(staged)
        raise

    if dry_run:
        return [t for _, t in staged]

    # commit phase: only now touch the live paths
    committed: list[Path] = []
    for tmp, target in staged:
        os.replace(tmp, target)
        committed.append(target)
    return committed


def _temp_db_matches(tmp: Path, info: dict) -> bool:
    if not verify_integrity(tmp):
        return False
    sha = _sha256(tmp)
    return sha == info.get("database_sha256")


def _cleanup_temps(staged: list[tuple[Path, Path]]) -> None:
    for tmp, _target in staged:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def inspect_backup(backup_dir: Path | None = None, *, db_path: Path | None = None) -> dict:
    """Human/script-readable snapshot summary of a backup or the live DB."""
    from .config import DB_PATH, REPORTS_DIR

    if backup_dir is not None:
        info = validate_backup(backup_dir)
        info["path"] = str(backup_dir)
        info["exists"] = True
        info["integrity_ok"] = True  # validate_backup already ran integrity+hash
        info["report_exists"] = (backup_dir / CORE_FILES["report_json"]).exists()
        pm_path = backup_dir / CORE_FILES["publish_manifest"]
        pm = read_manifest(pm_path) if pm_path.exists() else {}
        info["is_incremental_baseline"] = pm.get("is_incremental_baseline")
        info["state_committed"] = pm.get("state_committed")
        info["image_stage"] = pm.get("image_stage") or info.get("image_stage")
        return info
    db = db_path or DB_PATH
    manifest = read_manifest(manifest_path_for(db))
    return {
        "path": str(db),
        "exists": db.exists(),
        "integrity_ok": verify_integrity(db) if db.exists() else False,
        "snapshot_date": (manifest or {}).get("snapshot_date") or _db_snapshot_date(db),
        "run_id": (manifest or {}).get("run_id"),
        "database_sha256": _sha256(db) if db.exists() else None,
        "database_size": db.stat().st_size if db.exists() else 0,
        "schema_version": _read_user_version(db) if db.exists() else 0,
        "image_stage": (manifest or {}).get("image_stage"),
        "is_incremental_baseline": (manifest or {}).get("is_incremental_baseline"),
        "state_committed": (manifest or {}).get("state_committed"),
        "sources": (manifest or {}).get("sources"),
        "report_exists": (REPORTS_DIR / "data-quality.json").exists(),
    }
