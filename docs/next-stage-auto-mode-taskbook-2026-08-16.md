# DigiDex 下一阶段自动执行任务书

## 1. 任务定位

目标仓库：

    C:\Users\Hayas\Github\digimon-dictionary

目标：

将当前“核心图鉴功能可运行”的本地系统，推进到“真实数据库图片可用、路径可迁移、备份可恢复、真实浏览器验收通过、数据质量可审计”的自用稳定版本。

当前范围：

- 仅支持本地自用。
- 不做公网部署。
- 不新增账号、鉴权、云服务或远程数据库。
- 不提交第三方图片文件。
- 不虚构任何数码兽名称、技能、简介、等级、属性、图片或进化关系。

本文件可直接粘贴到 Claude Code 自动模式执行。

---

## 2. 执行规则

开始前必须阅读：

- C:\Users\Hayas\Github\digimon-dictionary\AGENTS.md
- C:\Users\Hayas\Github\digimon-dictionary\CLAUDE.md
- C:\Users\Hayas\Github\digimon-dictionary\README.md
- C:\Users\Hayas\Github\digimon-dictionary\docs\product-spec.md
- C:\Users\Hayas\Github\digimon-dictionary\docs\roadmap.md

进入仓库后首先执行：

~~~powershell
Set-Location C:\Users\Hayas\Github\digimon-dictionary
git status --short --branch
git log -5 --oneline --decorate
~~~

必须遵守：

1. 保留所有已有用户修改。
2. 禁止执行 git reset --hard、git clean、git checkout --、git push --force。
3. 禁止删除未确认的用户文件。
4. 不得通过删除测试、降低断言、跳过校验或隐藏异常来获得绿色结果。
5. 所有缺失数据必须保留为 NULL、unknown、unverified 或人工复核状态。
6. 不得把第三方 ID 作为主键。
7. 进化关系必须保持有向多对多模型，允许环。
8. 世界观字段和游戏字段必须分离。
9. data/images/ 仅作为本地缓存，不提交图片。
10. 每个独立阶段完成后检查 git diff，只提交本阶段相关文件，创建原子 commit，不 push。
11. 修改真实数据库前，必须先完成本地备份。
12. 最终结论必须同时依据真实数据库、真实 API 和真实浏览器验证，不能只依据 fixture。

Windows 测试约定：

如果 uv run pytest 或 Playwright webServer 中的 uv run uvicorn 出现以下错误：

    uv trampoline failed to canonicalize script path

优先使用：

~~~powershell
uv run python -m pytest
uv run python -m uvicorn
~~~

不得因此跳过测试。

---

## 3. 当前审查基线

当前 HEAD：

    500847c docs: third-round review fixes recorded (P1x2 + P2x3 + P3x1)

当前分支：

    main...origin/main

当前工作区在审查时干净。

已验证：

- Python Ruff 通过。
- 排除真实数据库图片 smoke test 后，Python 测试通过。
- 前端 svelte-check：0 errors、0 warnings。
- 前端 Vitest：3 个测试文件、15 个测试通过。
- 前端生产构建通过。
- 数据库 SQLite integrity_check 通过。
- 数据快照为 2026-08-16。
- 数据总量为 1736，其中 official 1316、extended 420。

当前阻塞：

1. 真实数据库测试

   C:\Users\Hayas\Github\digimon-dictionary\tests\integration\test_real_db_smoke.py

   的 test_images_served_or_absent 失败：

       GET /api/images/agumon/thumbnail -> 404

2. 当前数据库只有 1488 条 main_image 记录，没有 thumbnail image_type 记录。

3. data/images/thumbs/ 目录实际存在 1488 个缩略图文件，但数据库没有对应元数据。

4. 当前数据库中的 1488 条 local_path 全部指向旧 checkout：

       C:\Users\Hayas\Github\Digimon_Dictionary\...

   当前仓库实际路径为：

       C:\Users\Hayas\Github\digimon-dictionary\...

5. Playwright fixture E2E 和 realdb E2E 当前被 Windows 下的 uv trampoline 启动错误阻断。

