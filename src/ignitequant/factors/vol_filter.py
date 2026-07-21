"""Example shell: volatility filter — implement your own windows/thresholds.

This file is intentionally NOT a pre-tuned indicator. Replace the body with
your hypothesis code. Pipeline input is closed OHLCV only.
"""

from __future__ import annotations

from typing import Mapping

from ignitequant.factors import ClosedBars


def compute(bars_by_tf: Mapping[str, ClosedBars]) -> Mapping[str, float]:
    """Return Feature Dict. Keys match the lab module registration."""
    _ = bars_by_tf.get("5m")
    # TODO: read close/high/low/volume from closed bars; write your ratio logic.
    return {
        "vol_ratio": 0.0,
        "vol_regime": 0.0,
    }
