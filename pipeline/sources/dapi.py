"""Digi-API (https://digi-api.com/) adapter.

Structure verified against live responses (2026-08-13):
  GET /api/v1/digimon?pageSize=1000
      -> {"content":[{id,name,href,image}...], "pageable":{totalElements:1488,...}}
  GET /api/v1/digimon/{id}
      -> {"id","name","xAntibody","images":[{"href","transparent"}],
          "levels":[{"level"}],"types":[{"type"}],"attributes":[{"attribute"}],
          "fields":[{"field"}],"releaseDate","descriptions":[{"origin","language","description"}],
          "skills":[{"skill","translation","description"}],
          "priorEvolutions":[{"id","digimon","condition"}],
          "nextEvolutions":[{"id","digimon","condition"}]}

Notes:
  - digi-api provides English names only (no Japanese / Chinese name field).
  - priorEvolutions / nextEvolutions are loose "can evolve in some work" edges
    (many carry jogress conditions like "with V-mon"). We record them with
    confidence=medium, primary_line=false and keep the raw condition.
"""
from __future__ import annotations

import logging
from typing import Any

from pipeline.core.models import SourceDigimon, SourceName, SourceSkill
from pipeline.sources.base import SourceAdapter, save_raw

logger = logging.getLogger(__name__)

API_BASE = "https://digi-api.com/api/v1"
DAPI_RATE = 2.0  # requests/second; polite


def _first_name(rec: dict[str, Any], key: str) -> str | None:
    arr = rec.get(key) or []
    if not arr:
        return None
    # digi-api items use the singular field name, e.g. {"level": "Child"}.
    # digi-api sometimes lists "Unknown"/"None" FIRST even when a real value
    # exists later — skip placeholder values and prefer a concrete one.
    for item in arr:
        v = (item.get("name") or item.get(key.rstrip("s")) or "").strip()
        if not v:
            continue
        if v.lower() in ("unknown", "none", "no data", "no attribute", "not applicable", "no level"):
            continue
        return v
    return arr[0].get("name") or arr[0].get(key.rstrip("s")) or None


