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
    matchable: bool = True  # False = display-only, not used for entity matching


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


# ---------------------------------------------------------------------------
# Serialization (raw retention / offline candidate rebuild, T4)
# ---------------------------------------------------------------------------
def source_digimon_to_dict(rec: SourceDigimon) -> dict[str, Any]:
    """Lossless serialization of a SourceDigimon to a plain dict.

    Used to persist normalized records under data/raw/<source>/records.json so a
    candidate can be rebuilt without re-fetching the network (T4.6).
    """
    return {
        "source": rec.source,
        "source_id": rec.source_id,
        "names": [
            {"value": n.value, "language": n.language, "status": n.status,
             "source": n.source, "matchable": n.matchable}
            for n in rec.names
        ],
        "level": rec.level,
        "level_raw": rec.level_raw,
        "attribute": rec.attribute,
        "attribute_raw": rec.attribute_raw,
        "types": list(rec.types),
        "fields": list(rec.fields),
        "groups": list(rec.groups),
        "x_antibody": rec.x_antibody,
        "profile": dict(rec.profile),
        "skills": [
            {"names": dict(s.names), "descriptions": dict(s.descriptions),
             "skill_type": s.skill_type, "is_signature": s.is_signature, "source": s.source}
            for s in rec.skills
        ],
        "evolves_to": list(rec.evolves_to),
        "evolves_from": list(rec.evolves_from),
        "conditions": dict(rec.conditions),
        "first_appearance_title": rec.first_appearance_title,
        "first_appearance_date": rec.first_appearance_date,
        "first_appearance_medium": rec.first_appearance_medium,
        "name_origin": rec.name_origin,
        "image_url": rec.image_url,
        "image_page": rec.image_page,
        "is_official": rec.is_official,
        "extra": dict(rec.extra),
    }


def source_digimon_from_dict(d: dict[str, Any]) -> SourceDigimon:
    return SourceDigimon(
        source=d["source"],
        source_id=d["source_id"],
        names=[SourceName(**n) for n in d.get("names", [])],
        level=d.get("level"),
        level_raw=d.get("level_raw"),
        attribute=d.get("attribute"),
        attribute_raw=d.get("attribute_raw"),
        types=list(d.get("types", [])),
        fields=list(d.get("fields", [])),
        groups=list(d.get("groups", [])),
        x_antibody=d.get("x_antibody"),
        profile=dict(d.get("profile", {})),
        skills=[
            SourceSkill(names=dict(s.get("names", {})), descriptions=dict(s.get("descriptions", {})),
                        skill_type=s.get("skill_type", "special_move"),
                        is_signature=bool(s.get("is_signature")), source=s.get("source"))
            for s in d.get("skills", [])
        ],
        evolves_to=list(d.get("evolves_to", [])),
        evolves_from=list(d.get("evolves_from", [])),
        conditions=dict(d.get("conditions", {})),
        first_appearance_title=d.get("first_appearance_title"),
        first_appearance_date=d.get("first_appearance_date"),
        first_appearance_medium=d.get("first_appearance_medium"),
        name_origin=d.get("name_origin"),
        image_url=d.get("image_url"),
        image_page=d.get("image_page"),
        is_official=d.get("is_official"),
        extra=dict(d.get("extra", {})),
    )


def records_payload_hash(records: list[SourceDigimon]) -> str:
    """Hash of the *complete* normalized payload (all fields), so any change in
    a record that affects the canonical result forces a re-merge (T4.2)."""
    import hashlib
    import json as _json

    payload = _json.dumps(
        [source_digimon_to_dict(r) for r in records], sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
