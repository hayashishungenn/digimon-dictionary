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
