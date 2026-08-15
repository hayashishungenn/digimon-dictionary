# DigiDex 前端与 UI 制作任务书

> 用途：完整粘贴到 Claude Code 自动模式执行。
>
> 产品目标：在现有 SvelteKit + FastAPI 图鉴上制作一套适合个人长期查询的前端。公网部署不在本任务范围。
>
> 执行仓库：C:\Users\Hayas\Github\Digimon_Dictionary
>
> 设计方向：数码终端 / Digital Archive / Digivice 数据档案。界面应像一个专业的数字世界档案终端，不是通用后台，也不是普通卡片博客。

## 一、在线参考与借鉴原则

执行 UI 设计前必须实际查看以下参考，并把得到的交互结论写入实现说明：

1. 官方 Digimon Encyclopedia：
   https://digimon.net/reference_en/

   借鉴：
   - 入口优先是搜索和条件筛选；
   - 详情页聚焦名称、等级、类型、属性、必杀技和 Profile；
   - 多语言切换应靠近搜索/详情入口；
   - 官方数据与品牌导航有明确层级。

2. Wikimon Digimon Reference Book 说明：
   https://wikimon.net/Digimon_Reference_Book

   借鉴：
   - 兼顾官方集合和扩展资料；
   - 允许按名称、等级、属性、类型浏览；
   - 详情页要能表达资料来源和不同媒体/游戏背景。

3. Wikimon Visual List：
   https://wikimon.net/Visual_List_of_Digimon

   借鉴：
   - 图片网格适合快速扫览；
   - 按阶段和名称浏览适合发现型使用；
   - 视觉列表和详情页应互相跳转。

4. The Digital Empire species index：
   https://thedigitalempire.net/digidex/species/

   借鉴：
   - Table/Thumbnails 两种视图；
   - 点击或输入过滤；
   - 列表中同时呈现名称、等级、属性、类型、年份、Reference Book/Wikimon 链接；
   - 对个人查询，表格视图有时比纯卡片更高效。

5. DigiDex 开源项目：
   https://github.com/Marchin/DigiDex

   借鉴：
   - 搜索、数据详情、进化浏览、过滤、个人列表是完整图鉴的核心闭环；
   - 本地数据获取/缓存和 UI 展示应分层。
   不得复制其代码、图片、Unity 资源或品牌视觉。

6. Time Stranger Tree：
   https://github.com/BSoD38/time-stranger-tree

   借鉴：
   - Tree/Codex 双模式；
   - 搜索快捷键、lineage focus、生成阶段导航；
   - 图谱与表格互相跳转；
   - 循环图安全、深链和 route focus。
   当前项目只借鉴交互思想，不接入其游戏专属数值和代码。

7. Digimon Time Stranger Guide & Team Builder：
   https://github.com/vitorfdl/game-digimon-story-time

   借鉴：
   - 全局搜索；
   - reference sheet；
   - 响应式暗色界面；
   - localStorage 保存个人队伍/收藏的思路。
   不得把游戏攻略字段混入世界观图鉴字段。

8. The Digital Empire、Digi-Evolve 等站点用于观察表格、阶段筛选和进化浏览：
   https://digi-evolve.com/
   https://digidex.itch.io/app

参考边界：

- 只借鉴信息架构、交互模式、密度和可用性。
- 不复制源站 CSS、代码、图片、商标、logo、原文文案或布局细节。
- 任何第三方素材必须遵守项目现有版权和本地缓存规则。
- 如果参考站点之间冲突，以本项目真实 API、AGENTS.md 和 docs/product-spec.md 为准。
- 参考结果必须在最终任务报告中列出：参考对象、借鉴点、未采用点和原因。

## 二、执行规则

1. 开始前阅读 AGENTS.md、CLAUDE.md、README.md、docs/product-spec.md、本任务书和现有前端。
2. 执行 git status --short --branch，保留用户修改。
3. 先确认 API response contract，再实现 UI，不根据猜测修改字段。
4. 复用现有 Svelte 组件、API client、favorites store、PlaceholderImage、EvolutionGraph 和真实 DB。
5. 不重写为 React，不引入重量级 UI/CSS/图表框架，不依赖远程字体或公网图片。
6. 所有页面必须处理 loading、empty、error、missing data、missing image 和 truncated graph。
7. 缺失事实显示暂无、未知、未验证或待复核，不填充假内容。
8. 先定义统一 design tokens，再逐页改造。
9. 每个 UI 阶段补测试，至少跑一次真实 DB Playwright。
10. 每个阶段检查 diff 并创建原子 commit，不自动 push。

