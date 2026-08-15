# S1-2 数据覆盖调查报告

> 目的：按价值核实每类数据缺口的根因（真实无来源 vs 管线未提取），并落实唯一可执行的
> 管线改进（Wikimon 主图 URL 提取）。所有结论均对真实 raw 快照与真实数据库核验，不编造。

## 一、覆盖现状（快照 2026-08-15，真实 DB）

| 字段 | 覆盖 | 缺口 |
|---|---|---|
| 英文名 | 1,736 / 1,736 (100%) | 0 |
| 日文名 | 1,654 / 1,736 (95.3%) | 82 |
| 简体中文名 | 1,412 / 1,736 (81.3%) | 324 |
| 等级（非 unknown） | 1,565 | no_source 67 / no_level 99 / conflict 5 |
| 属性（非 unknown） | 1,475 | no_source 211 / no_level 49 / conflict 1 |
| 主图 | 1,488 (85.7%) | 248 |
| 简介（en/ja/zh） | 1,431 / 1,378 / 0 | zh 无可靠来源 |
| 技能 | 1,530 只有技能（7,213 个） | 206 无来源 |
| 首次登场 | 有日期 1,717；**有标题 0** | 标题/媒介无来源 |

## 二、逐项根因核实（对真实 raw 快照验证）

### 1. 日文名缺口（82）——真实无来源，非管线漏失
对 82 只缺名实体的 `wikimon_title` / `official_slug` / `digimons_net_slug` 逐条查
`data/raw/{wikimon,official,digimons_net}/records.json` 的 ja 名：
**命中 0/82**。三个来源各自的 ja 覆盖（1316/1331/1630）已全部摄入；这 82 只是仅存在于
dapi（无 ja 字段）且无任何带 ja 的来源记录匹配的扩展实体。

### 2. 简体中文名缺口（324）——真实无来源
digimons_net（1,331 zh）、official（1,316 zh）、wikimon（579 zh）已全部摄入；
324 只无任何来源提供 zh 名。**结论：不编造。**

### 3. 首次登场标题/媒介（0）——真实无来源
- dapi 提供 `first_appearance_date`（年）1,488 条。
- official raw 的 `first_appearance_title/medium` 字段为 **None**（官方列表不返回标题）。
- wikimon raw 仅 `design_year`（已回填 `first_appearance_date`），无标题字段。
**结论：标题/媒介在已接入来源中不存在；UI 已保证"有日期即显示"。**

### 4. 图片缺口（248）——管线未提取（可改进）
`data/raw/wikimon/records.json` 中 `image_url/image_page` 为 **0**——Wikimon 适配器此前
**未从 S2 infobox 提取主图字段**（`|image=Foo.jpg`）。这是管线限制，不是数据缺失。
digi-api 图片覆盖 1,488；248 只为无 digi-api 图片的实体。

## 三、本阶段落实的管线改进

**Wikimon 主图 URL 提取（S1-2）**：`pipeline/sources/wikimon.py` 现从 S2 infobox 的
`|image=` 提取文件名，生成：
- `image_url = https://wikimon.net/Special:FilePath/<file>`（重定向到真实文件，无需知道
  MediaWiki 哈希路径，URL 稳定）
- `image_page = https://wikimon.net/File:<file>`

版权边界（`docs/sources.md` 已确认）：Wikimon 图片未单独授权（Bandai/Toei 版权），
**仅本地缓存、不提交 git**；`scripts/download_images.py` 的 `ALLOWED_IMAGE_HOSTS` 已含
`wikimon.net`，content-type 白名单已含 jpeg/png 等。

**生效方式**：下次联网全量同步（`uv run python scripts/sync_data.py --sources wikimon --force`）
后，`scripts/download_images.py` 即可为这些实体建立本地主图缓存，填补 248 缺口。
本次不联网重抓（避免长时网络操作），由单元测试验证提取逻辑。

## 四、结论

- 已接入数据已充分覆盖：100% en / 95.3% ja / 81.3% zh / 85.7% 主图 / 88% 简介 / 88% 技能。
- 除图片外，其余缺口**全部为真实无来源**（逐条对 raw 验证，0 例可补救），按项目规则保持缺失。
- 图片缺口为管线限制，本阶段已落实提取逻辑 + 单测；下一次联网抓取即可兑现。
- 固定名单 16 只 + 随机 50 只抽样验证全部通过（无硬失败），覆盖率与报告一致。
