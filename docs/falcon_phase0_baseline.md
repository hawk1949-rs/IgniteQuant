# Falcon Phase 0 基线登记（行为冻结）

> 阶段：Phase 0 only。本文只记录证据与差异，不改变策略公式或参数。  
> 配套产物：`tests/fixtures/falcon_phase0/`、`tests/golden/falcon_phase0/`、`tests/characterization/`。  
> 日期：2026-07-17。

---

## 1. 决策核调用关系（当前事实）

```text
compute_indicators(klines)
  → detect_regime(ind)          # ADX≥25 + close vs MA52
  → score_signal(ind)           # gv + vol + kdj → signal∈[-3,3]
  → lots_from_signal(signal, regime)  # None=HOLD, int=目标净仓
  → RiskManager.check / on_entry / trigger  # sl=1.3 tp=2.3 cooldown=4（入口传入）
  → TargetPosTask.set_target_volume
```

公共纯函数包：`strategies/falcon/{indicators,regime,score,sizing,risk}.py`。

Golden Master 回放顺序（`tests/characterization/legacy_harness.py`）：

```text
tick_cooldown → 持仓风控 check → cooldown gate → sizing → target update / on_entry
```

---

## 2. 三入口行为差异

| 项目 | `falcon_au_backtest.py` | `falcon_au_sim.py` | `dashboard/runners.run_falcon_v2` |
| --- | --- | --- | --- |
| 账户 | `TqSim` + `TqBacktest` | `TqKq` | `TqSim` + `TqBacktest` |
| `web_gui` | `:9876` + 结束后 `wait_update` 保活 | `:9876` | `False`，可退出 |
| K 线 | 300s / data_length=400 | 同左 | 同左（默认 `kline_seconds=300`） |
| Risk 参数 | 显式 1.3 / 2.3 / 4 | 同左 | 同左 |
| 启动评估 | 无 | 有：启动时对最新 K 评估并可立即开仓 | 无 |
| 期末强平 | 有：`FLAT_DATE` 起目标=0 | 无 | 有（与 CLI 同逻辑） |
| 换月 | 先平旧再切新 | 同左 | 同左 |
| Excel 存档 | `ENABLE_ARCHIVE` 可选 | 无 | 无 |
| 心跳 | 无 | 60s 日志心跳（不调仓） | 无 |
| 退出平仓 | 无（回测结束） | `FLAT_ON_EXIT=True` | 无 |
| 返回值 | 打印 + 可选 Excel | 打印 | metrics + scorecard JSON |

**Phase 0 Golden Master 覆盖范围**：仅公共决策核 bar-by-bar 行为。  
**明确排除**：启动评估、换月事务、期末强平、UI 保活、Excel、心跳。这些差异已登记，留给 Phase 2 Runner 适配器处理。

---

## 3. 固定数据集

| 场景 | 文件 | bars | 区间（fixture） | 选择依据 |
| --- | --- | --- | --- | --- |
| `trend_up` | `tests/fixtures/falcon_phase0/trend_up.csv` | 400 | 2025-01-27 ~ 2025-02-10 | 最大净收益窗口 |
| `trend_down` | `tests/fixtures/falcon_phase0/trend_down.csv` | 400 | 2025-02-25 ~ 2025-02-28 | 最小净收益窗口 |
| `sideways_transition` | `tests/fixtures/falcon_phase0/sideways_transition.csv` | 400 | 2025-03-20 ~ 2025-03-26 | 最低路径效率 |

来源：`KQ.m@SHFE.au` 5 分钟历史；capture 脚本 `tools/capture_falcon_phase0.py`（仅 `--capture` 时联网）。  
清单与校验和：`tests/fixtures/falcon_phase0/manifest.json`。

---

## 4. Golden Master 快照字段

每根暖身后 K 线（自 bar_index≥51）记录：

- 指标：`ma7/14/52`、`atr`、`adx`、`kdj_k/d/j`、`vol_ma`、`close`
- `regime`、`signal` 及分项、`sizing_target`
- `target_before/after`、`applied_action`、`risk_action`
- `entry/stop/take`、`cooldown_left`

浮点：`FLOAT_DIGITS=10`。风险参数写入 golden：`{1.3, 2.3, 4}`。

每场景暖身后记录数：**349**（400 − 51）。

---

## 5. 已知风险登记（Phase 0）

| ID | 级别 | 现象 | 证据 |
| --- | --- | --- | --- |
| R-01 | High | `RiskManager` 类默认 1.5/2.5/3，三入口写死 1.3/2.3/4 | `risk.py` vs 入口构造 |
| R-02 | Critical | 三套主循环复制，环境差异未抽离 | backtest / sim / runners |
| R-03 | High | `None`=HOLD 与 `0`=FLAT 隐式约定 | `sizing.lots_from_signal` |
| R-04 | High | `on_entry` 在 `set_target_volume` 后立即调用，可能早于真实成交 | 三入口调仓分支 |
| R-05 | Medium | 1H→5m 参数未重标定 | `KLINE_SECONDS=300` + 原周期公式 |
| R-06 | Medium | `LOT_BY_SIGNAL` 全为 1 | `sizing.py` |
| R-07 | High | 无订单/成交持久化与启动对账 | 源码现状 |

---

## 6. 如何复现 / 验证

```powershell
# 离线：仅用已批准 fixtures 重生成 golden（不改策略）
python tools/capture_falcon_phase0.py

# 联网：仅在需要更新行情样本时（会改 fixtures，需重新批准）
python tools/capture_falcon_phase0.py --capture

# 运行 Phase 0 测试
python -m pytest tests/characterization -q
```

未经明确批准，不得修改 `tests/golden/falcon_phase0/*.json` 以迁就新实现。

---

## 7. Phase 0 退出条件检查

- [x] 三入口差异已文档化
- [x] 固定三段 400-bar 5m 数据 + SHA256
- [x] bar-by-bar 指标 / regime / score / 目标 / 风控事件 Golden Master
- [x] characterization tests 锁定基线
- [x] pytest 全绿：`13 passed`（2026-07-17，`python -m pytest tests/characterization -q`）

**下一步（Phase 1，未开始）**：`src/ignitequant` 领域对象与统一配置；保持 Golden Master 不变。
