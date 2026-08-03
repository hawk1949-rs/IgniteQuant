"""Broker position refresh + orphan SL/TP re-arm (fill_confirmed recovery)."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from ignitequant.config.decision import default_decision_config
from ignitequant.engine import FalconDecisionPipeline


class _FakePos:
    def __init__(self, net: int, *, avg: float = 882.16) -> None:
        self.pos = net
        self.pos_long = max(net, 0)
        self.pos_short = max(-net, 0)
        self.pos_long_today = max(net, 0)
        self.pos_long_his = 0
        self.pos_short_today = max(-net, 0)
        self.pos_short_his = 0
        self.open_price_long = avg if net > 0 else None
        self.open_price_short = avg if net < 0 else None


class _FakeApi:
    def __init__(self, refreshed: _FakePos) -> None:
        self._refreshed = refreshed
        self.calls = 0

    def get_position(self, _symbol: str) -> _FakePos:
        self.calls += 1
        return self._refreshed


def test_refresh_triggers_below_old_50k_margin() -> None:
    import strategies.falcon_au_sim as sim

    api = _FakeApi(_FakePos(-1))
    flat = _FakePos(0)
    account = SimpleNamespace(margin=44_596.0)
    pos, net = sim.refresh_broker_position(
        api, "SHFE.au2610", flat, account, pending_desired=-1
    )
    assert api.calls == 1
    assert net == -1
    assert pos.pos == -1


def test_refresh_skips_when_truly_flat_low_margin() -> None:
    import strategies.falcon_au_sim as sim

    api = _FakeApi(_FakePos(-1))
    flat = _FakePos(0)
    account = SimpleNamespace(margin=0.0)
    pos, net = sim.refresh_broker_position(api, "SHFE.au2610", flat, account)
    assert api.calls == 0
    assert net == 0
    assert pos is flat


def test_refresh_pending_forces_even_low_margin() -> None:
    import strategies.falcon_au_sim as sim

    api = _FakeApi(_FakePos(-1))
    flat = _FakePos(0)
    account = SimpleNamespace(margin=100.0)
    _pos, net = sim.refresh_broker_position(
        api, "SHFE.au2610", flat, account, pending_desired=-1
    )
    assert api.calls == 1
    assert net == -1


def test_orphan_rearm_short_sets_stop_above_entry() -> None:
    import strategies.falcon_au_sim as sim

    cfg = replace(default_decision_config(), entry_mode="fill_confirmed")
    pipeline = FalconDecisionPipeline(cfg)
    levels = sim._maybe_rearm_orphan_stops(
        pipeline,
        net=-1,
        fill_price=882.16,
        signal_atr=1.02,
        signal=-2,
        domestic_mark=885.0,
        overseas_close=4060.0,
        sl_atr_mult=1.3,
        tp_atr_mult=2.3,
    )
    assert levels is not None
    assert pipeline.risk.state.stop_price is not None
    assert pipeline.risk.state.take_price is not None
    assert pipeline.risk.state.entry_price is not None
    # Short: stop above entry (signal space after overseas map).
    assert pipeline.risk.state.stop_price > pipeline.risk.state.entry_price
    assert levels["display_stop_price"] > 882.16
    assert levels["display_take_price"] < 882.16


def test_orphan_rearm_noop_when_already_armed() -> None:
    import strategies.falcon_au_sim as sim

    cfg = replace(default_decision_config(), entry_mode="fill_confirmed")
    pipeline = FalconDecisionPipeline(cfg)
    pipeline.risk.on_entry(-1, 4000.0, 4.0, -2)
    before = pipeline.risk.state.stop_price
    levels = sim._maybe_rearm_orphan_stops(
        pipeline,
        net=-1,
        fill_price=882.16,
        signal_atr=1.02,
        signal=-2,
        domestic_mark=885.0,
        overseas_close=None,
    )
    assert levels is None
    assert pipeline.risk.state.stop_price == before
