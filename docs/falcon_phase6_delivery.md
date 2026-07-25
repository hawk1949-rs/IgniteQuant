# Falcon Phase 6 交付说明

> 阶段：Phase 6（5m 参数重标定 — 研究闭环）。  
> **生产默认仍为 legacy；Golden Master 不因候选档案改变。**  
> 日期：2026-07-17。

---

## 交付物

| 项 | 路径 |
| --- | --- |
| 版本化参数 JSON | `configs/falcon/*.json` |
| Profile 加载 | `ignitequant.config.profiles` |
| 离线标定 / 门禁 | `ignitequant.research.calibration` |
| CLI | `tools/calibrate_falcon_phase6.py` |
| 研究报告 | `docs/falcon_phase6_research.md` |
| Adapter 注入周期/手数 | `legacy_adapter` ← `FactorConfig` / `SizingConfig` |
| 模拟/回测开关 | 环境变量 `FALCON_PROFILE` |

## 不变量

1. `default_decision_config()` 与 Golden Master 行为不变。
2. 候选档案 `status=candidate`，`GoLiveGate.promote` 恒为 `False`。
3. 未达标前禁止把候选写进生产默认。

## 验证

```powershell
python -m pytest tests/characterization tests/unit -q
python tools/calibrate_falcon_phase6.py
```

## 启用候选（显式）

```powershell
$env:FALCON_PROFILE = "falcon_5m_sqrt_v1"
```
