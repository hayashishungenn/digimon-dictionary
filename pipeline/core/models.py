"""Intermediate data models shared by all ingestion sources.

Every source adapter (digi-api, Wikimon, digimons.net, official, ...) produces
records of these types. The normalize/matching/merge stages consume them, so a
new source only needs to map into this common shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceName:
    """One localized name with provenance."""
    value: str
    language: str  # zh_cn | zh_hk | zh_tw | en | en_dub | ja | romanized
    status: str | None = None  # official|community|transliteration|unverified
    source: str | None = None


@dataclass
class SourceSkill:
    names: dict[str, str | None] = field(default_factory=dict)  # zh_cn/en/ja
    descriptions: dict[str, str | None] = field(default_factory=dict)
    skill_type: str = "special_move"
    is_signature: bool = False
    source: str | None = None


@dataclass
class SourceDigimon:
    """A normalized, source-specific digimon record."""
    source: str  # dapi | wikimon | digimons_net | official | manual
    source_id: str  # source-local identifier (dapi_id, wikimon title, ...)

    names: list[SourceName] = field(default_factory=list)
    level: str | None = None
    level_raw: str | None = None
    attribute: str | None = None
    attribute_raw: str | None = None
    types: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    x_antibody: bool | None = None
    profile: dict[str, str] = field(default_factory=dict)  # zh_cn/en/ja
    skills: list[SourceSkill] = field(default_factory=list)
    evolves_to: list[str] = field(default_factory=list)  # source-local ids
    evolves_from: list[str] = field(default_factory=list)
    conditions: dict[str, str] = field(default_factory=dict)  # edge key -> condition
    first_appearance_title: str | None = None
    first_appearance_date: str | None = None
    first_appearance_medium: str | None = None
    name_origin: str | None = None
    image_url: str | None = None
    image_page: str | None = None
    is_official: bool | None = None  # present in official reference book
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class MatchedEntity:
    """Result of entity resolution: source records assigned to a canonical id."""
    canonical_slug: str
    records: list[SourceDigimon] = field(default_factory=list)
    digimon_id: int | None = None  # filled during merge
    confidence: str = "high"
    needs_review: bool = False
    review_reason: str | None = None
