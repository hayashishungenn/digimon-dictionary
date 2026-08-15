# DigiDex — 数码宝贝全图鉴 Canonical Knowledge Base

一个以**数据质量优先**的数码宝贝/数码兽全图鉴系统：三语言名称（简体中文 / English / 日本語）、等级、属性、类型、适应领域、所属组织、技能、进化关系（有向多对多图）、图片、简介、首次登场等资料，并提供可搜索、可筛选、可持续更新的 Web 图鉴。

> **声明**：本项目不隶属于 Bandai / Bandai Namco。数码宝贝相关的角色、名称与美术版权归其相应权利方所有。本项目仅用于个人研究、收藏与查询。

---

## 目标

- 尽可能覆盖所有已知数码兽（**官方 Reference Book** + **扩展集**：游戏独占、漫画独占、动画特殊个体、历史数码兽等）。
- 建立稳定的 **Canonical ID**，三种语言名称指向同一个实体。
- 每条数据保存 **Source / Provenance**，可追踪、可验证、不虚构。
- 数据持续可更新（增量同步），不依赖单一外部 API。

## 技术栈

| 层 | 技术 |
|---|---|
| 数据管线 | Python ≥3.12（开发/CI 用 3.14）· httpx · SQLite |
| API | Python · FastAPI |
| Web 前端 | TypeScript · SvelteKit（Node ≥22） |
| 测试 | pytest · Playwright · Vitest |
| 数据库 | SQLite (FTS5 全文搜索) |

## 目录结构

```text
apps/
  web/          # SvelteKit 前端图鉴
  api/          # FastAPI 后端
packages/
  shared/       # 前后端共享类型/常量
pipeline/
  sources/      # 各数据源抓取器（dapi / wikimon / digimons_net / official / digidb）
  normalize/    # 标准化（名称、level、attribute、type、field 枚举映射）
  matching/     # 实体匹配
  merge/        # 多源合并 + provenance + conflict
  validation/   # 数据质量校验
  core/         # 共享基础设施（请求保护、schema、db）
data/
  raw/          # 各源原始响应快照（fetch_date + source + http metadata）
  normalized/   # 标准化后的中间数据
  images/       # 本地图片缓存（gitignored，不提交第三方版权图片）
  reports/      # 数据质量报告
scripts/        # sync-data / download-images / validate-data / export-dataset
tests/          # unit / integration / e2e
docs/           # 文档（schema、sources、roadmap）
exports/        # digimon.json / digimon.csv / digidex.sqlite
```

## 快速开始

```bash
# 1. 数据管线（Python）
uv sync                       # 安装依赖
uv run python scripts/sync_data.py --sources dapi,official,digimons_net   # 抓取 + 标准化 + 匹配 + 合并 + 校验 + 建库
uv run python scripts/verify_samples.py      # 抽样人工验证（50 随机 + 16 固定）

# 2. API
uv run uvicorn apps.api.main:app --reload   # http://localhost:8000/docs

# 3. Web
cd apps/web
npm install
npm run dev                   # http://localhost:5173
```

> **完整数据源**（含 Wikimon，更全的三语名/进化/组织）：`uv run python scripts/sync_data.py --sources dapi,official,wikimon,digimons_net`

## 脚本

| 命令 | 作用 |
|---|---|
| `sync_data.py` | 完整 ETL：FETCH→RAW→NORMALIZE→MATCH→MERGE→VALIDATE→DB |
| `validate_data.py` | 数据质量报告（data/reports/data-quality.json/.md） |
| `verify_samples.py` | 抽样人工验证（随机 N 只 + 固定名单） |
| `download_images.py` | 本地缓存图片到 data/images/（不提交 git），并派生缩略图到 data/images/thumbs/ |
| `export_dataset.py` | 导出 digimon.json / digimon.csv / digidex.sqlite |
| `backup_local.py` | 本地备份到 `data/backups/backup-<时间戳>/`（DB+同步状态+发布 manifest+报告，可选图片缓存，`--with-images` / `--keep N` / `--dry-run`） |
| `restore_local.py` | 从备份恢复（先校验哈希/integrity/schema，再原子替换；默认 dry-run，覆盖需 `--yes`） |
| `inspect_snapshot.py` | 查看当前快照或备份目录摘要（`--path <backup>` / `--json`） |
| `uv run uvicorn apps.api.main:app` | FastAPI 后端 |
| `cd apps/web && npm run dev` | SvelteKit 前端 |

## 数据来源

| 源 | 用途 |
|---|---|
| [digimon.net/reference](https://digimon.net/reference_en/) | 官方状态验证、官方三语言名称 |
| [Wikimon](https://wikimon.net/Visual_List_of_Digimon) | 实体枚举、扩展集、简介、进化 |
| [Digi-API](https://digi-api.com/) | 结构化元数据、图片、技能、进化 |
| [digimons.net](https://digimons.net/digimon/) | 简体中文名（社区可靠长期译名） |
| [digidb.io](https://digidb.io/) | 游戏数值（Cyber Sleuth 等，独立于世界观数据） |

完整来源策略与版权边界见 [`docs/sources.md`](docs/sources.md)。

## 数据质量报告

```bash
uv run python scripts/validate_data.py
# 生成 data/reports/data-quality.json / .md
```

## 测试

```bash
uv run pytest                          # pipeline + API（含真实 DB smoke test，缺库自动跳过）
cd apps/web && npm run test            # 前端单元
cd apps/web && npm run test:e2e        # Playwright E2E（hermetic fixture）
cd apps/web && npm run test:e2e:realdb # Playwright E2E（真实 DB，桌面 + 窄屏；需先 sync_data）
```

## 数据库 Schema

见 [`docs/schema.md`](docs/schema.md)。

## 版权说明

- 元数据 / 社区文本 / 官方文本按各自来源的许可使用。
- **图片默认不随仓库分发**：官方与社区美术版权归权利人所有。`data/images/` 已被 gitignore，通过 `scripts/download_images.py` 在本地缓存。
- 本项目不隶属于 Bandai / Bandai Namco。
