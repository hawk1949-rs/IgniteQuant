"""Performance metrics matching tqsdk ``TqReport`` / ``get_sharp`` formulas.

Source of truth:
- ``tqsdk.report.TqReport._get_account_stat_metrics``
- ``tqsdk.tafunc.get_sharp`` (population std, rf=2.5%, 250 trading days)
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

TRADING_DAYS_OF_YEAR = 250
RISK_FREE_ANNUAL = 0.025


def daily_yields(balances: Sequence[float], *, init_balance: float) -> list[float]:
    """Per-day returns with shift(fill_value=init_balance), same as TqReport."""
    if not balances:
        return []
    prev = float(init_balance)
    out: list[float] = []
    for bal in balances:
        if prev <= 0:
            return []
        cur = float(bal)
        out.append(cur / prev - 1.0)
        prev = cur
    return out


def annual_yield_from_ror(ror: float, n_days: int) -> float | None:
    """``(1+ror) ** (250 / n_days) - 1`` — tqsdk annual_yield."""
    if n_days <= 0:
        return None
    try:
        value = (1.0 + float(ror)) ** (TRADING_DAYS_OF_YEAR / float(n_days)) - 1.0
    except (OverflowError, ValueError):
        return None
    return _finite(value)


def sharpe_from_daily_yields(
    yields: Sequence[float],
    *,
    risk_free_annual: float = RISK_FREE_ANNUAL,
    trading_days_of_year: int = TRADING_DAYS_OF_YEAR,
) -> float | None:
    """Annualized Sharpe — tqsdk ``get_sharp`` (population stdev)."""
    if len(yields) < 1:
        return None
    mean = sum(yields) / len(yields)
    var = sum((y - mean) ** 2 for y in yields) / len(yields)
    std = math.sqrt(var)
    if std <= 1e-18:
        return None
    rf_daily = (1.0 + float(risk_free_annual)) ** (1.0 / trading_days_of_year) - 1.0
    return _finite(math.sqrt(trading_days_of_year) * (mean - rf_daily) / std)


def sharpe_from_daily_balances(
    balances: Sequence[float],
    *,
    init_balance: float,
    risk_free_annual: float = RISK_FREE_ANNUAL,
    trading_days_of_year: int = TRADING_DAYS_OF_YEAR,
) -> float | None:
    yields = daily_yields(balances, init_balance=init_balance)
    return sharpe_from_daily_yields(
        yields,
        risk_free_annual=risk_free_annual,
        trading_days_of_year=trading_days_of_year,
    )


def max_drawdown_from_balances(balances: Sequence[float]) -> float:
    """Peak-to-trough drawdown ratio — tqsdk ``drawdown.max()``."""
    if not balances:
        return 0.0
    peak = float(balances[0])
    max_dd = 0.0
    for bal in balances:
        cur = float(bal)
        peak = max(peak, cur)
        if peak > 0:
            max_dd = max(max_dd, (peak - cur) / peak)
    return max_dd


def equity_curve_metrics(
    balances_by_day: Mapping[str, float],
    *,
    init_balance: float,
) -> dict[str, Any]:
    """Core equity metrics from a day→balance map (sorted by day key)."""
    days = sorted(balances_by_day.keys())
    balances = [float(balances_by_day[d]) for d in days]
    final = balances[-1] if balances else float(init_balance)
    init = float(init_balance)
    ror = (final / init - 1.0) if init else 0.0
    n_days = len(balances)
    return {
        "init_balance": init,
        "final_balance": final,
        "ror": ror,
        "annual_yield": annual_yield_from_ror(ror, n_days),
        "max_drawdown": max_drawdown_from_balances(balances),
        "sharpe": sharpe_from_daily_balances(balances, init_balance=init),
        "trading_days": n_days,
    }


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None
