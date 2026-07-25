"""Exchange trading-day helpers aligned with tqsdk.datetime (CST, 18:00 cutoff)."""

from __future__ import annotations

import datetime as dt

# 1990-01-01 00:00:00+08 → unix ns used by tqsdk internal clocks
_BEGIN_MARK_NS = 631_123_200_000_000_000
_DAY_NS = 86_400_000_000_000
_AFTERNOON_CUTOFF_NS = 64_800_000_000_000  # 18:00 within the UTC+8 day
_CST = dt.timezone(dt.timedelta(hours=8))


def trading_day_from_timestamp_ns(timestamp_ns: int) -> dt.date:
    """Map a nanosecond timestamp to its SHFE/DCE-style trading day (tqsdk rule).

    - Times at/after 18:00 CST roll to the next calendar day before weekend adjust.
    - Sat/Sun roll forward to Monday.
    """
    ts = int(timestamp_ns)
    days = (ts - _BEGIN_MARK_NS) // _DAY_NS
    if (ts - _BEGIN_MARK_NS) % _DAY_NS >= _AFTERNOON_CUTOFF_NS:
        days += 1
    week_day = days % 7
    if week_day >= 5:
        days += 7 - week_day
    nano = _BEGIN_MARK_NS + days * _DAY_NS
    return dt.datetime.fromtimestamp(nano / 1_000_000_000, tz=_CST).date()


def trading_day_iso_from_timestamp_ns(timestamp_ns: int) -> str:
    return trading_day_from_timestamp_ns(timestamp_ns).isoformat()
