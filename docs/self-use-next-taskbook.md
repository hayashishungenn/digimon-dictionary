# DigiDex 自用版下一阶段任务书

> 用途：完整粘贴到 Claude Code 自动模式执行。
>
> 产品定位：个人本地使用的数码宝贝全图鉴。本阶段不做公网部署、账号、云同步或公开 API。
>
> 执行仓库：C:\Users\Hayas\Github\Digimon_Dictionary
>
> 执行时必须重新读取当前代码、真实数据库和 Git 状态，本文中的数字只作为方向说明。

## 一、总体目标

把当前已经可用的图鉴 MVP 完善为适合长期个人使用的本地系统：

- 数据同步失败时不破坏上一次可用数据库。
- 可以备份、恢复、查看快照和比较更新。
- 缺失、冲突、未验证数据都有可追踪状态。
- 本地搜索、筛选、详情、技能、来源、进化、收藏长期稳定。
- 前端围绕真实数据提升查询效率和信息可读性。
- 所有功能不依赖公网服务。

明确不做：

- 公网部署、域名、HTTPS、云数据库、CDN、云存储。
- 登录、权限、多人协作、云端收藏。
- Redis、ElasticSearch、Kafka、Kubernetes、微服务拆分。
- 任何没有可靠来源的自动编造或批量补全。

## 二、执行规则

1. 开始前阅读 AGENTS.md、CLAUDE.md、README.md、docs/product-spec.md 和本任务书。
2. 执行 git status --short --branch，保留用户已有修改。
3. 缺失事实保留为 NULL、unknown 或 unverified，不得用模型记忆填充。
4. 优先复用现有 Python、SQLite、FastAPI、SvelteKit、Playwright、pytest、Vitest、uv 和 npm。
5. 每个独立阶段检查 diff，创建原子 commit，不自动 push。
6. 修改管线必须补失败注入或集成测试；修改 UI 必须补行为测试和真实数据库验收。
7. fixture 只能验证结构，不能替代 data/digidex.sqlite 的真实功能验证。
8. 任何删除数据库、raw、图片缓存或收藏的操作必须先解析绝对路径并保留恢复方案。
9. 最终报告必须列出完成项、未完成项、验证命令、退出码和剩余风险。

## 三、完成定义

自用稳定版必须满足：

1. 可从网络源同步，也可从保存的 raw 离线重建。
2. 源失败、校验失败、candidate 损坏、WAL checkpoint 失败、状态保存失败时，旧数据库保持可用。
3. 最近一次成功快照、质量报告、run_id 和发布 manifest 可追溯。
4. 备份可以恢复出可启动的 SQLite 数据库。
5. 真实 DB 的搜索、筛选、详情、技能、来源、进化、图片占位、收藏和移动布局通过验收。
6. 缺失、冲突、人工复核和未验证状态不会被隐藏。
7. 不需要公网服务就能完成全部自用功能。

## 四、按优先级执行的任务

---

## S0-0：锁定自用版运行基线

### 目标

确认当前版本真实可用状态，避免引用旧报告或小型 fixture。

### 改动范围

- 只读检查 AGENTS.md、CLAUDE.md、README.md、docs/product-spec.md。
- data/digidex.sqlite、data/reports/。
- 只有缺少真实 smoke test 时才新增测试。

### 执行要求

~~~bash
git status --short --branch
uv run ruff check .
uv run pytest -q
uv run python scripts/validate_data.py
uv run python scripts/verify_samples.py --n 50 --seed 20260815
cd apps/web && npm run check
cd apps/web && npm run test
cd apps/web && npm run build
cd apps/web && npm run test:e2e
cd apps/web && npm run test:e2e:realdb
~~~

另行执行 SQLite integrity_check、API health/meta、三语搜索、组合筛选、Agumon 详情和 depth 1/2/3 进化检查。

### 验收标准

- 每条命令有退出码。
- fixture 和真实 DB 结果分开记录。
- 失败分类为代码、数据、环境或测试隔离问题。
- 不降低断言、不跳过失败。

### 依赖关系

无。

### 风险

前端 check、build、E2E 不要并行运行，避免共同写入 .svelte-kit 产生假失败。

---

## S0-1：修复同步状态与正式数据库的一致性

### 目标

解决正式数据库已经替换、但同步状态保存失败时的状态分裂，使增量同步可靠。

### 改动范围

- scripts/sync_data.py
- pipeline/core/sync_state.py
- pipeline/core/schema.py
- tests/integration/test_sync_failures.py
- tests/integration/test_incremental_sync.py

### 执行要求

