# Falcon Phase 5 交付说明

> 阶段：Phase 5（回测真实性 / 归因 / 看板异步化）。  
> 依据：`docs/falcon2大框架.md` §9、§12.3、§14。  
> 不变量：不改 Falcon 公式与参数；Golden Master 保持。  
> 日期：2026-07-17。

---

## 交付物

| 项 | 路径 |
| --- | --- |
| 成本/滑点/换月模型 | `src/ignitequant/analytics/cost_model.py` |
| PnL 归因 | `src/ignitequant/analytics/attribution.py` |
| Walk-forward 窗口 | `src/ignitequant/analytics/walk_forward.py` |
| 成本压力测试 | `src/ignitequant/analytics/stress.py` |
| 异步 Job 队列 | `dashboard/jobs.py`（SQLite + ThreadPool） |
| API | `dashboard/api.py` v0.5 — 默认 async `/api/backtest` |
| Runner 增强 | `dashboard/runners.py` — attribution / stress / reproducibility |
| 前端轮询 | `web/src/lib/api.ts` — `runBacktest` 提交后轮询 job |
| 单元测试 | `tests/unit/test_phase5_analytics_jobs.py` |

## 行为约定

1. **长回测不阻塞 HTTP**：`POST /api/backtest` 默认返回 `{ mode: async, job }`；`sync=true` 仅短冒烟。
2. **幂等**：相同请求参数共享 `idempotency_key`，QUEUED/RUNNING/SUCCEEDED 不重复开跑。
3. **可复现字段**：每次 run 写入 `config_hash` / `cost_model` / `reproducibility` / `schema_version`。
4. **归因**：从 `TqSim.trade_log` 解析成交 → FIFO 毛利 − 模型手续费/滑点；并跑默认压力情景。
5. **Walk-forward**：`POST /api/research/walk-forward` 只规划窗口，不自动批量回测（避免误烧额度）。

## API 速查

```text
POST /api/backtest          # async 默认；body.sync=true 同步
GET  /api/jobs/{id}         # 进度 + 完成后 runs
POST /api/jobs/{id}/cancel
POST /api/research/walk-forward
```

## 验证

```powershell
python -m pytest tests/characterization tests/unit -q
```

## 非范围

- 真实部分成交/涨跌停撮合引擎（研究侧后续加深）
- 外部消息队列 / Celery
- Phase 6 参数重标定
