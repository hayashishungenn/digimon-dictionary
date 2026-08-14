"""Entity resolution: assign every source record to a canonical entity.

Resolution strategy (product spec §33):
  exact Japanese name -> exact English name -> alias match -> normalized name
  -> external-id mapping -> fuzzy candidate -> manual_review_queue.

The first-ingested source (digi-api) acts as the entity backbone. Overlay
sources (official, Wikimon, digimons.net) are matched into those entities or
become new extended entities when no match is found.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pipeline.core import naming
from pipeline.core.models import MatchedEntity, SourceDigimon

logger = logging.getLogger(__name__)

# Name-variant disambiguation: these suffixes distinguish forms that share a
# base romanized name. They are extracted from names so slugify produces stable
# unique slugs (e.g. "Agumon (Black)" -> agumon-black).
_SLUG_SUFFIX_PATTERNS = [
    (r"\((?:2006|2006 anime|2006 anime version|anime version)\)", "2006"),
    (r"\(x-antibody\)", "x-antibody"),
    (r"\(black\)", "black"),
    (r"\(virus\)", "virus"),
    (r"\(deva\)", "deva"),
    (r"\(dub\)", "dub"),
    (r"\(male\)", "male"),
    (r"\(female\)", "female"),
]


def slug_for_names(names: dict[str, str | None]) -> str:
    """Generate a canonical_slug from a record's names.

    Base: English name or romanized/Japanese fallback, lowercased with
    punctuation collapsed. Recognized variant suffixes are mapped to stable
    tokens ("X-Antibody" -> "-x-antibody", "(2006 Anime Version)" -> "-2006").
    """
    base = names.get("en") or names.get("romanized") or names.get("ja") or names.get("zh_cn") or ""
    s = base.strip()
    lower = s.lower()
    for pattern, token in _SLUG_SUFFIX_PATTERNS:
        if re.search(pattern, lower):
            s = re.sub(pattern, f"-{token}", s, flags=re.IGNORECASE)
    # collapse remaining punctuation/space to single hyphens (keep case-fold)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        # no latin characters available (e.g. Japanese-only name) -> stable fallback
        import hashlib

        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
        s = f"digimon-{digest}"
    return s


class Matcher:
    """Maps SourceDigimon records to canonical slugs."""

    def __init__(self) -> None:
        # normalized key -> list of slugs (a name may be ambiguous)
        self._index: dict[str, list[str]] = {}
        # (source, source_id) -> slug  (external-id mapping)
        self._external: dict[tuple[str, str], str] = {}
        self.entities: dict[str, MatchedEntity] = {}
        self.review_queue: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ index
    @staticmethod
    def _key_for(name: str, language: str | None = None) -> str:
        """Normalized matching key. Chinese names are also indexed by their
        simplified form so 亞古獸 / 亚古兽 match the same entity (§33 简繁)."""
        if language in ("zh_cn", "zh_hk", "zh_tw"):
            return naming.normalize_key_zh(name)
        return naming.normalize_key(name)

    def _add_name(self, slug: str, name: str, language: str | None = None) -> None:
        key = self._key_for(name, language)
        if not key:
            return
        self._index.setdefault(key, [])
        if slug not in self._index[key]:
            self._index[key].append(slug)

    def seed_entity(self, slug: str, record: SourceDigimon) -> None:
        """Register an entity and index its matchable names + external id."""
        entity = MatchedEntity(canonical_slug=slug, records=[record])
        self.entities[slug] = entity
        for n in record.names:
            if n.matchable:
                self._add_name(slug, n.value, n.language)
        self._add_name(slug, record.extra.get("alt_name") or "")
        self._external[(record.source, record.source_id)] = slug

    # ---------------------------------------------------------------- lookup
    def _lookup(self, key: str) -> list[str]:
        return self._index.get(key, [])

    def _resolve_by_external(self, record: SourceDigimon) -> str | None:
        return self._external.get((record.source, record.source_id))

    def resolve(self, record: SourceDigimon) -> tuple[str | None, bool]:
        """Return ``(canonical_slug, ambiguous)`` for a record.

        Resolution is exact-only (product spec §33: no pure-fuzzy auto-merge):
          external id -> exact ja -> exact en -> exact romanized -> exact zh
        ``ambiguous=True`` means the exact name hit several entities — the
        caller must NOT silently merge or fabricate a confirmed entity.
        """
        # 1. external-id mapping (covers records already seen from a source)
        ext = self._resolve_by_external(record)
        if ext:
            return ext, False

        names = record.names
        if not any(n.value and n.matchable for n in names):
            return None, False

        # 2. exact matches by priority order: ja, en, romanized, zh_cn, dub
        candidates: list[str] = []
        for priority in ("ja", "en", "romanized", "zh_cn", "en_dub", "zh_hk", "zh_tw"):
            for n in names:
                if n.language != priority or not n.matchable:
                    continue
                hits = self._lookup(self._key_for(n.value, n.language))
                if hits:
                    candidates = hits
                    break
            if candidates:
                break

        if len(candidates) == 1:
            return candidates[0], False
        if len(candidates) > 1:
            # ambiguous exact name: never auto-merge, flag for review
            self.review_queue.append(
                {
                    "reason": "ambiguous_name",
                    "source": record.source,
                    "source_id": record.source_id,
                    "names": [n.value for n in record.names],
                    "candidates": candidates,
                }
            )
            logger.warning("ambiguous name %s -> %s (review queued)", [n.value for n in names], candidates)
            return None, True
        return None, False

    # -------------------------------------------------------------- assembly
    def add(self, record: SourceDigimon) -> str:
        """Add a record, returning its canonical slug."""
        slug, ambiguous = self.resolve(record)
        if slug is None:
            slug = slug_for_names({n.language: n.value for n in record.names})
            # ensure uniqueness
            base = slug
            i = 1
            while slug in self.entities:
                slug = f"{base}-{i}"
                i += 1
            entity = MatchedEntity(canonical_slug=slug, records=[], confidence="high")
            if ambiguous:
                # never let an ambiguous record masquerade as a confirmed entity
                entity.needs_review = True
                entity.review_reason = "ambiguous exact name (see manual_review_queue)"
            self.entities[slug] = entity
            logger.info("new entity: %s (source %s %s)", slug, record.source, record.source_id)
        self.entities[slug].records.append(record)
        for n in record.names:
            if n.matchable:
                self._add_name(slug, n.value, n.language)
        self._external[(record.source, record.source_id)] = slug
        # register official→dapi cross-source id linking via names handled above
        return slug
