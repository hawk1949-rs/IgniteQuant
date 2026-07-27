# 数据主权与同步边界（C：研究 + 模拟盘）

## Source of Truth

| 域 | 权威 | 说明 |
| --- | --- | --- |
| 策略发布 / 回测 / ref_* / 研究指标 | **Supabase** | 公开研究页只读云端 |
| 决策 / 意图 / 订单 / 成交 / 心跳 | **本地 SQLite** | 交易热路径；经 `sync_outbox` 单向推云 |
| Runner 恢复状态 | **本地** | `strategy_state` 可重建云端投影，但下单以本地为准 |

禁止：公开页直连本地 SQLite；前端使用 `service_role`。

## 云端产品表

Migration: [`supabase/migrations/20260727010000_product_tenant_outbox.sql`](../supabase/migrations/20260727010000_product_tenant_outbox.sql)

- `profiles` — 对 `auth.users`
- `strategy_publication` — 研究/公开策略卡片（含 RLS：public published 可读）
- `sim_instance` — 模拟会话注册投影
- `trading_event_inbox` — 本地 outbox 落地

## 本地 outbox

- 表：`sync_outbox`（SCHEMA_VERSION ≥ 3）
- 写入：`PersistenceSession` 在 decision / intent / fill / heartbeat 后 best-effort 入队
- **自动推送**：`falcon_au_sim` 在启动对账后、每次心跳、每根 K 线收盘后调用 `try_push_outbox`
  - 需 `.env` 配置 `DATABASE_URL`（推荐 Session pooler）
  - 可用 `ENABLE_CLOUD_SYNC=0` 关闭
- 手动补推 / 调试：

```bash
export DATABASE_URL='postgresql://…pooler…'
PYTHONPATH=src python3 tools/sync_outbox_to_supabase.py --db data/runtime/falcon_au_sim.sqlite
```

## 页面读模型（约定）

- `/research` → `strategy_publication` + `backtest_*` + `ref_*`
- `/cockpit` → `sim_instance` +（登录后）inbox/私有投影；细节仍可回源本地 API

## 应用迁移

```bash
python3 tools/apply_supabase_schema.py
python3 tools/apply_supabase_schema.py --only product_tenant
```
