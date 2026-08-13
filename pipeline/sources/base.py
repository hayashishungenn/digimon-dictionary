"""Base classes + shared helpers for ingestion source adapters.

Every adapter implements `fetch(fetcher, force)` which:
  1. downloads raw responses,
  2. stores them under data/raw/<source>/ with fetch metadata,
  3. parses and returns `list[SourceDigimon]`.

Adapters are polite by construction: they receive the shared rate-limited
Fetcher (config timeouts/retries/backoff/UA/cache) and never open their own
unbounded concurrency.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.core.config import RAW_SOURCES
from pipeline.core.models import SourceDigimon

logger = logging.getLogger(__name__)


def save_raw(source: str, name: str, payload: Any, *, meta: dict[str, Any] | None = None) -> Path:
    """Write one raw snapshot under data/raw/<source>/ with fetch metadata.

    The companion `.meta.json` records fetch_date, source, source_url and any
    HTTP metadata so the provenance of every raw file is traceable (spec §29).
    """
    directory = RAW_SOURCES[source]
    directory.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        raw_path = directory / f"{name}.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
    else:
        raw_path = directory / f"{name}.raw"
        raw_path.write_bytes(payload if isinstance(payload, bytes) else str(payload).encode("utf-8"))
    meta = meta or {}
    meta.setdefault("fetch_date", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    meta.setdefault("source", source)
    (directory / f"{name}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), "utf-8"
    )
    return raw_path


class SourceAdapter(ABC):
    source: str

    @abstractmethod
    def fetch(self, fetcher: Any, force: bool = False) -> list[SourceDigimon]:
        """Download, cache raw, parse, and return normalized records."""

    @property
    def raw_dir(self) -> Path:
        return RAW_SOURCES[self.source]
