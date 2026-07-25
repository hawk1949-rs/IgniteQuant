# Falcon Phase 6 研究报告：5m 参数重标定

> 阶段：Phase 6（策略参数研究，与架构迁移隔离）。  
> 日期：2026-07-17。  
> **生产默认仍为 `falcon_legacy_v1`。候选档案不得自动上线。**

---

## 1. 问题陈述

Falcon 指标与风控参数源自更长周期（约 1H），在 `KLINE_SECONDS=300`（5m）上沿用后：

- 同等墙钟时间内 bar 数约为原来的 **12×**；
- MA/ADX/ATR/冷却的「记忆长度」被压缩，可能出现信号过密、冷却过短；
- `LOT_BY_SIGNAL` 全 1，信号强度未进入仓位。

Phase 0–5 已完成工程化，本阶段只做**版本化参数研究**，不改 Golden Master 锚定行为。

## 2. 尺度方案

| 档案 | 方法 | 要点 | 状态 |
| --- | --- | --- | --- |
| `falcon_legacy_v1` | 原样 | Golden Master / 生产默认 | **production_default** |
| `falcon_5m_sqrt_v1` | ×√12≈3.5 | MA/ADX/ATR/KDJ/量能/冷却加长 | candidate |
| `falcon_5m_half_v1` | ×6 并封顶 | 更偏墙钟；预热更长 | candidate |
| `falcon_5m_lots_v1` | 仅手数 | `{1:1,2:2,3:3}` | candidate |

路径：`configs/falcon/*.json`

## 3. 评估方法

1. **离线标定**（无 tqsdk）：Phase 0 fixture → `evaluate_bars` / `compare_profiles`  
   `python tools/calibrate_falcon_phase6.py`
2. **Walk-forward 窗口**：复用 Phase 5 `plan_walk_forward`（示例写入标定报告）
3. **成本压力**：Phase 5 `run_cost_stress`（fee/slip ×1/×2/×3）
4. **代理盈亏**：目标变更时用 bar close 合成 OPEN/CLOSE（非柜台成交；仅研究排序）

## 4. 上线门禁（GoLiveGate）

全部满足才进入「人工审批」队列（**代码永不 auto-promote**）：

| 检查 | 默认阈值 |
| --- | --- |
| 有效 warm bars | ≥ 200 |
| 持仓时间占比 | ≤ 85% |
| 调仓次数 | 3–120（防过稀/过密） |
| 成本压力 | 全部情景 `net>0` |
| 代理净利 | `proxy_net_pnl > 0` |

额外硬条件（流程，非代码）：

1. Golden Master（legacy）持续全绿；
2. 快期模拟盘影子跑 ≥ 约定交易日；
3. 研究结论写入本文件 / `data/research/*.json`；
4. 明确回滚版本 = `falcon_legacy_v1`。

## 5. 启用与回滚

```powershell
# 启用候选（仅本地/模拟）
$env:FALCON_PROFILE = "falcon_5m_sqrt_v1"
python strategies/falcon_au_sim.py

# 回滚生产默认
Remove-Item Env:FALCON_PROFILE
# 或
$env:FALCON_PROFILE = "falcon_legacy_v1"
```

看板 runner / API 默认同步 **不**读候选档案，避免研究参数污染批量回测；需要时在 runner 显式传入 `DecisionConfig`。

## 6. 当前结论（2026-07-17）

在 Phase 0 `trend_up` 400-bar fixture 上离线标定（代理成交 + 成本压力）：

| 档案 | 调仓 | 持仓占比 | 代理净利 | 门禁 |
| --- | --- | --- | --- | --- |
| legacy | 14 | 40% | <0 | FAIL |
| 5m_sqrt | 0 | 0% | 0 | FAIL（过钝） |
| 5m_lots | 18 | 40% | <0 | FAIL |
| 5m_half | 1 | 10% | <0 | FAIL |

- 工程交付：档案 + 加载器 + 离线标定 + 门禁 + 文档齐备；`56` 项表征/单元测试通过。
- **未批准任何候选为生产默认**（门禁与短样本均未达标）。
- 下一步：更长真实区间 walk-forward 样本外 + 快期影子盘，再人工决定是否启用 `FALCON_PROFILE`。

## 7. 交付物索引

| 项 | 路径 |
| --- | --- |
| 参数档案 | `configs/falcon/` |
| 加载器 | `src/ignitequant/config/profiles.py` |
| 标定 | `src/ignitequant/research/calibration.py` |
| CLI | `tools/calibrate_falcon_phase6.py` |
| 测试 | `tests/unit/test_phase6_calibration.py` |
| 本报告 | `docs/falcon_phase6_research.md` |
