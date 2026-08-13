# Roadmap

## 阶段一（当前）

- [x] INSPECT 环境
- [x] RESEARCH 数据源与现有实现（digi-api / Wikimon / digimon.net / digimons.net / GitHub / Reddit）
- [x] DEFINE SOURCES（来源优先级 + 版权边界）
- [x] DESIGN SCHEMA（`pipeline/core/schema.py`，22 张表 + FTS5）
- [x] IMPLEMENT INGESTION（dapi / official / wikimon / digimons_net / digidb 适配器）
- [x] 请求保护（timeout/retry/backoff/rate limit/UA/cache）
- [x] NORMALIZE（level/attribute 枚举映射、名称标准化、简繁转换）
- [x] ENTITY MATCHING（exact → alias → external id → review，禁止纯 fuzzy 合并）
- [x] MERGE（CanonicalStore + 进化边 Resolver + provenance + conflict + review queue）
- [x] VALIDATION（`scripts/validate_data.py` → data/reports/data-quality.*）
- [x] FETCH RAW DATA（digi-api 1,488 + official 1,316 + digimons_net 1,331）
- [ ] BUILD DATABASE（完整同步 + 三语言 + 进化图）
- [x] BUILD API（FastAPI：list/detail/search/filter/evolution/skills/aliases/groups/meta）
- [x] BUILD WEB UI（SvelteKit：首页 grid/搜索/筛选/详情/进化图/收藏/关于）
- [x] IMAGE PIPELINE（digimon_image 表 + download_images.py + 占位图 fallback）
- [x] TEST（pytest 单元 + API 集成）
- [ ] E2E（Playwright：三语言搜索→同一实体等）
- [ ] DATA QUALITY REVIEW（报告 + 抽样人工验证）
- [ ] CODE REVIEW / FIX / RETEST
- [ ] 交付报告

## 阶段二（后续增强）

- [ ] Wikimon 全量接入（日文名/中文名/组织/词源/主线进化的完整覆盖）
- [ ] 游戏数值导入（Cyber Sleuth / Next Order / Time Stranger → game_digimon_stats）
- [ ] 图片本地下载 + 缩略图生成 + 图库页
- [ ] 进化图交互增强（拖动/缩放/按作品过滤）
- [ ] 深度相关形态推理（mode_change / black_variant 自动标记）
- [ ] 增量同步状态（content_hash 跳过未变源）
- [ ] 公开部署（数据库已避免内置第三方版权图片）
