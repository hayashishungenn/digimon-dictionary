# 产品规格 — DigiDex 数码宝贝全图鉴

> 本文档是项目的**需求基线**。任何实现决策不得与之冲突。项目性质：**个人研究、收藏、查询用途**。核心原则：**数据质量优先于 UI**——必须先建立可靠、可追踪、可验证的数据层，再制作图鉴前端。

## 1. 最终效果

- 用户打开图鉴可见所有已收录数码兽。
- 搜索 `亚古兽` / `Agumon` / `アグモン` 三种语言命中同一实体（同一 canonical ID）。
- 详情页至少展示：三语言名称、等级、属性、类型、X抗体、适应领域、必杀技（三语言+说明）、首次登场、名称来源、简介、前置/后续进化、相关形态、图片。

## 2. “所有数码兽”的定义 — 两个集合

| 集合 | 含义 | 标记 |
|---|---|---|
| OFFICIAL | 官方 Digimon Reference Book 已正式登记 | `is_official_reference=true` |
| EXTENDED | 社区可靠资料存在但官方未收录：特殊形态、模式变化、游戏/漫画独占、动画特殊个体、历史数码兽等 | `is_official_reference=false, is_extended=true` |

- 首页允许切换：`全部 / 官方图鉴 / 扩展图鉴`。
- **禁止硬编码理论总数量**。每次更新计算 `official_count / extended_count / total_count`，保存 `snapshot_date / source_last_updated`。

## 3. Canonical ID 设计（项目最重要的部分）

- **禁止**直接以中文名或英文名作主键（地区译名差异：Omegamon/Omnimon、Tailmon/Gatomon）。
- 建立稳定内部 ID：`digimon_id`（整数）+ `canonical_slug`（如 `agumon`、`agumon-black`、`agumon-x-antibody`、`agumon-2006`、`omegamon`）。
- 外部来源 ID 单独保存：`dapi_id / wikimon_title / official_slug / digimons_net_slug`。禁止第三方 API ID 成为系统主键。

## 4. 核心 Schema（实体）

- **digimon**：`id, canonical_slug, name_zh_cn, name_en, name_ja, name_romanized, name_zh_hk, name_zh_tw, name_en_dub, level, type, attribute, x_antibody, release_date, first_appearance, is_official_reference, is_extended, main_image, thumbnail, profile_zh_cn, profile_en, profile_ja, name_origin, created_at, updated_at`。
- **digimon_alias**：`digimon_id, alias, language, region, alias_type, source, verified`。alias_type 如 `official/dub/romanization/old_translation/fan_translation/game_translation/anime_translation/alternative_spelling`。搜索必须匹配别名。

## 5. 简体中文名优先级

1. 官方简体中文译名；2. 可靠中文数据库长期通用译名；3. 官方中文游戏/卡牌/动画名称；4. 社区稳定译名；5. 音译或自动生成（须 `name_zh_cn_verified=false`）。
- 禁止 AI 自造中文名伪装成官方。所有名称记录 `name_zh_cn_source` 与 `name_zh_cn_status`（`official/official_game/official_anime/community/transliteration/unverified`）。

## 6. 日文/英文名

- 日文优先官方 Reference Book / Wikimon Original Name。
- 英文区分 `original_romaji / official_english / english_dub`（如 Tailmon/Gatomon），不要强行覆盖。

## 7. 数值隔离

- **禁止伪造统一战斗数值**。Canonical 只保存世界观属性：level/attribute/type/field/group/x_antibody/skill/profile。
- 游戏参数单独建 `game` + `game_digimon_stats`（hp/sp/atk/def/int/spd/memory/slots…），不同游戏绝不互相覆盖。

## 8. 枚举

- **level** 统一标准化：`Digi-Egg/Baby I/Baby II/Child/Adult/Perfect/Ultimate/Armor/Hybrid/Unknown`；UI 中文：数码蛋/幼年期Ⅰ/幼年期Ⅱ/成长期/成熟期/完全体/究极体/装甲体/混合体/不明。保留原始 source value。
- **attribute**：Vaccine/Virus/Data/Free/Variable/Unknown。
- **type** 独立建表（勿用前端写死大数组）。
- **field**（适应领域）独立建表 + 多对多：Nature Spirits/Virus Busters/Nightmare Soldiers/Metal Empire/Deep Savers/Dragon's Roar/Wind Guardians/Jungle Troopers/Unknown。
- **group**（组织）多对多：Royal Knights/Seven Great Demon Lords/Olympus XII/Three Great Angels/Four Holy Beasts/D-Brigade/Legend-Arms/Ten Legendary Warriors/Three Musketeers/Bancho/Vortex Warriors 等，UI 点击组织可查看成员。

## 9. 技能系统

- 建 `skill`（`id, name_zh_cn, name_en, name_ja, description_zh_cn, description_en, description_ja, source`）、`digimon_skill`（`digimon_id, skill_id, skill_type, is_signature`）、`skill_alias`。
- skill_type：`special_move/signature_move/attack/ability/other`。
- 同一技能的三语言名称必须是同一 skill 实体（如 Baby Flame/ベビーフレイム/小型火焰）。
- **canonical_skill 与 game_skill 分离**。

