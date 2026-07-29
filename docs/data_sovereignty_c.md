# 数据主权与同步边界（C：研究 + 模拟盘）

> **实现阶段说明（2026-07）**：交易热路径仍写 **ECS/本机 SQLite**；云端主库已切到 **阿里云 RDS PostgreSQL**（`DATABASE_URL` / `RDS_DATABASE_URL`，库名 `ignitequant`，实例 `pgm-uf6ro4p932k08bh8`）。大文件与 sqlite 备份落 **OSS**（`ignitequant` / cn-shanghai；需配置 `OSS_ACCESS_KEY_*`）。**Supabase 已停写**（仅保留只读对照，勿再把 `DATABASE_URL` 指回 Supabase）。公开 `/research` 路由尚未实现。

## Source of Truth

| 域 | 权威 | 说明 |
| --- | --- | --- |
| 策略发布 / 回测 / ref_* / 研究指标 | **阿里云 RDS** | Schema：[`supabase/rds/001_core_schema.sql`](../supabase/rds/001_core_schema.sql)；回测 JSON 仍可能在 `data/backtest_runs/` |
| 决策 / 意图 / 订单 / 成交 / 心跳（写入） | **本地 SQLite**（ECS） | 交易热路径；经 `sync_outbox` 单向推 **RDS** |
| 座舱读模型（决策/意图/成交/账户摘要） | **RDS 投影** | `sim_*_projection` + `sim_instance.payload_json`；API 用 `DATABASE_URL` |
| 行情文件 / 运行库备份 | **OSS** | `tools/sync_files_to_oss.py`；前缀 `market_cache/`、`runtime_backup/` |
| Runner 恢复状态 | **本地** | `strategy_state` 可重建云端投影，但下单以本地为准 |

禁止：公开页直连本地 SQLite（目标态）；前端使用 `service_role`。

## 云端产品表（RDS）

建库：`PYTHONPATH=src python tools/apply_rds_schema.py`（读 `RDS_DATABASE_URL`）。

从 Supabase 一次性迁入：

```bash
# .env 中 SOURCE_DATABASE_URL=旧 Supabase；RDS_DATABASE_URL=阿里云
PYTHONPATH=src python tools/migrate_supabase_to_rds.py --apply --truncate-target
# 或一键：
PYTHONPATH=src python tools/cutover_to_aliyun_rds.py --apply --with-oss
```

主要表：

- `profiles`（无 Supabase Auth 外键）
- `strategy_publication` / `sim_instance` / `trading_event_inbox`
- `sim_decision_projection` / `sim_intent_projection` / `sim_fill_projection`
- `ref_*` / `ref_product_margin` / `ref_overseas_pair` / `market_bar_archive`

历史 Supabase 迁移脚本仍保留在 [`supabase/migrations/`](../supabase/migrations/) 作档案；**新环境请用 `supabase/rds/`**。

## 本地 outbox

- 表：`sync_outbox`（SCHEMA_VERSION ≥ 4，含 `next_retry_at` 退避）
- 写入：`PersistenceSession` 在 decision / ops_decision / intent / fill / account·position snapshot / heartbeat 后 best-effort 入队
- 心跳 outbox 降采样：约每 5 分钟一条（本地 `heartbeat_event` 仍按原频率）
- **自动推送**：`falcon_au_sim` 在启动对账后、每次心跳、每根 K 线收盘后调用 `try_push_outbox`
  - 需 `.env` 配置 `DATABASE_URL` 指向 **RDS**（ECS 内网地址优先）
  - 可选 `SUPABASE_OWNER_ID`（UUID）写入 `owner_id`（兼容字段名；RDS 无 RLS）
  - 可用 `ENABLE_CLOUD_SYNC=0` 关闭
- 手动补推 / 调试：

```bash
export DATABASE_URL='postgresql://…rds…'
PYTHONPATH=src python3 tools/sync_outbox_to_supabase.py --db data/runtime/falcon_au_sim.sqlite
# 历史一次回填到投影表：
PYTHONPATH=src python3 tools/backfill_sim_projections_to_supabase.py --db data/runtime/falcon_au_sim.sqlite
```

成交补录（仍只走本地写库；家里只读座舱勿用）：

```bash
curl -X POST http://127.0.0.1:8787/api/sim/sessions/falcon_au_sim/repair-fills
```

## 页面读模型（约定 vs 当前）

| 页面 | 目标 | 当前实现 |
| --- | --- | --- |
| `/research` | RDS 研究表 | **未实现** |
| `#/sim` 座舱 | 云投影（默认） | ECS 上多为 `SIM_DATA_SOURCE=local`；只读机用 `cloud` + `DATABASE_URL`→RDS |
| `#/lab` 策略实验室 | 云 + API | **localStorage + 回测 API** |

## 历史 K 线归档

本地 `data/market_cache/**/300.csv` ↔ RDS `market_bar_archive`；文件冷备 ↔ OSS `market_cache/`：

```bash
# 上传到 RDS（工具名仍带 supabase，实际写 DATABASE_URL 指向的库）
PYTHONPATH=src python3 tools/upload_market_cache_to_supabase.py --ids au,ag,rb,fg

# 文件备份到 OSS
PYTHONPATH=src python3 tools/sync_files_to_oss.py --upload-cache --upload-runtime

# 从云端拉回本地（换机恢复）
PYTHONPATH=src python3 tools/download_market_cache_from_supabase.py --ids au,ag,rb,fg
```

若缓存缺失，先用天勤下载再建档。

```bash
PYTHONPATH=src python tools/apply_rds_schema.py
```

## 手工验证（座舱云端读）

1. ECS：`.env` 中 `DATABASE_URL`=`RDS_DATABASE_URL`；`systemctl restart ignitequant-api ignitequant-sim`
2. 确认 outbox 推送后 RDS 表 `sim_decision_projection` / `sim_intent_projection` / `sim_fill_projection` / `sim_instance` 有新行
3. （可选）历史回填：`PYTHONPATH=src python tools/backfill_sim_projections_to_supabase.py --db data/runtime/falcon_au_sim.sqlite`
4. 家里电脑：只起 API+前端，`.env` 含 RDS `DATABASE_URL` 与 `SIM_DATA_SOURCE=cloud`
5. 打开座舱：应能看到会话、决策、意图、成交与账户摘要
6. 本机调试：`SIM_DATA_SOURCE=local`

## 换机迁移清单

1. `.env`（`TQ_*`、`DATABASE_URL`→RDS、`RDS_DATABASE_URL`、`OSS_*`、`SIM_DATA_SOURCE`）
2. `data/runtime/*.sqlite` + `*.klines.json`（或从 OSS `runtime_backup/latest/` 拉取）
3. `data/market_cache/` 或 OSS / `download_market_cache_from_supabase.py`

