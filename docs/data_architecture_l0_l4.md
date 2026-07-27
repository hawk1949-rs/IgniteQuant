# 数据架构落地说明（L0–L4）

对应蓝图：热路径本地 SQLite，冷路径 / 参考数据 Supabase。

## 本地运行库（SCHEMA_VERSION = 2）

| 层级 | 内容 |
| --- | --- |
| L0 | `broker_order_event`、`heartbeat_event`、`runtime_health`；intent/fill/snapshot/recon 升列 |
| L1 | `factor_snapshot` / `signal_event` / `target_position_event` / `signal_state`；决策双写 |
| L2 | `market_bar`（+ 可选 `market_quote_l1`）；JSON 快照仍写，座舱可回退读库 |
| L3–L4 | 本地 `ref_*` / `backtest_*` / `config_version` / `factor_definition` 只读缓存；由 `ref_cache.seed_ref_tables` 从 `INSTRUMENTS` 播种 |

增量迁移：[`src/ignitequant/persistence/sqlite.py`](../src/ignitequant/persistence/sqlite.py)。

## Supabase

SQL：[`supabase/migrations/20260727000000_ref_and_research.sql`](../supabase/migrations/20260727000000_ref_and_research.sql)

```bash
# 在 .env 配置 DATABASE_URL（Session pooler 推荐）后：
python tools/apply_supabase_schema.py
```

当前 Cloud Agent 环境无法交互式完成 Supabase MCP OAuth；请在本机 Cursor 授权 MCP 或用上述脚本应用。

## 写入挂载

- 决策双写：`SqliteTradingRepository.append_decision`
- 意图 → 券商订单事件：`PersistenceSession.record_intent` / `record_fill`
- 心跳：`PersistenceSession.record_heartbeat`（`falcon_au_sim` 心跳路径）
- K 线入库：`_capture_live_klines(..., persist=)` → `persist_market_bars`
