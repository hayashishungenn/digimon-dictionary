# 自用稳定版交付报告 — DigiDex

> 覆盖：`docs/self-use-next-taskbook.md`（S0/S1/S2）+ `docs/frontend-ui-taskbook.md`（UI-P0/P1/P2）全部任务。
> 数据快照：**2026-08-15**（真实 DB 1,736 只，schema v8，当前发布 run_id `20260816T065459922120`）。
> 所有数字来自真实数据库与 `data/reports/data-quality.json`，非手工统计。

## 一、数据统计（真实 DB）

| 指标 | 值 |
|---|---|
| 总收录 / 官方 / 扩展 | **1,736 / 1,316 / 420** |
| 简体中文名 / 英文名 / 日文名 | 1,412 / 1,736 / 1,654 |
| 主图（本地缓存） | 1,488（缺 248，Wikimon 适配器已补图片 URL 提取，下次联网抓取可补齐） |
| 技能 / 有技能数码兽 | 7,213 / 1,530 |
| 简介 en / ja / zh | 1,431 / 1,378 / 0（中文简介无可靠来源，诚实留空） |
| 进化边 / 相关形态 / 别名 | 18,670 / 4,638 / 2,307 |
| 人工复核（open） | 775（wikitext 70 / external_target 563 / conflict 6 / matching_failure 2 / other 134） |
| 游戏数值（Cyber Sleuth） | 341（`game_skill` 因无许可来源保持为空，见 `docs/game-skills-s2-2.md`） |
| schema `PRAGMA user_version` | **8** |
| 发布 manifest | `data/.publish_manifest.json`：state_committed=true、baseline=true、schema=8 |

## 二、两本任务书完成情况

### 自用任务书（S0-0 … S2-2）
- **S0-0 基线**：真实运行基线 `docs/self-use-baseline.md`。
- **S0-1 同步状态一致性**：发布 manifest（run_id/snapshot/DB+报告 SHA-256/schema/图片阶段/基线/state_committed）；
  `sync_run.started_at` 真实开始时间；state.save() 失败不再静默（可识别"已发布但状态未提交"）；下次运行从 DB
  reconcile 状态并修复 manifest；发布前 candidate `PRAGMA integrity_check` 闸门；图片阶段与 canonical 成功区分；
  失败注入测试（状态保存/manifest 写/checkpoint/candidate 损坏/图片/publish 前后中断）。
- **S0-2 备份/恢复/快照**：`backup_local` / `restore_local`（两阶段：校验→临时文件→原子替换，失败正式库不变；
  dry-run 与 `--yes`）/ `inspect_snapshot`；真实 DB 往返验证通过；Windows 带空格路径可用。
- **S1-1 人工复核工作流**：schema v8 为 `manual_review_queue` 加 run_id + note；派生 category（区分
  external_target 与 matching_failure 等）；`/api/review` list/stats/export(json/csv)/resolve（必须带说明）；
  `scripts/review_queue.py`；wikitext 原文保留。
- **S1-2 数据覆盖**：Wikimon S2 infobox 主图 URL 提取（Special:FilePath，符合版权边界）；逐项核实缺口根因
  （82 ja / 324 zh / level / attribute / 首次登场标题均为真实无来源，0 例可补救）；报告 `docs/data-coverage-s1-2.md`。
- **S1-3 搜索/筛选/导出**：筛选状态 URL 化（刷新/深链恢复）；导出 JSON 加 dataset 摘要、CSV 加状态/来源列；
  API 每次请求记录 SQL 数 + 耗时（`sqlite3.Connection` 子类）。
- **S1-4 本地维护**：`scripts/diagnose.py`（只读健康摘要，绝不输出 Token/环境变量）+ `scripts/dev.ps1` + README。
- **S2-1 个人注释/标签/收藏**：`personal.svelte.ts`（备注/标签/历史，损坏安全，上限 20）；详情页个人备注区；
  收藏页个人数据面板（历史/导出/清空需确认）；不污染 canonical。
- **S2-2 游戏技能**：调研确认无许可来源（digidb.io 403、镜像无招式）→ `game_skill` 合法留空；schema 就绪。

### 前端任务书（UI-P0-0 … UI-P2-1）
- **UI-P0-0 审计**：`docs/ui-audit.md` + 参考结论 `docs/ui-design-notes.md`（实际查看 digimon.net/wikimon）。
- **UI-P0-1 壳层**：AppShell（logo/首页/收藏/关于）、StatusBar（运行时快照+总数）、SectionHeader、meta store、
  tokens 全量、自定义 favicon、skip-link、面包屑。
- **UI-P0-2 首页**：搜索（清除/模式标签）、FilterControls（桌面工具条+移动抽屉）、卡片（三语名/slug/官方扩展/
  中文名状态/收藏）、active-filter chips、URL 持久化。
- **UI-P0-3 详情页**：SectionHeader 分节、profile 已核验/来源待核验、技能缺口（缺名称/无描述）、来源表、冲突、
  图片状态。
