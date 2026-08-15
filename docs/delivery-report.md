# 交付报告 — DigiDex 数码宝贝全图鉴

> 数据快照：**2026-08-14**（由本次用改造后代码对真实 source 重新同步并发布；缓存辅助，含全量 5 源）
> 改造周期：T1–T9 可靠性 / 质量改造，commit 范围见文末。

## 数据统计（来自重新同步后的 `data/digidex.sqlite`，快照 2026-08-14）

| 指标 | 值 |
|---|---|
| **总收录 Digimon** | **1,736** |
| 官方图鉴（is_official_reference） | 1,316 |
| 扩展图鉴 | 420 |
| 拥有中文名 | 1,495（其中 verified 1,412；余为 transliteration/unverified） |
| 拥有英文名 | 1,736 |
| 拥有日文名 | 1,654 |
| 拥有主图 | 1,488（broken=0，pending=0） |
| 有技能数码兽 / 技能总数 | 1,530 / 7,188 |
| 进化关系数 | 18,670 |
| 相关形态数 | 4,633 |
| 别名数 | **2,307**（schema v2 去重后） |
| 游戏数值（Cyber Sleuth） | 327（`game_digimon_stats`，独立于世界观） |
| 数据冲突（data_conflict） | 445（已记录未静默） |
| 仍需人工确认（manual_review_queue open） | **707**（新增 resolver/review 如实上报的未解析进化/关系目标等） |
| `source_sync` 表 | **已填充**：5 源均 status=ok、raw_completeness=1（dapi 1488 / official 1316 / digimons_net 1331 / wikimon 1636 / digidb 341） |
| schema `PRAGMA user_version` | 3 |

## 本次改造（T1–T9）

| 任务 | 内容 | 验证 |
|---|---|---|
| T1 同步失败安全 | candidate SQLite + 原子发布；任何失败保持正式库不变；`--partial-ok` 默认不发布；并发锁；状态原子写 | 11 个集成测试（失败/partial/成功/临时文件卫生） |
| T2 schema/冲突/闸门 | migration 机制；value_hash 真值；冲突记录真实 source/source_id + 理由 + 复核状态；source priority 选值；validator 全覆盖；verify_samples 非零退出 | 17 个 schema/validator 测试 + 迁移数据无损测试 |
| T3 身份/匹配/关系/游戏 | 精确匹配 + 简繁归一；歧义→review；关系推断记规则；resolver 统计+review；digidb UPSERT | matcher/relations/resolver/game-stats 测试 |
| T4 raw retention + 增量 | source_sync 真实写入；完整 payload hash；unchanged 才跳过；`--from-raw` 离线重建 | 7 个增量/raw 测试 |
| T5 API 安全/搜索/契约 | health 无路径；CORS 环境变量+拒通配；LIKE 转义；FTS 可观测回退；relation direction；稳定 500 | 35 个 API 测试 |
| T6 Web/E2E | 请求序号防覆盖；进化图缺节点安全；hermetic fixture E2E；窄屏无横向溢出 | `npm run check/test/build` + 13 个 Playwright E2E |
| T7 CI 门禁 | `.github/workflows/ci.yml`（ruff/pytest/npm/E2E）；ruff 全仓清零 | ruff 0 errors |
| T8 图片下载 | 统一 Fetcher；host/content-type 白名单；临时文件+原子替换+尺寸校验；防碰撞；失败非零 | 10 个 mock 测试 |
| T9 导出/文档 | 导出原子替换；JSON 全域无 N+1；SQLite 导出过 integrity_check；冲突报告转义 Markdown | 7 个导出测试 |

## 验证结果（本次实际执行）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `uv run ruff check .` | 0 | All checks passed（全仓 0 error，改造前基线 63 error） |
| `uv run python -m pytest -q` | 0 | **152 passed** |
| `uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb` | 0 | **真实全量同步成功**：1736 实体、validation 0 errors、原子发布；`source_sync` 5 源全 ok |
| 同一命令再次执行 | 0 | **增量 no-op**：所有 source unchanged，跳过重建，数据库保持 |
| `uv run python scripts/validate_data.py` | 0 | 0 errors / 2 warnings / 4 info |
| `uv run python scripts/verify_samples.py --n 50` | **1** | 随机 32/50 + 固定 16/16；**18 只随机抽样存在缺失字段**（扩展形态缺图/缺 zh 等，均为真实数据空缺，诚实报错） |
| `npm ci` | 0 | — |
| `npm run check` | 0 | 230 files, 0 errors / 0 warnings |
| `npm run test` | 0 | 5 passed |
| `npm run build` | 0 | vite build ✓ |
| `npm run test:e2e` | 0 | **13 passed**（hermetic fixture，桌面 + 窄屏，无固定 sleep） |
| `scripts/export_dataset.py` | 0 | digimon.json(20MB)/digimon.csv/digidex.sqlite；SQLite `PRAGMA integrity_check = ok`，1736 行 |
| `git diff --check` | 0 | 无空白错误 |