## 10. 进化关系 = Graph（强制）

- 建 `evolution_edge`：`id, from_digimon_id, to_digimon_id, evolution_type, condition, source, confidence, is_primary_line`。
- 一兽可多来源进化到它、可进化成多兽。是 **有向多对多 Graph，不是 Tree**。禁止 prev/next 单链字段。
- evolution_type：`normal/jogress/dna/armor/spirit/slide/mode_change/x_evolution/burst/fusion/death/special/game_specific/unknown`。
- 动画主路线标 `is_primary_line=true`（如滚球兽→亚古兽→暴龙兽→机械暴龙兽→战斗暴龙兽），但**不删除其他可能路线**。详情页提供“代表进化路线/全部可能前置/全部可能后续”。

## 11. 简介 Profile

- 保存 `profile_zh_cn/profile_en/profile_ja` + `profile_source/profile_source_url/profile_verified`。
- **不得用 AI 自编设定填充缺失数据**；无可靠来源时显示“暂无可靠简介”。AI 只能翻译/整理/润色。

## 12. 首次登场与名称来源

- `first_appearance_date/title/medium`（medium：vpet/game/anime/manga/card/novel/web/other）。
- `name_origin` 仅在有可靠来源时保存；不得 AI 猜测并标成事实。

## 13. 图片系统

- 每兽至少 `main_image + thumbnail`；可扩展 `official_art/reference_art/sprite/card_art/anime_art/game_model`。
- 建 `digimon_image`：`id, digimon_id, image_type, remote_url, source_page, local_path, width, height, transparent, sha256, copyright_source, license_note, download_status`。
- 抓图前检查 robots.txt/ToS；优先 Digi-API / Wikimon 已有图片。
- `data/images/` 默认 gitignore，提供 `scripts/download_images.py` 本地下载。支持 fallback 与统一 placeholder，`image_status=missing` 不产生 broken image。

## 14. 数据来源策略

- 不设计成单一 API 失效→全项目不可用。外部源只是 INGEST SOURCE。
- 流程：`FETCH → RAW SNAPSHOT → PARSE → NORMALIZE → MATCH → MERGE → VALIDATE → DATABASE`。
- **保留 Raw**：`data/raw/<source>/` 保存 `fetch_date, source, source_url, HTTP metadata`。
- 推荐优先级：实体枚举=Wikimon Visual List + Digi-API；官方状态=Reference Book；日文=Official JP+Wikimon；英文=Official EN+Wikimon+Digi-API；简体中文=Official ZH-CN+可靠中文库+官方中文作品；技能=Digi-API+Wikimon+中文库；类型/属性/Field=Digi-API+Reference+Wikimon；进化=Digi-API+Wikimon；简介=Wikimon+Digi-API+允许的中文资料。
- **冲突不静默**：术语差异经 Normalization 映射统一枚举（非冲突）；真冲突写入 `data_conflict`（entity/field/source_a/value_a/source_b/value_b/resolution）。
- **Provenance**：关键字段保存 `source, source_url, retrieved_at, confidence`。

## 15. 实体匹配

- 策略：`Exact Japanese Name → Canonical English Name → Alias Match → Normalized Name → External ID mapping → Fuzzy Candidate → Manual Review`。
- 禁止纯 fuzzy 自动合并；置信度不足加入 `manual_review_queue`。

## 16. 标准化名称

- 处理空格/`-`/`:`/括号/全角半角/大小写/Unicode/X-Antibody/X Antibody/(X-Antibody)/Mode/模式。仅用于搜索匹配，不破坏原始显示名。

## 17. 搜索与筛选

- 搜索支持：中文、简繁转换、英文、日文、别名、部分匹配（`Agu`、`战暴`、`War Greymon`）。优先 SQLite FTS5。
- 筛选可组合：等级/属性/类型/X抗体/所属组织/Field/官方或扩展（如“究极体+疫苗+皇家骑士”）。
- 排序：名称/首次登场时间/最近添加/等级/ID。

## 18. 前端

- 首页视觉方向“数码终端/Digivice/数字世界数据库”，保持现代清晰高信息密度：LOGO、搜索框、等级 tab（全部/成长期/成熟期/完全体/究极体…）、筛选器、图鉴 Grid。
- 卡片：图片 + 中文名/英文名/日文名 + 等级/属性，不塞简介。
- 详情页结构：HEADER（大立绘+三语名+ID+别名）/ BASIC DATA / PROFILE / SKILLS / EVOLUTION / RELATED FORMS / NAME ORIGIN / SOURCE。
- 进化可视化：简单模式（前置↓当前↓后续）+ Graph 模式（默认 depth=1，可扩到 depth=2/3，禁止一次绘制全网络）。
- 相关形态 `digimon_relation`：`variant/x_antibody/mode_change/black_variant/same_species/fusion_component/counterpart/related`（如 WarGreymon/BlackWarGreymon/WarGreymon X）。
- 收藏：第一阶段 localStorage `favorite` 即可。

## 19. 技术栈与目录