6. pipeline/core/backup.py 存在以下问题：

   - conflicts_path 默认使用了 MANUAL_REVIEW_PATH。
   - CONFLICT_PATH 没有正确进入备份。
   - restore_backup 没有恢复 conflicts 和 manual_review。
   - 非数据库核心文件缺少完整哈希校验。
   - 自定义 --out 和 --keep 可能清理错误的备份根目录。

在 P0-1 和 P0-3 完成前，不得将项目标记为“稳定交付完成”。

---

## 4. 优先级和依赖关系

执行顺序：

    P0-0
      -> P0-1
          -> P0-2
          -> P0-3
              -> P1-1
              -> P1-2
                  -> P1-3
                      -> P2-1
                      -> P2-2
                          -> P3-1

---

## P0-0：建立真实数据基线和安全备份

### 目标

在修改真实数据库和图片元数据前，记录当前代码、数据库、图片缓存、同步状态和测试结果，并建立可恢复备份。

### 预期改动范围

- C:\Users\Hayas\Github\digimon-dictionary\data\digidex.sqlite
- C:\Users\Hayas\Github\digimon-dictionary\data\images\
- C:\Users\Hayas\Github\digimon-dictionary\data\.publish_manifest.json
- C:\Users\Hayas\Github\digimon-dictionary\data\.sync_state.json
- C:\Users\Hayas\Github\digimon-dictionary\scripts\diagnose.py
- C:\Users\Hayas\Github\digimon-dictionary\tests\integration\test_real_db_smoke.py

### 执行要求

~~~powershell
Set-Location C:\Users\Hayas\Github\digimon-dictionary

git status --short --branch
uv run ruff check .
uv run python -m pytest -q --disable-warnings
uv run python scripts\diagnose.py --json
~~~

修改真实数据库前执行：

~~~powershell
uv run python scripts\backup_local.py --with-images
~~~

使用只读查询记录：

- 数据库完整性。
- schema 版本。
- snapshot_date。
- official、extended、total 数量。
- 主图下载数量。
- 缩略图文件数量。
- digimon_image 各 image_type 数量。
- digimon.thumbnail 非空数量。
- 绝对路径数量。
- 缺少主图数量。
- open review queue 数量。

### 验收标准

- 备份目录存在。
- 备份数据库通过 SQLite integrity_check。
- 备份包含数据库、运行状态、manifest、报告和图片缓存。
- 记录当前失败测试，不得将当前失败误报为通过。
- 数据库修改前可以通过备份恢复到原始状态。

### 依赖

无。

### 风险和注意事项

- 真实数据库和 data/images/ 都是本地用户数据，不能删除。
- 当前仓库路径与旧 checkout 路径不同，不能假设旧绝对路径仍然有效。

---

## P0-1：修复图片路径契约和旧数据库迁移

### 目标

消除数据库中的 checkout 绝对路径，使图片缓存可以在不同目录、不同机器和备份恢复目录中正常使用。

### 影响范围

- C:\Users\Hayas\Github\digimon-dictionary\pipeline\core\config.py
- C:\Users\Hayas\Github\digimon-dictionary\scripts\download_images.py
- C:\Users\Hayas\Github\digimon-dictionary\pipeline\merge\store.py
- C:\Users\Hayas\Github\digimon-dictionary\apps\api\main.py
- C:\Users\Hayas\Github\digimon-dictionary\apps\api\queries.py
- 新增 C:\Users\Hayas\Github\digimon-dictionary\scripts\migrate_image_paths.py
- C:\Users\Hayas\Github\digimon-dictionary\tests\unit\
- C:\Users\Hayas\Github\digimon-dictionary\tests\integration\
- C:\Users\Hayas\Github\digimon-dictionary\tests\integration\test_real_db_smoke.py

### 路径契约

数据库中的 local_path 必须保存为相对于图片缓存根目录的相对路径，不得保存绝对路径。

推荐格式：

    digi_00001_<hash>.png
    thumbs/digi_00001.png

禁止写入：

    C:\...
    D:\...
    /Users/...
    data/images/...
    ..\...

图片缓存根目录：

