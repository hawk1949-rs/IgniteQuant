"""Unit tests: LocalSim fill prices mirror TqSim kline-backtest matching."""

from __future__ import annotations

from ignitequant.analytics.cost_model import ALIGN_MODE_TQ_KLINE, CostModel
from ignitequant.analytics.tq_match import (
    market_fill_price,
    metrics_delta,
    quote_from_bar_close,
    within_tolerances,
)
from ignitequant.engine.local_sim import LocalSimAccount
from ignitequant.market.symbols import cost_model_for, instrument_by_id


def test_tq_kline_quote_is_one_tick_book() -> None:
    q = quote_from_bar_close(800.0, 0.02)
    assert q.ask() == 800.02
    assert q.bid() == 799.98
    assert market_fill_price("BUY", q) == 800.02
    assert market_fill_price("SELL", q) == 799.98


def test_cost_model_tq_align_ignores_extra_roll_slip() -> None:
    cost = CostModel(
        tick_size=0.02,
        slippage_ticks=1.0,
        roll_slippage_ticks=2.0,
        align_mode=ALIGN_MODE_TQ_KLINE,
    ).as_tq_kline()
    assert cost.slip_price("BUY", 800.0, roll=False) == 800.02
    assert cost.slip_price("BUY", 800.0, roll=True) == 800.02
    assert cost.slip_price("SELL", 800.0, roll=True) == 799.98


def test_research_mode_still_widens_roll_slip() -> None:
    cost = CostModel(
        tick_size=0.02,
        slippage_ticks=1.0,
        roll_slippage_ticks=2.0,
    ).as_research()
    assert cost.slip_price("BUY", 800.0, roll=False) == 800.02
    assert cost.slip_price("BUY", 800.0, roll=True) == 800.04


def test_local_sim_fill_matches_tq_kline_helper() -> None:
    cost = cost_model_for(instrument_by_id("au"), tq_align=True)
    sim = LocalSimAccount(init_balance=1_000_000, cost=cost)
    fills = sim.fill_to_target(symbol="SHFE.au2506", desired=1, signal_price=800.0)
    assert len(fills) == 1
    assert fills[0].price == market_fill_price("BUY", quote_from_bar_close(800.0, 0.02))
    assert fills[0].fee == cost.open_fee_per_lot


def test_instrument_cost_default_is_tq_align() -> None:
    aligned = cost_model_for(instrument_by_id("au"), tq_align=True)
    research = cost_model_for(instrument_by_id("au"), tq_align=False)
    assert aligned.align_mode == ALIGN_MODE_TQ_KLINE
    assert aligned.roll_slippage_ticks == aligned.slippage_ticks == 1.0
    assert research.roll_slippage_ticks == 2.0


def test_within_tolerances_gate() -> None:
    local = {"ror": 0.10, "max_drawdown": 0.05, "final_balance": 1_100_000, "trade_count": 20}
    tq = {"ror": 0.11, "max_drawdown": 0.055, "final_balance": 1_105_000, "trade_count": 21}
    ok, fails = within_tolerances(local, tq)
    assert ok, fails
    bad = {**tq, "ror": 0.20}
    ok2, fails2 = within_tolerances(local, bad)
    assert not ok2
    assert any("ror" in f for f in fails2)


def test_metrics_delta_shape() -> None:
    delta = metrics_delta({"ror": 0.1, "trade_count": 10}, {"ror": 0.12, "trade_count": 10})
    assert abs(delta["ror"]["abs_diff"] - 0.02) < 1e-12
    assert delta["trade_count"]["abs_diff"] == 0.0