## 三、体验目标

个人用户进入图鉴通常有五类任务：

- 找到某个数码兽；
- 比较三语名称和属性；
- 查看技能、简介、来源和首次登场；
- 沿进化/关联形态继续探索；
- 收藏或记录个人研究信息。

首页必须优先服务搜索和筛选；详情页必须优先服务信息阅读和继续导航；About 页必须优先服务数据可信度和运行状态。

## 四、视觉系统

### 4.1 主题方向

采用数码终端 / 数字档案风格：

- 深石墨或深海蓝背景；
- 电光青作为主要交互色；
- 琥珀用于社区译名、未验证、待复核和警告；
- 红色只用于错误；
- 细网格、扫描线、编号标签、分层面板和微弱噪点制造终端氛围；
- 保持高信息密度，但使用清晰层级和留白；
- 形成一个可记忆的识别点：状态条、档案编号、数据快照和终端式卡片系统。

禁止：

- 紫色渐变白底的通用 AI 风格；
- 每个页面一套不同颜色；
- 大面积发光、弹跳、旋转；
- 依赖公网字体、图标或图片；
- 装饰压过名称和数据。

### 4.2 CSS tokens

在 apps/web/src/app.css 集中定义：

- 页面、面板、浮层背景；
- 主文本、次文本、弱文本、禁用文本；
- accent、accent-soft、warning、danger、success；
- border、focus-ring；
- spacing scale、radius scale；
- shadow/glow；
- 内容最大宽度、网格间距；
- 动画时长和 easing；
- prefers-reduced-motion 覆盖变量。

组件禁止散落大量硬编码颜色和间距。

### 4.3 字体与图标

1. 先检查仓库和系统可用字体。
2. 选择一个有辨识度的标题字体和一个可读正文/等宽辅助字体，但不得依赖网络加载。
3. 数字、canonical slug、source、snapshot、level 使用统一 mono 样式。
4. 优先使用现有 SVG/CSS 图标，不为几个图标引入大型库。
5. 图标按钮必须有 aria-label 和可见解释。

### 4.4 状态语义

统一表达：

- verified/source-present：青色或绿色；
- community/transliteration/unverified：琥珀；
- conflict/review：橙红；
- missing/no-source：灰色；
- loading：低对比 skeleton；
- error：红色提示；
- truncated：琥珀警告条。

状态必须同时有文字、图标或标签，不得只靠颜色。

## 五、按优先级执行的 UI 任务

---

## UI-P0-0：前端审计和视觉基线

### 目标

确认现有路由、组件、API 类型、CSS、测试和真实数据状态，建立可回滚 UI 基线。

### 改动范围

- apps/web/src/app.css
- apps/web/src/routes/+layout.svelte
- apps/web/src/routes/+page.svelte
- apps/web/src/routes/digimon/[slug]/+page.svelte
- apps/web/src/routes/group/[name]/+page.svelte
- apps/web/src/routes/about/+page.svelte
- apps/web/src/lib/components/
- apps/web/src/lib/api/
- apps/web/src/lib/stores/
- apps/web/tests/

### 执行要求

1. 使用真实 DB 记录首页、Agumon 详情、组织页、About、缺图页和图谱模式基线。
2. 清点颜色、字体、间距、按钮、卡片、状态提示和重复 CSS。
3. 清点 API 字段的 null、来源、冲突和截断状态。
4. 将问题按 correctness、readability、accessibility、performance、visual consistency 分类。
5. 不以小型 fixture 的漂亮状态替代真实长名称、缺失字段和大图谱。

### 验收标准

- 有路由/组件清单和 UI 基线说明。
- 明确复用组件和需要拆分的组件。
- 审计不改变数据和 API。

### 依赖关系

无。

### 风险

不要在审计阶段顺手升级 Svelte/Vite 或大规模重写。

---

## UI-P0-1：应用壳层、导航和终端档案感

### 目标

让用户打开页面就理解这是可搜索的数码宝贝数据档案系统。

### 改动范围

- apps/web/src/routes/+layout.svelte
- apps/web/src/app.css
- 可新增小型 AppShell、StatusBar、SectionHeader 组件
- apps/web/src/lib/assets/favicon.svg