- 默认数据库 data/digidex.sqlite 对应 data/images/。
- 使用 DIGIDEX_DB 指向其他数据库时，支持 DIGIDEX_IMAGES_DIR 指定缓存目录。
- 未指定时，使用数据库所在目录下的 images/。

### 执行要求

1. 新增统一图片路径解析函数。
2. 所有图片读写必须通过统一解析函数。
3. API 服务图片前必须 resolve 并检查路径位于缓存根目录内。
4. 拒绝路径穿越。
5. download_images.py 不得再把绝对路径写入数据库。
6. pipeline/merge/store.py 不得把绝对路径写入 local_path 或 digimon.thumbnail。
7. backfill_metadata() 和 ensure_thumbnails() 必须支持迁移后的相对路径。
8. 新增迁移脚本，要求：
   - 先验证数据库完整性。
   - 只处理旧图片缓存目录下的文件。
   - 通过文件名和缓存根目录安全重定位。
   - 无法定位的路径设置为明确的 pending 或 failed 状态。
   - 不把不存在的文件标记为 downloaded。
   - 不删除 remote_url。
   - 迁移前后输出数量统计。
9. 运行迁移前自动创建备份。
10. 迁移后重新生成本地缩略图元数据。
11. 不联网补图，优先修复现有本地图片。

### 验收标准

- 真实数据库中不存在图片绝对路径。
- local_path 只包含合法相对路径或 NULL。
- digimon.thumbnail 只包含合法相对路径或 NULL。
- 当前本地已有主图可以被 API 正常解析。
- 当前本地已有缩略图可以被 API 正常解析。
- 执行以下测试必须通过：

~~~powershell
uv run python -m pytest -q --disable-warnings tests/integration/test_real_db_smoke.py::test_images_served_or_absent
~~~

