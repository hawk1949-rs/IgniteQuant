"""Pure helpers for TargetPosTask align pricing / GFD day-end cancel."""

from __future__ import annotations

import math

_GFD_DAY_END_MSG = "交易日结束，自动撤销当日有效的委托单"


def is_gfd_day_end_cancel(exc: BaseException) -> bool:
    """True when TqSim cancels a GFD order at settle and TargetPosTask raises 错单."""
    msg = str(exc)
    return _GFD_DAY_END_MSG in msg or ("遇到错单" in msg and "GFD" in msg)


def align_limit_price(
    direction: str,
    *,
    pinned_last: float | None,
    tick: float,
    ask: float | None,
    bid: float | None,
    last: float | None,
    urgency: str = "NORMAL",
    chase_ticks: int = 0,
) -> float:
    """Limit that prefers decision open±tick but always crosses the book when possible.

    TqSim fills BUY only when ``limit >= ask`` (trade price = limit). A hard pin at
    open±tick that never updates leaves GFD orders alive until settle, and
    TargetPosTask treats the day-end cancel as a fatal 错单. Prefer the pin when it
    is already marketable; otherwise chase ask/bid so the order fills in-session.

    ``urgency=HIGH`` (exits / resync) chases several ticks through the book so the
    domestic leg fills quickly after an overseas signal trigger.
    """
    ref = pinned_last if pinned_last is not None else last
    if ref is None or not math.isfinite(float(ref)):
        ref = 0.0
    ref = float(ref)
    tick = float(tick)
    urg = str(urgency or "NORMAL").upper()
    extra = int(chase_ticks)
    if urg == "HIGH" and extra <= 0:
        extra = 3
    d = direction.upper()
    if d == "BUY":
        pinned = ref + tick
        if ask is not None and math.isfinite(float(ask)):
            return max(pinned, float(ask) + extra * tick)
        return pinned + extra * tick
    pinned = ref - tick
    if bid is not None and math.isfinite(float(bid)):
        return min(pinned, float(bid) - extra * tick)
    return pinned - extra * tick