- **UI-P0-4 进化**：简单+图谱双模式、depth 1–3、截断预算说明、节点等级+tooltip、进化类型图例。
- **UI-P1-1 状态系统**：SkeletonGrid/EmptyState/ErrorState、错误信息安全化（404/503/5xx/网络）、DB 未同步可区分。
- **UI-P1-2 响应式/可访问性**：筛选抽屉焦点圈定 + Escape、进化图方向键平移、reduced-motion。
- **UI-P1-3 图片**：真实首页网格无坏图/无图片错误 E2E。
- **UI-P1-4 动效**：首屏淡入、收藏星闪、图谱深度切换过渡（受 reduced-motion 控制）。
- **UI-P2-1 个人收藏**：见 S2-1。

## 三、验证结果（最终全量执行）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run pytest` | 0 | **262 passed**（含真实 DB smoke + 安全审查回归） |
| `uv run python scripts/validate_data.py` | 0 | 0 errors / 2 warnings / 4 info |
| `uv run python scripts/verify_samples.py --n 50 --seed 20260815` | 0 | 随机 50/50 + 固定 16/16，无硬失败 |
| `cd apps/web && npm run check` | 0 | 370 files, 0 errors, 0 warnings |
| `cd apps/web && npm run test` | 0 | **15 passed**（Vitest） |
| `cd apps/web && npm run build` | 0 | ✓ |
| `cd apps/web && npm run test:e2e` | 0 | **24 passed**（hermetic fixture） |
| `cd apps/web && npm run test:e2e:realdb` | 0 | **20 passed**（真实 DB，桌面 + 窄屏） |
| SQLite `PRAGMA integrity_check` | ok | 真实 DB |
| API 真实 smoke | ok | health / meta(1736) / 三语搜索 / by-id / review(775) / review CSV |
| 真实备份→恢复→临时目标 | ok | 1736 只可查询，schema v8 |

## 四、代码审查结论（已修复）

### 第一轮（任务书完成时，7 处缺陷）