**代码验证以 hermetic fixture / mock 为主**：所有同步、API、Web、E2E、导出测试均不依赖
真实网络 source 或手工预同步数据库。上面的真实全量同步是在 T1 失败安全 + T4 增量改造
完成后，用真实 source（缓存辅助）对完整管线做的端到端验证。

## 提交记录（本次改造）

```
fa4f34c T9: delivery report, roadmap, schema docs reflect true state
d26e226 T9: atomic exports, full domain coverage, markdown-safe conflict report
196a44f T8: fail-safe image download (unified fetcher, atomic writes)
10cbb53 T7: CI quality gates + zero-lint baseline
9b8a9df T6: request race guards, missing-node safety, hermetic E2E
d21fa2f T4 (follow-up): thread --force into every source adapter fetcher
6471532 T5: API security, search contract, stable errors
0b577f0 T4: trusted raw retention + incremental sync
e2d7fad T3: exact-only identity, audited relations/resolver, game-stats upsert
931deb6 T2: schema migrations, provenance/conflict auditing, quality gates
2ff4878 T1: fail-safe sync via candidate DB and atomic publish
```

> 真实同步后还修正了一个测试隔离问题（`test_from_raw_missing_source_fails` 需把 raw 目录
> 指向临时路径，避免被真实同步写入的 `data/raw/` 影响）——该修复已随工作区提交。

## 未验证项（DATA_NOT_VERIFIED）

- **verify_samples 的随机抽样缺失字段**：数据问题（扩展形态缺图/缺 zh/缺属性等），非代码
  失败，已由脚本如实报错（退出码 1）。其中 140 只官方形态缺图是**设计使然**（官方图片按
  `docs/sources.md` 不下载，且这些形态不在 digi-api 的 1,488 中）。
- **图片实际联网批量下载**：`download_images.py` 已通过 mock 测试；真实批量下载未执行
  （需逐张访问 digi-api/wikimon，且当前库 download_status 已全部为 downloaded）。
- **CI 工作流实际跑通**：`.github/workflows/ci.yml` 已编写并经 YAML 校验；本地无法执行
  GitHub Actions，流水线运行结果未在本机验证（但其内每条命令均已在本机单独通过）。
- **CI 工作流实际跑通**：`.github/workflows/ci.yml` 已编写并经 YAML 校验；因本地无法执行
  GitHub Actions，实际流水线运行结果未在本机验证。

## 运行方式

```bash
# 同步数据（fetch→normalize→match→merge→validate→db；失败安全，写 candidate 后原子发布）
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb
# 从持久化 raw 离线重建（不联网）
uv run python scripts/sync_data.py --sources dapi --from-raw
# 数据质量 / 冲突审查 / 抽样人工验证
uv run python scripts/validate_data.py
uv run python scripts/review_conflicts.py
uv run python scripts/verify_samples.py --n 50
# API（本地开发 CORS 默认 localhost）
uv run uvicorn apps.api.main:app --reload
# Web
cd apps/web && npm install && npm run dev
# 测试
uv run pytest
cd apps/web && npm run test && npm run test:e2e
# 导出 / 图片缓存
uv run python scripts/export_dataset.py
uv run python scripts/download_images.py
```

## 已知限制（诚实声明）

- 缺简体中文名 / 缺日文名 / 缺主图的数码兽均为真实来源空缺，未编造（validate_data 报
  warning：缺 zh 241 只、缺 ja 82 只；缺主图 248 只，其中 140 只官方形态按版权策略不下载官方图）。
- 83 条音译名明确标 `transliteration` + unverified。
- 部分更冷门的粉丝昵称不在数据中。
- 游戏数值仅 Cyber Sleuth 一作。
- `manual_review_queue` 有 **707** 条 open（改造前仅 1 条）：新增 resolver/review 逻辑如实上报
  了此前被静默丢弃的未解析进化/关系目标、自环、缺 base 变体、未匹配游戏记录等；多为数据源
  引用了不在当前数据集内的实体，需人工核验。
- 公开部署尚未配置（环境变量：`DIGIDEX_DB`、`DIGIDEX_CORS_ORIGINS`）。
