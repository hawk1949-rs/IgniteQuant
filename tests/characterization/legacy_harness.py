"""Phase 0 harness that records the current Falcon decision behavior.

This module intentionally calls the legacy functions directly.  It is test-only
evidence, not a replacement decision engine.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from strategies.falcon import (
    RiskAction,
    RiskManager,
    compute_indicators,
    detect_regime,
    lots_from_signal,
    score_signal,
)

WARMUP_BARS = 52
FLOAT_DIGITS = 10

# Single source of truth lives in ignitequant.config (Phase 1).
try:
    from ignitequant.config import default_decision_config

    RISK_PARAMETERS = default_decision_config().risk_kwargs()
except ImportError:  # pragma: no cover - editable install missing
    RISK_PARAMETERS = {
        "sl_atr_mult": 1.3,
        "tp_atr_mult": 2.3,
        "cooldown_bars": 4,
    }


def _number(value: Any) -> float | None:
    number = float(value)
    if not math.isfinite(number):
        return None
    rounded = round(number, FLOAT_DIGITS)
    return 0.0 if rounded == 0 else rounded


def run_legacy_characterization(bars: pd.DataFrame) -> list[dict[str, Any]]:
    """Replay the current pure Falcon modules and return one record per warm bar.

    The sequencing mirrors the common section of the three current runners:
    cooldown tick -> held-position exit check -> cooldown gate -> sizing ->
    target update.  It deliberately excludes environment-specific behavior such
    as startup evaluation, contract roll and backtest end-date flattening.
    """

    required = {"datetime", "open", "high", "low", "close", "volume"}
    missing = required.difference(bars.columns)
    if missing:
        raise ValueError(f"fixture is missing columns: {sorted(missing)}")
    if len(bars) < WARMUP_BARS:
        raise ValueError(f"fixture needs at least {WARMUP_BARS} bars")

    risk = RiskManager(**RISK_PARAMETERS)
    current_target = 0
    records: list[dict[str, Any]] = []

    for bar_index in range(WARMUP_BARS - 1, len(bars)):
        window = bars.iloc[: bar_index + 1]
        ind = compute_indicators(window)
        regime = detect_regime(ind)
        score = score_signal(ind)
        desired = lots_from_signal(score.signal, regime)

        target_before = current_target
        risk.tick_cooldown()
        risk_action = RiskAction.NONE
        applied_action = "HOLD"

        if current_target != 0:
            risk_action = risk.check(
                current_target,
                float(ind.high[-1]),
                float(ind.low[-1]),
                float(ind.close[-1]),
            )
            if risk_action != RiskAction.NONE:
                risk.trigger(risk_action)
                current_target = 0
                applied_action = risk_action.value

        if risk_action == RiskAction.NONE:
            if risk.in_cooldown:
                applied_action = "COOLDOWN_HOLD"
            elif desired is not None and desired != current_target:
                current_target = desired
                applied_action = "TARGET"
                if current_target == 0:
                    risk.on_flat()
                else:
                    risk.on_entry(
                        current_target,
                        float(ind.close[-1]),
                        float(ind.atr[-1]),
                        score.signal,
                    )

        records.append(
            {
                "bar_index": bar_index,
                "datetime": int(window.iloc[-1]["datetime"]),
                "close": _number(ind.close[-1]),
                "ma7": _number(ind.ma7[-1]),
                "ma14": _number(ind.ma14[-1]),
                "ma52": _number(ind.ma52[-1]),
                "atr": _number(ind.atr[-1]),
                "adx": _number(ind.adx[-1]),
                "kdj_k": _number(ind.k[-1]),
                "kdj_d": _number(ind.d[-1]),
                "kdj_j": _number(ind.j[-1]),
                "vol_ma": _number(ind.vol_ma[-1]),
                "regime": regime.value,
                "signal": score.signal,
                "granville": score.granville,
                "volume_score": score.volume,
                "kdj_score": score.kdj,
                "conflict_penalty": score.conflict_penalty,
                "sizing_target": desired,
                "target_before": target_before,
                "target_after": current_target,
                "applied_action": applied_action,
                "risk_action": risk_action.value,
                "entry_price": _number(risk.state.entry_price)
                if risk.state.entry_price is not None
                else None,
                "stop_price": _number(risk.state.stop_price)
                if risk.state.stop_price is not None
                else None,
                "take_price": _number(risk.state.take_price)
                if risk.state.take_price is not None
                else None,
                "cooldown_left": risk.state.cooldown_left,
            }
        )

    return records
