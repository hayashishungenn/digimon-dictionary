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

- [ ] 公开部署（数据库已避免内置第三方版权图片；部署所需环境变量见 `apps/api/main.py` `DIGIDEX_DB` / `DIGIDEX_CORS_ORIGINS`）
- [ ] 搜索/筛选/查询性能深化（P2-1）：真实规模下的 N+1 消除、索引确认、冷/热查询耗时回归
- [ ] 独立扩展游戏数据（P2-2）：更多游戏版本的 game_digimon_stats / game_skill 接入（当前仅 Cyber Sleuth，`game_skill` 为空是合法状态）

## 阶段三（发布前修复与后续建设，P0/P1 任务书）

### 已完成（2026-08-15，见 `docs/delivery-report.md`）

- [x] **P0-0 基线 + 真实数据验收入口**：`tests/integration/test_real_db_smoke.py` 真实 DB smoke test（缺库自动跳过）。
- [x] **P0-1 进化图规模/性能**：有界 BFS（节点 500 / 边 2500 预算 + `truncated`/`dropped_edges` 可解释状态），depth 仅 1–3，O(E²) 去重→O(1)，批量节点加载；真实 DB Agumon depth=3 由 ~43s → ~44ms；前端加载/截断/回到浅深度。
- [x] **P0-2 抽样验证 + 质量门禁**：`field_coverage` 审计（present/no_source/no_level/conflict/sync_failure）区分真实缺失与同步失败；`verify_samples` 可复现 seed + 分类 + JSON 审计报告；`parse_level` 补齐真实变体（In-TrainingⅠ/Ⅱ、XW 中文）；`--skip-validation` 不再绕过发布闸门。
- [x] **P0-3 图片/缩略图/首次登场**：Pillow 本地缩略图派生缓存（`data/images/thumbs/`，1488 张），主图/缩略图元数据（尺寸/sha256/content-type/抓取时间/失败原因），`/api/images/{id}/{kind}` 服务端点，前端列表用缩略图、详情用主图 + 图片状态；首次登场有日期即显示（标题缺失显示“标题未记录”）。
- [x] **P1-1 同步失败安全/raw/checkpoint/历史**：`source_sync` 按 (source, run_id) 保留每次运行历史 + `sync_run` 表；raw 原子写；`run_id` 含微秒；WAL checkpoint 失败拒绝发布；图片阶段失败返回非零；source 集合新增/删除均识别。
- [x] **P1-2 字段级 provenance/冲突/清洁文本**：递归 wikitext 清洗器（语言标记/词源模板/链接/ref 渲染），嵌套模板不再截断；`provenance.run_id`；每实体 content_hash 覆盖全部规范化字段；关系边记录真实来源；未解析模板保留原文并进 review queue；详情页来源表带“有来源/冲突/缺失”状态。
- [x] **P1-3 真实 DB 浏览器/窄屏验收**：`playwright.realdb.config.ts` + `tests/e2e-realdb/`（18/18 通过，桌面 + 窄屏），覆盖三语/简称/部分搜索、组合筛选、Agumon 详情、进化 depth2 截断、组织页、缺图占位、无横向溢出、键盘导航。
- [x] **P1-4 报告/文档刷新**：`docs/delivery-report.md` 数字与真实数据库一致。

## 阶段四（自用稳定版，S0 任务书）

> 目标：个人本地长期使用的图鉴系统。同步失败不破坏上次可用库，可备份/恢复/查看快照，
> 缺失与冲突可追踪，不依赖公网服务。执行顺序见 `docs/self-use-next-taskbook.md` 与
> `docs/frontend-ui-taskbook.md`。

### 已完成

- [x] **S0-0 基线锁定**：真实 DB 运行基线（`docs/self-use-baseline.md`）——integrity ok、三语搜索一致、
      组合筛选正确、进化图有界截断可解释、Python/前端/两种 E2E 全绿。
