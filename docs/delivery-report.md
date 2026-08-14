# 交付报告 — DigiDex 数码宝贝全图鉴

> 数据快照：**2026-08-14**（现有已同步数据库；本次未重新执行真实全量同步，见"未验证项"）
> 改造周期：T1–T9 可靠性 / 质量改造，commit 范围见文末。

## 数据统计（来自 `data/digidex.sqlite`，快照 2026-08-14）

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
| 别名数 | 2,870 |
| 游戏数值（Cyber Sleuth） | 327（`game_digimon_stats`，独立于世界观） |
| 数据冲突（data_conflict） | 445（已记录未静默） |
| 仍需人工确认（manual_review_queue open） | 1 |
| `source_sync` 表 | **0 行**（T4 起每次成功同步会写入；当前库为改造前同步产物） |

> 注：以上为现有数据库的真实查询结果；上表中的数字与旧的 2026-08-13 交付报告
> 不同，是因为数据库在 08-14 有一次更新，且旧的报告数字（447 冲突 / 2,879 别名 /
> 18,745 边）与当前库不一致，以本次实际查询为准。

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
| `uv run python scripts/validate_data.py` | 0 | 0 errors / 3 warnings / 4 info |
| `uv run python scripts/verify_samples.py --n 50` | **1** | 随机 39/50 + 固定 16/16；**11 只随机抽样存在缺失字段**（多为扩展形态缺图/属性），诚实报错 |
| `npm ci` | 0 | — |
| `npm run check` | 0 | 230 files, 0 errors / 0 warnings |
| `npm run test` | 0 | 5 passed |
| `npm run build` | 0 | vite build ✓ |
| `npm run test:e2e` | 0 | **13 passed**（hermetic fixture，桌面 + 窄屏，无固定 sleep） |
| `scripts/export_dataset.py` | 0 | digimon.json(20MB)/digimon.csv/digidex.sqlite；SQLite `PRAGMA integrity_check = ok`，1736 行 |
| `git diff --check` | 0 | 无空白错误 |

**代码验证以 hermetic fixture / mock 为主**：所有同步、API、Web、E2E、导出测试均不依赖
真实网络 source 或手工预同步数据库。

## 提交记录（本次改造）

```
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

## 未验证项（DATA_NOT_VERIFIED）

- **真实全量数据同步（`sync_data.py` 连真实 source）**：**DATA_NOT_VERIFIED** — 未执行。
  当前数据库为改造前的 2026-08-14 快照。T1–T9 的代码路径已用 fixture/mock 测试验证，
  但用改造后代码对真实 source 重新拉取并发布、以及 `source_sync` 表在真实同步中写入，
  尚未在本机运行验证。
- **verify_samples 的 11 只随机抽样缺失**：数据问题（多为扩展形态缺图/缺属性），非代码失败，
  已由脚本如实报错（退出码 1）。
- **图片实际下载**：`download_images.py` 已通过 mock 测试；真实联网批量下载未执行
  （需访问 digi-api/wikimon，且当前库 download_status 已全部为 downloaded）。
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

- 约 241 只扩展/冷门数码兽缺简体中文名（已系统探查各来源均无可靠资料；不编造）。
- 83 条音译名明确标 `transliteration` + unverified。
- 部分更冷门的粉丝昵称不在数据中。
- 游戏数值仅 Cyber Sleuth 一作。
- 当前数据库的 `source_sync` 为空（改造前产物）；下次成功同步会填充。
- 公开部署尚未配置（环境变量：`DIGIDEX_DB`、`DIGIDEX_CORS_ORIGINS`）。