- 以下请求必须返回 200 和 image/*：

    GET /api/images/agumon/main_image
    GET /api/images/agumon/thumbnail

- 将数据库和图片缓存复制到新的临时目录后，API 仍能正常读取图片。
- 路径穿越、旧目录不存在、文件缺失时返回明确的 404 或 placeholder 状态。
- API 响应不得泄漏服务器绝对路径。

### 依赖

依赖 P0-0。

### 风险和注意事项

- 必须覆盖 Windows 驱动器号、反斜杠、大小写差异。
- 不能简单替换旧目录字符串，必须基于缓存根目录和文件存在性安全重定位。
- 不得把 remote_url 当作 local_path 保存。

---

## P0-2：修复图片阶段、WAL、报告和 manifest 一致性

### 目标

保证图片阶段成功、失败、checkpoint 失败、报告重写失败和 manifest 写入失败时，系统都不会声称发布成功但实际状态不一致。

### 影响范围

- C:\Users\Hayas\Github\digimon-dictionary\scripts\sync_data.py
- C:\Users\Hayas\Github\digimon-dictionary\pipeline\core\schema.py
- C:\Users\Hayas\Github\digimon-dictionary\pipeline\core\manifest.py
- C:\Users\Hayas\Github\digimon-dictionary\tests\integration\test_sync_failures.py
- C:\Users\Hayas\Github\digimon-dictionary\tests\integration\test_incremental_sync.py

### 执行要求

1. 图片阶段 checkpoint_and_close() 失败时：
   - 退出码非零。
   - 不得生成 image_stage=ok。
   - 留下明确失败状态和恢复提示。
2. _restamp_report_db_sha() 失败时：
   - 退出码非零。
   - 不得保留旧 report_sha256 作为新哈希。
   - 保留可恢复报告或 staging 文件。
3. manifest 写入失败时：
   - 退出码非零。
   - 日志明确数据库是否已经发布。
   - 不得静默返回成功。
4. 成功流程必须保证：
   - 数据库 SHA-256 与 manifest 一致。
   - 报告中的 db_sha256 与数据库一致。
   - manifest.report_sha256 与报告文件一致。
   - image_stage 真实反映图片阶段。
5. 增加失败注入测试：
   - checkpoint 失败。
   - JSON 报告替换失败。
   - Markdown 报告替换失败。
   - report hash 重写失败。
   - manifest 写入失败。
   - 图片下载失败。
   - 缩略图生成失败。

### 验收标准

成功流程必须满足：

    数据库文件哈希 = manifest.database_sha256
    报告 JSON 中 db_sha256 = 数据库文件哈希
    manifest.report_sha256 = 报告 JSON 文件哈希
    image_stage = ok
    state_committed = true

失败流程必须满足：

- 退出码非零。
- 不出现“全部成功”的 manifest。
- 数据库、报告、manifest 和 state 的不一致可以被 diagnose.py 发现。
- 能区分 canonical DB 已发布、图片缓存失败、报告/manifest 未完成、state 未提交。

### 依赖

依赖 P0-1。

### 风险和注意事项

- 数据库已发布后，报告或 manifest 失败时不能假装整个同步已回滚。
- 必须保留 staging 和失败证据。

---

## P0-3：修复 Windows Playwright 启动链路并完成真实浏览器验收

### 目标

让 fixture E2E 和真实数据库 E2E 在 Windows 当前环境中可重复运行。

### 影响范围

- C:\Users\Hayas\Github\digimon-dictionary\apps\web\playwright.config.ts
- C:\Users\Hayas\Github\digimon-dictionary\apps\web\playwright.realdb.config.ts
- C:\Users\Hayas\Github\digimon-dictionary\apps\web\tests\e2e\
- C:\Users\Hayas\Github\digimon-dictionary\apps\web\tests\e2e-realdb\
- 必要时修改：
  - C:\Users\Hayas\Github\digimon-dictionary\scripts\diagnose.py
  - C:\Users\Hayas\Github\digimon-dictionary\apps\web\README.md

### 执行要求

1. 将 Playwright webServer 中的 uv run uvicorn 改为：

       uv run python -m uvicorn

2. 确保 fixture 数据构建和 API 服务使用当前仓库 Python 环境。
3. 不得用 test.skip 隐藏真实数据库存在时的失败。
4. 增加真实图片 API 浏览器断言。
5. 验证桌面和移动项目。
6. 如果仍依赖 shell 的 &&，抽出 Windows 可执行启动脚本。

### 验收标准

依次执行并通过：

~~~powershell
Set-Location C:\Users\Hayas\Github\digimon-dictionary\apps\web
npm run test:e2e
npm run test:e2e:realdb
~~~

fixture E2E 必须覆盖：

- 首页。
- 搜索。
- 多条件筛选。
- 详情。
- 组织页。
- 收藏。
- 进化图。
- 图片占位。
- 错误状态。
- 移动布局。
- 键盘访问。

真实数据库 E2E 必须覆盖：

- 真实数据总数。
- 三语搜索。
- 别名搜索。
- 组合筛选。
- Agumon 详情。
- 主图和缩略图。
- 图片缺失状态。
- 进化图截断。
- 组织页。
- 无横向滚动。
- 键盘导航。
- 无 broken image。
- 无 console error。

### 依赖

依赖 P0-1。

### 风险和注意事项

- 真实数据库 E2E 不能由 fixture 替代。
- 离线环境下远程 fallback 不能作为本地图片成功依据。
- 移动端必须使用真实窄屏浏览器验证。

---

## P1-1：修复备份和恢复完整性

### 目标

让本地备份真正包含并恢复数据库之外的运行状态、冲突记录、人工复核队列、报告和图片缓存。

### 影响范围

- C:\Users\Hayas\Github\digimon-dictionary\pipeline\core\backup.py
- C:\Users\Hayas\Github\digimon-dictionary\pipeline\core\config.py
- C:\Users\Hayas\Github\digimon-dictionary\scripts\backup_local.py
- C:\Users\Hayas\Github\digimon-dictionary\scripts\restore_local.py
- C:\Users\Hayas\Github\digimon-dictionary\tests\integration\test_backup_restore.py

### 执行要求

1. 正确使用 CONFLICT_PATH 和 MANUAL_REVIEW_PATH。
2. backup.json 记录每个实际复制文件的：
   - relative path
   - size
   - sha256
3. restore 覆盖：
   - database
   - sync_state
   - publish_manifest
   - report_json
   - report_md
   - conflicts
   - manual_review
   - images
4. 自定义 target 时，运行时文件跟随目标数据库目录。
5. --out DIR --keep N 只清理 DIR 所在的备份根目录。
6. 备份缺少可选文件时，必须明确处理，不得静默遗留旧文件。
7. 继续保持先验证、再 staging、最后原子替换；任一替换失败时回滚。

### 验收标准

测试必须覆盖：

- conflict 文件确实被备份。
- manual review 文件确实被备份。
- 两者都能恢复到目标目录。
- 修改备份中的 state、report、conflict、manual_review 后，validate 能发现哈希不一致。
- 自定义 --out 不会误删默认备份。
- 带图片备份可以恢复到不同根目录。
- 恢复后数据库中的相对图片路径仍能找到恢复后的图片。
- 恢复失败时 live DB、state、manifest、报告和图片缓存保持原状。

### 依赖

依赖 P0-1。

### 风险和注意事项

- 备份和恢复属于高风险本地数据操作，必须使用临时目录和失败注入测试。
- 禁止递归删除用户未确认的目录。

---

## P1-2：建立真实数据质量和人工复核闭环

### 目标

准确处理真实数据库中的缺失、冲突和来源问题，不为了追求数量而伪造数据。

### 影响范围

- C:\Users\Hayas\Github\digimon-dictionary\pipeline\validation\validator.py
- C:\Users\Hayas\Github\digimon-dictionary\scripts\verify_samples.py
- C:\Users\Hayas\Github\digimon-dictionary\scripts\review_queue.py
- C:\Users\Hayas\Github\digimon-dictionary\pipeline\sources\
- C:\Users\Hayas\Github\digimon-dictionary\pipeline\matching\
- C:\Users\Hayas\Github\digimon-dictionary\pipeline\merge\
- C:\Users\Hayas\Github\digimon-dictionary\tests\
- C:\Users\Hayas\Github\digimon-dictionary\docs\

### 执行要求

1. 重新查询当前数据库，不使用旧文档中的数字。
2. 分别统计：
   - 简体中文名缺失。
   - 日文名缺失。
   - 英文名缺失。
   - 等级缺失。
   - 属性缺失。
   - 类型缺失。
   - 简介缺失。
   - 技能缺失。
   - 主图缺失。
   - 缩略图缺失。
   - 首次登场缺失。
   - 进化关系缺失。
   - 来源缺失。
   - unresolved review queue。
3. verify_samples.py 增加可复现 seed。
4. 失败样本按来源无数据、抓取失败、匹配失败、字段解析失败、数据冲突、图片缺失、人工待确认分类。
5. 可靠来源不存在时保留 NULL、unknown 或 unverified。
6. 不得批量生成中文名，不得用默认等级或属性填充未知值。
7. 报告包含数据库快照、run_id、source、统计数量、失败原因和 review queue 状态。

### 验收标准

- 真实数据库验证报告的数字与数据库查询一致。
- validator error 数为 0，或者每个 error 都阻止发布并列出原因。
- 随机样本和固定样本可复现。
- wontfix 只表示暂不处理，不表示事实已验证。
- 无法确认的字段仍保持明确缺失状态。

### 依赖

依赖 P0-0、P0-1。

### 风险和注意事项

- 完整图鉴不等于所有字段必须非空。
- 不能为了让质量报告变绿而降低检查标准。

---

## P1-3：新增本地人工复核队列前端

### 目标

将现有 review API 变成可用的本地管理界面，支持查看、筛选、导出和带备注解决问题。

### 现有 API

- GET /api/review
- GET /api/review/stats
- GET /api/review/export
- POST /api/review/{review_id}/resolve

### 影响范围

- 新增 C:\Users\Hayas\Github\digimon-dictionary\apps\web\src\routes\review\+page.svelte
- 修改 C:\Users\Hayas\Github\digimon-dictionary\apps\web\src\routes\+layout.svelte
- 修改 C:\Users\Hayas\Github\digimon-dictionary\apps\web\src\lib\api\client.ts
- 修改 C:\Users\Hayas\Github\digimon-dictionary\apps\web\src\lib\api\types.ts
- 修改 C:\Users\Hayas\Github\digimon-dictionary\apps\web\src\app.css
- 增加前端和后端测试

### 功能要求

1. 显示 open、resolved、wontfix、category、entity_type 统计。
2. 支持 status、entity_type、category、q 筛选。
3. 支持分页。
4. 显示 detail、来源和 run_id。
5. 支持 resolved 和 wontfix，note 必填。
6. 处理 409、404、422。
7. 支持 JSON / CSV 导出。
8. 筛选和分页状态写入 URL。
9. 页面明确标识“仅本地自用”。
10. 不新增公网鉴权设计。

### UI 要求

- 复用现有设计 token 和组件。
- 复用 skeleton、error、empty 状态。
- 移动端可用。
- 支持键盘操作和可见 focus。
- resolve/wontfix 操作显示明确结果。
- 不复制第三方图鉴代码、图片和品牌视觉。
- 参考：
  - C:\Users\Hayas\Github\digimon-dictionary\docs\ui-design-notes.md
  - C:\Users\Hayas\Github\digimon-dictionary\docs\frontend-ui-taskbook.md

### 验收标准

- review 页面可从主导航进入。
- fixture review 数据可以完整操作。
- resolve/wontfix 后列表和统计正确刷新。
- note 为空时前端阻止提交，后端仍保留校验。
- API 失败时不出现假成功。
- 移动端无横向滚动。
- check、unit test、fixture E2E 和真实 E2E 通过。

### 依赖

依赖 P0-3、P1-2。

### 风险和注意事项

- 页面会修改本地数据库，必须复用现有 sync lock。
- 前端不得直接写 SQLite。

---

## P2-1：完成真实数据库前端视觉和交互验收

### 目标

在真实 1700+ 条数据和本地图片缓存下，验证首页、详情、收藏、组织页和复核页的可读性、响应式和可访问性。

### 影响范围

- C:\Users\Hayas\Github\digimon-dictionary\apps\web\src\routes\
- C:\Users\Hayas\Github\digimon-dictionary\apps\web\src\lib\components\
- C:\Users\Hayas\Github\digimon-dictionary\apps\web\src\app.css
- C:\Users\Hayas\Github\digimon-dictionary\apps\web\tests\e2e\
- C:\Users\Hayas\Github\digimon-dictionary\apps\web\tests\e2e-realdb\

### 执行要求

使用真实浏览器验证：

- 1440px 桌面宽度。
- 390px 移动宽度。
- 首页、搜索、筛选、详情、进化图、收藏、组织页、review 页。
- 图片缺失和图片加载失败 placeholder。
- loading、empty、error 状态。
- 键盘操作、focus、reduced motion。
- URL 状态恢复和刷新恢复。

### 验收标准

- fixture E2E 与 realdb E2E 均通过。
- 至少抽查：
  - Agumon
  - WarGreymon
  - Royal Knights
  - 无主图实体
  - 有冲突实体
  - 有进化截断实体
- 无横向滚动。
- 无 broken image。
- 无 console error。
- 不隐藏数据缺失状态。

### 依赖

依赖 P0-3、P1-3。

### 风险和注意事项

- 参考其他图鉴和 GitHub 项目时只参考交互模式和信息架构。
- 不复制代码、图片、品牌视觉或受版权保护的页面布局。

---

## P2-2：建立 API 和查询性能基线

### 目标

在真实数据规模下确认首页、搜索、详情和进化图不会出现明显卡顿或无界查询。

### 影响范围

- C:\Users\Hayas\Github\digimon-dictionary\apps\api\queries.py
- C:\Users\Hayas\Github\digimon-dictionary\apps\api\main.py
- C:\Users\Hayas\Github\digimon-dictionary\pipeline\core\schema.py
- C:\Users\Hayas\Github\digimon-dictionary\tests\
- 必要时新增 C:\Users\Hayas\Github\digimon-dictionary\scripts\benchmark_api.py

### 执行要求

测试：

- /api/meta
- /api/digimon
- /api/search
- /api/digimon/agumon
- /api/digimon/agumon/evolution?depth=1
- /api/digimon/agumon/evolution?depth=2
- /api/digimon/agumon/evolution?depth=3
- /api/groups/Royal%20Knights
- /api/review

检查：

- N+1 查询。
- 无分页查询。
- 索引是否正确。
- 进化图 node/edge budget。
- 稳定排序。
- 空结果和未知 slug 返回速度。

### 验收标准

- 先记录当前机器 cold/hot baseline。
- depth 2/3 不得出现无界响应。
- 真实数据库下不会因单个实体导致超时或异常内存增长。
- 性能测试不依赖公网。
- 不为当前规模过度引入复杂缓存。

### 依赖

依赖 P0-1、P0-3。

### 风险和注意事项

- 不能简单把 depth 上限改成 1 来掩盖性能问题。
- 截断必须返回 truncated、node_count、edge_count 和预算信息。

---

## P3-1：更新发布文档和一键自检流程

### 目标

让文档、任务状态、质量报告和实际数据库保持一致，避免文档声称“全部完成”但真实 smoke test 仍失败。

### 影响范围

- C:\Users\Hayas\Github\digimon-dictionary\README.md
- C:\Users\Hayas\Github\digimon-dictionary\apps\web\README.md
- C:\Users\Hayas\Github\digimon-dictionary\docs\roadmap.md
- C:\Users\Hayas\Github\digimon-dictionary\docs\delivery-report.md
- C:\Users\Hayas\Github\digimon-dictionary\docs\self-use-delivery-report.md
- C:\Users\Hayas\Github\digimon-dictionary\docs\claude-code-auto-mode-taskbook.md
- 必要时新增 C:\Users\Hayas\Github\digimon-dictionary\scripts\self_check.py

### 执行要求

1. 所有数字从当前数据库自动生成。
2. 文档明确：
   - snapshot_date
   - run_id
   - 数据总量
   - 缺失字段
   - 主图和缩略图数量
   - review queue 数量
   - 已知限制
   - 图片路径契约
   - 备份和恢复命令
   - Windows 测试命令
3. P0 全部通过前，不得写“全部完成”。
4. 建议新增一键自检：

~~~powershell
Set-Location C:\Users\Hayas\Github\digimon-dictionary
uv run ruff check .
uv run python -m pytest -q --disable-warnings
uv run python scripts\diagnose.py --json
Set-Location apps\web
npm run check
npm run test
npm run build
npm run test:e2e
npm run test:e2e:realdb
~~~

### 验收标准

- 文档数字与真实数据库查询一致。
- 文档不再声称真实 E2E 已通过，除非实际执行成功。
- 新用户按照 README 可以完成同步、图片缓存、备份、恢复、API 启动、前端启动和测试。
- Git diff 只包含本阶段相关文档和自检脚本。

### 依赖

依赖全部 P0、P1、P2 任务。

### 风险和注意事项

- 不手工修改统计数字。
- 不把 remote_url 描述为已下载图片。
- 不把 wontfix 描述为已验证。
- 不把 fixture 测试描述为真实数据库验收。

---

## 5. 最终完成门槛

只有同时满足以下条件，才可以将项目标记为“自用稳定版”：

1. git status 符合预期。
2. 图片数据库路径不含绝对路径。
3. Agumon 主图和缩略图 API 返回本地 200 image/*。
4. 真实数据库 smoke test 全部通过。
5. fixture E2E 和 realdb E2E 全部通过。
6. Python Ruff 通过。
7. Python 测试全量通过。
8. 前端 check、unit test、build 通过。
9. 备份、校验、恢复测试通过。
10. manifest、报告和数据库哈希一致。
11. 数据质量问题都有真实来源、明确缺失状态或 review queue 记录。
12. 没有提交第三方图片。
13. 没有新增公网部署、账号、云服务或鉴权。
14. 文档中的统计和完成状态与实际验证结果一致。
15. 每个独立阶段都有对应原子 commit。
16. 不执行 push。
