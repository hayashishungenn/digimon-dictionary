# Roadmap

## 阶段一（完成）

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
- [x] FETCH RAW DATA（digi-api 1,488 + official 1,316 + digimons_net 1,331 + Wikimon）
- [x] BUILD DATABASE（完整同步 + 三语言 + 进化图 + 别名）
- [x] BUILD API（FastAPI：list/detail/search/filter/evolution/skills/aliases/groups/meta）
- [x] BUILD WEB UI（SvelteKit：首页 grid/搜索/筛选/详情/进化图/收藏/关于）
- [x] IMAGE PIPELINE（digimon_image 表 + download_images.py + 占位图 fallback）
- [x] TEST（pytest 单元 + API 集成 + Vitest + Playwright E2E）
- [x] E2E（Playwright：三语言搜索→同一实体等）
- [x] DATA QUALITY REVIEW（报告 + 抽样人工验证 16/16 固定名单）
- [x] CODE REVIEW / FIX / RETEST
- [x] 交付报告

## 阶段二（进行中）

### 已完成（2026-08 可靠性/质量改造）

- [x] **同步失败安全与原子发布**（T1）：`sync_data.py` 只写临时 candidate SQLite，成功后才原子替换正式库；任何 fetch/parse/merge/validation 失败保持正式库字节不变并退出非零；`--partial-ok` 默认不发布；并发锁；同步状态原子写。
- [x] **schema 迁移 / provenance / 冲突审计 / 数据质量闸门**（T2）：`PRAGMA user_version` + 增量迁移（旧库原地升级不丢数据）；`provenance.value_hash` 为字段真实规范化值哈希；`data_conflict` 记录每个候选的真实 source/source_id、选定值、全部候选、选择理由与复核状态；world-view 字段按文档化 source priority 选择，不再按输入顺序；validator 覆盖所有 join 表孤儿、失效引用、非法枚举、provenance/source_sync/FTS/计数/快照一致性、verified/present 区分。
- [x] **canonical identity / 匹配 / 关系 / 游戏数据**（T3）：精确匹配 + 简繁归一；歧义名生成 needs_review 实体并进 review queue；关系推断记录 slug 规则且缺 base 进 review；进化 resolver 输出 unknown/self 统计并进 review；digidb 游戏数值 UPSERT（可更新），未匹配记录进 review queue。
- [x] **可信 raw retention + 增量同步**（T4）：`source_sync` 表真实记录每次运行各源的 run_id/状态/数量/完整度/完整 payload hash；payload 任意字段变化触发重新 merge；相同 payload 第二次同步安全跳过；`--from-raw` 可离线重建 candidate；adapter 的 `force` 真正绕过 HTTP cache。
- [x] **API 安全 / 搜索 / 响应契约**（T5）：`/api/health` 不泄露本地路径；CORS 由 `DIGIDEX_CORS_ORIGINS` 控制且默认拒绝通配符；搜索 LIKE 转义 `%`/`_`；FTS 失败可观测回退；relation 显式 direction/from_id/to_id；SQLite 异常映射为稳定 JSON 500。
- [x] **Web 状态一致性 / 可访问性 / hermetic E2E**（T6）：首页/详情请求序号令牌防止旧响应覆盖新结果；进化图不假定节点恒存在；E2E 使用确定性 fixture DB（不联网、不同步、无固定 sleep），覆盖桌面与窄屏。
- [x] **CI 质量门禁**（T7）：`.github/workflows/ci.yml`（ruff / pytest / npm ci / check / test / build / hermetic E2E），ruff 全仓清零，统一 Python/Node 版本说明。
- [x] **图片下载失败安全**（T8）：统一 Fetcher（限速/重试/超时），host/content-type 白名单，临时文件 + 原子替换 + 尺寸校验，防 basename 碰撞，失败返回非零。
- [x] **导出 / 文档 / 交付报告**（T9）：导出全部走临时文件 + 原子替换（失败保留旧文件）；JSON 覆盖全部数据域且无 N+1；SQLite 导出过 `PRAGMA integrity_check`；冲突报告转义 Markdown。

### 待完成

- [ ] 缩略图生成（download_images.py 本地缓存已完成，缩略图缩放未实现）
- [ ] 进化图交互增强（拖动/缩放）
- [ ] 公开部署（数据库已避免内置第三方版权图片；部署所需环境变量见 `apps/api/main.py` `DIGIDEX_DB` / `DIGIDEX_CORS_ORIGINS`）
