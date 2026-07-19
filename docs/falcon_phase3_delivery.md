# Falcon Phase 3 交付说明

> 阶段：Phase 3（风控 / 执行 / 状态机）。  
> 依据：`docs/falcon2大框架.md` §7、`docs/falocn2小框架.md` SOP 5。  
> 不变量：不改 Falcon 公式与参数；Phase 0 Golden Master 必须保持一致。  
> 日期：2026-07-17。

---

## 交付物

| 项 | 路径 |
| --- | --- |
| 领域对象 | `EntryContext` / `OrderIntent` / `FillEvent` / `PositionPhase` / `ReasonCode` 等 |
| RiskEngine 规则链 | `src/ignitequant/risk/`（KillSwitch → recon → gateway → stale → factor → roll → contract → limit → RESIZE） |
| 仓位状态机 | `src/ignitequant/engine/state_machine.py` |
| 换月状态机 | `src/ignitequant/execution/roll.py` |
| TargetPositionExecutor | `src/ignitequant/execution/target_position.py`（包装 `TargetPosTask`） |
| 运行时桥接 | `src/ignitequant/engine/runtime_bridge.py`（`apply_pretrade` / `healthy_runtime` / `make_risk_engine`） |
| 看板 runner | `dashboard/runners.py` |
| CLI 回测 | `strategies/falcon_au_backtest.py` |
| 快期模拟 | `strategies/falcon_au_sim.py` |
| 单元测试 | `tests/unit/test_phase3_risk_execution.py` |

## 行为约定（对照小框架 SOP5）

1. **RiskEngine 不下单**：只产出 `PASS` / `RESIZE` / `REJECT` / `HALT`；执行层只消费 `approved_position`。
2. **减仓/平仓可绕过多数拦阻**：规则链区分 risk-reducing vs risk-increasing。
3. **换月**：冻结新开仓 → 旧合约目标归零 → 等净仓为 0 → 销毁旧 Executor → 新建合约 Executor（看板用 `RollStateMachine` 显式门控）。
4. **双入场语义**（`DecisionConfig.entry_mode`）：
   - `intent_legacy`：决策核在意图时刻锁 SL/TP（Characterization / Golden Master）
   - `fill_confirmed`：Runner 路径在 `poll_position` 确认净仓匹配后再建 `EntryContext`（日志可见「成交确认」）

## 验证

```powershell
python -m pytest tests/characterization tests/unit -q
```

期望：表征测试 + Phase 3 单元测试全部通过（≥35）。

## 非范围（留给后续 Phase）

- 订单/决策持久化与对账（Phase 4）
- 看板 UI 展示风控命中与换月状态（Phase 5）
- 5m 参数重标定 / 候选 Alpha（Phase 6）
