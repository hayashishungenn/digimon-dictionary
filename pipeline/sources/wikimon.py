"""Wikimon (https://wikimon.net/) adapter.

Wikimon is a MediaWiki wiki; content is CC-BY-SA 3.0. Key facts verified live:
  - open MediaWiki API: action=query&prop=revisions&rvprop=content&rvslots=main
  - every digimon page embeds the {{S2}} infobox template with fields:
      kan (Japanese name), dub (English dub), ol (CHI/ZHO/KOR other-language
      names), l1/a1/t1 (level/attribute/type), f1..fN (fields), g1 (group),
      s1..sN (related forms), pn/pe/pj (profile blocks)
  - ==Evolves From== / ==Evolves To== bullet lists; '''bold''' = primary line,
    conditions in parentheses; generic card-game lines are noise.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from pipeline.core.models import SourceDigimon, SourceName, SourceSkill
from pipeline.sources.base import SourceAdapter, save_raw
from pipeline.sources.wikitext import (
    extract_template,
    extract_wiki_section,
    parse_ol_field,
    strip_markup,
    strip_markup_keep_templates,
)

logger = logging.getLogger(__name__)

WIKIMON_API = "https://wikimon.net/api.php"
WIKIMON_RATE = 2.0

# All page titles carry redirects; skip them.
_REDIRECT_RE = re.compile(r"^\s*#redirect\s*\[\[", re.IGNORECASE)
# noise evolution bullets (generic rules, not canonical digimon-to-digimon)
_JUNK_RE = re.compile(
    r"(card game|battle spirits|any \w+ lv\.|also evolves from|any digimon|any adult|"
    r"any child|any armor|any \w+ digimon from|adventure lv|black lv|blue lv|red lv|"
    r"green lv|yellow lv|hero lv|cs lv|dm lv|st lv|bt lv|ex lv|p-00)",
    re.IGNORECASE,
)

_LANG_JA = ("kan", "ja", "official", "wikimon")
_LANG_EN = ("dub", "en", "official", "wikimon")


class WikimonAdapter(SourceAdapter):
    source = "wikimon"

    def __init__(self, rate_per_second: float = WIKIMON_RATE, batch_size: int = 40) -> None:
        self.rate_per_second = rate_per_second
        self.batch_size = batch_size

    # ------------------------------------------------------------ enumeration
    def _all_pages(self, fetcher: Any) -> list[str]:
        """Enumerate digimon page titles via Category:Digimon (≈1,650 members).

        allpages over the whole wiki returns ~14,000 articles (attacks, items,
        games, ...) — far too noisy. Category:Digimon is the precise set.
        """
        titles: list[str] = []
        cmcontinue = ""
        while True:
            params = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": "Category:Digimon",
                "cmlimit": 500,
                "format": "json",
            }
            if cmcontinue:
                params["cmcontinue"] = cmcontinue
            payload = fetcher.get_json(WIKIMON_API, params=params)
            members = payload.get("query", {}).get("categorymembers", [])
            for m in members:
                titles.append(m.get("title", ""))
            cont = payload.get("continue")
            if not cont or not cont.get("cmcontinue"):
                break
            cmcontinue = cont["cmcontinue"]
        titles = [t for t in titles if t]
        save_raw("wikimon", "all_pages", titles, meta={"source_url": WIKIMON_API, "count": len(titles)})
        return titles

    # ------------------------------------------------------------- wikitext
    def _fetch_wikitexts(self, fetcher: Any, titles: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(titles), self.batch_size):
            batch = titles[i : i + self.batch_size]
            params = {
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
                "titles": "|".join(batch),
            }
            try:
                payload = fetcher.get_json(WIKIMON_API, params=params)
            except Exception as exc:  # noqa: BLE001
                logger.warning("wikitext fetch failed for batch %d: %s", i, exc)
                continue
            for page in payload.get("query", {}).get("pages", {}).values():
                if "revisions" not in page:
                    continue
                try:
                    content = page["revisions"][0]["slots"]["main"]["*"]
                    out[page["title"]] = content
                except (KeyError, IndexError):
                    continue
            if i and i % 400 == 0:
                logger.info("wikimon wikitext: %d/%d titles", i, len(titles))
        return out

    # ---------------------------------------------------------------- parse
    def _parse_page(self, title: str, content: str) -> SourceDigimon | None:
        if _REDIRECT_RE.match(content):
            return None
        found = extract_template(content, "S2")
        if not found:
            return None  # not a digimon infobox page
        params, _ = found
        pd = dict(params)
        names: list[SourceName] = []
        kan = (pd.get("kan") or "").strip()
        if kan:
            names.append(SourceName(kan, "ja", status="official", source="wikimon"))
        name_en = title
        if not title.startswith("Digimon"):
            names.append(SourceName(title, "en", status="community", source="wikimon"))
        dub = (pd.get("dub") or "").strip()
        if dub and dub.lower() != title.lower():
            names.append(SourceName(dub, "en_dub", status="official", source="wikimon"))
        ol = parse_ol_field(pd.get("ol", ""))
        for lang, value in ol.items():
            if lang == "zh_cn":
                names.append(SourceName(value, "zh_cn", status="community", source="wikimon"))
            elif lang == "zh_tw":
                names.append(SourceName(value, "zh_tw", status="community", source="wikimon"))
            elif lang == "ko":
                names.append(SourceName(value, "ko", status="community", source="wikimon"))

        rec = SourceDigimon(
            source="wikimon",
            source_id=title,
            names=names,
            extra={"source_url": f"https://wikimon.net/{title.replace(' ', '_')}"},
        )

        # Official Reference Book status: drbentry present => officially registered
        drbentry = (pd.get("drbentry") or "").strip()
        if drbentry and "{{DRBEntry" in drbentry:
            rec.is_official = True
            m = re.search(r"{{DRBEntry\|([^|}]+)", drbentry)
            if m:
                rec.extra["drb_entry"] = m.group(1).strip()

        l1 = (pd.get("l1") or "").strip()
        if l1:
            rec.level_raw = l1
        a1 = (pd.get("a1") or "").strip()
        if a1:
            rec.attribute_raw = a1
        t = (pd.get("t1") or "").strip()
        if t:
            rec.types.append(t)
        if pd.get("t2"):
            rec.types.append((pd.get("t2") or "").strip())
        for i in range(1, 8):
            f = (pd.get(f"f{i}") or "").strip()
            if f and f.lower() != "unknown":
                rec.fields.append(f)
        g1 = (pd.get("g1") or "").strip()
        if g1:
            rec.groups.append(g1)

        # name origin (ety) + design year (yd)
        ety = (pd.get("ety") or "").strip()
        if ety:
            rec.name_origin = strip_markup(ety)
        yd = (pd.get("yd") or "").strip()
        if yd and yd.isdigit():
            rec.extra["design_year"] = yd
            if not rec.first_appearance_date:
                rec.first_appearance_date = yd

        # profiles: pn=N label, pe=N english, pj=N japanese (n can have sub-indexes)
        for key, value in pd.items():
            if re.fullmatch(r"pe\d*[a-z]*", key) and value.strip():
                rec.profile.setdefault("en", value.strip())
            if re.fullmatch(r"pj\d*[a-z]*", key) and value.strip():
                rec.profile.setdefault("ja", value.strip())

        # special moves referenced via {{AT|Name}} / {{ATK|Name}} inside profiles
        seen_sm: set[str] = set()
        for lang in ("en", "ja"):
            text = rec.profile.get(lang, "")
            for m in re.finditer(r"\{\{\s*AT(?:K)?\s*\|([^|}]+)", text):
                name = m.group(1).strip()
                if name and name not in seen_sm:
                    seen_sm.add(name)
                    rec.skills.append(
                        SourceSkill(names={lang: name}, skill_type="special_move", source="wikimon")
                    )

        # related forms from s1..sN
        for i in range(1, 16):
            s = (pd.get(f"s{i}") or "").strip()
            if s:
                rec.extra.setdefault("related", []).append({"slug": s, "name": s})

        # evolution sections
        for ref, direction in ((extract_wiki_section(content, "Evolves From"), "from"),
                               (extract_wiki_section(content, "Evolves To"), "to")):
            for bullet in ref:
                if _JUNK_RE.search(bullet):
                    continue
                m = re.search(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]", bullet)
                if not m:
                    continue
                target = m.group(2) or m.group(1)
                if _JUNK_RE.search(target):
                    continue
                is_primary = bool(re.match(r"\*\s*'{2,}", bullet))
                cond = ""
                # condition lives in the FIRST parenthesized group BEFORE any
                # {{template}}/ref markup (refs like "{{rfc|BT12|059 (DCG)}}"
                # contain "(DCG)" which is not an evolution condition)
                after = bullet[m.end():]
                pre = after.split("{{")[0]
                cm = re.search(r"\((.*?)\)", pre)
                if cm:
                    cond = cm.group(1).strip()
                if direction == "from":
                    rec.evolves_from.append(target)
                    rec.conditions[f"from:{target}"] = cond
                    if is_primary:
                        rec.extra.setdefault("primary_from", []).append(target)
                else:
                    rec.evolves_to.append(target)
                    rec.conditions[f"to:{target}"] = cond
                    if is_primary:
                        rec.extra.setdefault("primary_to", []).append(target)
        return rec

    # ------------------------------------------------------------- pipeline
    def fetch(self, fetcher: Any, force: bool = False) -> list[SourceDigimon]:
        from pipeline.core.request import Fetcher

        wf = Fetcher(
            rate_per_second=self.rate_per_second,
            max_concurrency=2,
            cache_dir=fetcher._cache_dir,
        )
        titles = self._all_pages(wf)
        logger.info("wikimon: %d pages enumerated", len(titles))

        # Fetch in batches; save checkpoint after each 1000.
        records: list[SourceDigimon] = []
        wikitexts: dict[str, str] = {}
        for i in range(0, len(titles), self.batch_size):
            batch = titles[i : i + self.batch_size]
            wikitexts.update(self._fetch_wikitexts(wf, batch))
            if i and i % 800 == 0:
                logger.info("wikimon wikitext fetched: %d", len(wikitexts))
        save_raw("wikimon", "wikitexts", wikitexts,
                 meta={"source_url": WIKIMON_API, "count": len(wikitexts)})

        for title, content in wikitexts.items():
            rec = self._parse_page(title, content)
            if rec is not None:
                records.append(rec)
        logger.info("wikimon: %d digimon records parsed", len(records))
        wf.close()
        return records
