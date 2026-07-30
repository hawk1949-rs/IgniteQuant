"""Characterization: overseas fixture → deterministic scores; closed bars gate."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ignitequant.config import DecisionConfig, default_decision_config
from ignitequant.domain.enums import ReasonCode, RiskAction
from ignitequant.engine import FalconDecisionPipeline, apply_pretrade, make_risk_engine
from ignitequant.market.overseas_bars import bars_dicts_to_dataframe
from ignitequant.market.session import TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN


def _synthetic_overseas_bars(n: int = 420) -> pd.DataFrame:
    """Deterministic upward COMEX-like series for score stability checks."""
    rng = np.random.default_rng(42)
    t0 = 1_700_000_000
    price = 2000.0
    rows = []
    for i in range(n):
        drift = 0.15
        noise = float(rng.normal(0, 0.8))
        o = price
        c = price + drift + noise
        h = max(o, c) + abs(float(rng.normal(0, 0.4)))
        l = min(o, c) - abs(float(rng.normal(0, 0.4)))
        rows.append(
            {
                "time": t0 + i * 300,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 100 + i % 17,
            }
        )
        price = c
    return bars_dicts_to_dataframe(rows, underlying_symbol="XAUUSD")


def _cfg() -> DecisionConfig:
    base = default_decision_config()
    return DecisionConfig(
        decision_mode=base.decision_mode,
        entry_mode=base.entry_mode,
        config_version=base.config_version,
        symbol="XAUUSD",
        factor=base.factor,
        signal=base.signal,
        sizing=base.sizing,
        risk=base.risk,
    )


def _replay_signals(bars: pd.DataFrame) -> list[tuple[int | None, str]]:
    pipe = FalconDecisionPipeline(_cfg())
    out: list[tuple[int | None, str]] = []
    warmup = max(int(pipe.config.factor.warmup_bars), 60)
    for i in range(warmup, len(bars)):
        window = bars.iloc[: i + 1]
        result = pipe.on_bar_close(window, trade=True)
        out.append((result.signal.legacy_signal, result.factors.regime.value))
    return out


def test_overseas_fixture_scores_deterministic() -> None:
    bars = _synthetic_overseas_bars()
    a = _replay_signals(bars)
    b = _replay_signals(bars)
    assert len(a) == len(b)
    assert len(a) > 50
    assert a[-50:] == b[-50:]


def test_closed_session_blocks_after_signal() -> None:
    bars = _synthetic_overseas_bars()
    cfg = _cfg()
    pipe = FalconDecisionPipeline(cfg)
    risk = make_risk_engine(cfg)
    result = None
    for i in range(200, len(bars)):
        window = bars.iloc[max(0, i - 399) : i + 1]
        result = pipe.on_bar_close(window, trade=True)
    assert result is not None
    assert result.signal is not None

    # Force a non-flat target for the gate check if last bar was HOLD.
    from ignitequant.domain.enums import DecisionAction
    from ignitequant.domain.models import TargetPosition
    from decimal import Decimal

    if int(result.target.desired_position) == 0:
        forced = TargetPosition(
            target_id=result.target.target_id,
            signal_id=result.signal.signal_id,
            symbol="SHFE.au2608",
            decision_action=DecisionAction.TARGET,
            current_position=0,
            desired_position=1,
            delta=1,
            planned_entry_price=600.0,
            planned_stop_price=None,
            stop_distance=None,
            risk_per_lot=None,
            requested_risk=Decimal("0"),
            sizing_method="legacy_fixed_lot",
            reason_codes=("TEST_FORCE",),
            config_version=cfg.config_version,
        )
        from dataclasses import replace

        result = replace(result, target=forced, applied_action="TARGET")

    pre_open = apply_pretrade(
        result,
        net_position=0,
        last_price=600.0,
        risk_engine=risk,
        trade_status=TRADE_STATUS_OPEN,
        symbol="SHFE.au2608",
    )
    pre_closed = apply_pretrade(
        result,
        net_position=0,
        last_price=600.0,
        risk_engine=risk,
        trade_status=TRADE_STATUS_CLOSED,
        symbol="SHFE.au2608",
    )
    assert pre_closed.action is RiskAction.REJECT
    assert ReasonCode.MARKET_CLOSED.value in pre_closed.rule_hits
    assert pre_closed.approved_position == 0
    assert ReasonCode.MARKET_CLOSED.value not in pre_open.rule_hits
