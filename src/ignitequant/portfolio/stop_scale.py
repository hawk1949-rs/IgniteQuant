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


def map_fill_to_signal_price(
    fill_price: float,
    *,
    domestic_mark: float | None,
    overseas_close: float | None,
    ratio_tol: float = 0.05,
) -> float:
    """Map a domestic fill into overseas signal space for ``risk.check``.

    Live sim and local replay arm SL/TP in the same units as the decision
    window high/low (XAUUSD). Without this remap, a ~2900 overseas high
    immediately hits a ~680 yuan stop.
    """
    fill = float(fill_price)
    if (
        overseas_close is not None
        and overseas_close > 0
        and domestic_mark is not None
        and domestic_mark > 0
        and abs(float(overseas_close) / float(domestic_mark) - 1.0) > float(ratio_tol)
    ):
        return fill * (float(overseas_close) / float(domestic_mark))
    return fill


def relative_atr_fraction(atr: float, close: float) -> float:
    if atr <= 0 or close <= 0:
        return 0.0
    return float(atr) / float(close)
