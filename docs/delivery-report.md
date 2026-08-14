# 交付报告 — DigiDex 数码宝贝全图鉴

> 数据快照：2026-08-13（每次 sync-data 后更新）

## 数据统计

| 指标 | 值 |
|---|---|
| **总收录 Digimon** | **1,736** |
| 官方图鉴（is_official_reference） | **1,315**（官方参考书 1,316，覆盖 99.9%） |
| 扩展图鉴 | 421 |
| 拥有中文名 | 1,411 |
| 拥有英文名 | 1,736（100%） |
| 拥有日文名 | 1,653 |
| 三语言完整率 | 1,410 / 1,736（81.2%） |
| 拥有图片 | 1,488（85.7%） |
| 拥有简介（EN） | 1,431（82.4%） |
| 有技能数码兽 | 1,530 |
| 技能总数 | 7,062 |
| 进化关系数 | 18,745（含 1,888 条主线） |
| 相关形态数 | 4,633（含 178 条自动推理：X抗体 122/黑变 29/模式变化 20/变体 7） |
| 别名数 | 2,873 |
| 所属组织 | 50 个（成员 348 条） |
| X抗体数码兽 | 220 |
| 游戏数值（Cyber Sleuth） | 327 / 341 只（`game_digimon_stats`，独立于世界观） |
| 仍需人工确认（manual_review_queue） | 4 |
| 数据冲突（data_conflict，已记录未静默） | 447（审查报告见 `docs/data-conflicts.md`） |

## 数据来源

| 源 | 贡献 |
|---|---|
| digi-api.com | 1,488 条结构化记录（英文名/等级/属性/类型/领域/技能/简介/进化/图片） |
| digimon.net 官方 Reference Book | 1,316 条（官方状态、官方三语名、官方等级、必杀技、简介） |
| digimons.net | 1,331 条（简体中文社区长期译名、日/英/中文名） |
| Wikimon | 1,658 页（日文名、中文名、配音名、组织、词源、主线进化、相关形态） |

## 测试结果

| 套件 | 结果 |
|---|---|
| pytest（单元 + 集成） | 57 passed |
| Vitest（前端单元） | 5 passed |
| svelte-check（类型检查） | 0 errors / 0 warnings |
| Playwright E2E | 7 passed |

## Build 结果

`npm run build`（vite build）✓

## E2E 场景（全部通过）

- 打开首页 ✓
- 搜索"亚古兽"/"Agumon"/"アグモン" → 同一实体 ✓
- 详情页三语名 ✓
- 查看技能 ✓
- 点击后续进化 → 对应详情 ✓
- 按"究极体+疫苗"组合筛选 ✓
- 收藏 → 刷新后仍存在 ✓
- 缺图显示占位（无 broken image）✓

## 运行方式

```bash
# 同步数据（fetch→normalize→match→merge→validate→db）
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon

# 数据质量报告
uv run python scripts/validate_data.py        # → data/reports/data-quality.{json,md}

# 抽样人工验证（随机 + 16 固定名单）
uv run python scripts/verify_samples.py --n 50

# API（http://localhost:8000/docs）
uv run uvicorn apps.api.main:app --reload

# Web（http://localhost:5173）
cd apps/web && npm install && npm run dev

# 测试
uv run pytest
cd apps/web && npm run test && npm run test:e2e

# 导出（JSON / CSV / SQLite）
uv run python scripts/export_dataset.py        # → exports/

# 图片本地缓存（不提交 git）
uv run python scripts/download_images.py
```

## 已知限制（诚实声明）

- 81.2% 三语言完整率：约 325 只扩展/冷门数码兽缺简体中文名（无可靠来源；提供 `scripts/generate_transliterations.py` 可选音译并标 unverified）
- 部分冷门缩写/昵称不在数据中（已内置常见粉丝别名如"战暴/奥叔"；其余不编造）
- 游戏数值仅 Cyber Sleuth 一作（327/341）；其他作品可依 `game_digimon_stats` / `game_skill` 表继续导入
- Wikimon 的 4 条待人工确认（ambiguous names）
- 447 条跨源数据冲突已记录未静默（见 `docs/data-conflicts.md` 供人工裁决）
