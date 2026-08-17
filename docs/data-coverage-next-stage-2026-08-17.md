# DigiDex 真实数据覆盖与人工复核状态（P1-2，2026-08-17）

> 所有数字来自对 `data/digidex.sqlite`（snapshot 2026-08-16，schema v8）的只读查询，
> 不是旧文档拷贝。本页是"数据质量 + 人工复核闭环"的事实基线：
> 有来源则记录来源，无来源则保留明确缺失，不编造、不默认填充。

## 总量

- 总数 1736 = 官方 1316 + 扩展 420

## 逐字段覆盖（当前真实库）

| 字段 | 缺失/未知 | 说明 |
|---|---:|---|
| 简体中文名 | 324 | 均无可信来源（field_coverage `no_source`），不批量生成 |
| 日文名 | 82 | 同上 |
| 英文名 | 0 | 完整 |
| 等级 | 171 | `level IS NULL OR 'unknown'`（含 No Level 特殊实体） |
| 属性 | 261 | 同上 |
| 类型 | 201 | 无 digimon_type 行 |
| 简介 | 305 | 三语言简介全空 |
| 技能 | 206 | 无 digimon_skill 行 |
| 主图（digimon_image main_image 行） | 248 | 1488 只有主图行/文件 |
| 缩略图（digimon_image thumbnail 行） | 248 | 1488 只有缩略图（`thumbs/digi_<id>.png`，均已下载） |
| 首次登场 | 19 | date 与 title 均空 |
| 进化关系 | 118 | 无 in/out evolution_edge |
| 来源/provenance | 0 | 每条 digimon 均有 provenance 行 |

## 图与技能规模

- evolution_edge：18670 条（有向多对多，允许环）
- skill：7213 个

## 人工复核队列（`manual_review_queue`）

- open：775
- resolved：0
- wontfix：0

> wontfix 语义：仅表示"暂不处理"，不表示"事实已验证"（任务书规则）。未解决冲突
> 保留在队列与 `data_conflict`，不伪装为已确认数据。

## 图片路径契约（P0-1 迁移后）

- `digimon_image.local_path` 绝对路径：**0**（1488 主图 + 1488 缩略图全部为缓存根相对路径）
- `digimon.thumbnail` 非空：1488，全部为 `thumbs/digi_<id>.png` 相对路径
- 主图文件已统一为哈希式文件名 `digi_<id>_<sha8>.<ext>`

## 失败样本分类（verify_samples --json）

`verify_samples.py --n 50 --seed 20260815`：50/50 干净通过，固定 16/16。
报告含 `run_id`、`sources`、`review_queue`、`failure_categories`（
`no_source` / `fetch_failure` / `parse_failure` / `match_failure` / `conflict` /
`image_missing`；`manual_pending` 以 `review_queue.open` 表达）。本次抽查
failure_categories = `{image_missing: 7, no_source: 7}`（仅记录缺口，不阻塞发布）。

## 结论

无 pipeline 丢失字段的硬失败（`sync_failure` 0、validator error 0 或每项均列出原因）；
全部缺口均为真实无来源或待人工复核，按任务书保留 NULL/unknown/unverified。
