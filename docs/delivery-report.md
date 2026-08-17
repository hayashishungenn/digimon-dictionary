# 交付报告 — DigiDex 数码宝贝全图鉴

> 数据快照：**2026-08-15**（由当前代码对真实 source 的持久化 raw 记录重建并原子发布，5 源全量）
> 覆盖范围：初版 MVP（T1–T9）基础上的发布前修复与后续建设任务书 **P0-0 至 P1-4**。
> 本文所有数字均来自 `data/digidex.sqlite` 的真实查询 / `scripts/validate_data.py` 生成的
> `data/reports/data-quality.json`，不是手工填写的旧统计。

## 一、数据统计（真实数据库，快照 2026-08-15）

| 指标 | 值 |
|---|---|
| **总收录 Digimon** | **1,736** |
| 官方图鉴（is_official_reference） | 1,316 |
| 扩展图鉴 | 420 |
| 简体中文名 | 1,412 / 1,736（81.3%）——official 1,306 + community 106，另有 324 只无任何可靠来源提供中文名 |
| 英文名 | 1,736 / 1,736（100%） |
| 日文名 | 1,654 / 1,736（95.3%），82 只缺（多为无 Wikimon 页的扩展形态） |
| 等级（非 unknown） | 1,565（未知/无等级 171，其中 67 无来源、99 明确无等级、5 未决冲突） |
| 属性（非 unknown） | 1,475（未知/无属性 261，其中 211 无来源、49 明确无属性、1 未决冲突） |
| 主图（main_image） | 1,488（本地缓存 1,488 张，download_status 全部 downloaded） |
| 缩略图（本地派生） | **1,488**（`data/images/thumbs/`，Pillow 派生，0 失败） |
| 缺主图 | 248（无任何已接入来源提供图片 URL） |
| 简介 profile_en / ja / zh_cn | 1,431 / 1,378 / 0（中文简介尚无可靠来源，诚实留空） |
| 技能 | 7,213 个；有技能数码兽 1,530；en 5,114 / ja 2,095 / zh 0 / 有描述 3,567 |
| 首次登场日期 | 1,717（标题 first_appearance_title 为 0，UI 已改为“有日期即显示”） |
| 进化边 evolution_edge | 18,670 |
| 相关形态 digimon_relation | 4,638 |
| 别名 digimon_alias | 2,307 |
| provenance 行 | 14,534（均带 run_id，schema v7） |
| 数据冲突 data_conflict | 445（已记录未静默，含 6 个 level/attribute 未决冲突） |
| 人工复核 manual_review_queue（open） | **775**（其中 70 条为无法安全解析的 wikitext 词源，原文已保留） |
| 游戏数值 game_digimon_stats（Cyber Sleuth） | 327（独立于世界观字段） |
| 游戏技能 game_skill | **0（尚未接入，合法状态，报告如实说明）** |
| schema `PRAGMA user_version` | 7 |
| source_sync 运行历史 | 3 次运行保留（按 source+run_id，P1-1） |

## 二、本阶段完成的任务（P0-0 … P1-4）

| 任务 | 内容 | 验证 |
|---|---|---|
| P0-0 基线 + 真实验收入口 | `tests/integration/test_real_db_smoke.py`：真实 DB 上的 health/meta/三语搜索/组合筛选/详情/组织/进化深度，缺库自动跳过 | 随 pytest 通过 |
| P0-1 进化图规模/性能 | 有界 BFS（节点 500/边 2500 预算），depth 仅 1–3，O(E²)→O(1)，批量节点；`truncated`/`dropped_edges`/`node_count`/`edge_count`；前端加载/截断/回到浅深度 | 真实 DB Agumon depth=3：**~43s → ~44ms**；depth 0/4/5 → 422 |
| P0-2 抽样验证 + 质量门禁 | `field_coverage` 审计表区分 present/no_source/no_level/conflict/sync_failure；`verify_samples --seed` 可复现 + JSON 审计；`parse_level` 补齐 In-TrainingⅠ/Ⅱ、XW 中文；`--skip-validation` 不再发布未验证库；报告含覆盖审计与处置分类 | `verify_samples --n 50`（seed 20260815）**50/50 随机 + 16/16 固定通过，退出码 0** |
| P0-3 图片/缩略图/首次登场 | Pillow 本地缩略图派生（1488）；主图/缩略图元数据（尺寸/sha256/content-type/抓取时间/失败原因）；`/api/images/{id}/{kind}` 服务；列表用缩略图、详情用主图 + 状态；首次登场有日期即显示 | 1488 缩略图 0 失败；缺图实体 API 404 → 前端占位；`validate_data` 报告含 thumbnail 计数 |
| P1-1 同步失败安全/历史 | `source_sync` 按 (source,run_id) 保留历史 + `sync_run` 表；raw 原子写；run_id 含微秒；WAL checkpoint 失败拒绝发布；图片阶段失败非零；source 新增/删除识别 | 3 次运行历史可查；失败注入测试退出码非零且正式库不变 |
| P1-2 provenance/冲突/清洁文本 | 递归 wikitext 清洗器（语言标记/词源/链接/ref 渲染，嵌套模板不再截断）；`provenance.run_id`；content_hash 覆盖全部规范化字段；关系边记录真实来源；未解析模板原文进 review；详情来源表“有来源/冲突/缺失” | DB 中 name_origin/profile **0 残留模板**；14,534 条 provenance 全带 run_id |
| P1-3 真实 DB 浏览器/窄屏验收 | `playwright.realdb.config.ts` + `tests/e2e-realdb/`：真实 DB 上的搜索/筛选/详情/进化/组织/缺图/窄屏/键盘 | **18/18 通过**（桌面 9 + 窄屏 9）；fixture E2E 13/13 仍通过 |
| P1-4 报告/文档刷新 | 本报告 + `docs/roadmap.md` + README 与真实数据库一致 | 数字与 `data-quality.json` 一致 |

