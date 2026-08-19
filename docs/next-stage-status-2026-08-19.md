# 下一阶段执行状态（2026-08-19）

对应任务书：`docs/next-stage-auto-mode-taskbook-2026-08-16.md`。本文件记录当前本地工作区的可验证状态；历史交付报告中的旧测试数量不覆盖本记录。

## 当前数据库证据

| 项目 | 当前值 |
|---|---|
| snapshot_date | 2026-08-16 |
| run_id | `20260816T065459922120-127c8` |
| 数码兽 | 1,736（official 1,316 / extended 420） |
| schema | v8 |
| SQLite integrity | ok |
| open review | 775 |
| 主图 | 1,488，缺 248 |
| 缩略图 | 数据库 1,488 条，缓存 1,488 条 |
| 图片路径契约 | 绝对路径 0，非空相对路径 2,976 |
| manifest/report/DB 哈希 | 三方一致，`state_committed=true` |

缺失字段、缺图和 review queue 都是当前真实数据状态，不通过填充虚假值来消除。

## 任务状态

| 任务 | 状态 | 证据 |
|---|---|---|
| P0-0 至 P1-2 | 已完成 | 既有原子 commits、Python/API/真实 DB 验收 |
| P1-3 本地人工复核队列前端 | 已完成 | `/review`；fixture E2E 26/26；支持筛选、分页、导出、备注解决 |
| P2-1 真实数据库浏览器验收 | 已完成 | realdb E2E 24/24，桌面 + 窄屏 |
| P2-2 API 性能基线 | 已完成 | `docs/api-performance-baseline-2026-08-19.md` |
| P3-1 文档与一键自检 | 已完成 | `scripts/self_check.py --all` 8/8 checks passed，文档与当前数据库证据已刷新 |

## 已执行验证

```text
uv run ruff check .                         passed
uv run python -m pytest -o addopts='' -q  353 passed, 1 existing deprecation warning
uv run scripts/self_check.py --python-only 3/3 checks passed
uv run scripts/self_check.py --all          8/8 checks passed
cd apps/web && npm run check                0 errors, 0 warnings
cd apps/web && npm run test                 15 passed
cd apps/web && npm run build                passed
cd apps/web && npm run test:e2e             26 passed
cd apps/web && npm run test:e2e:realdb      24 passed
uv run scripts/benchmark_api.py ...         passed; depth 2/3 bounded
```

上述 fixture 与 realdb 结果均为本地真实执行；fixture 不代替真实数据库验收。

## 已知限制

- 本地 manifest 的 `image_stage=skipped` 表示最后一次同步未执行图片下载阶段；已有图片缓存和缩略图可供本地验收，248 个实体仍缺主图。
- review 写接口没有认证，只允许 localhost 自用；当前不做公网或局域网部署。
- API 性能基线是单机单并发测量，不是线上 SLO；精确逐请求 SQL 计数未从本次 Uvicorn 重定向日志中取得，因此不能把它写成已测得的固定 N+1 数字。
- 本次 P3-1 文档和自检已完成；最后一次同步的 `image_stage=skipped` 仍表示未在本地执行图片下载阶段，不把它误报为本次已刷新图片。