### 执行要求

1. 顶部提供 Logo/产品名、首页、收藏、About/数据状态。
2. 数据快照和总数来自 API，不硬编码。
3. 桌面和移动端都能快速回首页和搜索。
4. 统一页面容器、顶栏、分隔线、标题、面包屑。
5. 用编号、标签和状态条增强终端感，但不阻碍内容。
6. 所有交互具备 hover、focus-visible、active、disabled 状态。

### 验收标准

- 任意页面一到两步可回首页或开始搜索。
- 390×844 无横向溢出。
- 键盘可以到导航、搜索、收藏和主要按钮。
- About 展示运行时 snapshot、官方、扩展和总数。
- 刷新后收藏不丢。

### 依赖关系

依赖 UI-P0-0。

### 风险

不要把导航做成只有鼠标可用的图标条；不要在顶栏塞入过多统计。

---

## UI-P0-2：首页搜索、筛选和图鉴卡片

### 目标

把首页做成高效率查询入口，同时支持按阶段、属性和组织发现内容。

### 改动范围

- apps/web/src/routes/+page.svelte
- apps/web/src/lib/components/DigimonCard.svelte
- apps/web/src/lib/components/Badges.svelte
- apps/web/src/lib/components/PlaceholderImage.svelte
- apps/web/src/lib/api/client.ts、types.ts
- apps/web/src/app.css

### 执行要求

1. 搜索框为首屏第一主操作，支持输入、清除、loading、无结果和失败。
2. 搜索模式与普通列表模式有明确标签。
3. 支持等级、属性、类型、领域、组织、X-Antibody、官方/扩展和排序。
4. 桌面使用分组筛选工具条；移动端使用抽屉或 bottom sheet。
5. 卡片展示缩略图/占位、三语名、slug/编号、等级、属性、官方/扩展、中文名状态和收藏。
6. 长名称、无中文名、无日文名和模式名称不能撑破卡片。
7. 收藏按钮与链接不能产生嵌套交互问题。
8. 分页、总数、当前条件和清除入口清楚。

### 验收标准

- 真实 DB 搜索 亚古兽、Agumon、アグモン、战暴、Wargre 正确。
- 旧搜索结果不会覆盖新结果。
- 组合筛选与 API 一致。
- 390×844、768、1366×768、1920×1080 稳定。
- 缺失图片和名称状态可见。
- 不一次性渲染 1736 条数据。

### 依赖关系

依赖 UI-P0-1 和 API contract。

### 风险

不能用虚构中文名填补卡片空白，不能删除分页。

---

## UI-P0-3：详情页信息架构和可信度表达

### 目标

让详情页成为真正的档案页：快速读核心信息，也能继续追踪来源和关系。

### 改动范围

- apps/web/src/routes/digimon/[slug]/+page.svelte
- apps/web/src/lib/components/Badges.svelte
- apps/web/src/lib/components/PlaceholderImage.svelte
- apps/web/src/lib/api/types.ts
- apps/web/src/app.css
- 必要时新增 ProfileBlock、SourceStatus、SkillList、AppearanceMeta

### 信息层级

1. Header：主图/占位、三语名、slug、官方/扩展、收藏、中文名状态。
2. Basic Data：level、attribute、type、X-Antibody、field、group。
3. Profile：三语简介、来源、URL、verified；无可靠简介时明确空状态。
4. First Appearance：date、title、medium 分开；有日期无标题仍显示日期。
5. Skills：名称、类型、signature、语言缺失、描述和来源。
6. Evolution：简单模式、图谱模式、深度、节点、边、截断。
7. Related Forms、Name Origin、Source：方向、清洗文本、字段级来源和冲突状态。

### 验收标准

- Agumon 真实详情页三语名、技能、首次登场、图片和来源可见。
- 缺失字段不会出现假内容或大面积空白。
- profile_verified=false 不得显示已验证。
- 外部来源链接可理解、可点击、新标签打开。
- 长简介、技能名、多个 group 不破坏布局。
- 可从进化、组织、关联形态继续导航。

### 依赖关系

依赖 UI-P0-1、UI-P0-2 和 API 返回 contract。

### 风险

不得把 community、transliteration、unverified 显示成官方；不得把游戏数值和世界观属性混在一起。

---

## UI-P0-4：进化图和关系浏览

### 目标

