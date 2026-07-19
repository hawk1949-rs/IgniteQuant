# Falcon Phase 2 交付说明

> 阶段：Phase 2（统一事件循环 / 决策入口）。  
> 不变量：不改 Falcon 公式与参数；Phase 0 Golden Master 必须保持一致。  
> 日期：2026-07-17。

---

## 交付物

| 项 | 路径 |
| --- | --- |
| 统一决策入口 | `src/ignitequant/engine/decision_pipeline.py` → `FalconDecisionPipeline.on_bar_close` |
| CLI 回测 | `strategies/falcon_au_backtest.py` |
| 快期模拟 | `strategies/falcon_au_sim.py` |
| 看板 runner | `dashboard/runners.py` |

## 分工

- **决策核（唯一）**：指标 → regime → score → sizing → ATR 风控 → `PipelineResult`
- **环境适配（各入口保留）**：换月、期末强平、`web_gui`、心跳、Excel、启动评估、进度回调

`on_bar_close(..., trade=False)` 用于回测期末日：只观察 + 冷却递减，不触发开平（与旧语义一致），再由 runner `force_flat()`。

## 验证

```powershell
python -m pytest tests/characterization tests/unit -q
```

## 非范围

- 未做真实成交驱动 EntryContext（Phase 3）
- 未做订单持久化 / 对账（Phase 4）
- 未改 5m 参数（Phase 6）