1. **reconcile/diagnose 读取错误的 sync_run**（`ORDER BY rowid DESC` 取到最旧 run，历史保留会打乱 rowid）→ 改为 `ORDER BY run_id DESC`；否则状态丢失后每次都会重新发布。
2. **restore_backup 默认写到全局 data/**（恢复非默认目标时清掉了真实 `.sync_state.json`/reports）→ 运行时文件默认跟随目标目录；并修复了被测试误写的真实状态文件（经 reconcile 恢复为 5 源真实哈希）。
3. **备份记录的 schema 取 stale manifest**（v7 manifest + v8 DB 时备份记录 v7）→ 改取副本真实 `PRAGMA user_version`。
4. **`_preserve_review_history` 丢失 note/run_id**（跨重建解决说明丢失，违反 S1-1）→ 列感知携带。
5. **favorites 清空不持久**（直接置空 reactive 数组未 save，刷新后恢复）→ 增加 `clearFavorites()`。
6. **meta 重试失效**（`ensureMeta` 一次性守卫）→ `ensureMeta(true)` 强制重取。
7. **首页空态与错误态叠加显示**（报错时误显"没有找到"）→ 错误时不渲染空态。

### 第二轮（安全审查 P1/P2/P3，全部修复）

**P1 高优先级**
- **P1-01 写锁协调**：API `/api/review/{id}/resolve` 与 CLI resolve 与同步管线共用 `db_lock_path` 锁；同步进行中返回 409 / 非零，不再与原子发布竞态（并发测试覆盖）。
- **P1-02 源完整性门禁**：每个适配器上报 expected/parsed/raw_completeness；分页到上限、页面缺失、首次同步全空均禁止发布（live DB 不变）。
- **P1-03 迁移安全**：迁移前自动备份带数据旧库（`<db>.pre-migrate-v<ver>.sqlite`）；v2 别名去重合并 source/verified、冲突先确定性去重再建唯一索引（不中止）；逐版本 0..7 迁移数据保留测试。
- **P1-04 恢复标记**：reconcile 仅在 `state.save()` 真正成功后才把 manifest 标记 committed。
- **P1-05 恢复可回滚**：恢复提交全量回滚（DB+state+manifest+reports 同一快照）+ 同步锁。

**P2 中优先级**
- **P2-01 报告描述 live DB**：报告先写 `.staging`，仅发布成功后提升并重打 `db_sha256`；失败候选的报告永不覆盖真实报告；`diagnose` 校验报告是否匹配当前 DB（真实 DB 验证 True）。
- **P2-02 错误类型 state 文件**：`[]`/`null` 等合法但错误形状视为损坏，自动重建（不崩溃）。
- **P2-03 审查分页**：category 用 SQL CASE，list/count 用 LIMIT/OFFSET + COUNT(*)；导出超过 1 万条返回 413 / 非零，不再静默截断。
- **P2-04 by-id Unicode 数字**：仅接受 ASCII 十进制，`²` 等被忽略，不再 500。
- **P2-05 搜索 N+1**：详情批量 `WHERE id IN`（单次），搜索窗口扩大不再逐条查询。
- **P2-06 图片恢复**：`--with-images` 备份恢复时还原 `images/` 缓存（staging + 回滚）。
- **P2-07 前端过期响应**：详情进化展开/收藏页/组织页加入请求序号 + 安全错误文案。
- **P2-08 WAL checkpoint busy**：校验 `wal_checkpoint` 返回值，busy≠0 视为失败不发布。

**P3 Info**
- **P3-01** diagnose 在 Windows 用 `.cmd` 解析 npm/node。
- **P3-02/03** `apps/web/README.md` 重写（本地启动 / VITE_API_BASE / realdb E2E / adapter 说明）。
- **P3-04** README 记录公网部署边界（写接口无认证；局域网/公网需认证/CSRF/CORS/HTTPS）。
- **P3-05** CI 增加 `pip-audit` + `npm audit --omit=dev`。

> 每项均有回归测试。第一轮 7 处 + 第二轮 5 P1 + 8 P2 + 5 P3 全部修复并复验（`pytest 262 passed`、前端 `check/test/build/E2E(24)/realdb(20)` 全绿）。

### 第三轮（发布期一致性审查，P1×2 + P2×3 + P3×1）

**P1 高优先级**
- **P1-1 `--images` 发布后改库使哈希失真**：图片阶段在 DB 发布后修改 `digimon_image`/`digimon.thumbnail`，但 manifest `database_sha256` 与报告 `db_sha256` 仍指向图片前文件。现在图片阶段先做审计 `sync_run` 更新、`wal_checkpoint(TRUNCATE)` 折回 WAL，再重算并原子回填 manifest + 报告两个哈希（顺带修复 `backup_local` 发布后立即备份静默丢图片行的问题）。
- **P1-2 报告发布非原子 + 误导性报错**：JSON 成功/Markdown 失败时原本留下"DB 已更新、报告不完整、manifest/state 未写"的半提交且暂存被删。现在 JSON 提升失败致命中止（`ReportPublishError`，诚实报错 + 保留暂存）；Markdown 失败仅告警（JSON 为权威报告），同步照常完成并提交 manifest/state；`db_published` 跟踪原子替换，KeyboardInterrupt/意外异常不再误报"official database unchanged"。

**P2 中优先级**
- **P2-1 `/api/digimon/²` 500**：`get_digimon` 改用 `re.fullmatch(r"[0-9]+")`（与 by-id 一致），Unicode 数字按未知 slug 走 404；覆盖 detail/evolution/skills/aliases/relations/images 六条 `{ident}` 路由。
- **P2-2 reconcile 把 partial 当作基线**：状态文件丢失后 partial 发布可被当成增量基线。SQL 只接受 `status='ok'` + manifest `is_incremental_baseline=false` 且 `state_committed=true` 的防御纵深（`state_committed` 守卫保留 S0-1"已发布但状态未提交"恢复路径）。
- **P2-3 进化图节点预算边界（误报）**：逐条核验 + 对抗性图实测 `node_count` 永不超预算（frontier ⊆ visited → 每条边至多新增 1 节点），不加生产改动，仅加边界回归测试锁定不变量。

**P3 Info**
- **P3-01 修复** diagnose Windows npm 误报"未找到"（`shutil.which` 依 PATHEXT 返回 `npm.CMD` 但 CreateProcess 不解无扩展名）→ 始终传解析后的完整路径；本机实测 `npm 11.6.2`。

> 每项均有回归测试（新增 7 个：图片哈希重算、MD 非致命、JSON 诚实中止、reconcile 拒绝 partial、Unicode 数字 404、进化图边界、diagnose npm），`pytest 269 passed`。


## 五、诚实声明 / 已知限制

- **324 缺中文名 / 82 缺日文名 / 67 缺等级来源 / 211 缺属性来源 / 首次登场标题 0**：均为真实无来源
  （逐条对 raw 核实 0 例可补救），未编造。
- **248 缺主图**：Wikimon 图片 URL 提取已落地，需下一次联网抓取兑现。
- **profile_zh_cn / 中文技能名为 0**：无可靠来源。
- **`game_skill` 为空**：无许可明确的游戏技能来源（S2-2 已调研记录）。
- **775 条人工复核**：全部可经 `/api/review` 或 `review_queue` 筛选/查看/处理/导出。
- **提交**：两本任务书基线 44 个 commit 已按用户要求推送 GitHub；第二轮安全审查新增 8 个原子 commit、第三轮发布期一致性审查新增 3 个原子 commit（均 `origin/main` 之后，未 push）。
- **公网部署未做**：本阶段明确不做；`dev.ps1` 与本机命令足以启动。

## 六、运行方式

```bash
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb --from-raw
uv run python scripts/validate_data.py
uv run python scripts/verify_samples.py --n 50 --seed 20260815
uv run python scripts/diagnose.py
uv run uvicorn apps.api.main:app --reload     # :8000/docs
cd apps/web && npm run dev                    # :5173
powershell -ExecutionPolicy Bypass -File scripts\dev.ps1   # 一条命令启动，打印 PID 与停止方式
uv run python scripts/backup_local.py --keep 5
uv run python scripts/review_queue.py list --category wikitext
```