1. source_sync 和 sync_run 使用同一个 run_id，并记录 started_at、finished_at、status、sources、snapshot_date。
2. 修复 sync_run.started_at 为空的问题。
3. 增加本地发布 manifest，包含 run_id、snapshot_date、数据库 SHA-256、报告 SHA-256、schema version、图片阶段状态和是否可作为增量基线。
4. state.save() 失败时不能静默成功；必须能识别“数据库已发布但状态未提交”，并提供恢复路径。
5. 图片阶段失败要区分“canonical 数据库成功”和“图片缓存失败”。
6. 增加失败注入测试：状态保存、manifest 写入、checkpoint、candidate 损坏、图片阶段和 publish 前后中断。

### 验收标准

- 失败场景有非零退出码或明确的部分成功状态。
- 旧数据库不会被损坏或替换成不可打开文件。
- 下一次运行可识别上次发布是否完整。
- 恢复后 integrity_check、API health、meta 和 Agumon 详情通过。
- source_sync 和 sync_run 的运行记录可追溯。

### 依赖关系

依赖 S0-0；S0-2、S1-1 和持续更新依赖本任务。

### 风险

Windows 文件占用、WAL、-shm、-wal 和 os.replace 必须实测；不能只靠返回 1 代替恢复方案。

---

## S0-2：本地备份、恢复和快照检查

### 目标

支持更新前备份、误同步回滚、电脑迁移和数据库损坏恢复。

### 改动范围

- 可新增 scripts/backup_local.py
- 可新增 scripts/restore_local.py
- 可新增 scripts/inspect_snapshot.py
- pipeline/core/config.py
- README.md、docs/roadmap.md
- tests/unit/、tests/integration/

### 执行要求

备份至少包含：

- data/digidex.sqlite；
- data/.sync_state.json；
- 发布 manifest；
- data/reports/data-quality.json 和 data-quality.md；
- raw 索引和 schema version。

data/images/ 作为可选本地缓存备份，不提交 Git。

备份文件记录：

- 日期、run_id；
- 数据库 SHA-256；
- 文件大小；
- schema version；
- 是否包含图片缓存。

恢复过程：

1. 校验备份清单、哈希和 SQLite integrity_check。
2. 先写临时文件。
3. 验证通过后再替换正式数据库。
4. 失败时正式数据库保持不变。
5. 默认提供预览或 dry-run，不直接覆盖未知路径。

### 验收标准

- 临时目录备份可恢复。
- 恢复后 API health、meta、Agumon 详情和搜索通过。
- 哈希不匹配、缺文件、schema 不兼容时拒绝恢复。
- Windows 路径带空格时可用。

### 依赖关系

依赖 S0-1。

### 风险

备份可能包含第三方图片缓存，必须在文档中标注为个人本地缓存，不自动上传。

---

## S1-1：把人工复核队列变成可操作的本地工作流

### 目标

让 manual_review_queue 可以筛选、查看、处理、导出和审计，不再只是报告中的数量。

### 改动范围

- apps/api/main.py
- apps/api/queries.py
- pipeline/core/schema.py
- 可新增 scripts/review_queue.py
- apps/web/src/routes/about/+page.svelte 或新增 review 页面
- API、CLI 和真实 DB E2E 测试

### 执行要求

1. 按 status、reason、entity_type、source、run_id 查询。
2. 导出 JSON/CSV，不删除原始记录。
3. 支持 resolved、wontfix，记录时间和说明。
4. 展示未安全解析的 Wikitext 原文、来源 URL 和失败原因。
5. 将“外部目标不在当前集合”和“匹配失败”区分。
6. 不提供无来源的批量自动确认。

### 验收标准

- 可以定位指定实体的全部待复核项。
- 状态变更可重复读取且不丢失。
- 原始候选值和来源保留。
- review 数量与质量报告一致。
- 普通图鉴浏览不被 review 页面阻塞。

### 依赖关系

依赖 S0-1；API contract 确定后与 UI 任务并行。

### 风险

wontfix 不等于事实已验证，必须保留处理理由。

---

## S1-2：按价值补齐数据覆盖

### 目标

优先提高个人实际查询价值，不追求无来源的字段 100% 非空。

### 改动范围

- pipeline/sources/
- pipeline/normalize/
- pipeline/matching/
- pipeline/merge/
- data/raw/、data/reports/
- scripts/verify_samples.py
- tests/unit/、tests/integration/

### 推荐顺序

1. 固定名单和常用实体的三语名、等级、属性、技能、简介、图片。
2. 官方集合的日文名、等级和属性缺口。
3. 扩展集合中有可靠来源的中日文名。
4. profile_verified 和字段级人工确认。
5. first_appearance title/medium。
6. Wikimon 图片 URL 提取，先确认版权和来源策略。
7. game_skill，确认来源和版本边界后再做。

### 验收标准

- 每次增强都报告覆盖率、冲突数和来源变化。
- canonical_slug 不改变，不产生重复实体。
- 新字段有 provenance、source_url、retrieved_at 和状态。
- validate_data、verify_samples 和真实 DB E2E 继续通过。
- 无可靠来源时保持缺失。