- 前端 TypeScript + SvelteKit；后端 Python + FastAPI；数据库 SQLite；管线 Python；测试 pytest + 前端单测 + Playwright。
- 禁止无意义引入 K8s/Redis/ES/Kafka/微服务。
- 目录见根 README。命令：`sync-data`（检查源→抓新增→Raw→Normalize→Match→Merge→Validation→Reports→Database）。
- **增量更新**：保存 `source_updated_at/last_seen_at/content_hash`，hash 未变则跳过。
- **请求保护**：timeout/retry/exponential backoff/rate limit/User-Agent/cache；保守并发。

## 20. 数据验证与覆盖率报告

- 自动检查：duplicate canonical_slug、duplicate external ID、missing 中/英/日名、missing image、missing level/attribute、broken image、broken evolution edge、self evolution、unknown target、duplicate edge、orphan skill/relation。输出 `data/reports/data-quality.json` + `.md`。
- 覆盖率：名称（zh/en/ja，分别 total/verified/community/unverified/missing）；图片（total/available/downloaded/missing/broken）；简介（zh/en/ja）；技能（有技能兽数/技能总数/各语言名/有描述）；进化完整性（from/to 必须存在、禁悬空引用、Graph 必须支持 cycle——发现环不算错误）。

## 21. 版权

- 图片不因网页可访问就公开重分发。区分 metadata/community text/official text/official artwork/community artwork。
- 不明确允许分发的图片保存 source URL + download script + local cache，不提交 git。
- README 声明：Digimon 相关角色、名称与美术版权归相应权利方；本项目不隶属 Bandai/Bandai Namco。

## 22. 性能 / 移动端 / 可访问性

- lazy image、分页/虚拟化 grid、search debounce、image cache、route-level loading。
- 适配 1920×1080 / 1440×900 / 1366×768 / iPad / 390×844。
- 图片 alt、键盘搜索、明显 focus、按钮语义、合理 contrast。

## 23. 测试要求

- Pipeline：parser/normalizer/entity matching/alias matching/merge/dedup/graph/validation。
- API：list/detail/search/filter/aliases/evolution。
- Frontend：search/filter/detail navigation/favorite/missing image/empty state。
- E2E：打开首页→搜索“亚古兽”→找到 Agumon→详情三语名；搜“Agumon”“アグモン”→同一实体；查看技能；点击后续进化→对应详情；按“究极体+疫苗”筛选；收藏；刷新后收藏仍在。
- 人工抽样验证 ≥50 只随机 + 固定列表（Agumon/Gabumon/Greymon/WarGreymon/Omegamon/Tailmon/Angewomon/Renamon/Dukemon/Imperialdramon/Lucemon/Alphamon/Jesmon/Beelzebumon/Shoutmon/Gammamon）核对三语名/等级/类型/属性/图片/技能/简介/进化。
- 特殊案例：X-Antibody、Black variants、Burst/Fighter/Paladin/Crimson Mode、Mode Change、Armor、Hybrid、Jogress、Xros、同名/近似名、无 Level 特殊实体、多属性实体、多类型来源冲突。

## 24. 版本与导出

- About 页显示运行时生成的 snapshot date 与 official/extended/total 数量（禁止 README 写死总数）。
- 导出 JSON/CSV/SQLite → `exports/digimon.json, digimon.csv, digidex.sqlite`。

## 25. 不可退化

- 不能只产出 `digimon.json` 了事（必须存在可用 Web 图鉴）；也不能用几十条 mock 数据做漂亮 UI（UI 必须连接真实 canonical dataset）。

## 26. 执行顺序

INSPECT → RESEARCH → DEFINE SOURCES → DESIGN SCHEMA → IMPLEMENT INGESTION → FETCH RAW DATA → NORMALIZE → ENTITY MATCHING → MERGE → VALIDATE → FIX DATA PROBLEMS → BUILD DATABASE → BUILD API → BUILD WEB UI → SEARCH → FILTER → DETAIL PAGE → SKILLS → EVOLUTION GRAPH → IMAGE PIPELINE → TEST → BUILD → E2E → DATA QUALITY REVIEW → CODE REVIEW → FIX → RETEST。

## 27. 第一阶段完成标准

数据：官方集合+扩展集合、稳定 Canonical ID、三语言体系、无严重重复、来源可追踪、技能/进化图/图片管线正常、质量报告生成。
图鉴：列表/搜索/筛选/详情/三语言/技能/简介/图片/进化/相关形态/收藏/来源。
工程：build + unit + integration + E2E + data validation。

## 28. 最终交付报告

必须给出真实统计：1.总收录数 2.官方数 3.扩展数 4.有中文名数 5.有英文名数 6.有日文名数 7.三语言完整率 8.有图片数 9.图片覆盖率 10.有简介数 11.有技能数 12.技能总数 13.进化关系数 14.数据来源 15.仍需人工确认数据 16.测试结果 17.Build 结果 18.E2E 结果 19.运行方式。

## 29. 最终原则

目标是**可长期维护的 Canonical Knowledge Base**，UI 只是查询入口。最重：完整、准确、三语言、可追踪、可验证、可更新、不重复、不虚构。冲突时保存来源并比较，无法自动判断进 `manual_review_queue`。
