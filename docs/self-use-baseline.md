# 自用版基线记录 — S0-0

> 用途：记录 S0-0 真实运行基线，作为 S0-1 起所有改动的回滚参照与最终验收基准。
> 生成：2026-08-15（真实 DB 快照 2026-08-15，digimon 1,736）。
> fixture 与真实 DB 结果分开记录；失败分类见文末。

## 一、真实数据库状态

| 项 | 值 |
|---|---|
| `data/digidex.sqlite` | 存在，`PRAGMA integrity_check` = ok |
| digimon 总数 | 1,736（official 1,316 / extended 420） |
| snapshot_date | 2026-08-15 |
| schema `PRAGMA user_version` | 7 |
| 表 | digimon、digimon_alias、digimon_field、digimon_fts*、digimon_group、digimon_image、digimon_relation、digimon_skill、digimon_type、evolution_edge、field、field_coverage、game、game_digimon_stats、game_skill、grp、manual_review_queue、provenance、skill、skill_alias、snapshot、source_sync、sync_run、type、data_conflict |

## 二、命令与退出码（Python / 数据侧）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `git status --short --branch` | 0 | 工作区干净，`main` 领先 `origin/main` 21 |
| `uv run ruff check .` | 0 | All checks passed |
| `uv run pytest -q` | 0 | 196 通过（含真实 DB smoke test，未跳过） |
| `uv run python scripts/validate_data.py` | 0 | 0 errors / 2 warnings / 4 info |
| `uv run python scripts/verify_samples.py --n 50 --seed 20260815` | 0 | 随机 50/50 + 固定 16/16，0 硬失败，33 文档化缺口 |

## 三、命令与退出码（前端 / E2E，串行执行避免 `.svelte-kit` 假失败）

| 命令 | 退出码 | 结果 |
|---|---|---|
| `npm run check` | 0 | 357 files, 0 errors |
| `npm run test` | 0 | 5 passed（Vitest） |
| `npm run build` | 0 | ✓ built |
| `npm run test:e2e` | 0 | 13 passed（hermetic fixture） |
| `npm run test:e2e:realdb` | 0 | 18 passed（真实 DB，桌面 + 窄屏） |

## 四、手工 API 检查（真实 DB，uvicorn:8123）

| 检查 | 结果 |
|---|---|
| `/api/health` | ok=true, db_ready=true |
| `/api/meta` | snapshot 2026-08-15；official 1,316 / extended 420 / total 1,736；levels 11 / attributes 6 / types 200 / fields 12 / groups 50 |
| 搜索 亚古兽 / Agumon / アグモン | 均首位命中 `agumon`（同一实体） |
| 搜索 战暴 / Wargre | 首位命中 `war-greymon` |
| 组合筛选 究极体+疫苗+皇家骑士 | total=11（alphamon、craniummon、sleipmon、magnamon-x、ulforce-v-dramon 等） |
| Agumon 详情 | 三语名全（zh 亚古兽 official / en Agumon / ja アグモン）；level child / attribute vaccine；skills 20；profile_en 有值且 verified=false；first_appearance date=1997；types Reptile；fields 5；groups Agumon-species；provenance 带 run_id；conflicts 0 |
| 进化 depth=1 | node 106 / edge 109，truncated=false |
| 进化 depth=2 | node 500（预算上限）/ edge 2500，truncated=true，dropped_edges=3892 |
| 进化 depth=3 | 仍受 500 节点预算截断，`depth` 如实返回实际遍历深度（≤请求值），truncated=true |
| 进化 depth=4 / 0 / 非数字 | 422（bounds 1..3） |

> 说明：depth=3 返回 `depth:2` 是预算截断的既定语义（见 `tests/integration/test_real_db_smoke.py`
> `test_evolution_depths_bounded_and_consistent`：`depth` 报告实际遍历深度，`truncated` 传达截断）。

## 五、问题分类（S0-0 无失败）

- 代码问题：无（ruff / pytest / check / build 全绿）。
- 数据问题：0 errors，2 warnings（324 缺中文名、82 缺日文名，均为真实 no_source），4 info。
- 环境问题：Windows 控制台 GBK 编码导致终端中文显示乱码（数据本身 UTF-8 完好，不影响验收）；
  realdb E2E 结束时的 `ConnectionResetError` 为 uvicorn 进程关闭时的 Windows 连接复位噪音，非测试失败。
- 测试隔离：fixture（13）与真实 DB（18）E2E 各自独立通过；真实 DB smoke test 未跳过。

## 六、结论

当前 MVP 满足 S0-0 基线：真实 DB 可查询、三语搜索一致、组合筛选正确、进化图有界且截断可解释、
前后端构建与全部测试通过。S0-1 起在此基础上做同步状态一致性加固。
