"""Official Digimon Reference Book adapter (digimon.net).

Data obtained from digimon.net. Copyright statement on the site prohibits
unauthorized reuse of images, text, and data; we therefore only read metadata
for personal research use, never redistribute it, and never download official
images (digi-api / Wikimon images are used for display instead).

Strategy (verified against live HTML):
  - request.php list API in ja/en/zh-CHS (14 pages x 96 each = 1,316 digimon)
    returns localized names, localized levels, X-Antibody marker (relate_word6).
  - detail.php?directory_name=<slug> (EN) is server-rendered HTML containing
    Type / Attribute / Special Move / Profile / related digimon.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup

from pipeline.core.models import SourceDigimon, SourceName
from pipeline.sources.base import SourceAdapter, save_raw

logger = logging.getLogger(__name__)

REFERENCE_URL = "https://digimon.net"
LIST_PAGE_SIZE = 96
PAGE_COUNT = 14  # 13 full pages + partial; we paginate until next == -1

LANGUAGES = {
    "ja": "reference",
    "en": "reference_en",
    "zh_cn": "reference_zh-CHS",
}

_XAB_RE = re.compile(r"〇")  # "〇" marks X-Antibody in relate_word6


@dataclass
class ListRow:
    directory_name: str
    name: str
    level: str | None
    level_2: str | None
    x_antibody: bool
    icon_20th: bool
    icon_new: bool


def parse_list_rows(payload: dict[str, Any], lang: str) -> list[ListRow]:
    rows: list[ListRow] = []
    for raw in payload.get("rows", []):
        rows.append(
            ListRow(
                directory_name=raw.get("directory_name", ""),
                name=raw.get("name") or "",
                level=raw.get("level"),
                level_2=raw.get("level_2"),
                x_antibody=bool(_XAB_RE.search(raw.get("relate_word6") or "")),
                icon_20th=bool(raw.get("icon_20th")),
                icon_new=bool(raw.get("icon_new")),
            )
        )
    return rows


class OfficialAdapter(SourceAdapter):
    source = "official"

    def __init__(self, languages: tuple[str, ...] = ("ja", "en", "zh_cn"),
                 fetch_details: bool = True) -> None:
        self.languages = languages
        self.fetch_details = fetch_details

    def _make_fetcher(self, fetcher: Any) -> Any:
        """The reference site's AJAX endpoint requires browser-like headers."""
        from pipeline.core.request import Fetcher

        return Fetcher(
            rate_per_second=1.0,
            max_concurrency=2,
            cache_dir=fetcher._cache_dir,
            headers={
                "Referer": f"{REFERENCE_URL}/reference_en/",
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
                ),
            },
        )

    # ---------------------------------------------------------------- lists
    def _fetch_list(self, fetcher: Any, lang: str) -> list[ListRow]:
        sub = LANGUAGES[lang]
        url = f"{REFERENCE_URL}/{sub}/request.php"
        all_rows: list[ListRow] = []
        offset = 0
        pages: list[dict[str, Any]] = []
        while offset <= 5000:  # defensive cap (expected: 0..1248)
            payload = fetcher.get_json(
                url,
                params={
                    "digimon_name": "",
                    "name": "",
                    "digimon_level": "",
                    "attribute": "",
                    "type": "",
                    "next": offset,
                    "view_more": "",
                },
            )
            pages.append(payload)
            all_rows.extend(parse_list_rows(payload, lang))
            next_off = payload.get("next")
            if next_off is None or int(next_off) == -1 or int(next_off) <= offset:
                break
            offset = int(next_off)
        save_raw("official", f"list_{lang}", pages, meta={"source_url": url, "language": lang})
        return all_rows

    # -------------------------------------------------------------- details
    def _fetch_detail(self, fetcher: Any, slug: str) -> dict[str, Any]:
        url = f"{REFERENCE_URL}/reference_en/detail.php"
        html = fetcher.get(url, params={"directory_name": slug}).text
        soup = BeautifulSoup(html, "lxml")
        out: dict[str, Any] = {"slug": slug}

        # info dl: Level / Type / Attribute / Special Move
        info = soup.select_one(".p-ref__info")
        if info:
            for dl in info.find_all("dl"):
                dt = dl.find("dt")
                dd = dl.find("dd")
                if dt and dd:
                    key = dt.get_text(strip=True)
                    out[f"info_{key.lower().replace(' ', '_')}"] = dd.get_text(" ", strip=True)

        # profile
        prof = soup.select_one(".p-ref__txt")
        if prof:
            out["profile"] = prof.get_text(" ", strip=True)

        # related digimon
        related: list[dict[str, str]] = []
        for li in soup.select(".p-refRelationList"):
            a = li.select_one("a")
            name = li.select_one(".p-refRelationList__name")
            if a and name:
                href = a.get("href", "")
                m = re.search(r"directory_name=([^&]+)", href)
                related.append({"slug": m.group(1) if m else "", "name": name.get_text(strip=True)})
        out["related"] = related
        return out

    # ------------------------------------------------------------- pipeline
    def fetch(self, fetcher: Any, force: bool = False) -> list[SourceDigimon]:
        of = self._make_fetcher(fetcher)
        # 1. lists per language -> slug -> per-language names/levels/xab
        slug_names: dict[str, dict[str, str]] = {}  # slug -> {lang: name}
        slug_levels: dict[str, dict[str, str]] = {}
        slug_xab: dict[str, bool] = {}
        all_slugs: list[str] = []
        for lang in self.languages:
            rows = self._fetch_list(of, lang)
            logger.info("official: %s list -> %d rows", lang, len(rows))
            for r in rows:
                all_slugs.append(r.directory_name)
                slug_names.setdefault(r.directory_name, {})[lang] = r.name
                if r.level:
                    slug_levels.setdefault(r.directory_name, {})[lang] = r.level
                slug_xab[r.directory_name] = slug_xab.get(r.directory_name, False) or r.x_antibody

        # de-dup slugs while preserving first-seen order
        seen: set[str] = set()
        slugs: list[str] = []
        for s in all_slugs:
            if s not in seen:
                seen.add(s)
                slugs.append(s)
        logger.info("official: total unique slugs = %d", len(slugs))

        # 2. details (EN) for type/attribute/skill/profile
        details: dict[str, dict[str, Any]] = {}
        if self.fetch_details:
            for i, slug in enumerate(slugs):
                try:
                    details[slug] = self._fetch_detail(of, slug)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("official detail failed for %s: %s", slug, exc)
                    details[slug] = {"slug": slug}
                if i and i % 100 == 0:
                    logger.info("official: fetched %d/%d details", i, len(slugs))
            save_raw(
                "official", "details_en", details,
                meta={"source_url": f"{REFERENCE_URL}/reference_en/detail.php", "count": len(details)},
            )

        # 3. build SourceDigimon records
        records: list[SourceDigimon] = []
        for slug in slugs:
            rec = SourceDigimon(
                source="official",
                source_id=slug,
                x_antibody=slug_xab.get(slug, False),
                is_official=True,
                extra={"source_url": f"{REFERENCE_URL}/reference_en/detail.php?directory_name={slug}"},
            )
            # names from lists
            names_by_lang = slug_names.get(slug, {})
            if names_by_lang.get("ja"):
                rec.names.append(SourceName(names_by_lang["ja"], "ja", status="official", source="official"))
            if names_by_lang.get("en"):
                rec.names.append(SourceName(names_by_lang["en"], "en", status="official", source="official"))
            if names_by_lang.get("zh_cn"):
                rec.names.append(SourceName(names_by_lang["zh_cn"], "zh_cn", status="official", source="official"))
            # levels per language (store raw; normalize later)
            levels = slug_levels.get(slug, {})
            if levels.get("en"):
                rec.level_raw = levels["en"]
            elif levels.get("ja"):
                rec.level_raw = levels["ja"]
            rec.extra["level_ja"] = levels.get("ja")
            rec.extra["level_zh"] = levels.get("zh_cn")

            d = details.get(slug, {})
            if d.get("info_type"):
                rec.types.append(d["info_type"])
            if d.get("info_attribute"):
                rec.attribute_raw = d["info_attribute"]
            if d.get("info_special_move"):
                sm = d["info_special_move"].lstrip("・").strip()
                rec.skills.append(_mk_skill(sm, "en", source="official"))
            if d.get("profile"):
                rec.profile["en"] = d["profile"]
            # related digimon -> relation (NOT evolution; official "related" lists)
            rel = d.get("related", [])
            if rel:
                rec.extra["related"] = rel
            records.append(rec)
        return records


def _mk_skill(name: str, lang: str, *, source: str | None = None) -> Any:
    from pipeline.core.models import SourceSkill

    return SourceSkill(names={lang: name}, skill_type="special_move", source=source)
