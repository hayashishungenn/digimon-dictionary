"""Local publish manifest: a durable, on-disk record of every successful publish.

The live database (`data/digidex.sqlite`) and the incremental state file
(`data/.sync_state.json`) are updated at different moments during a publish.
If the process dies between the two, the database has been replaced but the
state has not — a "database published but state not committed" split that
would corrupt the incremental baseline.

The manifest bridges that window (S0-1):
- written atomically immediately AFTER the atomic DB replace, with
  ``state_committed=false``;
- rewritten ``state_committed=true`` only after ``.sync_state.json`` has been
  durably saved.

A run that reads the manifest and sees a live DB + ``state_committed=false``
(or no manifest) can *recognize* the split and reconcile its state from the
database's own ``sync_run`` / ``source_sync`` / ``snapshot`` rows instead of
trusting a stale state file.

The manifest is intentionally a small JSON file beside the database (never
committed to git) — it is a runtime artifact, not canonical data.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .config import DATA_DIR

# Default location, next to the live database. Tests can pass their own path
# via ``manifest_path_for(db_path)`` (a temp dir alongside their fixture DB).
MANIFEST_PATH = DATA_DIR / ".publish_manifest.json"


def manifest_path_for(db_path: str | Path) -> Path:
    """Publish manifest lives next to the database it describes."""
    return Path(db_path).parent / ".publish_manifest.json"


def read_manifest(path: str | Path = MANIFEST_PATH) -> dict | None:
    """Load the manifest; None when absent or unparseable (never raises)."""
    try:
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text("utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None
    return None


def write_manifest(manifest: dict, path: str | Path = MANIFEST_PATH) -> None:
    """Persist the manifest atomically (write temp file, then replace).

    A process killed mid-write leaves only a ``.tmp`` file (ignored by
    ``read_manifest``), never a half-written manifest the next run would
    misread. Raises OSError so callers can treat a failed manifest write as a
    failed publish (the DB is live but no durable record exists).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), "utf-8")
    os.replace(tmp, p)


def build_manifest(
    *,
    run_id: str,
    snapshot_date: str,
    sources: list[str],
    db_sha256: str | None,
    report_sha256: str | None,
    schema_version: int,
    image_stage: str,
    is_incremental_baseline: bool,
    state_committed: bool,
    published_at: str | None = None,
    notes: str | None = None,
) -> dict:
    """Assemble a publish manifest describing one published database.

    Every field is what a future run / the user needs to answer "is the live
    DB complete, and is it a safe incremental baseline?":
    - ``db_sha256`` — fingerprint of the published database file.
    - ``report_sha256`` — fingerprint of ``data/reports/data-quality.json``
      for the same run (so a stale report can be detected).
    - ``schema_version`` — the schema the DB was built against.
    - ``image_stage`` — ok | failed | skipped | pending (canonical DB success
      is recorded separately from the image cache, S0-1).
    - ``is_incremental_baseline`` — true only when this publish is complete
      and its state is committed, so a later incremental run may trust the
      stored hashes.
    - ``state_committed`` — whether ``.sync_state.json`` was durably saved for
      this publish (the split-recognition flag).
    """
    return {
        "run_id": run_id,
        "snapshot_date": snapshot_date,
        "published_at": published_at,
        "sources": sorted(sources),
        "database_sha256": db_sha256,
        "report_sha256": report_sha256,
        "schema_version": schema_version,
        "image_stage": image_stage,
        "is_incremental_baseline": is_incremental_baseline,
        "state_committed": state_committed,
        "notes": notes,
    }


def stamp_db_hash(
    db_path: str | Path,
    report_json: str | Path | None = None,
    manifest_path: str | Path | None = None,
) -> dict | None:
    """Refresh the manifest + report hashes after the DB bytes changed.

    Used by the image stage (P0-2) and the image-path migration (P0-1): recompute
    ``database_sha256``, re-stamp the JSON report's ``db_sha256`` and recompute
    ``manifest.report_sha256`` from the (possibly re-stamped) report file. Writes
    are atomic. Returns the updated manifest, or None when no manifest exists.
    Raises OSError/ValueError so callers can exit non-zero instead of silently
    recording a stale hash.
    """
    import hashlib

    db = Path(db_path)
    manifest_p = Path(manifest_path or manifest_path_for(db))
    report = Path(report_json) if report_json else db.parent / "reports" / "data-quality.json"
    manifest = read_manifest(manifest_p)
    if manifest is None:
        return None
    db_sha = hashlib.sha256(db.read_bytes()).hexdigest()
    if report.exists():
        data = json.loads(report.read_text("utf-8"))
        data["db_sha256"] = db_sha
        tmp = report.with_name(report.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
        os.replace(tmp, report)
        manifest["report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
    manifest["database_sha256"] = db_sha
    write_manifest(manifest, manifest_p)
    return manifest


def consistency_report(db_path: str | Path) -> dict:
    """Cross-check manifest / report / database hashes (P0-2, diagnose).

    Returns booleans per relationship, or None when a side is missing, plus the
    manifest's run_id / image_stage / state_committed so diagnose can surface
    "database published but image cache / report / manifest incomplete".
    """
    import hashlib

    db = Path(db_path)
    manifest = read_manifest(manifest_path_for(db)) or {}
    manifest_present = bool(manifest)
    db_sha = hashlib.sha256(db.read_bytes()).hexdigest() if db.exists() else None
    report = db.parent / "reports" / "data-quality.json"
    report_sha = hashlib.sha256(report.read_bytes()).hexdigest() if report.exists() else None
    report_db_sha = None
    if report.exists():
        try:
            report_db_sha = json.loads(report.read_text("utf-8")).get("db_sha256")
        except (OSError, ValueError):
            report_db_sha = None
    return {
        "manifest_present": manifest_present,
        "db_exists": db.exists(),
        "database_sha256_matches_db": (
            manifest.get("database_sha256") == db_sha if manifest_present and db_sha else None
        ),
        "report_sha256_matches_report": (
            manifest.get("report_sha256") == report_sha if manifest_present and report_sha else None
        ),
        "report_db_sha256_matches_db": (report_db_sha == db_sha if report_db_sha and db_sha else None),
        "run_id": manifest.get("run_id"),
        "image_stage": manifest.get("image_stage"),
        "state_committed": manifest.get("state_committed"),
    }
