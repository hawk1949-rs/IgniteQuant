"""Overseas bar normalization + stop scaling."""

from __future__ import annotations

import pandas as pd

from ignitequant.execution.target_position import build_sl_tp
from ignitequant.market.overseas_bars import bars_dicts_to_dataframe
from ignitequant.portfolio.stop_scale import relative_atr_fraction, scale_atr_to_entry


def test_bars_dicts_to_dataframe_deterministic() -> None:
    bars = [
        {"time": 1_700_000_000, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 10},
        {"time": 1_700_000_300, "open": 1.5, "high": 2.5, "low": 1.0, "close": 2.0, "volume": 12},
    ]
    df = bars_dicts_to_dataframe(bars, underlying_symbol="GC=F")
    assert list(df.columns)[:5] == ["datetime", "open", "high", "low", "close"]
    assert int(df.iloc[0]["datetime"]) == 1_700_000_000 * 1_000_000_000
    assert float(df.iloc[-1]["close"]) == 2.0
    assert df.iloc[-1]["underlying_symbol"] == "GC=F"


def test_normalize_and_drop_forming() -> None:
    from ignitequant.market.overseas_bars import drop_forming_5m_bar, normalize_5m_bars

    t0 = 1_700_000_100 - (1_700_000_100 % 300)  # aligned 5m open
    raw = [
        {"time": t0, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 1},
        {"time": t0 + 100, "open": 1.5, "high": 2.2, "low": 1.4, "close": 2.0, "volume": 2},
        {"time": t0 + 300, "open": 2.0, "high": 2.5, "low": 1.8, "close": 2.1, "volume": 3},
    ]
    norm = normalize_5m_bars(raw)
    assert len(norm) == 2
    assert norm[0]["time"] == t0
    assert norm[0]["close"] == 2.0
    assert norm[1]["time"] == t0 + 300

    completed = drop_forming_5m_bar(norm, now=t0 + 300 + 60)
    assert len(completed) == 1
    assert completed[0]["time"] == t0
    done = drop_forming_5m_bar(norm, now=t0 + 300 + 301)
    assert len(done) == 2


def test_scale_atr_to_entry() -> None:
    # overseas atr=20 on close=2000 → 1%; domestic entry 600 → atr_dom=6
    scaled = scale_atr_to_entry(20.0, 2000.0, 600.0)
    assert abs(scaled - 6.0) < 1e-9
    assert relative_atr_fraction(20.0, 2000.0) == 0.01


def test_build_sl_tp_relative_mode() -> None:
    stop, take = build_sl_tp(
        1,
        fill_price=600.0,
        atr=20.0,
        sl_mult=1.3,
        tp_mult=2.3,
        overseas_close=2000.0,
    )
    assert stop is not None and take is not None
    # atr_dom = 6; stop = 600 - 1.3*6 = 592.2
    assert abs(stop - 592.2) < 1e-6
    assert abs(take - (600.0 + 2.3 * 6.0)) < 1e-6