class DapiAdapter(SourceAdapter):
    source = "dapi"

    def __init__(self, rate_per_second: float = DAPI_RATE, max_concurrency: int = 2) -> None:
        self.rate_per_second = rate_per_second
        self.max_concurrency = max_concurrency

    def _fetch_all_ids(self, fetcher: Any) -> tuple[list[dict[str, Any]], bool, int | None]:
        """Fetch the full list via pageSize=1000 pagination.

        NOTE: digi-api's `pageable.totalPages` is unreliable (reports 1 even
        when more pages exist), so pagination must NOT trust totalPages. We
        stop when a page returns fewer rows than pageSize (or an empty page).
        Returns ``(content, complete, expected)`` — ``complete`` is False when
        the defensive page cap was reached without a short page (P1-02).
        """
        content: list[dict[str, Any]] = []
        complete = False
        expected: int | None = None
        page = 0
        while page <= 50:  # defensive cap (2 pages expected)
            payload = fetcher.get_json(
                f"{API_BASE}/digimon", params={"pageSize": 1000, "page": page}
            )
            page_content = payload.get("content", [])
            if expected is None:
                expected = (payload.get("pageable") or {}).get("totalElements")
                if isinstance(expected, bool):
                    expected = None
            content.extend(page_content)
            if not page_content or len(page_content) < 1000:
                complete = True  # short page -> pagination ended naturally
                break
            page += 1
        save_raw("dapi", "list", content, meta={"source_url": f"{API_BASE}/digimon", "total": len(content)})
        return content, complete, expected

    def _fetch_detail(self, fetcher: Any, dapi_id: int) -> dict[str, Any] | None:
        try:
            return fetcher.get_json(f"{API_BASE}/digimon/{dapi_id}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("dapi detail failed for id %s: %s", dapi_id, exc)
            return None

    def fetch(self, fetcher: Any, force: bool = False) -> list[SourceDigimon]:
        # Use a faster fetcher for the big detail sweep (still rate-limited).
        from pipeline.core.request import Fetcher

        list_fetcher = fetcher
        ids, list_complete, expected = self._fetch_all_ids(list_fetcher)
        logger.info("dapi: list -> %d digimon", len(ids))
        save_raw("dapi", "list_index", [{"id": d["id"], "name": d["name"]} for d in ids],
                 meta={"source_url": f"{API_BASE}/digimon"})

        detail_fetcher = Fetcher(
            rate_per_second=self.rate_per_second,
            max_concurrency=self.max_concurrency,
            cache_dir=fetcher._cache_dir,
            force=force,
        )
        # fetch, tracking failures for a re-sweep (digi-api has ~1% transient resets)
        records: list[SourceDigimon] = []
        failed: list[int] = [item["id"] for item in ids]
        for sweep in range(3):
            pending = list(failed)
            if not pending:
                break
            failed = []
            for i, dapi_id in enumerate(pending):
                rec = self._fetch_detail(detail_fetcher, dapi_id)
                if rec is None:
                    failed.append(dapi_id)
                    continue
                records.append(self._to_record(rec))
                if i and i % 100 == 0:
                    logger.info("dapi: sweep %d, %d/%d", sweep, i, len(pending))
            logger.info("dapi: sweep %d done, %d failed remain", sweep, len(failed))
        save_raw("dapi", "details_en", [r.source_id for r in records],
                 meta={"source_url": f"{API_BASE}/digimon/{{id}}", "count": len(records),
                       "failed": failed})
        detail_fetcher.close()
        if failed:
            # A partial detail sweep must never be treated as a successful sync
            # (T1.4): missing records would silently drop entities from the
            # canonical DB. Raise so the candidate is aborted, never published.
            raise RuntimeError(
                f"dapi: {len(failed)} digimon details could not be fetched after retries: "
                f"{failed[:20]}"
            )
        # P1-02: report completeness so the pipeline refuses to publish when the
        # list pagination hit its defensive cap (raw_completeness=False).
        self._report(parsed=len(records), expected=expected, complete=list_complete)
        return records

    def _to_record(self, rec: dict[str, Any]) -> SourceDigimon:
        r = SourceDigimon(
            source="dapi",
            source_id=str(rec["id"]),
            x_antibody=bool(rec.get("xAntibody")),
            extra={"source_url": f"{API_BASE}/digimon/{rec['id']}"},
        )
        name_en = rec.get("name")
        if name_en:
            r.names.append(SourceName(name_en, "en", status="community", source="dapi"))

        level = _first_name(rec, "levels")
        if level:
            r.level_raw = level
        attr = _first_name(rec, "attributes")
        if attr:
            r.attribute_raw = attr
        for t in rec.get("types") or []:
            if t.get("type"):
                r.types.append(t["type"])
        for f in rec.get("fields") or []:
            if f.get("field"):
                r.fields.append(f["field"])
        release = rec.get("releaseDate")
        if release and release.strip():
            r.first_appearance_date = release.strip()

        # descriptions -> profiles (en_us + jap)
        for d in rec.get("descriptions") or []:
            lang = d.get("language")
            desc = (d.get("description") or "").strip()
            if not desc:
                continue
            if lang == "en_us":
                r.profile["en"] = desc
            elif lang == "jap":
                r.profile["ja"] = desc

        # skills
        for s in rec.get("skills") or []:
            name = s.get("skill")
            if not name:
                continue
            translation = s.get("translation") or ""
            desc = s.get("description") or ""
            sk = SourceSkill(
                names={"en": name},
                descriptions={"en": desc if desc else None},
                skill_type="special_move",
                source="dapi",
            )
            if translation.strip():
                sk.descriptions["en"] = sk.descriptions.get("en") or f"{translation.strip()} — {desc}"
            r.skills.append(sk)

        # evolution (loose edges)
        for ev in rec.get("priorEvolutions") or []:
            if ev.get("id"):
                r.evolves_from.append(str(ev["id"]))
                r.conditions[f"from:{ev['id']}"] = ev.get("condition") or ""
        for ev in rec.get("nextEvolutions") or []:
            if ev.get("id"):
                r.evolves_to.append(str(ev["id"]))
                r.conditions[f"to:{ev['id']}"] = ev.get("condition") or ""

        # image
        imgs = rec.get("images") or []
        if imgs:
            best = max(imgs, key=lambda i: 1 if i.get("transparent") else 0)
            r.image_url = best.get("href")
            r.extra["transparent"] = bool(best.get("transparent"))
        return r
