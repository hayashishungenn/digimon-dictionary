"""digimons.net adapter — 简体中文名字来源（社区可靠长期译名）。

digimons.net is a Simplified-Chinese fan database (content CC BY-SA). Its
`sort.html` index is a single table where each <tr> is:
    [链接(点击图鉴 -> slug/index.html)] [等级] [日文名] [英文名] [中文名]

We use it strictly as a Chinese-name overlay; names are marked status=community
(a reliable long-standing Chinese database), never official. Site requires
plain HTTP (https returns 403).
"""
from __future__ import annotations

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from pipeline.core.models import SourceDigimon, SourceName
from pipeline.sources.base import SourceAdapter, save_raw

logger = logging.getLogger(__name__)

BASE = "http://www.digimons.net/digimon"
_SLUG_RE = re.compile(r"([^/]+)/index\.html")


class DigimonsNetAdapter(SourceAdapter):
    source = "digimons_net"

    def __init__(self, rate_per_second: float = 1.5) -> None:
        self.rate_per_second = rate_per_second

    def _make_fetcher(self, fetcher: Any) -> Any:
        from pipeline.core.request import Fetcher

        return Fetcher(
            rate_per_second=self.rate_per_second,
            max_concurrency=2,
            cache_dir=fetcher._cache_dir,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DigiDex/0.1 research"},
        )

    def _fetch_sort_index(self, fetcher: Any) -> str:
        html = fetcher.get(f"{BASE}/sort.html").text
        save_raw("digimons_net", "sort_index", html, meta={"source_url": f"{BASE}/sort.html"})
        return html

    def fetch(self, fetcher: Any, force: bool = False) -> list[SourceDigimon]:
        df = self._make_fetcher(fetcher)
        html = self._fetch_sort_index(df)
        soup = BeautifulSoup(html, "lxml")

        records: list[SourceDigimon] = []
        seen: set[str] = set()
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue
            link = tds[0].find("a")
            if not link or not link.get("href"):
                continue
            m = _SLUG_RE.search(link["href"])
            if not m:
                continue
            slug = m.group(1)
            if slug in seen:
                continue
            seen.add(slug)

            level = tds[1].get_text(" ", strip=True)
            ja = tds[2].get_text(" ", strip=True)
            en = tds[3].get_text(" ", strip=True)
            zh = tds[4].get_text(" ", strip=True)

            rec = SourceDigimon(
                source="digimons_net",
                source_id=slug,
                extra={"source_url": f"{BASE}/{slug}/index.html"},
            )
            if zh and zh not in ("?", "暂无"):
                rec.names.append(SourceName(zh, "zh_cn", status="community", source="digimons_net"))
            if en and en != zh:
                rec.names.append(SourceName(en, "en", status="community", source="digimons_net"))
            if ja and ja != en:
                rec.names.append(SourceName(ja, "ja", status="community", source="digimons_net"))
            if level:
                rec.level_raw = level
            records.append(rec)
        save_raw("digimons_net", "records", [r.source_id for r in records],
                 meta={"source_url": f"{BASE}/sort.html", "count": len(records)})
        df.close()
        logger.info("digimons_net: %d records from sort index", len(records))
        return records
