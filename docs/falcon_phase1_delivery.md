# Falcon Phase 1 交付说明

> 阶段：Phase 1（包结构 / 领域对象 / 统一配置 / legacy 适配）。  
> 不变量：不改 Falcon 公式与参数；Phase 0 Golden Master 必须保持一致。  
> 日期：2026-07-17。

---

## 交付物

| 项 | 路径 |
| --- | --- |
| 可安装包 | `pyproject.toml` + `src/ignitequant/` |
| 领域枚举 | `src/ignitequant/domain/enums.py` |
| 领域对象 | `src/ignitequant/domain/models.py` |
| 统一配置 | `src/ignitequant/config/decision.py` |
| Legacy 适配 | `src/ignitequant/strategies/falcon/legacy_adapter.py` |
| 占位包 | `portfolio/` `risk/` `engine/`（Phase 2+） |

## 配置单一来源

`DecisionConfig`（`decision_mode=legacy_compatible`）提供：

- 风险：`sl=1.3` / `tp=2.3` / `cooldown=4`
- 手数：`legacy_fixed_lot`，`{1:1,2:1,3:1}`
- K 线：`300` 秒，warmup `52`

`tests/characterization/legacy_harness.RISK_PARAMETERS` 改为读取该配置。

## 适配器语义

`LegacyDecisionAdapter` 调用现有 `strategies.falcon.*`，产出：

`FactorSnapshot → SignalEvent → TargetPosition → RiskDecision → PipelineResult`

显式区分 `DecisionAction.HOLD / TARGET / FLAT`（对应旧 `None / int / 0`）。

## 验证

```powershell
pip install -e .
python -m pytest tests/characterization tests/unit -q
```

退出门禁：Golden Master 全绿；adapter 投影行与 golden 逐条相等。

## 非范围（未做）

- 未合并三套事件循环（Phase 2）
- 未启用候选因子 / Alpha / 风险定仓（Phase 6）
- 未改 backtest/sim/dashboard 入口调用路径（仍用旧模块；Phase 2 再切）
