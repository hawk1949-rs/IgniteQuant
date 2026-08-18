"""Local market cache + offline replay engine tests (no tqsdk network)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from ignitequant.engine.local_replay import run_local_falcon_backtest
from ignitequant.engine.local_sim import LocalSimAccount
from ignitequant.execution.roll import RollStateMachine
from ignitequant.market.cache import load_bars, merge_and_save, slice_bars
from ignitequant.market.symbols import INSTRUMENTS, cost_model_for, instrument_by_id


def _synthetic_bars(
    *,
    n: int = 500,
    start: dt.datetime | None = None,
    roll_at: int = 300,
) -> pd.DataFrame:
    start = start or dt.datetime(2025, 1, 2, 9, 0, 0)
    rows = []
    price = 600.0
    for i in range(n):
        ts = start + dt.timedelta(minutes=5 * i)
        # mild uptrend with noise
        price += 0.05 + (0.02 if i % 7 == 0 else -0.01)
        underlying = "SHFE.au2506" if i < roll_at else "SHFE.au2508"
        rows.append(
            {
                "datetime": int(ts.timestamp() * 1_000_000_000),
                "open": price - 0.1,
                "high": price + 0.2,
                "low": price - 0.2,
                "close": price,
                "volume": 1000 + i,
                "open_oi": 100000,
                "close_oi": 100000,
                "underlying_symbol": underlying,
            }
        )
    return pd.DataFrame(rows)


def test_instruments_four_products() -> None:
    assert set(INSTRUMENTS) == {"au", "ag", "rb", "fg"}
    assert instrument_by_id("rb").signal_symbol == "KQ.m@SHFE.rb"
    assert instrument_by_id("fg").signal_symbol == "KQ.m@CZCE.FG"
    cost = cost_model_for(instrument_by_id("ag"))
    assert cost.multiplier == 15.0
    assert cost.tick_size == 1.0


def test_cache_merge_and_slice(tmp_path: Path) -> None:
    bars = _synthetic_bars(n=200, roll_at=150)
    merge_and_save("KQ.m@SHFE.au", bars.iloc[:120], root=tmp_path)
    merge_and_save("KQ.m@SHFE.au", bars.iloc[100:], root=tmp_path)
    loaded = load_bars("KQ.m@SHFE.au", root=tmp_path)
    assert len(loaded) == 200
    assert "underlying_symbol" in loaded.columns
    start = dt.date(2025, 1, 2)
    end = dt.date(2025, 1, 3)
    sliced = slice_bars(loaded, start=start, end=end, warmup_bars=50)
    assert not sliced.empty
    assert int(sliced["datetime"].iloc[-1]) >= int(
        dt.datetime.combine(start, dt.time.min).timestamp() * 1_000_000_000
    )


def test_slice_bars_gma_warmup_keeps_more_history_than_falcon() -> None:
    bars = _synthetic_bars(n=9000, roll_at=8000)
    start = dt.date(2025, 1, 30)
    end = dt.date(2025, 1, 31)
    falcon = slice_bars(bars, start=start, end=end, warmup_bars=400)
    gma = slice_bars(bars, start=start, end=end, warmup_bars=8000)
    assert len(gma) - len(falcon) >= 7000


def test_local_sim_roundtrip_pnl() -> None:
    cost = cost_model_for(instrument_by_id("au"))
    sim = LocalSimAccount(init_balance=1_000_000, cost=cost)
    sim.fill_to_target(symbol="SHFE.au2506", desired=1, signal_price=800.0)
    sim.mark("SHFE.au2506", 810.0)
    assert sim.net_pos("SHFE.au2506") == 1
    assert sim.equity() > sim.init_balance - 100  # MTM up minus fees
    sim.fill_to_target(symbol="SHFE.au2506", desired=0, signal_price=810.0)
    assert sim.net_pos("SHFE.au2506") == 0
    assert sim.realized_pnl > 0


def test_roll_flattens_before_switch() -> None:
    cost = cost_model_for(instrument_by_id("au"))
    sim = LocalSimAccount(init_balance=1_000_000, cost=cost)
    roll = RollStateMachine()
    sim.fill_to_target(symbol="SHFE.au2506", desired=1, signal_price=800.0)
    roll.detect("SHFE.au2506", "SHFE.au2508")
    roll.mark_flattening()
    sim.fill_to_target(
        symbol="SHFE.au2506",
        desired=0,
        signal_price=801.0,
        is_roll=True,
        regime="ROLL",
    )
    roll.on_old_position(sim.net_pos("SHFE.au2506"))
    assert sim.net_pos("SHFE.au2506") == 0
    assert roll.complete_switch() == "SHFE.au2508"
    assert any(f.is_roll for f in sim.fills)


def test_local_replay_runs_offline_on_fixture_like_bars() -> None:
    # Reuse Phase 0 fixture if present; else synthetic.
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "falcon_phase0" / "trend_up.csv"
    if fixture.is_file():
        bars = pd.read_csv(fixture)
        bars["underlying_symbol"] = "SHFE.au2506"
        # Force a mid-series roll to exercise roll path.
        mid = len(bars) // 2
        bars.loc[mid:, "underlying_symbol"] = "SHFE.au2508"
        start = dt.date(2025, 1, 27)
        end = dt.date(2025, 1, 29)
    else:
        bars = _synthetic_bars(n=450)
        start = dt.date(2025, 1, 2)
        end = dt.date(2025, 1, 5)

    out = run_local_falcon_backtest(
        signal_symbol="KQ.m@SHFE.au",
        start=start,
        end=end,
        init_balance=1_000_000,
        bars=bars,
        auto_download=False,
    )
    assert out["engine"] == "local"
    assert out["metrics"]["final_balance"] is not None
    assert "cost_model" in out
    assert out["reproducibility"]["engine"] == "local"
