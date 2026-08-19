# DigiDex 本地 API 性能基线

> 记录日期：2026-08-19
> 范围：Windows 本地单进程 API，禁止公网依赖，不代表生产 SLO。
> 对应任务：`docs/next-stage-auto-mode-taskbook-2026-08-16.md` 的 P2-2。

## 环境与数据快照

| 项目 | 值 |
|---|---|
| 平台 | Windows 11 |
| Python / uv | Python 3.12.12 / uv 0.12.3 |
| API | FastAPI + Uvicorn，`127.0.0.1:8020` |
| 数据库 | `data/digidex.sqlite`，SQLite schema v8，`integrity_check=ok` |
| snapshot_date | 2026-08-16 |
| run_id | `20260816T065459922120-127c8` |
| 数码兽 | 1,736（official 1,316 / extended 420） |
| open review | 775 |

## 可复现命令

先在一个终端启动本地 API：

```powershell
uv run python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8020
```

再在仓库根目录执行：

```powershell
uv run scripts/benchmark_api.py `
  --base-url http://127.0.0.1:8020/api `
  --warmup 3 `
  --iterations 20 `
  --json
```

脚本固定覆盖 `/meta`、列表、命中/空搜索、详情、Agumon 进化 depth 1/2/3、Royal Knights、review 和未知 slug。`cold_ms` 是首个请求，`hot_*` 是预热后的 20 次请求统计。

## 2026-08-19 结果

| Endpoint | cold ms | hot p50 ms | hot p95 ms | max ms | status | 关键标记 |
|---|---:|---:|---:|---:|---:|---|
| `/meta` | 46.14 | 17.64 | 18.46 | 18.62 | 200 | total=1736 |
| `/digimon?limit=60` | 26.58 | 17.50 | 26.61 | 28.43 | 200 | 分页 |
| `/search?q=Agumon` | 87.63 | 32.27 | 36.36 | 39.67 | 200 | count=20 |
| `/search?q=NoSuchMon` | 21.68 | 30.53 | 32.32 | 36.80 | 200 | count=0 |
| `/digimon/agumon` | 23.96 | 20.97 | 22.72 | 23.74 | 200 | 详情 |
| `evolution depth=1` | 8.07 | 10.62 | 19.86 | 20.64 | 200 | node=106, edge=109, truncated=false |
| `evolution depth=2` | 51.14 | 56.08 | 70.91 | 75.14 | 200 | node=500, edge=2500, truncated=true |
| `evolution depth=3` | 52.68 | 53.13 | 63.46 | 71.34 | 200 | node=500, edge=2500, truncated=true |
| `/groups/Royal Knights` | 9.95 | 11.62 | 19.57 | 26.18 | 200 | count=31 |
| `/review?status=open&limit=20` | 18.65 | 8.40 | 18.40 | 19.93 | 200 | total=775 |
| unknown slug | 16.78 | 6.31 | 17.02 | 17.21 | 404 | 诚实返回未知 |

## 结论与边界

- depth 2/3 均受 node=500、edge=2500 预算约束，返回 `truncated` 和计数，不存在无界响应。
- 列表和 review 使用分页；进化图使用批量节点加载和预算；当前代码与索引检查没有发现需要为本地 1,736 条数据引入缓存或复杂查询重构的证据。
- `apps/api/main.py` 已有 `_CountingConnection` 查询计数/耗时埋点。此次重定向启动的 Uvicorn 日志只记录了访问日志，未形成可引用的逐请求 SQL 计数，因此本文件不虚报 N+1 的精确数字；查询结构和集成测试仅作为辅助证据。
- 这是单机、单并发、热进程基线，耗时会受磁盘、解释器和后台进程影响。数据库、索引、API 查询或图片缓存变更后，应使用同一命令重新记录，并与本文件比较，而不是把本表当成硬性线上阈值。
