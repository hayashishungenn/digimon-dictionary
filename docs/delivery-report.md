# 交付报告 — DigiDex 数码宝贝全图鉴

> 数据快照：2026-08-13（每次 sync-data 后更新）

## 数据统计

| 指标 | 值 |
|---|---|
| **总收录 Digimon** | **1,736** |
| 官方图鉴（is_official_reference） | **1,315 / 1,316**（官方参考书，覆盖 99.9%） |
| 扩展图鉴 | 421 |
| 拥有中文名 | 1,411 |
| 拥有英文名 | 1,736（100%） |
| 拥有日文名 | 1,653 |
| 三语言完整率 | 1,410 / 1,736（81.2%） |
| 拥有图片 | 1,488（85.7%）；本地缓存 1,488 张（148MB，gitignored） |
| 拥有简介（EN） | 1,431（82.4%） |
| 有技能数码兽 | 1,530 |
| 技能总数 | 7,153 |
| 进化关系数 | 18,745（含 1,884 条主线） |
| 相关形态数 | 4,633（含 178 条自动推理：X抗体/黑变/模式变化/变体） |
| 别名数 | 2,879（含粉丝缩写"战暴/奥叔"、游戏译名、繁体中英对照） |
| 所属组织 | 50 个（皇家骑士/七大魔王/十二神等，成员 348 条） |
| X抗体数码兽 | 220 |
| 游戏数值（Cyber Sleuth） | 327 / 341 只（`game_digimon_stats`，独立于世界观） |
| 仍需人工确认（manual_review_queue） | 1 |
| 数据冲突（data_conflict，已记录未静默） | 447（审查报告 `docs/data-conflicts.md`） |

## 数据来源

| 源 | 贡献 |
|---|---|
| digi-api.com | 1,488 条结构化记录（英文名/等级/属性/类型/领域/技能/简介/进化/图片） |
| digimon.net 官方 Reference Book | 1,316 条（官方状态、官方三语名、官方等级、必杀技、简介、Xros 标记） |
| digimons.net | 1,331 条（简体中文社区长期译名、日/英/中文名） |
| Wikimon | 1,658 页（日文名、中文名、配音名、组织、词源、主线进化、相关形态） |
| digidb.io（社区镜像） | 341 条 Cyber Sleuth 游戏数值（独立导入） |
| manual | 粉丝缩写别名（fan_translation，明确标注） |

## 搜索覆盖（§35 全部示例）

`亚古兽`/`Agumon`/`アグモン`/`亞古獸`（简繁）/`Agu`（部分）/`战暴`（粉丝缩写）/`War Greymon`（空格）/`ウォーグレイモン` → 全部命中正确实体 ✓

## 测试结果

| 套件 | 结果 |
|---|---|
| pytest（单元 + 集成 + 特殊案例） | 79 passed |
| Vitest（前端单元） | 5 passed |
| svelte-check（类型检查） | 0 errors / 0 warnings |
| Playwright E2E | 12 passed（§62 场景 + 官方/扩展切换 + About 快照 + 代表主线 + 空状态 + 战暴） |

## Build 结果

`npm run build`（vite build）✓

## 运行方式

```bash
# 同步数据（fetch→normalize→match→merge→validate→db）
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon,digidb

# 数据质量报告 / 冲突审查 / 抽样人工验证
uv run python scripts/validate_data.py
uv run python scripts/review_conflicts.py
uv run python scripts/verify_samples.py --n 50

# 音译候选（可选，标 unverified；dry-run 默认）
uv run python scripts/generate_transliterations.py [--apply]

# API（http://localhost:8000/docs）
uv run uvicorn apps.api.main:app --reload

# Web（http://localhost:5173）
cd apps/web && npm install && npm run dev

# 测试
uv run pytest
cd apps/web && npm run test && npm run test:e2e

# 导出 / 图片缓存
uv run python scripts/export_dataset.py        # → exports/
uv run python scripts/download_images.py       # → data/images/（gitignored）
```

## 已知限制（诚实声明）

- 81.2% 三语言完整率：约 325 只扩展/冷门数码兽缺简体中文名（无可靠来源；可选音译工具已提供并标 unverified）
- 部分更冷门的粉丝昵称不在数据中（内置常见缩写，其余不编造）
- 游戏数值仅 Cyber Sleuth 一作；其他作品可循 `game_digimon_stats` / `game_skill` 表继续导入
- 1 条歧义名称待人工确认
- 447 条跨源 level/attribute 分歧已记录未静默（dapi 与官方对部分数码兽分类不同，见 `docs/data-conflicts.md`）
