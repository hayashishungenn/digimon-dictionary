# 交付报告 — DigiDex 数码宝贝全图鉴

> 生成时间：{{DATE}}（随每次同步更新）

## 数据统计

| 指标 | 值 |
|---|---|
| 总收录 Digimon | {{total}} |
| 官方图鉴（is_official_reference） | {{official}} |
| 扩展图鉴 | {{extended}} |
| 拥有中文名 | {{zh}} |
| 拥有英文名 | {{en}} |
| 拥有日文名 | {{ja}} |
| 三语言完整率 | {{trilingual}} / {{total}} ({{pct}}%) |
| 拥有图片 | {{images}} ({{img_pct}}%) |
| 拥有简介（EN） | {{profiles}} |
| 有技能数码兽 | {{skills_digimon}} |
| 技能总数 | {{skills_total}} |
| 进化关系数 | {{edges}} |
| 相关形态数 | {{relations}} |
| 别名数 | {{aliases}} |
| X抗体数码兽 | {{xab}} |
| 仍需人工确认（manual_review_queue） | {{review}} |
| 数据冲突（data_conflict） | {{conflicts}} |

## 数据来源

- digi-api.com（1,488 条结构化记录：英文名/等级/属性/类型/领域/技能/简介/进化/图片）
- digimon.net 官方 Reference Book（1,316 条：官方状态、官方三语名、官方等级、必杀技、简介）
- digimons.net（1,331 条：简体中文社区长期译名、日/英/中文名）
- Wikimon（MediaWiki：日文名、中文名、配音名、组织、词源、主线进化、相关形态）

## 测试结果

| 套件 | 结果 |
|---|---|
| pytest（单元 + 集成） | {{pytest}} |
| Vitest（前端单元） | {{vitest}} |
| svelte-check（类型检查） | {{svelte_check}} |
| Playwright E2E | {{e2e}} |

## Build 结果

`npm run build`（vite build）✓

## E2E 场景

- 打开首页 ✓
- 搜索"亚古兽"→ Agumon → 详情三语名 ✓
- 搜索"Agumon"→ 同一实体 ✓
- 搜索"アグモン"→ 同一实体 ✓
- 查看技能 ✓
- 点击后续进化 → 对应详情 ✓
- 按"究极体+疫苗"筛选 ✓
- 收藏 → 刷新后仍存在 ✓

## 运行方式

```bash
# 同步数据（fetch→normalize→match→merge→validate→db）
uv run python scripts/sync_data.py --sources dapi,official,digimons_net,wikimon

# 数据质量报告
uv run python scripts/validate_data.py

# API
uv run uvicorn apps.api.main:app --reload   # http://localhost:8000/docs

# Web
cd apps/web && npm install && npm run dev   # http://localhost:5173

# 测试
uv run pytest
cd apps/web && npm run test && npm run test:e2e

# 导出
uv run python scripts/export_dataset.py      # exports/digimon.{json,csv}, digidex.sqlite

# 图片本地缓存（不提交 git）
uv run python scripts/download_images.py
```
