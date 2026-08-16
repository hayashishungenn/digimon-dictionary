"""Canonical database writer (MERGE stage).

Takes matched entities (each = canonical slug + one or more SourceDigimon
records from different sources) and upserts them into SQLite. Tracks per-field
provenance, records genuine conflicts in `data_conflict`, and never deletes
history — the write is idempotent for incremental syncs.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pipeline.core import naming
from pipeline.core.enums import (
    AliasType,
    NameStatus,
    parse_attribute,
    parse_level,
)
from pipeline.core.models import MatchedEntity, SourceDigimon, SourceName, SourceSkill
from pipeline.sources.wikitext import strip_residual_markup

logger = logging.getLogger(__name__)

_STATUS_RANK = {
    NameStatus.OFFICIAL: 4,
    NameStatus.OFFICIAL_GAME: 3,
    NameStatus.OFFICIAL_ANIME: 3,
    NameStatus.COMMUNITY: 2,
    NameStatus.TRANSLITERATION: 1,
    NameStatus.UNVERIFIED: 0,
}

# Documented canonical priority for world-view fields (level/attribute/profile/
# first appearance/name origin) when multiple sources disagree — per product
# spec §14 the official Reference Book is authoritative, then Wikimon, then
# digi-api, then community sites. Image selection uses a separate documented
# order (see _pick_main_image). Never "first source in input order".
SOURCE_PRIORITY = {
    "official": 4,
    "wikimon": 3,
    "dapi": 2,
    "manual": 2,
    "digimons_net": 1,
    "digidb": 0,
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _pick_name(names: list[SourceName], language: str) -> SourceName | None:
    """Pick the best name for a language by status priority."""
    candidates = [n for n in names if n.language == language and n.value and n.value.strip()]
    if not candidates:
        return None
    candidates.sort(key=lambda n: _STATUS_RANK.get(NameStatus(n.status) if n.status else NameStatus.UNVERIFIED, 0), reverse=True)
    return candidates[0]


def _skill_match_key(s: SourceSkill) -> str:
    for lang in ("en", "ja", "zh_cn"):
        v = (s.names.get(lang) or "").strip()
        if v:
            return naming.normalize_key(v)
    return ""


class CanonicalStore:
    def __init__(self, conn: sqlite3.Connection, *, run_id: str | None = None) -> None:
        self.conn = conn
        self.run_id = run_id  # provenance rows record which sync run wrote them (P1-2)

    # ------------------------------------------------------------------ helpers
    def _lookup_type(self, name: str) -> int | None:
        row = self.conn.execute("SELECT id FROM type WHERE name = ?", [name]).fetchone()
        return row["id"] if row else None

    def _ensure_type(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM type WHERE name = ?", [name]).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute("INSERT OR IGNORE INTO type(name) VALUES(?)", [name])
        if cur.lastrowid:
            return cur.lastrowid
        return self.conn.execute("SELECT id FROM type WHERE name = ?", [name]).fetchone()["id"]

    def _ensure_field(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM field WHERE name = ?", [name]).fetchone()
        if row:
            return row["id"]
        self.conn.execute("INSERT OR IGNORE INTO field(name) VALUES(?)", [name])
        return self.conn.execute("SELECT id FROM field WHERE name = ?", [name]).fetchone()["id"]

    def _ensure_group(self, name: str) -> int:
        row = self.conn.execute("SELECT id FROM grp WHERE name = ?", [name]).fetchone()
        if row:
            return row["id"]
        self.conn.execute("INSERT OR IGNORE INTO grp(name) VALUES(?)", [name])
        return self.conn.execute("SELECT id FROM grp WHERE name = ?", [name]).fetchone()["id"]

    def _ensure_skill(self, s: SourceSkill) -> int:
        key = _skill_match_key(s)
        if key:
            row = self.conn.execute("SELECT id FROM skill WHERE match_key = ?", [key]).fetchone()
            if row:
                # backfill missing language names/descriptions
                self._merge_skill_row(row["id"], s)
                return row["id"]
            cur = self.conn.execute(
                "INSERT INTO skill(match_key, name_zh_cn, name_en, name_ja, "
                "description_zh_cn, description_en, description_ja, source) "
                "VALUES(?,?,?,?,?,?,?,?)",
                [
                    key,
                    s.names.get("zh_cn"),
                    s.names.get("en"),
                    s.names.get("ja"),
                    s.descriptions.get("zh_cn"),
                    s.descriptions.get("en"),
                    s.descriptions.get("ja"),
                    s.source,
                ],
            )
            return cur.lastrowid
        # No reliable key: create anyway (orphan skills are flagged in validation).
        cur = self.conn.execute(
            "INSERT INTO skill(name_zh_cn, name_en, name_ja, source) VALUES(?,?,?,?)",
            [s.names.get("zh_cn"), s.names.get("en"), s.names.get("ja"), s.source],
        )
        return cur.lastrowid

    def _merge_skill_row(self, skill_id: int, s: SourceSkill) -> None:
        for col, lang in (("name_zh_cn", "zh_cn"), ("name_en", "en"), ("name_ja", "ja")):
            v = (s.names.get(lang) or "").strip()
            if v:
                self.conn.execute(
                    f"UPDATE skill SET {col} = COALESCE(NULLIF({col}, ''), ?) WHERE id = ?",
                    [v, skill_id],
                )
        for col, lang in (
            ("description_zh_cn", "zh_cn"),
            ("description_en", "en"),
            ("description_ja", "ja"),
        ):
            v = (s.descriptions.get(lang) or "").strip()
            if v:
                self.conn.execute(
                    f"UPDATE skill SET {col} = COALESCE(NULLIF({col}, ''), ?) WHERE id = ?",
                    [v, skill_id],
                )

    # ------------------------------------------------------------------ main
    def upsert_entity(self, entity: MatchedEntity) -> int:
        """Merge all records of an entity into the digimon table. Returns id."""
        records = [r for r in entity.records if r is not None]
        if not records:
            raise ValueError(f"entity {entity.canonical_slug} has no records")

        digimon_id = self._upsert_digimon_row(entity)
        # reset derived rows for a clean idempotent write
        self._reset_derived(digimon_id)

        for rec in records:
            self._merge_names(digimon_id, rec)
            self._merge_types(digimon_id, rec)
            self._merge_fields(digimon_id, rec)
            self._merge_groups(digimon_id, rec)
            self._merge_skills(digimon_id, rec)
            self._merge_image(digimon_id, rec)
        # profile / first appearance / name origin are single-valued fields:
        # they are merged by documented source priority, not input order.
        self._merge_profiles(digimon_id, records)
        self._merge_first_appearance(digimon_id, records)
        self._merge_name_origin(digimon_id, records)
        # record why each audited field is present or absent (P0-2): a missing
        # field is a documented gap (no_source/no_level/conflict), never a
        # silent drop. verify_samples and the validator consult this to tell a
        # real data gap from a sync/pipeline bug.
        self._record_coverage(digimon_id, records)
        return digimon_id

    # ------------------------------------------------------------------ coverage
    def _record_coverage(self, digimon_id: int, records: list[SourceDigimon]) -> None:
        """Per-field coverage audit: present | no_source | no_level | conflict |
        sync_failure.

        Distinguishes "this field is genuinely absent across all ingested
        sources" from "a source had it but the pipeline lost it". A raw value
        that fails to map to a canonical enum is recorded as no_level; a real
        unresolvable cross-source tie (already in data_conflict) as conflict.
        """
        conn = self.conn
        row = conn.execute(
            """SELECT name_zh_cn, name_en, name_ja, level, attribute, main_image,
                      profile_zh_cn, profile_en, profile_ja
               FROM digimon WHERE id = ?""",
            [digimon_id],
        ).fetchone()

        def put(field: str, status: str, sources: list[str], detail: str | None = None) -> None:
            conn.execute(
                """INSERT OR REPLACE INTO field_coverage(digimon_id, field, status, sources, detail)
                   VALUES(?,?,?,?,?)""",
                [digimon_id, field, status,
                 ",".join(sorted({s for s in sources if s})) or None, detail],
            )

        srcs = [r.source for r in records if r]

        # names
        for lang, col in (("zh_cn", "name_zh_cn"), ("en", "name_en"), ("ja", "name_ja")):
            if row[col]:
                put(lang, "present", srcs)
            else:
                provided = [
                    r.source for r in records
                    if any(n.language == lang and n.value and n.value.strip() for n in r.names)
                ]
                if provided:
                    put(lang, "sync_failure", provided,
                        "source provided a name but the merge produced no value")
                else:
                    put(lang, "no_source", srcs,
                        "no ingested source provides a name in this language")

        # level / attribute
        for col, get_raw in (
            ("level", lambda r: r.level_raw or r.level),
            ("attribute", lambda r: r.attribute_raw or r.attribute),
        ):
            if row[col] and row[col] != "unknown":
                put(col, "present", srcs)
                continue
            raw_sources = [r for r in records if get_raw(r)]
            if not raw_sources:
                put(col, "no_source", srcs, "no ingested source provides this field")
                continue
            raw_values = [str(get_raw(r)).strip() for r in raw_sources if str(get_raw(r)).strip()]
            unresolved = conn.execute(
                "SELECT COUNT(*) FROM data_conflict "
                "WHERE entity_type='digimon' AND entity_id=? AND field=? AND resolved=0",
                [digimon_id, col],
            ).fetchone()[0]
            if unresolved:
                put(col, "conflict", [r.source for r in raw_sources],
                    f"unresolved source disagreement (raw values: {raw_values[:4]})")
            else:
                put(col, "no_level", [r.source for r in raw_sources],
                    f"raw values do not map to a canonical value: {raw_values[:4]}")

        # image
        if row["main_image"]:
            put("image", "present", srcs)
        else:
            img = conn.execute(
                """SELECT download_status FROM digimon_image
                   WHERE digimon_id=? AND image_type='main_image'""",
                [digimon_id],
            ).fetchone()
            img_srcs = [r.source for r in records if r.image_url]
            if img and img["download_status"] == "failed":
                put("image", "sync_failure", img_srcs, "image download failed")
            elif img:
                put("image", "sync_failure", img_srcs,
                    f"image row exists but main_image empty (status {img['download_status']})")
            elif img_srcs:
                put("image", "sync_failure", img_srcs,
                    "source provided an image URL but no image row was written")
            else:
                put("image", "no_source", srcs,
                    "no ingested source carried an image URL (wikimon images not yet extracted)")

        # skills
        n_skills = conn.execute(
            "SELECT COUNT(*) FROM digimon_skill WHERE digimon_id=?", [digimon_id]
        ).fetchone()[0]
        if n_skills:
            put("skills", "present", srcs)
        else:
            sk_srcs = [r.source for r in records if r.skills]
            if sk_srcs:
                put("skills", "sync_failure", sk_srcs,
                    "sources provided skills but none were written")
            else:
                put("skills", "no_source", srcs, "no ingested source provides skills")

        # profile (any language)
        has_profile = any(row[c] for c in ("profile_zh_cn", "profile_en", "profile_ja"))
        if has_profile:
            put("profile", "present", srcs)
        else:
            pr_srcs = [
                r.source for r in records
                if any((r.profile.get(lang) or "").strip() for lang in ("zh_cn", "en", "ja"))
            ]
            if pr_srcs:
                put("profile", "sync_failure", pr_srcs,
                    "sources provided a profile but none was written")
            else:
                put("profile", "no_source", srcs, "no ingested source provides a profile")

    # ---- canonical value selection (documented source priority) ------------
    @staticmethod
    def _field_candidates(entity: MatchedEntity, raw_fn: Callable[[SourceDigimon], str]) -> list[tuple[str, str, str]]:
        """[(canonical_value, source, source_id), ...] for a world-view field."""
        out: list[tuple[str, str, str]] = []
        for r in entity.records:
            if not r:
                continue
            raw = raw_fn(r)
            if not raw:
                continue
            out.append((raw, r.source, r.source_id))
        return out

    @staticmethod
    def _pick_canonical(candidates: list[tuple[str, str, str]], default: str = "unknown"):
        """Pick the canonical value by SOURCE_PRIORITY (never input order).

        Returns ``(value, choice)``. ``choice`` is None when there is no
        concrete value, otherwise a dict with value/source/source_id/candidates/
        reason/needs_review. A tie between distinct values at the same top
        priority is left unresolved (needs_review=True) rather than guessed.
        """
        concrete = [(v, s, sid) for v, s, sid in candidates if v and v != "unknown"]
        if not concrete:
            return default, None
        ranked: dict[str, dict[str, Any]] = {}
        for v, s, sid in concrete:
            prio = SOURCE_PRIORITY.get(s, 0)
            if v not in ranked or prio > ranked[v]["prio"]:
                ranked[v] = {"prio": prio, "source": s, "source_id": sid}
        top_prio = max(r["prio"] for r in ranked.values())
        top_values = [v for v, r in ranked.items() if r["prio"] == top_prio]
        candidates_json = [{"value": v, "source": s, "source_id": sid} for v, s, sid in concrete]
        if len(top_values) > 1:
            reason = f"equal source priority {top_prio} between {sorted(top_values)}; manual review required"
            return default, {
                "value": None, "source": None, "source_id": None,
                "candidates": candidates_json, "reason": reason, "needs_review": True,
            }
        v = top_values[0]
        reason = f"source priority: {ranked[v]['source']} (priority {top_prio})"
        return v, {
            "value": v, "source": ranked[v]["source"], "source_id": ranked[v]["source_id"],
            "candidates": candidates_json, "reason": reason, "needs_review": False,
        }

    @staticmethod
    def _source_last_updated(entity: MatchedEntity) -> str:
        """Best source timestamp across records; falls back to retrieved_at.

        A real source-provided update time is never blindly overwritten with
        the current clock. When the source does not report its own timestamp,
        the fetch time (retrieved_at) is used instead.
        """
        stamps = [
            r.extra.get("source_last_updated") or r.extra.get("source_updated_at")
            or r.extra.get("fetch_date")
            for r in entity.records if r
        ]
        stamps = [s for s in stamps if s]
        return max(stamps) if stamps else _now()

    # ---- digimon row ------------------------------------------------------
    def _upsert_digimon_row(self, entity: MatchedEntity) -> int:
        conn = self.conn
        slug = entity.canonical_slug
        row = conn.execute("SELECT id FROM digimon WHERE canonical_slug = ?", [slug]).fetchone()
        now = _now()

        # --- gather merged values from all records ---
        zh = _pick_name([n for r in entity.records if r for n in r.names], "zh_cn")
        en = _pick_name([n for r in entity.records if r for n in r.names], "en")
        ja = _pick_name([n for r in entity.records if r for n in r.names], "ja")
        rom = _pick_name([n for r in entity.records if r for n in r.names], "romanized")
        zh_hk = _pick_name([n for r in entity.records if r for n in r.names], "zh_hk")
        zh_tw = _pick_name([n for r in entity.records if r for n in r.names], "zh_tw")
        en_dub = _pick_name([n for r in entity.records if r for n in r.names], "en_dub")

        # canonical world-view values selected by documented source priority;
        # every candidate and its real source/source_id is kept for auditing.
        levels = self._field_candidates(
            entity, lambda r: parse_level(r.level_raw or r.level).value
        )
        attrs = self._field_candidates(
            entity, lambda r: parse_attribute(r.attribute_raw or r.attribute).value
        )
        level_value, level_choice = self._pick_canonical(levels)
        attr_value, attr_choice = self._pick_canonical(attrs)

        xab = any(r.x_antibody for r in entity.records if r.x_antibody is not None)
        is_official = any(r.is_official is True for r in entity.records if r.is_official is not None)

        level_raw = next((r.level_raw or r.level for r in entity.records if r and (r.level_raw or r.level)), None)
        attr_raw = next((r.attribute_raw or r.attribute for r in entity.records if r and (r.attribute_raw or r.attribute)), None)
        level_2 = next((r.extra.get("level_2") for r in entity.records if r.extra.get("level_2")), None)

        # external ids
        dapi_id = next((int(r.source_id) for r in entity.records if r.source == "dapi" and r.source_id.isdigit()), None)
        wikimon_title = next((r.source_id for r in entity.records if r.source == "wikimon"), None)
        official_slug = next((r.source_id for r in entity.records if r.source == "official"), None)
        digimons_net_slug = next((r.source_id for r in entity.records if r.source == "digimons_net"), None)

        # image: prefer dapi transparent art, then official, then wikimon
        image = self._pick_main_image(entity.records)

        # content hash (for incremental detection)
        content_hash = self._content_hash(entity)
        source_last_updated = self._source_last_updated(entity)

        # zh name "verified" reflects the chosen status on both INSERT and
        # UPDATE (previously only INSERT set it — T2.8).
        zh_verified = int(
            bool(zh) and NameStatus(zh.status) in (
                NameStatus.OFFICIAL, NameStatus.OFFICIAL_GAME,
                NameStatus.OFFICIAL_ANIME, NameStatus.COMMUNITY,
            )
        )

        if row:
            digimon_id = row["id"]
            conn.execute(
                """UPDATE digimon SET
                    canonical_slug=?, name_zh_cn=COALESCE(?, name_zh_cn),
                    name_zh_cn_source=COALESCE(?, name_zh_cn_source),
                    name_zh_cn_status=COALESCE(?, name_zh_cn_status),
                    name_zh_cn_verified=CASE WHEN ? IS NOT NULL THEN ? ELSE name_zh_cn_verified END,
                    name_en=COALESCE(?, name_en), name_ja=COALESCE(?, name_ja),
                    name_romanized=COALESCE(?, name_romanized),
                    name_zh_hk=COALESCE(?, name_zh_hk), name_zh_tw=COALESCE(?, name_zh_tw),
                    name_en_dub=COALESCE(?, name_en_dub),
                    level=?, level_raw=?, level_2=COALESCE(?, level_2), attribute=?, attribute_raw=?,
                    x_antibody=?, is_official_reference=?, main_image=COALESCE(?, main_image),
                    thumbnail=COALESCE(?, thumbnail),
                    dapi_id=COALESCE(?, dapi_id), wikimon_title=COALESCE(?, wikimon_title),
                    official_slug=COALESCE(?, official_slug),
                    digimons_net_slug=COALESCE(?, digimons_net_slug),
                    content_hash=?, source_last_updated=?, updated_at=?,
                    is_extended=?
                WHERE id=?""",
                [
                    slug, zh.value if zh else None, zh.source if zh else None,
                    zh.status if zh else None,
                    zh.value if zh else None, zh_verified,
                    en.value if en else None, ja.value if ja else None,
                    rom.value if rom else None, zh_hk.value if zh_hk else None,
                    zh_tw.value if zh_tw else None, en_dub.value if en_dub else None,
                    level_value, level_raw, level_2, attr_value, attr_raw,
                    1 if xab else 0, 1 if is_official else 0,
                    image.main if image else None, None,  # P0-1: thumbnail must be relative/NULL, never a remote URL
                    dapi_id, wikimon_title, official_slug, digimons_net_slug,
                    content_hash, source_last_updated, now, 0 if is_official else 1,
                    digimon_id,
                ],
            )
        else:
            cur = conn.execute(
                """INSERT INTO digimon(
                    canonical_slug, name_zh_cn, name_zh_cn_source, name_zh_cn_status,
                    name_zh_cn_verified, name_zh_hk, name_zh_tw, name_en, name_en_dub,
                    name_ja, name_romanized, level, level_raw, level_2, attribute, attribute_raw,
                    x_antibody, is_official_reference, is_extended, main_image, thumbnail,
                    dapi_id, wikimon_title, official_slug, digimons_net_slug,
                    content_hash, source_last_updated, updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    slug, zh.value if zh else None, zh.source if zh else None,
                    zh.status if zh else None, zh_verified,
                    zh_hk.value if zh_hk else None, zh_tw.value if zh_tw else None,
                    en.value if en else None, en_dub.value if en_dub else None,
                    ja.value if ja else None, rom.value if rom else None,
                    level_value, level_raw, level_2, attr_value, attr_raw,
                    1 if xab else 0, 1 if is_official else 0, 0 if is_official else 1,
                    image.main if image else None, None,  # P0-1: thumbnail must be relative/NULL, never a remote URL
                    dapi_id, wikimon_title, official_slug, digimons_net_slug,
                    content_hash, source_last_updated, now,
                ],
            )
            digimon_id = cur.lastrowid

        # provenance for core fields (value_hash = hash of the actual value)
        names_value = {
            "zh_cn": zh.value if zh else None,
            "en": en.value if en else None,
            "ja": ja.value if ja else None,
        }
        self._prov("digimon", digimon_id, "names", entity, value=names_value)
        self._prov("digimon", digimon_id, "level", entity, value=level_value)
        self._prov("digimon", digimon_id, "attribute", entity, value=attr_value)
        self._prov("digimon", digimon_id, "is_official_reference", entity, value=is_official)
        if image and image.main:
            self._prov("digimon", digimon_id, "main_image", entity, value=image.main)

        # record real cross-source disagreements now that the id is known
        self._record_value_conflicts("digimon", digimon_id, "level", levels, level_choice)
        self._record_value_conflicts("digimon", digimon_id, "attribute", attrs, attr_choice)
        return digimon_id

    def _pick_main_image(self, records: list[SourceDigimon]) -> Any:
        """Pick main_image + thumbnail URLs by source priority."""
        order = {"dapi": 3, "official": 2, "wikimon": 1, "digimons_net": 0, "digidb": 0, "manual": 2}
        main = None
        thumb = None
        best = -1
        for r in records:
            rank = order.get(r.source, 0)
            if r.image_url and rank > best:
                best = rank
                main = r.image_url
        for r in records:
            if r.image_url and r.image_url != main:
                thumb = r.image_url
                break
        class _Img:
            pass
        img = _Img()
        img.main = main
        img.thumb = thumb
        return img

    def _content_hash(self, entity: MatchedEntity) -> str:
        """Hash of the full normalized payload (P1-2).

        Covers every normalized field that affects the final entity — names,
        level/attribute, types/fields/groups, skills, profiles, evolutions,
        first appearance, image URLs — not just ``extra``. A change in any of
        them changes the per-entity content hash.
        """
        from pipeline.core.models import source_digimon_to_dict

        payload = json.dumps(
            [source_digimon_to_dict(r) for r in entity.records if r],
            sort_keys=True, default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _reset_derived(self, digimon_id: int) -> None:
        # digimon_relation is not reset here: it uses from/to columns and is
        # appended by the edge resolver, not by per-entity upserts.
        # digimon_image thumbnail rows are preserved across syncs: they point
        # at local derived cache files (data/images/thumbs/) that survive a
        # rebuild — only main_image rows are re-derived from source records.
        for tbl in ("digimon_alias", "digimon_type", "digimon_field", "digimon_group",
                    "digimon_skill"):
            self.conn.execute(f"DELETE FROM {tbl} WHERE digimon_id = ?", [digimon_id])
        self.conn.execute(
            "DELETE FROM digimon_image WHERE digimon_id = ? AND image_type = 'main_image'",
            [digimon_id],
        )

    # ---- field mergers -----------------------------------------------------
    def _merge_names(self, digimon_id: int, rec: SourceDigimon) -> None:
        # row's chosen primary display names (from _upsert_digimon_row)
        primary = self.conn.execute(
            "SELECT name_zh_cn, name_en, name_ja FROM digimon WHERE id = ?", [digimon_id]
        ).fetchone()
        primary_map = {"zh_cn": primary["name_zh_cn"], "en": primary["name_en"], "ja": primary["name_ja"]}
        for n in rec.names:
            if not n.value or not n.value.strip():
                continue
            # primary display names live on the digimon row; alternative names
            # (dub, regional, romanized, ko, and alternate spellings of the
            # primary languages) are indexed as searchable aliases so e.g.
            # "Omnimon" -> omegamon and dapi's "Omegamon" both resolve (§7).
            if n.language in ("zh_cn", "en", "ja"):
                chosen = primary_map.get(n.language)
                if chosen and naming.normalize_key(n.value) != naming.normalize_key(chosen):
                    self._add_alias(digimon_id, n)
                continue
            self._add_alias(digimon_id, n)

    def _add_alias(self, digimon_id: int, n: SourceName) -> None:
        alias_type = self._alias_type(n)
        self.conn.execute(
            """INSERT OR IGNORE INTO digimon_alias
               (digimon_id, alias, language, region, alias_type, source, verified)
               VALUES(?,?,?,?,?,?,?)""",
            [
                digimon_id, n.value, n.language, None, alias_type,
                n.source or "?", 0,
            ],
        )

    def _alias_type(self, n: SourceName) -> str:
        lang = n.language
        if lang == "en_dub":
            return AliasType.DUB.value
        if lang == "romanized":
            return AliasType.ROMANIZATION.value
        if lang in ("zh_hk", "zh_tw"):
            return AliasType.ALTERNATIVE_SPELLING.value
        return AliasType.OFFICIAL.value

    def _merge_types(self, digimon_id: int, rec: SourceDigimon) -> None:
        for i, t in enumerate(rec.types):
            type_id = self._ensure_type(t)
            self.conn.execute(
                "INSERT OR IGNORE INTO digimon_type(digimon_id, type_id, is_primary, source) VALUES(?,?,?,?)",
                [digimon_id, type_id, 1 if i == 0 else 0, rec.source],
            )

    def _merge_fields(self, digimon_id: int, rec: SourceDigimon) -> None:
        for f in rec.fields:
            field_id = self._ensure_field(f)
            self.conn.execute(
                "INSERT OR IGNORE INTO digimon_field(digimon_id, field_id, source) VALUES(?,?,?)",
                [digimon_id, field_id, rec.source],
            )

    def _merge_groups(self, digimon_id: int, rec: SourceDigimon) -> None:
        for g in rec.groups:
            group_id = self._ensure_group(g)
            self.conn.execute(
                "INSERT OR IGNORE INTO digimon_group(digimon_id, group_id, source) VALUES(?,?,?)",
                [digimon_id, group_id, rec.source],
            )

    def _merge_skills(self, digimon_id: int, rec: SourceDigimon) -> None:
        for i, s in enumerate(rec.skills):
            skill_id = self._ensure_skill(s)
            self.conn.execute(
                """INSERT OR IGNORE INTO digimon_skill
                   (digimon_id, skill_id, skill_type, is_signature, source, sort_order)
                   VALUES(?,?,?,?,?,?)""",
                [digimon_id, skill_id, s.skill_type or "special_move",
                 1 if s.is_signature else 0, rec.source, i],
            )

    def _merge_profiles(self, digimon_id: int, records: list[SourceDigimon]) -> None:
        """Merge profile text per language by documented source priority."""
        for lang, col in (("zh_cn", "profile_zh_cn"), ("en", "profile_en"), ("ja", "profile_ja")):
            best: tuple[str, SourceDigimon] | None = None
            best_prio = -1
            for r in records:
                text = (r.profile.get(lang) or "").strip()
                if not text:
                    continue
                prio = SOURCE_PRIORITY.get(r.source, 0)
                if prio > best_prio:
                    best = (text, r)
                    best_prio = prio
            if best is None:
                continue
            text, rec = best
            # P1-2: never show raw wikitext to users. If a profile still carries
            # unresolved {{...}}/[[...]] after cleaning, strip it for the visible
            # value and preserve the original in the review queue.
            if "{{" in text or "[[" in text:
                visible = strip_residual_markup(text)
                self.conn.execute(
                    f"UPDATE digimon SET {col}=?, profile_source=?, profile_source_url=? WHERE id=?",
                    [visible or None, rec.source, rec.extra.get("source_url"), digimon_id],
                )
                self._queue_wikitext_review(digimon_id, f"profile_{lang}", text)
            else:
                self.conn.execute(
                    f"UPDATE digimon SET {col}=?, profile_source=?, profile_source_url=? WHERE id=?",
                    [text, rec.source, rec.extra.get("source_url"), digimon_id],
                )
            self._prov("digimon", digimon_id, f"profile_{lang}", rec, value=text)

    def _merge_image(self, digimon_id: int, rec: SourceDigimon) -> None:
        if not rec.image_url:
            return
        # P0-1 contract: local_path is stored CACHE-ROOT-RELATIVE (or NULL). If a
        # local cached file for this digimon already exists, preserve the
        # 'downloaded' state across syncs (files are keyed digi_<id>_<...>).
        local = None
        status = "pending"
        from pipeline.core.images import cache_root_for, to_cache_relative

        cache_root = cache_root_for(None, conn=self.conn)
        try:
            for f in cache_root.glob(f"digi_{digimon_id:05d}_*"):
                local = to_cache_relative(cache_root, f)
                status = "downloaded"
                break
        except OSError:
            pass
        self.conn.execute(
            """INSERT INTO digimon_image
               (digimon_id, image_type, remote_url, source_page, local_path, download_status)
               VALUES(?,?,?,?,?,?)""",
            [digimon_id, "main_image", rec.image_url, rec.image_page, local, status],
        )
        # a surviving local thumbnail (derived cache under data/images/thumbs/)
        # is preserved across syncs and keeps digimon.thumbnail populated.
        thumb = self.conn.execute(
            "SELECT local_path FROM digimon_image WHERE digimon_id=? AND image_type='thumbnail'",
            [digimon_id],
        ).fetchone()
        if thumb and thumb["local_path"]:
            self.conn.execute(
                "UPDATE digimon SET thumbnail=? WHERE id=?",
                [thumb["local_path"], digimon_id],
            )

    def _merge_first_appearance(self, digimon_id: int, records: list[SourceDigimon]) -> None:
        """Pick first-appearance fields from the highest-priority source."""
        best_prio = -1
        best: SourceDigimon | None = None
        for r in records:
            if not (r.first_appearance_title or r.first_appearance_date):
                continue
            prio = SOURCE_PRIORITY.get(r.source, 0)
            if prio > best_prio:
                best = r
                best_prio = prio
        if best is None:
            return
        if best.first_appearance_title:
            self.conn.execute(
                "UPDATE digimon SET first_appearance_title = COALESCE(?, first_appearance_title), "
                "first_appearance_medium = COALESCE(?, first_appearance_medium) WHERE id = ?",
                [best.first_appearance_title, best.first_appearance_medium, digimon_id],
            )
            self._prov("digimon", digimon_id, "first_appearance_title", best,
                       value=best.first_appearance_title)
        if best.first_appearance_date:
            self.conn.execute(
                "UPDATE digimon SET first_appearance_date = COALESCE(?, first_appearance_date) WHERE id = ?",
                [best.first_appearance_date, digimon_id],
            )
            self._prov("digimon", digimon_id, "first_appearance_date", best,
                       value=best.first_appearance_date)

    def _merge_name_origin(self, digimon_id: int, records: list[SourceDigimon]) -> None:
        """Pick name origin from the highest-priority source that provides one."""
        best_prio = -1
        best: SourceDigimon | None = None
        for r in records:
            if not r.name_origin:
                continue
            prio = SOURCE_PRIORITY.get(r.source, 0)
            if prio > best_prio:
                best = r
                best_prio = prio
        if best and best.name_origin:
            text = best.name_origin
            # P1-2: strip residual wikitext for the visible value; keep the
            # original in the review queue so nothing is silently deleted.
            if "{{" in text or "[[" in text:
                visible = strip_residual_markup(text)
                self.conn.execute(
                    "UPDATE digimon SET name_origin = COALESCE(?, name_origin) WHERE id = ?",
                    [visible or None, digimon_id],
                )
                self._queue_wikitext_review(digimon_id, "name_origin", text)
            else:
                self.conn.execute(
                    "UPDATE digimon SET name_origin = COALESCE(?, name_origin) WHERE id = ?",
                    [text, digimon_id],
                )
            self._prov("digimon", digimon_id, "name_origin", best, value=text)

    def _queue_wikitext_review(self, digimon_id: int, field: str, text: str) -> None:
        """Flag a user-visible field that still carries unresolved wikitext."""
        slug_row = self.conn.execute(
            "SELECT canonical_slug FROM digimon WHERE id=?", [digimon_id]
        ).fetchone()
        self.queue_review(
            "digimon", digimon_id,
            f"{field} contains unresolved wikitext (P1-2)",
            {"canonical_slug": slug_row["canonical_slug"] if slug_row else None,
             "field": field, "value": text[:300]},
        )

    # ---- evolution edges ---------------------------------------------------
    def add_edge(self, from_id: int, to_id: int, evolution_type: str = "normal",
                 condition: str | None = None, source: str | None = None,
                 is_primary_line: bool = False, confidence: str = "high") -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO evolution_edge
               (from_digimon_id, to_digimon_id, evolution_type, condition, source,
                confidence, is_primary_line)
               VALUES(?,?,?,?,?,?,?)""",
            [from_id, to_id, evolution_type, condition, source, confidence,
             1 if is_primary_line else 0],
        )

    def add_relation(self, from_id: int, to_id: int, relation_type: str,
                     source: str | None = None, note: str | None = None) -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO digimon_relation
               (from_digimon_id, to_digimon_id, relation_type, source, note)
               VALUES(?,?,?,?,?)""",
            [from_id, to_id, relation_type, source, note],
        )

    # ---- provenance / conflicts --------------------------------------------
    def _prov(self, entity_type: str, entity_id: int, field: str,
              rec: SourceDigimon | MatchedEntity, *, value: Any = None,
              source_url: str | None = None) -> None:
        if isinstance(rec, SourceDigimon):
            source = rec.source
            url = source_url or rec.extra.get("source_url")
        else:
            source = ",".join(sorted({r.source for r in rec.records if r}))
            url = None
        # value_hash is the hash of the *normalized field value* itself, so a
        # change in the value (not just the source metadata) is detectable.
        value_hash = (
            hashlib.sha256(json.dumps(value, default=str, sort_keys=True).encode("utf-8")).hexdigest()[:16]
            if value is not None else None
        )
        self.conn.execute(
            """INSERT OR IGNORE INTO provenance
               (entity_type, entity_id, field, source, source_url, retrieved_at, confidence, value_hash, run_id)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            [entity_type, entity_id, field, source, url, _now(), "high", value_hash, self.run_id],
        )

    def _record_value_conflicts(self, entity_type: str, entity_id: int, field: str,
                                candidates: list[tuple[str, str, str]], choice: dict | None) -> None:
        """Record a real cross-source disagreement, keeping every candidate.

        ``candidates`` is [(canonical_value, source, source_id)]. "unknown"
        placeholders are not disagreements. The chosen value/source comes from
        the documented SOURCE_PRIORITY selection (never "first input source").
        A tie that cannot be safely resolved is flagged review_status='review'
        and also queued for manual review.
        """
        distinct: dict[str, dict[str, Any]] = {}
        for v, s, sid in candidates:
            if v is None or v == "unknown":
                continue
            prio = SOURCE_PRIORITY.get(s, 0)
            if v not in distinct or prio > distinct[v]["prio"]:
                distinct[v] = {"source": s, "source_id": sid, "prio": prio}
        if len(distinct) < 2:
            return
        items = list(distinct.items())  # [(value, {source, source_id, prio})]
        (va, ca), (vb, cb) = items[0], items[1]
        resolution = choice["reason"] if choice else "unresolved"
        review_status = "review" if (choice and choice["needs_review"]) else "auto"
        self.conn.execute(
            """INSERT OR IGNORE INTO data_conflict
               (entity_type, entity_id, field, source_a, source_id_a, value_a,
                source_b, source_id_b, value_b, chosen_value, chosen_source,
                candidates, review_status, resolution)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                entity_type, entity_id, field,
                ca["source"], ca["source_id"], va,
                cb["source"], cb["source_id"], vb,
                choice["value"] if choice else None,
                choice["source"] if choice else None,
                json.dumps(choice["candidates"] if choice else [], ensure_ascii=False),
                review_status, resolution,
            ],
        )
        if review_status == "review":
            self.queue_review(
                entity_type, entity_id,
                f"{field} conflict cannot be resolved by source priority",
                {"field": field, "candidates": choice["candidates"] if choice else [],
                 "reason": resolution},
            )

    def queue_review(self, entity_type: str, entity_id: int | None, reason: str, detail: Any) -> None:
        self.conn.execute(
            """INSERT INTO manual_review_queue(entity_type, entity_id, reason, detail, run_id)
               VALUES(?,?,?,?,?)""",
            [entity_type, entity_id, reason, json.dumps(detail, ensure_ascii=False, default=str),
             self.run_id],
        )

    # ---- finalize -----------------------------------------------------------
    def rebuild_fts(self) -> None:
        conn = self.conn
        # contentless FTS5 tables don't allow DELETE — use the 'delete-all' command
        conn.execute(
            "INSERT INTO digimon_fts(digimon_fts, rowid, canonical_slug, name_zh_cn, name_en, "
            "name_ja, name_romanized, name_en_dub, aliases) "
            "VALUES('delete-all', 0, '', '', '', '', '', '', '')"
        )
        rows = conn.execute(
            """SELECT d.id, d.canonical_slug, d.name_zh_cn, d.name_en, d.name_ja,
                      d.name_romanized, d.name_en_dub,
                      (SELECT GROUP_CONCAT(alias, ' ') FROM digimon_alias a WHERE a.digimon_id = d.id) AS aliases
               FROM digimon d"""
        ).fetchall()
        conn.executemany(
            "INSERT INTO digimon_fts(rowid, canonical_slug, name_zh_cn, name_en, name_ja, name_romanized, name_en_dub, aliases) VALUES(?,?,?,?,?,?,?,?)",
            [
                (r["id"], r["canonical_slug"] or "", r["name_zh_cn"] or "", r["name_en"] or "",
                 r["name_ja"] or "", r["name_romanized"] or "", r["name_en_dub"] or "",
                 r["aliases"] or "")
                for r in rows
            ],
        )

    def write_snapshot(self, notes: str | None = None) -> dict[str, int]:
        counts = self.conn.execute(
            """SELECT
                (SELECT COUNT(*) FROM digimon) AS total,
                (SELECT COUNT(*) FROM digimon WHERE is_official_reference = 1) AS official,
                (SELECT COUNT(*) FROM digimon WHERE is_extended = 1 AND is_official_reference = 0) AS extended"""
        ).fetchone()
        self.conn.execute(
            """INSERT INTO snapshot(snapshot_date, official_count, extended_count, total_count, notes)
               VALUES(?,?,?,?,?)""",
            [_now()[:10], counts["official"], counts["extended"], counts["total"], notes],
        )
        self.conn.commit()
        return {"total": counts["total"], "official": counts["official"], "extended": counts["extended"]}

    def commit(self) -> None:
        self.conn.commit()