### 依赖关系

依赖 S1-1 和 S0-1。

### 风险

中文译名、游戏数据、动画数据和世界观字段不能未经标记混合。

---

## S1-3：本地搜索、筛选和导出效率

### 目标

让个人可以快速查询、保存筛选状态和导出研究数据。

### 改动范围

- apps/api/queries.py、apps/api/main.py
- apps/web/src/routes/+page.svelte
- apps/web/src/lib/api/client.ts、types.ts
- scripts/export_dataset.py
- SQLite FTS/index
- API、前端和 E2E 测试

### 验收标准

- 亚古兽、Agumon、アグモン、战暴、Wargre 指向正确实体。
- URL 可保存筛选状态，刷新后恢复。
- JSON/CSV 导出包含 snapshot_date、null/unknown/unverified 和来源。
- 搜索竞态、空结果、分页和非法筛选有稳定行为。
- 真实 DB 查询有耗时和 SQL 数量记录。

### 依赖关系

依赖 S0-0；导出安全依赖 S0-1。

### 风险

不能为性能删除来源、关系或缺失状态。

---

## S1-4：本地启动和维护体验

### 目标

减少个人使用时的命令记忆和排障成本。

### 改动范围

- pyproject.toml、apps/web/package.json
- 可新增只读诊断脚本
- README.md、docs/roadmap.md
- 必要时新增 Windows PowerShell 启动脚本

### 验收标准

README 能指导完成：

~~~bash
uv run python scripts/validate_data.py
uv run python scripts/verify_samples.py --n 50 --seed 20260815
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb --from-raw
uv run python -m uvicorn apps.api.main:app --reload
cd apps/web && npm run dev
~~~

可选诊断命令输出 Python/Node/uv/npm 版本、DB 路径、snapshot、总数、图片状态和最近同步状态，但不得输出 Token、Cookie、环境变量或 .env。

### 依赖关系

依赖 S0-1、S0-2。

### 风险

Windows PowerShell、Git Bash 和 CI 路径必须分别验证；后台进程必须说明停止方式。

---

## S2-1：个人注释、标签和收藏增强

### 目标

增加个人研究信息，但不改变 canonical 数据。

### 改动范围

- apps/web/src/lib/stores/
- 收藏页、详情页、卡片和首页筛选
- 优先 localStorage；只有跨浏览器本地需求明确时才增加个人 SQLite 表
- Vitest 和 E2E

### 验收标准

- 个人备注和官方来源字段分离。
- canonical 更新不覆盖个人信息。
- 支持导出和清除个人数据，清除有确认。
- 不需要登录或公网。

### 依赖关系

依赖 S1-3 和 UI-P2-1。

### 风险

个人备注不是事实来源，不能显示在官方简介或来源表中。

---

## S2-2：独立接入游戏技能

### 目标

在来源、版本和许可明确后接入 game_skill，保持与世界观技能分离。

### 改动范围

- game、game_skill、game_digimon_stats schema/API
- pipeline/sources/digidb.py 或新增适配器
- 详情页游戏数据区
- docs/sources.md、docs/schema.md
- 测试和质量报告

### 验收标准

- 每条游戏技能包含游戏、版本、来源、抓取时间。
- 不覆盖 canonical skill 或 world-view 属性。
- 无来源时显示暂无。
- 至少一组真实版本样本可追溯。

### 依赖关系

依赖 S1-2；不阻塞核心自用图鉴。

### 风险

不同游戏版本同名技能不能未经标记合并。

## 五、执行顺序

1. S0-0 基线。
2. S0-1 同步与发布一致性。
3. S0-2 备份恢复。
4. UI-P0 系列前端核心制作。
5. S1-1 人工复核。
6. S1-2 数据覆盖。
7. S1-3 搜索筛选导出。
8. S1-4 本地维护体验。
9. UI-P1/UI-P2。
10. S2-1、S2-2。

## 六、自用稳定版验收

~~~bash
git status --short --branch
uv run ruff check .
uv run pytest -q
uv run python scripts/validate_data.py
uv run python scripts/verify_samples.py --n 50 --seed 20260815
cd apps/web && npm run check
cd apps/web && npm run test
cd apps/web && npm run build
cd apps/web && npm run test:e2e
cd apps/web && npm run test:e2e:realdb
~~~

只有以下条件全部满足，才能称为自用稳定版：

- 正式数据库和上一版本均可恢复。
- 同步失败不破坏上一版本。
- run_id、source_sync、sync_run 和 manifest 可解释。
- 质量校验 0 errors，抽样无 sync_failure。
- 真实 DB 浏览器 E2E 通过。
- 个人信息不污染 canonical 数据。
- README 不以公网部署为前提。
- Git 工作区干净，相关修改有原子 commit，未自动 push。
