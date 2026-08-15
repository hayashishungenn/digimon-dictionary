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
import os
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pipeline.core.config import RAW_SOURCES
from pipeline.core.models import SourceDigimon

logger = logging.getLogger(__name__)


def _atomic_write(path: Path, data: bytes) -> None:
    """Write `data` atomically: temp file + os.replace (P1-1).

    A process killed mid-write leaves only a `.tmp` file; the final raw
    snapshot is never truncated or half-written, so a subsequent run can never
    treat a partial snapshot as complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    _atomic_write(path, text.encode(encoding))


def save_raw(source: str, name: str, payload: Any, *, meta: dict[str, Any] | None = None) -> Path:
    """Write one raw snapshot under data/raw/<source>/ with fetch metadata.

    The companion `.meta.json` records fetch_date, source, source_url and any
    HTTP metadata so the provenance of every raw file is traceable (spec §29).
    Both files are written atomically (P1-1).
    """
    directory = RAW_SOURCES[source]
    directory.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        raw_path = directory / f"{name}.json"
        _atomic_write_text(raw_path, json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        raw_path = directory / f"{name}.raw"
        _atomic_write(raw_path, payload if isinstance(payload, bytes) else str(payload).encode("utf-8"))
    meta = meta or {}
    meta.setdefault("fetch_date", datetime.now(UTC).isoformat(timespec="seconds"))
    meta.setdefault("source", source)
    _atomic_write_text(
        directory / f"{name}.meta.json",
        json.dumps(meta, ensure_ascii=False, indent=2),
    )
    return raw_path


def save_records(source: str, records: list[SourceDigimon]) -> Path:
    """Persist the normalized records under data/raw/<source>/records.json.

    Retains enough content to rebuild a candidate offline (without re-fetching
    the network) — the full normalized payload, not just id lists (T4.6).
    Written atomically so a partial write is never misread as complete (P1-1).
    """
    from pipeline.core.models import source_digimon_to_dict

    directory = RAW_SOURCES[source]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "records.json"
    _atomic_write_text(
        path,
        json.dumps([source_digimon_to_dict(r) for r in records], ensure_ascii=False, indent=1),
    )
    meta_path = directory / "records.meta.json"
    _atomic_write_text(
        meta_path,
        json.dumps({
            "source": source,
            "fetch_date": datetime.now(UTC).isoformat(timespec="seconds"),
            "count": len(records),
        }, ensure_ascii=False),
    )
    return path


def load_records(source: str) -> list[SourceDigimon]:
    """Load normalized records previously persisted by save_records()."""
    from pipeline.core.models import source_digimon_from_dict

    path = RAW_SOURCES[source] / "records.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text("utf-8"))
    return [source_digimon_from_dict(d) for d in data]


class SourceAdapter(ABC):
    source: str

    @abstractmethod
    def fetch(self, fetcher: Any, force: bool = False) -> list[SourceDigimon]:
        """Download, cache raw, parse, and return normalized records."""

    @property
    def raw_dir(self) -> Path:
        return RAW_SOURCES[self.source]
