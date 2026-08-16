# S2-2 游戏技能接入 — 来源调研与现状

> 结论：**当前无可靠、可及、许可明确的游戏技能来源**，`game_skill` 保持为空（合法状态，
> 与质量报告一致），不阻塞核心自用图鉴。本文记录调研过程与未来接入路径。

## 一、调研结论

| 项 | 结论 |
|---|---|
| digidb.io（Cyber Sleuth 游戏数据源） | 对机器人返回 **403**（适配器 docstring 已注明），无法直接抓取每只的招式页 |
| 本仓库使用的社区镜像 `data/raw/digidb/digidb.json` | 341 行，列：no/digimon/image/stage/type/attribute/memory/equip slots/hp/sp/atk/def/int/spd —— **不含招式/技能列** |
| 已接入的其他来源（dapi/wikimon/official/digimons_net） | 均为世界观技能（`skill` / `digimon_skill`），**不是**按游戏的 `game_skill` |
| 许可/版本 | 未找到带明确"游戏名 + 版本 + 许可"的可及数据集 |

## 二、为什么 `game_skill` 为空是合法状态

- 产品规格 §10/§17：canonical 世界观技能与 `game_skill` 严格分离；无来源时显示"暂无"。
- 当前 schema（v8）已包含 `game` / `game_digimon_stats` / `game_skill` 三张表；
  `game_skill` 有 `game_id / skill_id / digimon_id / name / description / effect /
  power / element / source / UNIQUE(game_id, name, digimon_id)`，**就绪可用**。
- `game_digimon_stats`（Cyber Sleuth 数值）已有 341 行真实样本可追溯
  （来源 digidb、游戏名/版本在 `game` 表 notes 中）——这是"真实版本样本可追溯"的既有部分。

## 三、未来接入路径（当来源明确时）

1. 找到带明确许可、可及的游戏技能数据集（如社区镜像补充 moves 列、或官方 API）。
2. 在 `pipeline/sources/digidb.py`（或新适配器）解析为 `game_skill` 形状，逐条记录：
   `game_id / 版本 / source / source_url / fetched_at`，绝不与 canonical `skill` 混写。
3. 同名不同版本技能：按 `(game_id, name, digimon_id)` 唯一键区分，不跨版本合并（任务书风险项）。
4. 详情页"游戏数据"区在 `game_skill` 非空时展示，空时保持现状（无假内容）。

## 四、现状验收

- "不覆盖 canonical skill 或 world-view 属性"：`game_skill` 为空 → 零污染 ✓
- "无来源时显示暂无"：详情页游戏区只展示真实 `game_digimon_stats`，技能无假数据 ✓
- "至少一组真实版本样本可追溯"：`game_digimon_stats` 341 行（Cyber Sleuth）可追溯 ✓
- 质量报告已如实标注 `game_skill` 为 0（合法状态，非误报完成）。
