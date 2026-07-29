"""Map overseas ATR onto a domestic fill price via relative volatility."""

from __future__ import annotations


def scale_atr_to_entry(
    atr_overseas: float,
    overseas_close: float,
    entry_price: float,
) -> float:
    """Convert overseas ATR to domestic price units: entry * (atr / close)."""
    if atr_overseas <= 0 or overseas_close <= 0 or entry_price <= 0:
        return 0.0
    if atr_overseas != atr_overseas or overseas_close != overseas_close:
        return 0.0
    return float(entry_price) * (float(atr_overseas) / float(overseas_close))


def relative_atr_fraction(atr: float, close: float) -> float:
    if atr <= 0 or close <= 0:
        return 0.0
    return float(atr) / float(close)
