"""entry_mode=fill_confirmed must not arm stops on TARGET intent alone."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from ignitequant.config.decision import default_decision_config
from ignitequant.domain.models import OrderIntent
from ignitequant.execution.target_position import TargetPositionExecutor
from ignitequant.strategies.falcon.legacy_adapter import LegacyDecisionAdapter
from strategies.falcon.regime import Regime as LegacyRegime


def _minimal_bars(n: int = 80) -> pd.DataFrame:
    rows = []
    for i in range(n):
        px = 100.0 + i * 0.5
        rows.append(
            {
                "datetime": 1_700_000_000_000_000_000 + i * 300_000_000_000,
                "open": px - 0.1,
                "high": px + 0.4,
                "low": px - 0.4,
                "close": px,
                "volume": 1000 + i,
                "open_oi": 100,
                "close_oi": 100,
            }
        )
    return pd.DataFrame(rows)


def test_fill_confirmed_skips_on_entry_until_runner_confirms(monkeypatch) -> None:
    monkeypatch.setattr(
        "ignitequant.strategies.falcon.legacy_adapter.lots_from_signal",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        "ignitequant.strategies.falcon.legacy_adapter.detect_regime",
        lambda *args, **kwargs: LegacyRegime.TREND_UP,
    )
    cfg = replace(default_decision_config(), entry_mode="fill_confirmed")
    adapter = LegacyDecisionAdapter(cfg)
    bars = _minimal_bars()
    result = adapter.on_bar_window(bars, bar_index=70, trade=True)
    assert result.applied_action == "TARGET"
    assert result.target_after == 1
    assert adapter.risk.state.entry_price is None
    assert adapter.risk.state.stop_price is None


def test_intent_legacy_still_arms_on_target(monkeypatch) -> None:
    monkeypatch.setattr(
        "ignitequant.strategies.falcon.legacy_adapter.lots_from_signal",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        "ignitequant.strategies.falcon.legacy_adapter.detect_regime",
        lambda *args, **kwargs: LegacyRegime.TREND_UP,
    )
    cfg = replace(default_decision_config(), entry_mode="intent_legacy")
    adapter = LegacyDecisionAdapter(cfg)
    bars = _minimal_bars()
    result = adapter.on_bar_window(bars, bar_index=70, trade=True)
    assert result.applied_action == "TARGET"
    assert adapter.risk.state.entry_price is not None
    assert adapter.risk.state.stop_price is not None


def test_poll_position_skips_zero_qty_fill() -> None:
    class _Api:
        pass

    ex = TargetPositionExecutor(_Api(), "SHFE.au2610", align_tq_kline=False)
    from datetime import datetime, timezone

    ex.active_intent = OrderIntent(
        intent_id="intent-x",
        decision_id="d",
        symbol="SHFE.au2610",
        current_position=0,
        desired_position=0,
        urgency="HIGH",
        idempotency_key="k",
        created_at=datetime.now(timezone.utc),
        reason_codes=(),
    )
    fill = ex.poll_position(0, last_price=900.0, atr=1.0, signal=1)
    assert fill is None
    assert ex.active_intent is None
