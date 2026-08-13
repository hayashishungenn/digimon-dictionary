# 数据库 Schema

数据库：SQLite（`data/digidex.sqlite`），FTS5 全文搜索。所有 schema 定义见 `pipeline/core/schema.py`。

## 设计原则

- **Canonical ID**：`digimon.canonical_slug` 是稳定内部标识（如 `agumon`、`agumon-x-antibody`）。外部 ID（`dapi_id`、`wikimon_title`、`official_slug`、`digimons_net_slug`、`digidb_id`）只是普通列，**永不作主键**。
- **进化 = 有向多对多图**：`evolution_edge(from, to)`，允许环与多源。
- **枚举独立建表**：type/field/group 均为 lookup + join 表。
- **Provenance**：`provenance` 表按 (entity, field, source) 记录出处。
- **世界观与游戏数值分离**：`game_digimon_stats` 按游戏独立，绝不混入 digimon 主表。

## 表一览

| 表 | 用途 |
|---|---|
| `digimon` | 核心实体：canonical_slug、三语言名、level/attribute/type、X抗体、官方/扩展标记、首次登场、简介、图片、外部 ID |
| `digimon_alias` | 别名（official/dub/romanization/... 各语言），搜索匹配 |
| `type` / `digimon_type` | 类型（独立表 + 多对多，`is_primary` 标记主类型） |
| `field` / `digimon_field` | 适应领域（多对多） |
| `grp` / `digimon_group` | 组织（多对多） |
| `skill` / `skill_alias` / `digimon_skill` | 技能（三语言实体）、技能别名、数码兽-技能关联（skill_type, is_signature） |
| `evolution_edge` | 进化边（from→to, evolution_type, condition, source, confidence, is_primary_line） |
| `digimon_relation` | 非进化关联（variant/x_antibody/mode_change/...） |
| `digimon_image` | 图片记录（类型、URL、本地路径、sha256、下载状态、版权备注） |
| `provenance` | 逐字段出处 |
| `data_conflict` | 数据冲突（source_a vs source_b + resolution） |
| `manual_review_queue` | 需人工确认的实体/关系 |
| `game` / `game_digimon_stats` | 游戏及该游戏内的数值（hp/sp/atk/def/int/spd/memory/slots/extras） |
| `snapshot` | 数据集快照（snapshot_date、official/extended/total count） |
| `source_sync` | 各源同步状态（content_hash → 增量跳过） |
| `digimon_fts` | FTS5 搜索索引（canonical_slug + 三语言名 + aliases） |

## 关键枚举（规范化后）

- level：`digi_egg | baby_i | baby_ii | child | adult | perfect | ultimate | super_ultimate | armor | hybrid | unknown`（原始值保存于 `level_raw`）
- attribute：`vaccine | virus | data | free | variable | unknown`
- evolution_type：`normal | jogress | dna | armor | spirit | slide | mode_change | x_evolution | burst | fusion | death | special | game_specific | unknown`
- relation_type：`variant | x_antibody | mode_change | black_variant | same_species | fusion_component | counterpart | related`
- name_zh_cn_status：`official | official_game | official_anime | community | transliteration | unverified`

定义见 `pipeline/core/enums.py`。
