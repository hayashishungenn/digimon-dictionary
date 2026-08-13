"""Central configuration: paths, sync state, and source settings."""
from __future__ import annotations

from pathlib import Path

# Repository root (this file is at <root>/pipeline/core/config.py).
ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
IMAGES_DIR = DATA_DIR / "images"
REPORTS_DIR = DATA_DIR / "reports"
EXPORTS_DIR = ROOT / "exports"

DB_PATH = DATA_DIR / "digidex.sqlite"

# Sub-directories for each ingestion source (raw snapshots).
RAW_SOURCES: dict[str, Path] = {
    "dapi": RAW_DIR / "dapi",
    "wikimon": RAW_DIR / "wikimon",
    "official": RAW_DIR / "official",
    "digimons_net": RAW_DIR / "digimons_net",
    "digidb": RAW_DIR / "digidb",
    "manual": RAW_DIR / "manual",
}

# A safe, descriptive default User-Agent for all outbound HTTP.
DEFAULT_USER_AGENT = (
    "DigiDex/0.1 (personal research project; "
    "https://github.com/hayas/digidex; contact via repo issues)"
)

# Conservative politeness defaults (per product spec §48).
DEFAULT_TIMEOUT = 15.0  # seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_RATE_PER_SECOND = 1.0  # requests per second per source
DEFAULT_MAX_CONCURRENCY = 2  # conservative; never hammer targets

# Source-specific overrides are defined in the source modules.

# Manual review / conflict storage.
MANUAL_REVIEW_PATH = DATA_DIR / "manual_review_queue.json"
CONFLICT_PATH = DATA_DIR / "data_conflicts.json"

# Content-hash marker for incremental sync (see §47).
SYNC_STATE_PATH = DATA_DIR / ".sync_state.json"