在真实关系规模下保持可读、可操作和可解释。

### 改动范围

- apps/web/src/lib/components/EvolutionGraph.svelte
- apps/web/src/lib/components/EvolutionSvg.svelte
- apps/web/src/routes/digimon/[slug]/+page.svelte
- apps/web/src/lib/api/types.ts
- apps/web/src/app.css
- apps/web/tests/e2e-realdb/

### 执行要求

1. 简单模式优先显示当前、全部直接前置、全部直接后续。
2. 图谱模式默认 depth=1，显式展开 depth=2/3。
3. 显示 node_count、edge_count、truncated、dropped_edges。
4. 截断时显示原因、数量和回到浅深度按钮。
5. 节点名称、等级、方向、进化类型和 condition 可读。
6. 节点可点击进入详情；当前节点突出。
7. 500 节点预算下仍可缩放、滚动、返回。
8. 循环、孤立、缺失目标、重复边和特殊类型稳定显示。

### 验收标准

- 真实 Agumon depth 1/2/3 可打开，超上限请求不会发出。
- 截断状态明确显示。
- 图失败不影响详情其他区域。
- 窄屏无不可关闭的横向滚动。
- E2E 覆盖展开、截断、回退、节点导航和空图。

### 依赖关系

依赖 UI-P0-3 和 API graph contract。

### 风险

不能把有来源的边静默删除，不能把有向多对多关系强行画成树。

---

## UI-P1-1：加载、空、错误和缺失状态系统

### 目标

让用户知道当前是加载中、没有资料、请求失败，还是来源本身缺失。

### 改动范围

- apps/web/src/lib/components/
- apps/web/src/routes/
- apps/web/src/lib/api/client.ts
- apps/web/src/app.css
- Vitest 和 Playwright

### 必须实现

- 页面和卡片 skeleton；
- 搜索 loading；
- 无结果；
- 无技能；
- 无简介；
- 无来源；
- 图片缺失；
- API 404；
- API 5xx/网络失败；
- 进化图截断；
- 数据库不可用；
- 重试和返回入口。

### 验收标准

- 每个状态有文字说明和下一步动作。
- loading 不造成明显布局跳动。
- 错误不暴露 SQL、文件路径、环境变量或堆栈。
- 空状态不放假数据。
- fixture 和真实 DB 各有失败/空状态覆盖。

### 依赖关系

依赖 UI-P0-2 至 UI-P0-4。

### 风险

不要把“暂无资料”和“加载失败”混为一谈，也不要静默展示上一次结果。

---

## UI-P1-2：响应式、可访问性和键盘效率

### 目标

让个人在桌面、平板和手机窗口都能长期舒适使用。

### 改动范围

- apps/web/src/app.css
- 所有路由和交互组件
- apps/web/tests/e2e-realdb/

### 必测尺寸

- 390×844；
- 768×1024；
- 1366×768；
- 1440×900；
- 1920×1080。

### 执行要求

- 无意外水平溢出。
- 搜索、筛选、收藏、展开、分页、图谱可键盘访问。
- focus-visible 清晰。
- 图片 alt 使用真实名称或明确占位。
- button、link、select、input 语义正确。
- 对比度和字号可读。
- prefers-reduced-motion 关闭非必要动画。
- 触控目标足够大，移动端不依赖 hover。

### 验收标准

- realdb mobile E2E 通过。
- 键盘能完成搜索、筛选、进入详情和收藏。
- 标题、区域、按钮和错误状态有清晰语义。
- reduced-motion 下页面仍可用。

### 依赖关系

依赖 UI-P1-1。

### 风险

不能用 tabindex 大范围重排自然键盘顺序，不能只靠颜色表达状态。

---

## UI-P1-3：图片性能、缓存和视觉稳定

### 目标

在真实 1736 条数据下保持首屏和详情稳定。

### 改动范围

- apps/web/src/lib/components/DigimonCard.svelte
- apps/web/src/lib/components/PlaceholderImage.svelte
- 详情页、app.css
- API client/types
- E2E 和性能 smoke test

### 执行要求

1. 列表优先 thumbnail，详情使用 main image。
2. 固定 aspect-ratio，避免布局跳动。
3. 合理 lazy loading。
4. 图片失败回占位并显示状态。
5. 不提交 data/images/。
6. 分别测试 0 图、仅主图、仅缩略图、远程回退和损坏文件。

