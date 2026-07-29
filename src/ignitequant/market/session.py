"""Domestic exchange session helpers (execution gate, not signal clock)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_CST = timezone(timedelta(hours=8))

# MarketSnapshot.trade_status values used by RiskEngine.
TRADE_STATUS_OPEN = "CONTINUOUS"
TRADE_STATUS_CLOSED = "CLOSED"


def shfe_precious_session_open(now: datetime | None = None) -> dict[str, Any]:
    """SHFE gold/silver session flag in Asia/Shanghai.

    Used for execution gating (MARKET_CLOSED) and cockpit display.
    """
    cst = now.astimezone(_CST) if now else datetime.now(_CST)
    wd = cst.weekday()  # Mon=0 … Sun=6
    hm = cst.hour * 100 + cst.minute
    # Night session crosses midnight: Fri 21:00 → Sat 02:30 still open.
    in_night = hm >= 2100 or hm < 230
    in_day = (900 <= hm < 1015) or (1030 <= hm < 1130) or (1330 <= hm < 1500)
    if wd == 5:  # Saturday
        open_now = hm < 230  # only leftover Friday night
    elif wd == 6:  # Sunday
        open_now = False
    elif wd == 0 and hm < 900:
        # Monday before day session: no Sunday night for SHFE au
        open_now = False
    else:
        open_now = in_day or in_night
    return {
        "open": open_now,
        "local_time": cst.strftime("%Y-%m-%d %H:%M:%S"),
        "label": "交易时段" if open_now else "非交易时段",
        "trade_status": TRADE_STATUS_OPEN if open_now else TRADE_STATUS_CLOSED,
        "note": None
        if open_now
        else "内盘休市：外盘信号可照常产生，成交门禁为 MARKET_CLOSED，持仓保留。",
    }


def trade_status_for_session(now: datetime | None = None) -> str:
    return str(shfe_precious_session_open(now)["trade_status"])


def is_session_open_at(ts_ns: int) -> bool:
    """Whether SHFE precious metals are open at a bar timestamp (ns since epoch)."""
    when = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=timezone.utc)
    return bool(shfe_precious_session_open(when)["open"])
