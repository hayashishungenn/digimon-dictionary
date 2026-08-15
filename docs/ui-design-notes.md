# UI 参考与设计结论（UI-P0 前置）

> 执行 UI 设计前实际查看的参考与借鉴结论，最终任务报告需据此列出借鉴点/未采用点。

## 一、实际查看的参考

| 参考对象 | 查看方式 | 时间 |
|---|---|---|
| 官方 Digimon Encyclopedia `digimon.net/reference_en/` | 抓取真实 HTML 解析 | 2026-08-15 |
| Wikimon Visual List `wikimon.net/Visual_List_of_Digimon` | 抓取真实 HTML 解析 | 2026-08-15 |
| Marchin/DigiDex（GitHub） | README 不可直接获取；采用任务书转述的交互闭环 | 2026-08-15 |
| BSoD38/time-stranger-tree（GitHub） | README 不可直接获取；采用任务书转述的 Tree/Codex 双模式 | 2026-08-15 |

## 二、实际观察到的交互结论

### digimon.net/reference_en（官方图鉴）

- 首页**入口即搜索 + 条件筛选**：`Refined search`（精炼搜索）叠加字母序 A–Z 与 `None` 选项。
- 筛选维度：**Level**（In-Training Ⅰ / Ⅱ、Rookie、Champion、Ultimate、Mega、Armor、Hybrid、Xros Wars、Unknown）、
  **Attribute**（Vaccine / Data / Virus / Free / Variable / Unknown / NO DATA）、**Type**（Undead / Invader / Alien /
  Humanoid / Ancient / Ghost / Cyborg / Slime …）。
- 视觉为**高密度列表优先**（字母网格），不是装饰性卡片墙；`NO DATA` 明确出现在筛选项里（缺失不隐藏）。
- 品牌导航与数据区层级分明（顶部品牌导航、下方数据列表）。

**借鉴**：入口第一是搜索与筛选；缺失值显式可选（`NO DATA`）；列表密度高；字母/名称浏览。
**未采用**：官方纯英文名枚举列表，无三语并列；不复制其版式/配色/文案。

### wikimon.net/Visual_List_of_Digimon（视觉列表）

- 全页**图片网格**，按名称字母顺序扫览，适合发现型使用；每格即缩略图入口。
- 与详情页（Reference Book 页）互相跳转；兼顾官方与扩展资料。

**借鉴**：图片网格用于快速扫览；缩略图→详情跳转；官方+扩展同列表呈现。
**未采用**：无筛选工具条，纯字母网格；不复制其图片/排版。

### Marchin/DigiDex（开源图鉴）

任务书转述：搜索、数据详情、进化浏览、过滤、个人列表构成完整闭环；本地数据获取/缓存与 UI 分层。
**借鉴**：核心闭环完整性；本地优先。
**未采用**：不复制其代码/资源/品牌视觉。

### time-stranger-tree（交互思想）

任务书转述：Tree/Codex 双模式、搜索快捷键、lineage focus、生成阶段导航、图谱与表格互跳、循环图安全、深链与 route focus。
**借鉴**：本项目的进化图已支持"简单列表 + 图谱 depth 1..3"双模式与循环安全，与此思想一致。
**未采用**：不接入其游戏专属数值与代码。

## 三、落到本项目的设计决策

1. 首页 = 搜索框（首屏主操作）+ 等级/属性/类型/领域/组织/X抗体/官方扩展筛选工具条 + 图鉴网格；
   桌面用分组工具条，移动端用抽屉/bottom sheet。
2. 缺失值显式表达：`unknown / 暂无 / 未验证` 用琥珀/灰色标签，绝不隐藏（对齐官方 `NO DATA` 的诚实）。
3. 卡片高密度：缩略图/占位 + 三语名 + slug/编号 + 等级 + 属性 + 官方/扩展 + 中文名状态 + 收藏；
   长名称不撑破卡片（截断/换行策略），不一次性渲染全部 1736 条（分页）。
4. 详情页 = 档案页：HEADER（主图+三语名+slug+状态+收藏）→ BASIC DATA → Profile → 首次登场 →
   Skills → Evolution（简单/图谱双模式）→ Related/Name Origin/Source。
5. 数据快照/总数来自 API，不硬编码（对齐 spec §24）。
6. 视觉：数码终端/数字档案（深石墨/深海蓝底、电光青交互色、琥珀警告、红色仅错误、细网格/扫描线、
   编号标签、mono 数字），禁用网络字体/图标/图片。

## 四、统一 design tokens（落在 apps/web/src/app.css）

- 背景：页面 `--bg-page` / 面板 `--bg-panel` / 浮层 `--bg-overlay`。
- 文本：`--text-primary / secondary / muted / disabled`。
- 状态色：`--accent`（电光青）、`--accent-soft`、`--warning`（琥珀）、`--danger`（红，仅错误）、`--success`（绿）。
- 边界/焦点：`--border`、`--focus-ring`。
- 间距 `--space-1..8`、圆角 `--radius-sm/md/lg`、阴影/辉光 `--shadow/glow`。
- 内容最大宽度、网格间距、动画时长与 easing、`prefers-reduced-motion` 覆盖。
