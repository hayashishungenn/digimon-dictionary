# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

DigiDex — a canonical, multilingual (简体中文 / EN / 日本語) Digimon encyclopedia. It is a **data-quality-first** project: a maintainable canonical knowledge base whose Web UI is only one query surface. Full product spec: `docs/product-spec.md`.

## Non-negotiable rules

1. **Never fabricate data.** Do not fill in names, attributes, skills, debuts, evolutions, or profiles from model memory. Missing data = `NULL` / `unknown` / `unverified`, never invented. AI may only translate / reformat / polish existing sourced data.
2. **Never treat a third-party API id as the canonical primary key.** Every digimon has a stable internal `canonical_slug` (e.g. `agumon`, `agumon-black`, `agumon-x-antibody`). External ids (`dapi_id`, `wikimon_title`, `official_slug`, `digimons_net_slug`) are stored separately on the entity.
3. **Never overwrite user changes.** No `git reset --hard`, `git checkout -- .`, `git clean`, `git stash` without explicit approval.
4. **Evolution is a directed many-to-many graph** (`evolution_edge`), never a single prev/next pair.
5. **Don't merge game stats into canonical world-view stats.** World-view fields live on `digimon` (level/attribute/type/field/skill/profile); game numbers go in `game_digimon_stats` per game, never blended.
6. **Chinese names require provenance.** `name_zh_cn_status` must be one of `official | official_game | official_anime | community | transliteration | unverified`. Auto-generated names must be marked `unverified` — never masquerade an invented name as official.
7. **Images are not committed to git.** `data/images/` is gitignored. Download via `scripts/download_images.py`. Respect third-party copyright.
8. **Every field keeps provenance.** Record `source`, `source_url`, `retrieved_at`; real conflicts go to `data_conflict` and unresolved entity matches go to `manual_review_queue`.
9. **The total count is never hardcoded.** `official_count` / `extended_count` / `total_count` are always computed at runtime and stored with a `snapshot_date`.

## Tech stack

- Data pipeline: Python ≥3.12 (dev/CI use 3.14), httpx, SQLite. Package manager: `uv`.
- API: FastAPI + uvicorn.
- Web: SvelteKit + TypeScript, Node ≥22 (dev uses 24).
- Tests: pytest (pipeline + API), Vitest (frontend unit), Playwright (E2E).

## Commands

```bash
uv sync                                # install python deps
uv run python scripts/sync_data.py     # full data sync (fetch→normalize→match→merge→validate→db)
uv run python scripts/validate_data.py # quality report
uv run python scripts/export_dataset.py# json/csv/sqlite export
uv run uvicorn apps.api.main:app --reload
cd apps/web && npm install && npm run dev
uv run pytest                          # python tests
```

## Directory map

- `pipeline/` — `sources/` (fetchers), `normalize/`, `matching/`, `merge/`, `validation/`, `core/` (shared infra, db).
- `apps/web/` — SvelteKit frontend; `apps/api/` — FastAPI backend.
- `data/` — `raw/` (source snapshots), `normalized/`, `images/` (gitignored), `reports/`.
- `docs/` — schema, sources, product spec, roadmap.
- `scripts/` — sync-data / download-images / validate-data / export-dataset.
- `tests/` — `unit/`, `integration/`, `e2e/`.

## Execution order (from product spec)

INSPECT → RESEARCH → DEFINE SOURCES → DESIGN SCHEMA → IMPLEMENT INGESTION → FETCH RAW → NORMALIZE → ENTITY MATCHING → MERGE → VALIDATE → FIX → BUILD DB → BUILD API → BUILD WEB → SEARCH → FILTER → DETAIL → SKILLS → EVOLUTION GRAPH → IMAGE PIPELINE → TEST → BUILD → E2E → DATA QUALITY REVIEW → CODE REVIEW → FIX → RETEST → DELIVER REPORT.
