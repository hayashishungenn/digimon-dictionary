# 前端审计与视觉基线 — UI-P0-0

> 审计日期：2026-08-15。审计不改变数据和 API；仅记录现状、问题分类与后续 UI 阶段的输入。
> 设计方向与参考结论见 `docs/ui-design-notes.md`。

## 一、路由与组件清单

| 路由 | 文件 | 状态 |
|---|---|---|
| `/` 首页 | `apps/web/src/routes/+page.svelte` | 搜索/筛选/分页/卡片齐全 |
| `/about` 关于 | `apps/web/src/routes/about/+page.svelte` | 运行时计数 + 快照日期 + 来源/技术栈 |
| `/digimon/[slug]` 详情 | `apps/web/src/routes/digimon/[slug]/+page.svelte` | 档案页（header/basic/profile/skills/evolution/relations/name origin/conflicts/source/game stats） |
| `/group/[name]` 组织 | `apps/web/src/routes/group/[name]/+page.svelte` | 成员网格 |

| 组件 | 作用 | 复用情况 |
|---|---|---|
| `DigimonCard.svelte` | 卡片（缩略图/占位、三语名、level/attribute） | 首页 + 组织页 |
| `Badges.svelte` | level/attribute 徽章 + 中文标签映射 | 详情 + 卡片 |
| `PlaceholderImage.svelte` | 图片优雅降级（加载中/失败→占位） | 卡片 + 详情 + 进化 |
| `EvolutionGraph.svelte` | 简单模式 + 图谱模式（depth 1..3、截断） | 详情页 |
| `EvolutionSvg.svelte` | 图谱 SVG 渲染 | 进化图图谱模式 |
| `favorites.svelte.ts` | localStorage 收藏 store | 卡片 + 详情 |

需要拆分的组件（后续阶段）：AppShell（顶栏/导航/状态条）、SectionHeader（区域标题）、StatusBar（数据状态条）、SkillList、ProfileBlock、SourceTable。

## 二、设计现状（app.css）

已有较完整的暗色 "Digivice" tokens：`--bg/surface*/border/text*/accent/accent-2/gold/red/green/radius*/mono/sans/shadow`、level/attribute 语义色、卡片/按钮/输入/徽章/进化组件样式、两档响应式断点。

**缺口（对照 UI 任务书 §4）**：
- 无 `--space-*`、`--radius-md/lg`、`--focus-ring`、`--warning/danger/success` 语义别名。
- 无动画时长/easing tokens、无 `prefers-reduced-motion` 覆盖。
- `--accent-2`（紫色）用于 `name-tag`/`n-rel` 等状态，与“紫色渐变白底通用 AI 风格”需严格区分的约束接近——状态语义应收敛到 青/琥珀/红/灰。
- 大量内联样式（`style="font-size:11px"`、`style="color:var(--gold)"`）散落组件，应收敛为类。

## 三、API 字段 / 空 / 冲突 / 截断 清点

- 详情页已表达：来源缺失（`prov-status.missing`）、冲突（`conflict`）、图片状态（`downloaded/failed/missing`）、进化截断（`evo-status.warn` + `truncated` 说明）、游戏数值与世界观分离提示。
- **缺口**：`profile_verified` 未展示（"未验证"状态不可见）；无 404（未知 slug）专用状态（当前落入通用 error）；无 DB 不可用（503）专用文案。

## 四、问题分类

### correctness
- 首页 `LEVEL_TABS` 硬编码，缺 `super_ultimate` 与 `unknown`（meta 有 11 个 level）；应改由 `meta.levels` 派生，避免与 API 漂移。
- 组页 `load()` 无请求序号令牌（详情页已有 reqSeq），组名快速切换时旧响应可能覆盖新结果。

### readability
- 详情 profile 无 verified/未验证标记；名称状态标签用紫色，与状态语义系统不一致。
- 卡片缺 slug/编号与官方/扩展标记（任务书要求）。

### accessibility
- 无 skip-link；无 `prefers-reduced-motion`。
- 移动端筛选用 `<select>` 工具条（任务书要求抽屉/bottom sheet）。
- 顶栏无“收藏”入口（任务书要求导航含 首页/收藏/About）。

### performance
- 首页每页 60 张卡片 + lazy image，未一次渲染 1736 ✓。
- 无骨架屏（当前为 spinner，任务书 UI-P1-1 要求 skeleton）。

### visual consistency
- 紫色 `--accent-2` 作状态色与"无紫色 AI 风"约束冲突；内联样式需收敛。

## 五、UI 阶段输入（结论）

1. UI-P0-1 壳层：AppShell（Logo/首页/收藏/About）+ StatusBar（快照/总数来自 API）+ 统一容器/标题/面包屑；补 `prefers-reduced-motion` 与完整 tokens。
2. UI-P0-2 首页：等级 tabs 改由 `meta` 派生；移动端筛选抽屉；卡片补 slug/编号 + 官方/扩展 + 中文名状态；组页补请求序号。
3. UI-P0-3 详情：展示 profile verified 状态；404/DB 不可用专用状态。
4. UI-P0-4 进化：现状已达标（简单/图谱双模式、depth 1..3、截断可解释），仅做视觉收口。

## 六、基线

- `npm run check` / `test` / `build` / `test:e2e`（fixture 13）/ `test:e2e:realdb`（18）在审计前全绿（见 `docs/self-use-baseline.md`）。
- 审计本身零代码改动，作为可回滚 UI 基线。
