# 数据主权与同步边界（C：研究 + 模拟盘）

> **实现阶段说明（2026-07）**：交易热路径仍写本地 SQLite；座舱 API **默认从云投影只读**（`SIM_DATA_SOURCE=cloud`）。公开 `/research` 路由尚未实现。

## Source of Truth

| 域 | 权威 | 说明 |
| --- | --- | --- |
| 策略发布 / 回测 / ref_* / 研究指标 | **Supabase**（目标） | 公开研究页只读云端；**当前**回测 JSON 仍在 `data/backtest_runs/` |
| 决策 / 意图 / 订单 / 成交 / 心跳（写入） | **本地 SQLite** | 交易热路径；经 `sync_outbox` 单向推云 |
| 座舱读模型（决策/意图/成交/账户摘要） | **Supabase 投影** | `sim_*_projection` + `sim_instance.payload_json`；API 用 `DATABASE_URL` 绕过 RLS |
| Runner 恢复状态 | **本地** | `strategy_state` 可重建云端投影，但下单以本地为准 |

禁止：公开页直连本地 SQLite（目标态）；前端使用 `service_role`。

## 云端产品表

Migration: [`supabase/migrations/20260727010000_product_tenant_outbox.sql`](../supabase/migrations/20260727010000_product_tenant_outbox.sql)

- `profiles` — 对 `auth.users`
- `strategy_publication` — 研究/公开策略卡片（含 RLS：public published 可读）
- `sim_instance` — 模拟会话注册投影（`payload_json` 含最新账户/持仓/价/目标）
- `trading_event_inbox` — 本地 outbox 落地

座舱投影：[`supabase/migrations/20260728000000_sim_cockpit_projections.sql`](../supabase/migrations/20260728000000_sim_cockpit_projections.sql)

- `sim_decision_projection` / `sim_intent_projection` / `sim_fill_projection`
- 由 `cloud_sync.push_outbox_once` 与 inbox **同事务 upsert**；可用 `tools/backfill_sim_projections_to_supabase.py` 回填历史

研究/行情表 RLS：[`supabase/migrations/20260727020000_rls_research_tables.sql`](../supabase/migrations/20260727020000_rls_research_tables.sql)

## 本地 outbox

- 表：`sync_outbox`（SCHEMA_VERSION ≥ 4，含 `next_retry_at` 退避）
- 写入：`PersistenceSession` 在 decision / ops_decision / intent / fill / account·position snapshot / heartbeat 后 best-effort 入队
- 心跳 outbox 降采样：约每 5 分钟一条（本地 `heartbeat_event` 仍按原频率）
- **自动推送**：`falcon_au_sim` 在启动对账后、每次心跳、每根 K 线收盘后调用 `try_push_outbox`
  - 需 `.env` 配置 `DATABASE_URL`（推荐 Session pooler）
  - 可选 `SUPABASE_OWNER_ID`（UUID）写入 `owner_id`，供 RLS 读模型
  - 可用 `ENABLE_CLOUD_SYNC=0` 关闭
- 手动补推 / 调试：

```bash
export DATABASE_URL='postgresql://…pooler…'
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
| `/research` | Supabase 研究表 | **未实现** |
| `#/sim` 座舱 | 云投影（默认） | **`SIM_DATA_SOURCE=cloud`** → API 读 Supabase；本机调试可设 `local` |
| `#/lab` 策略实验室 | 云 + API | **localStorage + 回测 API** |

## 历史 K 线归档

本地 `data/market_cache/**/300.csv` ↔ Supabase `market_bar_archive`：

```bash
# 上传
PYTHONPATH=src python3 tools/upload_market_cache_to_supabase.py --ids au,ag,rb,fg

# 从云端拉回本地（换机恢复）
PYTHONPATH=src python3 tools/download_market_cache_from_supabase.py --ids au,ag,rb,fg
```

若缓存缺失，先用天勤下载再建档。

```bash
python3 tools/apply_supabase_schema.py
python3 tools/apply_supabase_schema.py --only product_tenant
```

## 手工验证（座舱云端读）

1. 交易机：`.env` 配好 `DATABASE_URL`；`python tools/apply_supabase_schema.py --only sim_cockpit_projections`
2. 交易机跑 `falcon_au_sim` → 确认 outbox 推送后云表 `sim_decision_projection` / `sim_intent_projection` / `sim_fill_projection` / `sim_instance` 有行
3. （可选）历史回填：`PYTHONPATH=src python tools/backfill_sim_projections_to_supabase.py --db data/runtime/falcon_au_sim.sqlite`
4. 家里电脑：只起 API+前端，`.env` 含 `DATABASE_URL` 与默认 `SIM_DATA_SOURCE=cloud`，**无需** `data/runtime/*.sqlite`
5. 打开 `#/sim`：应能看到会话、决策、意图、成交与账户摘要；K 线可能为空并提示「仅交易机有实时 K 线」
6. 本机调试旧行为：`SIM_DATA_SOURCE=local`

## 换机迁移清单

1. `.env`（`TQ_*`、`DATABASE_URL`、`SUPABASE_OWNER_ID`、`SIM_DATA_SOURCE`）
2. `data/runtime/*.sqlite` + `*.klines.json`（模拟会话连续性；家里只读云可不拷）
3. `data/market_cache/` 或运行 `download_market_cache_from_supabase.py`

