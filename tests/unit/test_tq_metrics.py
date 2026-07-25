"""Unit tests: tqsdk-aligned trading day + equity metrics."""

from __future__ import annotations

import datetime as dt

from ignitequant.analytics.tq_metrics import (
    annual_yield_from_ror,
    equity_curve_metrics,
    sharpe_from_daily_balances,
)
from ignitequant.market.trading_day import trading_day_from_timestamp_ns


def _cst_ns(s: str) -> int:
    """Parse 'YYYY-MM-DD HH:MM:SS' as Asia/Shanghai wall time → ns."""
    naive = dt.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    aware = naive.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
    return int(aware.timestamp() * 1_000_000) * 1000


def test_trading_day_matches_tqsdk_night_session_weekend_roll() -> None:
    assert trading_day_from_timestamp_ns(_cst_ns("2025-01-02 09:00:00")) == dt.date(2025, 1, 2)
    assert trading_day_from_timestamp_ns(_cst_ns("2025-01-02 21:05:00")) == dt.date(2025, 1, 3)
    # Friday night / Saturday early → Monday trading day
    assert trading_day_from_timestamp_ns(_cst_ns("2025-01-03 21:05:00")) == dt.date(2025, 1, 6)
    assert trading_day_from_timestamp_ns(_cst_ns("2025-01-04 01:00:00")) == dt.date(2025, 1, 6)


def test_annual_yield_matches_tqsdk_formula() -> None:
    ror = 0.02502
    n = 37
    expected = (1.0 + ror) ** (250 / n) - 1.0
    assert annual_yield_from_ror(ror, n) == expected
    # Locked to the known TQ run deb266f400ed
    assert abs(expected - 0.18172332127952973) < 1e-12


def test_sharpe_from_tq_equity_curve_reproduces_reported() -> None:
    # First/last + day count from deb266f400ed; full curve not required for formula check —
    # verify population-std sharpe on a synthetic path that mirrors TQ init fill.
    balances = [1_000_000.0, 999_970.0, 1_005_640.0, 1_025_020.0]
    s = sharpe_from_daily_balances(balances, init_balance=1_000_000.0)
    assert s is not None
    # Same formula as tqsdk get_sharp on these yields
    yields = [
        balances[0] / 1_000_000.0 - 1.0,
        balances[1] / balances[0] - 1.0,
        balances[2] / balances[1] - 1.0,
        balances[3] / balances[2] - 1.0,
    ]
    import math

    mean = sum(yields) / len(yields)
    std = math.sqrt(sum((y - mean) ** 2 for y in yields) / len(yields))
    rf = (1.025) ** (1 / 250) - 1
    expect = math.sqrt(250) * (mean - rf) / std
    assert abs(s - expect) < 1e-12


def test_equity_curve_metrics_uses_settle_day_count() -> None:
    by_day = {
        "2025-01-01": 1_000_000.0,
        "2025-01-02": 1_010_000.0,
        "2025-01-03": 1_020_000.0,
    }
    m = equity_curve_metrics(by_day, init_balance=1_000_000.0)
    assert m["trading_days"] == 3
    assert abs(m["ror"] - 0.02) < 1e-12
    assert abs(m["annual_yield"] - ((1.02) ** (250 / 3) - 1.0)) < 1e-12
    assert m["sharpe"] is not None
