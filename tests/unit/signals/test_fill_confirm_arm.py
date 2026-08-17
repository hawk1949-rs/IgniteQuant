"""Fill confirm path must arm stops and sync confirmed_net."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ignitequant.config.decision import default_decision_config
from ignitequant.domain.models import FillEvent, OrderIntent
from ignitequant.engine import FalconDecisionPipeline
from ignitequant.execution.target_position import TargetPositionExecutor


class _FakePos:
    def __init__(self, net: int, *, avg: float = 900.0) -> None:
        self.pos = net
        self.pos_long = max(net, 0)
        self.pos_short = max(-net, 0)
        self.pos_long_today = max(net, 0)
        self.pos_long_his = 0
        self.pos_short_today = max(-net, 0)
        self.pos_short_his = 0
        self.float_profit = 0.0
        self.margin = 0.0
        self.open_price_long = avg if net > 0 else None
        self.open_price_short = avg if net < 0 else None


def test_try_confirm_fill_arms_and_persists(monkeypatch) -> None:
    import strategies.falcon_au_sim as sim

    cfg = replace(default_decision_config(), entry_mode="fill_confirmed")
    pipeline = FalconDecisionPipeline(cfg)
    pipeline._adapter.current_target = 1

    saved: dict = {}

    class _Persist:
        instance_id = "t"
        repo = SimpleNamespace(load_strategy_state=lambda _id: None)

        def record_fill(self, fill):  # noqa: ANN001
            saved["fill"] = fill

        def snapshot_position(self, snap, *, source="broker"):  # noqa: ANN001
            saved["snap_net"] = snap.net_position
            saved["source"] = source

        def save_state(self, **kwargs):  # noqa: ANN003
            saved["state"] = kwargs

    # Patch session.save_state used by _persist_state
    def _save_state(session, pipeline, **kwargs):  # noqa: ANN001,ANN003
        saved["persist_kwargs"] = kwargs
        saved["entry"] = pipeline.risk.state.entry_price
        saved["stop"] = pipeline.risk.state.stop_price
        saved["net"] = kwargs.get("net")
        saved["pending"] = kwargs.get("pending")
        saved["display"] = kwargs.get("display_levels")

    monkeypatch.setattr(sim, "_persist_state", _save_state)

    ex = TargetPositionExecutor(SimpleNamespace(), "SHFE.au2610", align_tq_kline=False)
    ex.active_intent = OrderIntent(
        intent_id="intent-1",
        decision_id="d1",
        symbol="SHFE.au2610",
        current_position=0,
        desired_position=1,
        urgency="NORMAL",
        idempotency_key="k1",
        created_at=datetime.now(timezone.utc),
        reason_codes=(),
    )

    fill = sim._try_confirm_fill(
        executor=ex,
        position=_FakePos(1),
        persist=_Persist(),
        last_price=900.0,
        atr=2.0,
        signal=2,
        pipeline=pipeline,
        trade_symbol="SHFE.au2610",
        config_hash="h",
        last_bar_id="bar1",
        domestic_mark=900.0,
        overseas_close=4100.0,
        signal_atr=8.0,
        sl_atr_mult=1.3,
        tp_atr_mult=2.3,
    )
    assert isinstance(fill, FillEvent)
    assert fill.qty == 1
    assert fill.price == 900.0
    assert pipeline.risk.state.stop_price is not None
    assert saved["net"] == 1
    assert saved["pending"] is None
    assert saved["display"] is not None
    assert saved["display"]["display_stop_price"] < 900.0


def test_try_confirm_fill_arms_from_broker_avg_not_last(monkeypatch) -> None:
    """Delayed confirm must lock SL/TP on open avg, not drifted last_price."""
    import strategies.falcon_au_sim as sim

    cfg = replace(default_decision_config(), entry_mode="fill_confirmed")
    pipeline = FalconDecisionPipeline(cfg)
    pipeline._adapter.current_target = -1

    saved: dict = {}

    def _save_state(session, pipeline, **kwargs):  # noqa: ANN001,ANN003
        saved["display"] = kwargs.get("display_levels")

    monkeypatch.setattr(sim, "_persist_state", _save_state)

    class _Persist:
        def record_fill(self, fill):  # noqa: ANN001
            saved["fill"] = fill

        def snapshot_position(self, *a, **k):  # noqa: ANN001,ANN003
            return None

    avg = 949.59
    last = 938.40
    atr = 1.41
    ex = TargetPositionExecutor(SimpleNamespace(), "SHFE.au2610", align_tq_kline=False)
    ex.active_intent = OrderIntent(
        intent_id="intent-short",
        decision_id="d-short",
        symbol="SHFE.au2610",
        current_position=0,
        desired_position=-1,
        urgency="NORMAL",
        idempotency_key="k-short",
        created_at=datetime.now(timezone.utc),
        reason_codes=(),
    )
    fill = sim._try_confirm_fill(
        executor=ex,
        position=_FakePos(-1, avg=avg),
        persist=_Persist(),
        last_price=last,
        atr=atr,
        signal=-2,
        pipeline=pipeline,
        trade_symbol="SHFE.au2610",
        config_hash="h",
        last_bar_id="bar-short",
        domestic_mark=last,
        overseas_close=None,
        signal_atr=atr,
        sl_atr_mult=1.3,
        tp_atr_mult=2.3,
    )
    assert fill is not None
    assert fill.price == avg
    assert saved["fill"].price == avg
    assert saved["display"] is not None
    assert saved["display"]["display_entry_price"] == avg
    # Short: stop above avg, take below avg — never anchored to drifted last.
    assert saved["display"]["display_stop_price"] == pytest.approx(avg + 1.3 * atr)
    assert saved["display"]["display_take_price"] == pytest.approx(avg - 2.3 * atr)
    assert saved["display"]["display_stop_price"] > avg
    assert abs(saved["display"]["display_stop_price"] - (last + 1.3 * atr)) > 0.5


def test_try_confirm_fill_flat_clears_stops(monkeypatch) -> None:
    import strategies.falcon_au_sim as sim

    cfg = replace(default_decision_config(), entry_mode="fill_confirmed")
    pipeline = FalconDecisionPipeline(cfg)
    pipeline._adapter.current_target = 0
    pipeline.risk.on_entry(1, 4100.0, 8.0, 2)

    monkeypatch.setattr(sim, "_persist_state", lambda *a, **k: None)

    class _Persist:
        def record_fill(self, fill):  # noqa: ANN001
            return None

        def snapshot_position(self, *a, **k):  # noqa: ANN001,ANN003
            return None

    ex = TargetPositionExecutor(SimpleNamespace(), "SHFE.au2610", align_tq_kline=False)
    ex.active_intent = OrderIntent(
        intent_id="intent-2",
        decision_id="d2",
        symbol="SHFE.au2610",
        current_position=1,
        desired_position=0,
        urgency="HIGH",
        idempotency_key="k2",
        created_at=datetime.now(timezone.utc),
        reason_codes=(),
    )
    fill = sim._try_confirm_fill(
        executor=ex,
        position=_FakePos(0),
        persist=_Persist(),
        last_price=890.0,
        atr=2.0,
        signal=0,
        pipeline=pipeline,
        trade_symbol="SHFE.au2610",
        config_hash="h",
        last_bar_id="bar2",
    )
    assert fill is not None
    assert pipeline.risk.state.stop_price is None
    assert pipeline.risk.state.entry_price is None
