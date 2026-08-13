# 数据来源策略

本文档汇总对每个数据源的调研结论与使用方式。原则：外部源只是 INGEST SOURCE，项目自带 Canonical 数据库；单一源失效不影响系统。

## 源总览

| 源 | 类型 | 用途 | 许可证/版权 | 状态 |
|---|---|---|---|---|
| digi-api.com | REST API | 实体骨架、英文名、等级/属性/类型/领域、技能、简介(EN/JA)、进化、图片 | CC-BY-SA 3.0（内容源自 Wikimon）；商标归 Bandai | ✅ 已实现 |
| wikimon.net | MediaWiki API | 日文名、中文名(CHI/ZHO)、英文配音名、类型/领域/组织、相关形态、进化、简介、词源、设计年份 | 内容 CC-BY-SA 3.0；图片未单独授权（Bandai/Toei 版权） | ✅ 已实现 |
| digimon.net/reference | HTML/PHP | **官方状态验证**、官方三语名称、官方等级、必杀技、简介 | **明确禁止无断转用/转载** → 仅个人研究读取元数据，不下载官方图片 | ✅ 已实现 |
| digimons.net | HTML | 简体中文社区通用译名 | 中文社区站 | ⏳ 调研中 |
| digidb.io | HTML | 游戏数值（Cyber Sleuth 等，独立于世界观） | — | ⏳ 调研中 |

## digi-api.com（已核实）

- **总数 1,488**（ID 1–1488 连续）；列表 `GET /api/v1/digimon?pageSize=1000`
- 记录字段：`id / name(仅英文) / xAntibody / images[{href,transparent}] / levels[{level}] / types[{type}] / attributes[{attribute}] / fields[{field}] / releaseDate / descriptions[{origin,language(ja|en_us),description}] / skills[{skill,translation,description}] / priorEvolutions[{id,digimon,condition}] / nextEvolutions[...]`
- **无中文/日文名**（日文仅在 descriptions 的 `jap` 语言）
- 进化：`prior/nextEvolutions` 是宽松的“某作品可进化”边（条件含 jogress 等），噪声大，标记 confidence=medium
- 图片：`https://digi-api.com/images/digimon/w/{Name}.png`，320×320 不透明 PNG
- 覆盖：含官方 Reference Book 之外的游戏/动画/粉丝形态；有 fanmade-only 记录；缺少量官方中文专属条目
- 维护：个人项目，无速率限制文档，Cloudflare CDN 缓存

## Wikimon（已核实）

- MediaWiki 1.35，API 开放；`action=query&prop=revisions&rvprop=content` 批量可取 wikitext
- `{{S2}}` 信息框字段：`kan`(日文名)、`dub`(配音名)、`ol`({{CHI}}繁/{{ZHO}}简/{{KOR}}韩)、`l1/a1/t1`(等级/属性/类型)、`f1..f7`(领域)、`g1`(组织)、`s1..s15`(相关形态)、`pn/pe/pj`(简介块，编号不统一)、`ety`(词源)、`yd`(设计年份)、`drbentry`(官方图鉴登记号 → 官方状态)
- `==Evolves From==` / `==Evolves To==`：`* [[名]]`，**加粗=主线**，括号=条件；卡牌通用规则行是噪声需过滤
- **API 慢且间歇 500** → 必须重试+退避
- 枚举：`Category:Digimon`（约 1,658 成员）或 `allpages`
- 覆盖为官方超集：含游戏/动画/未发售/联动形态

## digimon.net 官方 Reference Book（已核实）

- **总数 1,316**；列表 `reference_{lang}/request.php`（`next` 分页 96/页，返回 -1 结束）
- 语言子目录：`reference`(JA)、`reference_en`(EN)、`reference_zh-CHS`(简体)、`reference_ko`(KO)
- 列表字段：`directory_name`(全局 slug)、`name`(本地化名)、`level`(本地化等级)、`level_2`(Xros Wars 标记)、`icon_20th`、`icon_new`、`relate_word6`(〇 = X抗体)
- 详情页（服务端渲染）：Level→Type→Attribute→Special Move→Profile→相关数码兽
- **官方图鉴已无 Field 数据**；图片来源 `cimages/digimon/{slug}.jpg`（320×320 白底 JPEG，非透明）
- 版权页明确禁止无断转载 → **不下载官方图片**；仅读取元数据验证官方状态与官方名称
- 无反爬

## 名称来源优先级

| 语言 | 优先级 |
|---|---|
| 简体中文 | ① 官方 ZH-CN（digimon.net list）② digimons.net 长期通用译名 ③ Wikimon {{ZHO}} ④ 官方中文作品/游戏 |
| 繁体中文 | Wikimon {{CHI}} |
| 日文 | ① 官方 Reference（list ja）② Wikimon `kan` |
| 英文 | ① 官方 EN ② digi-api `name` ③ Wikimon 页面标题 |
| 英文配音 | Wikimon `dub` |
| 韩文 | Wikimon {{KOR}}（辅助） |

## 冲突处理

- 术语差异（如 Rookie/Child）→ Normalization 映射到统一枚举，**非冲突**
- 同字段不同源不同值 → 记录 `data_conflict`（source_a/source_b/value_a/value_b/resolution）
- 无法自动判断 → `manual_review_queue`

## 版权边界

- **元数据**（名称、等级、类型、属性等事实性数据）：各源使用，来源可追溯
- **官方文本**（简介、技能描述）：个人研究使用，不公开重新分发
- **图片**：一律不提交 git，仅通过 `scripts/download_images.py` 本地缓存（digi-api/wikimon 源）；官方图片不下载
- README 声明：Digimon 角色/名称/美术版权归相应权利方，本项目不隶属 Bandai/Bandai Namco