## 三、验证结果（当前实际执行）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `uv run ruff check .` | 0 | All checks passed |
| `uv run pytest -q` | 0 | 全部通过（含真实 DB smoke test） |
| `uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb --from-raw` | 0 | 1736 实体、validation 0 errors、原子发布、source_sync 历史保留 |
| `uv run python scripts/validate_data.py` | 0 | 0 errors / 2 warnings / 4 info；报告含覆盖审计、处置、缩略图、首次登场、type/field/alias/provenance 覆盖 |
| `uv run python scripts/verify_samples.py --n 50` | 0 | 随机 50/50 + 固定 16/16，文档化缺口另列 |
| `uv run python scripts/download_images.py` | 0 | 主图 1488 + 缩略图 1488 派生，0 失败 |
| `cd apps/web && npm run check` | 0 | 357 files, 0 errors |
| `cd apps/web && npm run test` | 0 | 5 passed |
| `cd apps/web && npm run build` | 0 | ✓ |
| `cd apps/web && npm run test:e2e` | 0 | **13 passed**（hermetic fixture） |
| `cd apps/web && npm run test:e2e:realdb` | 0 | **18 passed**（真实 DB，桌面 + 窄屏） |

> 真实数据验证以 `data/digidex.sqlite`（gitignored，可由 `sync_data.py` 重建）为唯一依据；
> fixture/mock 只作为补充。

## 四、仍不完整 / 已知限制（诚实声明）

- **`game_skill` 为空**：游戏技能独立于世界观技能（spec §17），当前仅接入 Cyber Sleuth 数值
  （`game_digimon_stats` 327），`game_skill` 尚未接入 —— 这是合法状态，报告如实说明而非误报完成。
- **324 只缺简体中文名、82 只缺日文名**：均为真实来源空缺（对应 Wikimon 页无 CHI/ZHO / kan），
  未编造；`field_coverage` 标记为 `no_source`。
- **248 只缺主图**：无任何已接入来源提供图片 URL（Wikimon 图片提取未实现，见 P2 建议）。
- **中文简介（profile_zh_cn）与中文技能名为 0**：尚无可靠中文简介/技能来源，诚实留空。
- **445 条 data_conflict、775 条人工复核**：其中 70 条为无法安全解析的 wikitext 词源（原文已保留
  于 review queue，页面不展示原始模板）；其余多为数据源引用了不在当前数据集内的进化/关系目标。
- **first_appearance_title 为 0**：标题来源未接入；UI 已保证“有日期即显示”，标题缺失显示“标题未记录”。
- **图片为本地缓存**：`data/images/` 被 gitignore，不提交第三方版权图片；按 `docs/sources.md`
  官方 digimon.net 图片按版权策略不下载。
- **公开部署尚未配置**：环境变量 `DIGIDEX_DB` / `DIGIDEX_CORS_ORIGINS`（默认本地开发 origin）。

## 五、运行方式

```bash
# 数据管线（fetch→normalize→match→merge→validate→db；失败安全，写 candidate 后原子发布）
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb
# 从持久化 raw 离线重建（不联网）
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb --from-raw
# 数据质量 / 抽样人工验证（可复现 seed）/ 图片（含缩略图）
uv run python scripts/validate_data.py
uv run python scripts/verify_samples.py --n 50 --seed 20260815 --json /tmp/verify.json
uv run python scripts/download_images.py
# API / Web
uv run python -m uvicorn apps.api.main:app --reload
cd apps/web && npm install && npm run dev
# 测试（fixture + 真实 DB 浏览器验收）
uv run pytest
cd apps/web && npm run check && npm run test && npm run test:e2e && npm run test:e2e:realdb
# 导出
uv run python scripts/export_dataset.py
```

## 六、提交范围（本阶段）

```
a467357 P1-3 real-data-e2e: real-DB Playwright profile + narrow-screen acceptance
0be9f9d P1-2 provenance-and-clean-text: recursive wikitext cleaner, run_id, conflicts
e84409c P1-1 sync-fail-safe: per-run history, atomic raw, checkpoint/image gates
80f99fe P0-3 image-and-appearance: local thumbnails, image metadata, first-appearance UI
b8e904b P0-2 data-quality-gate: field coverage audit, seeded verify_samples, gate hardening
cb4c7a1 P0-1 evolution-bounded: bounded BFS graph, depth<=3, budget/truncation metadata
```

> 所有提交均为原子 commit，未 push（本地 `main` 领先 `origin/main`）；工作区在最终验收时已清理。
