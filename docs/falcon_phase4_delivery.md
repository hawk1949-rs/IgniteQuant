# Falcon Phase 4 交付说明

> 阶段：Phase 4（持久化 / 恢复 / 对账）。  
> 依据：`docs/falcon2大框架.md` §8、§11；小框架「不得用日志代替持久化」。  
> 不变量：不改 Falcon 公式与参数；Phase 0 Golden Master 必须保持一致。  
> 日期：2026-07-17。

---

## 交付物

| 项 | 路径 |
| --- | --- |
| Schema / 迁移 | `src/ignitequant/persistence/schema.py` + `sqlite.py`（SQLite WAL） |
| Repository | `src/ignitequant/persistence/repositories.py` |
| Session 门面 | `src/ignitequant/persistence/session.py` |
| 对账 / 启动恢复 | `src/ignitequant/engine/reconciliation.py` |
| Pipeline 恢复 | `FalconDecisionPipeline.restore_runtime` |
| 模拟盘接入 | `strategies/falcon_au_sim.py`（`ENABLE_PERSISTENCE=True`） |
| 运行库路径 | `data/runtime/falcon_au_sim.sqlite`（gitignore） |
| 单元测试 | `tests/unit/test_phase4_persistence.py` |

## 行为约定

1. **事实源**：仓位以柜台 `BrokerFacts` 为准；本地 `current_target` 不得单独推断真实持仓。
2. **启动**：加载 `strategy_state` → 对账 → 恢复冷却/入场/幂等键 → 一致才 `READY/RUNNING`，否则 `DEGRADED`（禁止新增风险）。
3. **追加写**：决策、风控、意图、成交、对账、质量事件、审计链均为 append-only；`strategy_state` 为可变投影。
4. **审计链**：`audit_event` 用 `prev_hash → event_hash` 串联，可 `verify_audit_chain`。
5. **幂等**：`UNIQUE(instance_id, idempotency_key)` + Executor `restore_idempotency_keys`，重启不重复下单。
6. **持久化不健康**：`RuntimeSnapshot.persistence_healthy=False` → Gateway 规则拦新开（减仓仍可）。

## 验证

```powershell
python -m pytest tests/characterization tests/unit -q
```

## 非范围

- PostgreSQL 迁移（实盘前再做）
- 看板异步 job 表（Phase 5）
- 行情 Parquet 湖仓（研究侧）
- 5m 参数重标定（Phase 6）
