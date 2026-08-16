"""Sync state tracking for incremental updates (product spec §47)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import SYNC_STATE_PATH


class SyncState:
    """Persists per-source state: last_seen_at, content_hash, records."""

    def __init__(self, path: Path = SYNC_STATE_PATH) -> None:
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self.path.exists():
                self._data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            # A half-written state file (e.g. process killed mid-write) must not
            # crash the sync — fall back to empty state rather than raising.
            self._data = {}

    def get(self, source: str) -> dict[str, Any]:
        return self._data.setdefault(source, {})

    def set(self, source: str, **values: Any) -> None:
        self._data.setdefault(source, {}).update(values)

    def unchanged(self, source: str, content_hash: str) -> bool:
        """True when this source has already been ingested with this hash."""
        return self._data.get(source, {}).get("content_hash") == content_hash

    def previous_records(self, source: str) -> int:
        """How many records the last *successful* sync reported for a source."""
        return int(self._data.get(source, {}).get("records", 0) or 0)

    def save(self) -> None:
        """Persist state atomically: write a temp file, then replace.

        A process killed mid-write leaves only a `.tmp` file (ignored on load),
        never a half-written state file that the next run would misread.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), "utf-8"
        )
        os.replace(tmp, self.path)

    def reconcile_from_db(self, db_path: str | Path) -> bool:
        """Rebuild per-source state from the database's latest successful run.

        Recovery path for the "database published but state not committed" split
        (S0-1): the live DB is the source of truth, so when `.sync_state.json`
        has no source set yet the DB has one, we reconstruct the incremental
        markers (per-source payload hash + record count + source set) from the
        DB's own `sync_run` / `source_sync` rows instead of trusting a stale or
        missing state file.

        Returns True when the state was rebuilt; False when the DB has no
        successful run to reconcile from (caller should leave state as-is).
        """
        import sqlite3

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                run = conn.execute(
                    """SELECT run_id, sources FROM sync_run
                       WHERE status IN ('ok','partial')
                       ORDER BY run_id DESC LIMIT 1"""
                ).fetchone()
                if run is None:
                    return False
                rows = conn.execute(
                    """SELECT source, content_hash, payload_hash, records,
                              last_seen_at
                       FROM source_sync WHERE run_id = ?""",
                    [run["run_id"]],
                ).fetchall()
            finally:
                conn.close()
        except (sqlite3.Error, OSError):
            return False

        self._data = {}
        self.set(
            "sync_data",
            sources=[s for s in (run["sources"] or "").split(",") if s],
            run_id=run["run_id"],
        )
        for r in rows:
            digest = r["content_hash"] or r["payload_hash"] or None
            self.set(
                r["source"],
                content_hash=digest,
                payload_hash=r["payload_hash"] or digest,
                last_seen_at=r["last_seen_at"],
                records=r["records"],
            )
        return True
