# DigiDex Web（SvelteKit 前端）

DigiDex 图鉴的前端。数据来自本地 FastAPI 后端（`apps/api`），所有数据读自
`data/digidex.sqlite`（真实数据库，非 mock）。个人功能（收藏/备注/标签/查询历史）
仅存于浏览器 localStorage，不写入 canonical 数据。

## 启动

```bash
# 1. 先启动后端（提供 /api/* 与图片缓存服务）
uv run python -m uvicorn apps.api.main:app --reload        # http://localhost:8000/docs

# 2. 前端开发服务器
npm install
npm run dev                                       # http://localhost:5173
```

后端地址由 `VITE_API_BASE` 覆盖（默认 `http://localhost:8000/api`）：

```bash
VITE_API_BASE=http://localhost:8000/api npm run dev
```

## 依赖数据

前端不依赖 mock：页面读 `/api/meta`、`/api/digimon`、`/api/search` 等，要求
`data/digidex.sqlite` 存在。首次运行先：

```bash
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb
uv run python scripts/download_images.py   # 本地图片缓存（可选，缺图自动占位）
```

## 测试

```bash
npm run check          # svelte-check（类型 + 模板）
npm run test           # Vitest 单元（stores 等）
npm run test:e2e       # Playwright（hermetic fixture，无网络）
npm run test:e2e:realdb  # Playwright（真实 data/digidex.sqlite，桌面 + 窄屏）
```

> `test:e2e` / `test:e2e:realdb` / `build` 会共用 `.svelte-kit`，请串行执行。

## 构建

```bash
npm run build
npm run preview
```

本地运行使用 `@sveltejs/adapter-auto`（本地适配器即静态/Node 自适应）；若部署到具体平台，
按平台选择 SvelteKit adapter（`@sveltejs/adapter-node` 等）。本仓库定位是个人本地自用，
不依赖公网部署。

## 目录

- `src/routes/` — 首页（搜索/筛选/卡片）、详情页、组织页、收藏页、About。
- `src/lib/api/` — FastAPI client（client.ts / types.ts）。
- `src/lib/stores/` — meta（运行时快照/计数）、favorites、personal（本地备注/标签/历史）。
- `src/lib/components/` — 卡片、徽章、进化图、筛选控件、状态组件（skeleton/空/错误）、壳层。
- `tests/` — `unit/`（Vitest）、`e2e/`（fixture）、`e2e-realdb/`（真实数据库）。