- [x] **S0-1 同步状态与正式库一致性**：`source_sync` 与 `sync_run` 同 run_id 且 `sync_run.started_at`
      记录真实开始时间；本地发布 manifest `data/.publish_manifest.json`（run_id / snapshot_date / DB 与
      报告 SHA-256 / schema 版本 / 图片阶段 / 增量基线 / state_committed）；`state.save()` 失败不再静默
      （manifest 记录 state_committed=false，可识别"已发布但状态未提交"）；下一次运行从 DB 的
      `sync_run`/`source_sync` 自动 reconcile 状态并修复 manifest；发布前对 candidate 做
      `PRAGMA integrity_check`（candidate 损坏不发布）；图片阶段失败在 manifest 的 image_stage 与
      sync_run 注释中与 canonical 库成功区分；失败注入测试覆盖状态保存 / manifest 写 / checkpoint /
      candidate 损坏 / 图片阶段 / publish 前后中断。
- [x] **S0-2 本地备份、恢复与快照检查**：`scripts/backup_local.py`（时间戳目录 + `backup.json`，含 DB /
      同步状态 / 发布 manifest / 质量报告，可选图片缓存，`--keep` 修剪，`--dry-run`）、
      `scripts/restore_local.py`（先校验 manifest+哈希+integrity+schema 兼容，再写临时文件，原子替换，
      失败正式库不变，默认 dry-run/需 `--yes`）、`scripts/inspect_snapshot.py`（实时或备份目录的
      快照摘要，`--json`）。真实 DB 备份→恢复→临时目标验证通过；Windows 路径带空格可用。
- [x] **UI-P0 前端核心**：UI-P0-0 审计与参考基线、UI-P0-1 壳层/导航/状态条/tokens、
      UI-P0-2 首页搜索/筛选/卡片/移动抽屉、UI-P0-3 详情页可信度（profile 核验/技能缺口）、
      UI-P0-4 进化图（截断原因/节点等级/类型图例）。fixture E2E 18 + realdb E2E 18 全绿。
- [x] **S1-1 人工复核队列工作流**：schema v8 为 `manual_review_queue` 增加 `run_id` + `note`；
      派生 category（external_target / matching_failure / conflict / wikitext / other，区分
      "外部目标不在当前集合"与"匹配失败"）；`GET /api/review`（status/entity-type/q/category +
      分页）、`/api/review/stats`、`/api/review/export`（JSON/CSV，不删除）、
      `POST /api/review/{id}/resolve`（resolved/wontfix 必须带说明，wontfix ≠ 事实已验证）；
      `scripts/review_queue.py`（stats/list/show/resolve/export）；API/CLI/迁移测试 + 真实 DB 验证
      （775 开放项，wikitext 原文保留）。
- [x] **S1-2 数据覆盖**：Wikimon 适配器提取 S2 infobox 主图 URL（Special:FilePath，本地缓存、
      符合版权边界，下一次联网抓取补齐 248 图片缺口）；`docs/data-coverage-s1-2.md` 逐项核实各
      缺口根因——82 日文 / 324 中文 / 等级 / 属性 / 首次登场标题均为真实无来源（0 例可补救），不编造。
- [x] **S1-3 搜索/筛选/导出效率**：首页筛选状态写入 URL（`?level=…&attribute=…&q=…`，
      replaceState 无历史噪音），刷新/深链恢复；导出 JSON 增加 `dataset` 摘要（schema/snapshot/
      官方/扩展/总数），CSV 增加 `name_zh_cn_status/name_zh_cn_source/profile_verified`；
      API 每次请求经 `sqlite3.Connection` 子类统计 SQL 数 + 耗时并记录日志（真实 DB 查询可观测）。
- [x] **S1-4 本地维护体验**：`scripts/diagnose.py` 只读健康摘要（版本/DB/snapshot/计数/图片/最近同步/
      发布 manifest，`--json`，绝不输出 Token/环境变量，测试覆盖）；`scripts/dev.ps1` 启动后端+前端并
      打印 PID 与停止方式；pyproject 增加 backup/restore/inspect/review/diagnose 控制台别名；
      README 新增本地维护章节。

### 待完成

- [ ] UI-P1-2 响应式与可访问性完善（移动抽屉键盘/焦点、reduced-motion 全量）
- [ ] UI-P1-3 图片性能、UI-P1-4 动效收口、UI-P2-1 个人收藏
- [ ] S2-1 个人注释标签收藏、S2-2 独立游戏技能接入
