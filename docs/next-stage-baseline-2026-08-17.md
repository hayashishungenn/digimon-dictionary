# DigiDex 下一阶段真实数据基线（P0-0，2026-08-17）

> 用途：下一阶段任务书（P0-0..P3-1）执行前的真实基线，锁定当前"破坏的"真实状态，
> 作为 P0-1 图片路径迁移的还原点。所有数字来自对 `data/digidex.sqlite` 的只读查询
> 与 `scripts/diagnose.py --json`，**不是**手工推测。

## 提交与工作区

- HEAD：`9f697be docs: add next-stage Claude Code taskbook`（origin/main 前 1 个提交）
- 工作区：干净
- ruff：通过

## 数据库（只读实测）

| 项 | 值 |
|---|---|
| integrity_check | ok |
| schema `user_version` | 8 |
| snapshot_date | 2026-08-16 |
| 总数 / 官方 / 扩展 | 1736 / 1316 / 420 |
| `digimon_image` 行数 | 1488 |
| `image_type` 分布 | main_image=1488、thumbnail=**0** |
| `download_status` 分布 | downloaded=1488 |
| `digimon.thumbnail` 非空 | **0** |
| `local_path` 绝对路径数 | **1488**（全部指向旧 checkout `C:\Users\Hayas\Github\Digimon_Dictionary\data\images\digi_00001_Agumon.png`，旧"名称式"文件名） |
| 缺少 main_image 的 digimon | 248 |
| open `manual_review_queue` | 775 |

## 磁盘图片缓存（只读实测）

- `data/images/`：1488 张主图（旧文件名 `digi_00001_Agumon.png` 等，含空格/括号）+ `.gitkeep`
- `data/images/thumbs/`：1488 个缩略图 `digi_00001.png`..`digi_01488.png`，**数据库无对应元数据**

## 发布 manifest（`data/.publish_manifest.json`）

- run_id：`20260816T065459922120-127c8`
- `image_stage`：`skipped`（图片阶段未在本快照运行）
- `state_committed`：`true`

## 已知失败（如实记录，不报为通过）

- `tests/integration/test_real_db_smoke.py::test_images_served_or_absent` **当前失败**：
  `GET /api/images/agumon/thumbnail -> 404`。原因：DB 无 thumbnail 元数据行，且 `local_path`
  全部是旧 checkout 绝对路径，API 按绝对路径找不到文件 → 不返回 200。
  本阶段只记录，不在 P0-1 迁移前修复。

## 备份

执行 `uv run python scripts/backup_local.py --with-images` 生成：

- 备份目录：`data/backups/backup-20260816T170006/`
- 备份库 `digidex.sqlite`：`PRAGMA integrity_check = ok`、schema v8、1488 行 `digimon_image`
- backup.json：`db sha256 = 9098dfb6b8d131347b3c44cb1634e0c94d9976fc0c49a394f172d6009755d4b4`、`db size = 14659584`
- 图片缓存：`images/`（1488 主图）+ `images/thumbs/`（1488 缩略图）均已复制且可读
- 该备份包含数据库、同步状态、发布 manifest、质量报告与图片缓存，可作为 P0-1 迁移前的还原点（P0-1 迁移脚本还会自动再建一次备份）

## 结论

当前系统不能被称为"自用稳定版"：数据库内图片路径不可迁移、缩略图元数据缺失。
修复路径见 `docs/next-stage-auto-mode-taskbook-2026-08-16.md`（P0-1..P3-1）。