### 验收标准

- 首页真实数据首屏布局稳定。
- 缺图无 broken image。
- Agumon 缩略图和详情主图可加载。
- 图片失败不影响名称、筛选和收藏。
- 控制台无未处理图片异常。

### 依赖关系

依赖 UI-P0-2、UI-P0-3。

### 风险

不绕过后端图片状态访问任意外部 URL，不把大量图片转成 base64。

---

## UI-P1-4：动效和视觉细节收口

### 目标

增加适量终端感动效，提升完成度但不牺牲查询效率。

### 改动范围

- apps/web/src/app.css
- 页面和组件局部 class
- 必要时新增小型 transition helper

### 允许的动效

- 首屏短距离淡入；
- 搜索结果轻量状态变化；
- 卡片 hover/focus；
- 图谱展开过渡；
- 收藏短反馈；
- 低强度 skeleton 扫描。

### 验收标准

- 动效服务于状态变化。
- 普通本机不明显掉帧。
- reduced-motion 关闭非必要动画。
- 视觉截图桌面和移动端稳定。

### 依赖关系

依赖 UI-P1-2、UI-P1-3。

### 风险

不引入大型动效库，不使用持续高频闪烁和大面积发光。

---

## UI-P2-1：个人收藏、标签和查询历史

### 目标

增强个人长期研究场景，不污染 canonical 数据。

### 改动范围

- apps/web/src/lib/stores/favorites.svelte.ts
- 可新增 personal store
- 收藏路由或面板
- 卡片、详情和首页筛选
- Vitest、Playwright

### 验收标准

- 收藏、取消、收藏列表、空状态通过。
- localStorage 损坏时安全恢复为空。
- 个人标签/备注不进入来源表和官方简介。
- 清除个人数据有确认。
- 不依赖登录或公网。

### 依赖关系

依赖 UI-P0-1、UI-P0-2 和自用任务 S2-1。

### 风险

localStorage 不是 canonical database，不能用于保存正式数据修复。

## 六、执行顺序和提交边界

推荐顺序：

1. UI-P0-0 审计和视觉基线。
2. UI-P0-1 应用壳层和 tokens。
3. UI-P0-2 首页搜索、筛选、卡片。
4. UI-P0-3 详情页。
5. UI-P0-4 进化体验。
6. UI-P1-1 状态系统。
7. UI-P1-2 响应式和可访问性。
8. UI-P1-3 图片稳定性。
9. UI-P1-4 动效收口。
10. UI-P2-1 个人功能。

推荐 commit：

- ui/audit-and-tokens
- ui/app-shell
- ui/home-search-filter
- ui/detail-data-trust
- ui/evolution-experience
- ui/states-and-errors
- ui/responsive-accessibility
- ui/image-performance
- ui/motion-polish
- ui/personal-collection

## 七、验收命令与人工验收

~~~bash
cd apps/web
npm run check
npm run test
npm run build
npm run test:e2e
npm run test:e2e:realdb
~~~

真实数据库人工验收：

1. 首页显示运行时总数和图鉴卡片。
2. 搜索 亚古兽、Agumon、アグモン、战暴、Wargre。
3. 使用究极体 + 疫苗 + 皇家骑士筛选。
4. 打开 Agumon 详情，检查三语名、技能、简介、首次登场、图片和来源。
5. 展开 depth 2/3，检查截断和回到浅深度。
6. 打开无图片扩展实体，检查占位图。
7. 打开 Royal Knights 组织页。
8. 收藏、刷新、返回和再次搜索。
9. 桌面和 390×844 检查无水平溢出。
10. 只用键盘完成搜索、筛选、进入详情和收藏。
11. 开启 reduced-motion。
12. 检查控制台无未处理异常。

## 八、最终 UI 完成标准

- 设计 tokens、字体、颜色、间距和状态语义统一。
- 首页是高效搜索/筛选入口，而不是装饰性卡片墙。
- 详情页清楚区分事实、来源、缺失、冲突和未验证。
- 进化图真实数据下可用，截断可解释。
- 缺图、缺名、缺简介、无技能、API 失败和空结果均有明确状态。
- 桌面、平板、移动端和键盘通过验收。
- fixture 和真实 DB E2E 都通过。
- 不依赖公网、远程字体、云服务或 mock 数据。
- Git diff 已审查，工作区干净，相关修改已原子提交，未自动 push。
