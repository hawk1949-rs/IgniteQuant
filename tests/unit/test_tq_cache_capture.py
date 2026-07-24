"""Tests for Tq-aligned cache capture and local decision windows."""

from __future__ import annotations

import pandas as pd

from ignitequant.engine.local_replay import _tq_datetime_change_window
from ignitequant.market.download import upsert_completed_and_stub


def test_upsert_finalizes_previous_bar_with_full_ohlc() -> None:
    by_dt: dict[int, dict] = {}
    # First event: only stub bar A
    k1 = pd.DataFrame(
        [
            {
                "datetime": 100,
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 0,
                "open_oi": 0,
                "close_oi": 0,
            }
        ]
    )
    upsert_completed_and_stub(by_dt, k1, underlying="SHFE.au2502")
    assert by_dt[100]["volume"] == 0.0

    # Second event: A completed + B stub
    k2 = pd.DataFrame(
        [
            {
                "datetime": 100,
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 100,
                "open_oi": 1,
                "close_oi": 1,
            },
            {
                "datetime": 200,
                "open": 10.5,
                "high": 10.5,
                "low": 10.5,
                "close": 10.5,
                "volume": 0,
                "open_oi": 1,
                "close_oi": 1,
            },
        ]
    )
    upsert_completed_and_stub(by_dt, k2, underlying="SHFE.au2502")
    assert by_dt[100]["high"] == 11.0
    assert by_dt[100]["low"] == 9.5
    assert by_dt[100]["close"] == 10.5
    assert by_dt[100]["volume"] == 100.0
    assert by_dt[200]["volume"] == 0.0
    assert by_dt[200]["high"] == by_dt[200]["open"]


def test_coverage_ok_requires_reaching_end() -> None:
    from ignitequant.market.cache import coverage_ok
    import datetime as dt

    start = dt.datetime(2025, 1, 2, 9, 0, 0)
    rows = []
    for i in range(20):
        ts = start + dt.timedelta(days=i)
        rows.append(
            {
                "datetime": int(ts.timestamp() * 1_000_000_000),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 10,
                "open_oi": 0,
                "close_oi": 0,
                "underlying_symbol": "SHFE.au2506",
            }
        )
    bars = pd.DataFrame(rows)
    assert coverage_ok(bars, start=dt.date(2025, 1, 2), end=dt.date(2025, 1, 10), max_end_gap_days=3)
    # Truncated cache with no bars after end → still missing
    assert not coverage_ok(
        bars, start=dt.date(2025, 1, 2), end=dt.date(2025, 2, 28), max_end_gap_days=3
    )


def test_coverage_ok_allows_holiday_gap_when_later_bars_exist() -> None:
    """CNY-style gap: last January session 1/27, February already cached."""
    from ignitequant.market.cache import coverage_ok
    import datetime as dt

    rows = []
    for day in (2, 10, 20, 27):
        ts = dt.datetime(2025, 1, day, 15, 0, 0)
        rows.append(
            {
                "datetime": int(ts.timestamp() * 1_000_000_000),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 10,
                "open_oi": 0,
                "close_oi": 0,
                "underlying_symbol": "SHFE.au2506",
            }
        )
    # Feb session after CNY
    rows.append(
        {
            "datetime": int(dt.datetime(2025, 2, 5, 9, 0, 0).timestamp() * 1_000_000_000),
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 10,
            "open_oi": 0,
            "close_oi": 0,
            "underlying_symbol": "SHFE.au2506",
        }
    )
    bars = pd.DataFrame(rows)
    assert coverage_ok(bars, start=dt.date(2025, 1, 1), end=dt.date(2025, 1, 31), max_end_gap_days=3)
    # Without later bars, January ending 1/27 fails calendar end check
    assert not coverage_ok(
        bars.iloc[:-1], start=dt.date(2025, 1, 1), end=dt.date(2025, 1, 31), max_end_gap_days=3
    )


def test_coverage_ok_rejects_months_later_resume() -> None:
    """Broken cache: Jan–Feb present, hole through Oct, Nov+ still on disk."""
    from ignitequant.market.cache import coverage_ok
    import datetime as dt

    rows = []
    for day in (2, 15, 28):
        ts = dt.datetime(2025, 2, day, 15, 0, 0)
        rows.append(
            {
                "datetime": int(ts.timestamp() * 1_000_000_000),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": 10,
                "open_oi": 0,
                "close_oi": 0,
                "underlying_symbol": "SHFE.au2504",
            }
        )
    # Months later — must NOT satisfy Mar 31 coverage
    rows.append(
        {
            "datetime": int(dt.datetime(2025, 11, 3, 9, 0, 0).timestamp() * 1_000_000_000),
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "volume": 10,
            "open_oi": 0,
            "close_oi": 0,
            "underlying_symbol": "SHFE.au2512",
        }
    )
    bars = pd.DataFrame(rows)
    assert not coverage_ok(
        bars, start=dt.date(2025, 1, 1), end=dt.date(2025, 3, 31), max_end_gap_days=3
    )


def test_tq_datetime_change_window_stubs_last_bar() -> None:
    bars = pd.DataFrame(
        [
            {
                "datetime": 100,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 50,
            },
            {
                "datetime": 200,
                "open": 10.5,
                "high": 12.0,
                "low": 10.0,
                "close": 11.0,
                "volume": 80,
            },
        ]
    )
    window = _tq_datetime_change_window(bars, 1, 400)
    assert float(window.iloc[0]["high"]) == 11.0
    assert float(window.iloc[-1]["open"]) == 10.5
    assert float(window.iloc[-1]["high"]) == 10.5
    assert float(window.iloc[-1]["low"]) == 10.5
    assert float(window.iloc[-1]["close"]) == 10.5
    assert float(window.iloc[-1]["volume"]) == 0.0
