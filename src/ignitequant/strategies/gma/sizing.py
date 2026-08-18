"""Map GMA integer signal to target lots. HOLD=None, FLAT=0."""

from __future__ import annotations

from typing import Mapping


def lots_from_gma_signal(
    signal: int,
    *,
    lot_by_signal: Mapping[int, int],
    max_lots: int = 2,
) -> int | None:
    """``signal==0`` means HOLD (None), not flatten."""
    if signal == 0:
        return None
    strength = abs(int(signal))
    lots = int(lot_by_signal.get(strength, lot_by_signal.get(1, 1)))
    lots = max(0, min(lots, int(max_lots)))
    if lots <= 0:
        return None
    return lots if signal > 0 else -lots


def apply_hold_flat_and_no_flip(
    *,
    sizing_lots: int | None,
    explicit_flat: bool,
    current_target: int,
) -> int | None:
    """HOLD vs FLAT, and never reverse through a non-zero target."""
    if explicit_flat:
        return 0
    if sizing_lots is None:
        return None
    if current_target > 0 and sizing_lots < 0:
        return 0
    if current_target < 0 and sizing_lots > 0:
        return 0
    if current_target != 0 and (sizing_lots * current_target) > 0:
        # same direction: never shrink on a weaker continuation signal
        if abs(sizing_lots) < abs(current_target):
            return None
    return sizing_lots
