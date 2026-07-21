"""Factor mining layer: pure modules over closed OHLCV only.

Main / runners must not embed indicator formulas. They call FactorModule.compute
and consume the returned Feature Dict. Write your own MA/ADX/filters here.
"""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

# Closed bar window: raw fields only (no precomputed MA/KDJ columns).
ClosedBars = Mapping[str, object]


@runtime_checkable
class FactorModule(Protocol):
    """Stateless factor logic. No account, position, or forming bars."""

    def compute(self, bars_by_tf: Mapping[str, ClosedBars]) -> Mapping[str, float]:
        """Return Feature Dict with keys you define."""
        ...


__all__ = ["ClosedBars", "FactorModule"]
