# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project

DigiDex — canonical multilingual (简体中文 / English / 日本語) Digimon encyclopedia. Data-quality-first; the Web UI is one query surface over a canonical SQLite knowledge base. Full spec: `docs/product-spec.md`.

## Non-negotiables

1. **Never fabricate data.** Missing = NULL/unknown/unverified, never invented. AI may translate/reformat/polish sourced text only.
2. **Never make a third-party id the primary key.** `canonical_slug` is the stable internal identity; external ids (`dapi_id`, `wikimon_title`, `official_slug`, `digimons_net_slug`) are plain columns.
3. **Never `git reset --hard` / `git clean` / overwrite user changes** without explicit approval.
4. **Evolution is a directed many-to-many graph** (`evolution_edge`); never single prev/next columns. Cycles are allowed (not errors).
5. **World-view vs game stats stay separate.** `game_digimon_stats` is per-game; never blend into `digimon`.
6. **Chinese names carry provenance** (`name_zh_cn_status`); invented names must be `unverified`, never presented as official.
7. **Images are not committed.** `data/images/` is gitignored; use `scripts/download_images.py`.
8. **Totals are computed at runtime** with `snapshot_date`, never hardcoded.
9. **Entity matching is exact-only** (spec §33): no pure-fuzzy auto-merge; ambiguous → `manual_review_queue`.

## Architecture (summary)

- `pipeline/sources/*` → `SourceDigimon` records (shared shape in `pipeline/core/models.py`)
- `pipeline/matching/matcher.py` → canonical slugs (exact name / external-id matching)
- `pipeline/merge/store.py` → CanonicalStore upserts entities + provenance/conflicts
- `pipeline/merge/resolver.py` → evolution edges (source-local refs → digimon ids)
- `pipeline/validation/validator.py` → quality report
- `apps/api/main.py` + `apps/api/queries.py` → FastAPI read API
- `apps/web/` → SvelteKit frontend
- `scripts/` → sync-data / validate-data / verify-samples / download-images / export-dataset

## Commands

```bash
uv run python scripts/sync_data.py --sources dapi,official,digimons_net
uv run python scripts/validate_data.py
uv run python scripts/verify_samples.py --n 50
uv run pytest
cd apps/web && npm run check && npm run test:e2e
```

## Key data facts (verified 2026-08)

- digi-api.com: 1,488 records (ids 1–1488), English names only, no zh/ja name fields, CC-BY-SA.
- Official Reference Book (digimon.net): 1,316, per-language list API `request.php` (96/page), zh-CHS exists.
- Wikimon: MediaWiki API open; `{{S2}}` infobox has `kan`/`ol`(CHI/ZHO/KOR)/`dub`/`l1..t1..f1..g1`/`ety`/`yd`/`drbentry`; content CC-BY-SA; images not individually licensed.
- digimons.net: sort.html table rows = [slug link, level, ja, en, zh]; plain HTTP only; community zh names.
