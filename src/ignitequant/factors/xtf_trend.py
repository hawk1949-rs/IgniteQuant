"""Example shell: cross-timeframe trend bias — you own the formula.

Use only the last *closed* 60m bar when aligning to 5m (no future function).
"""

from __future__ import annotations

from typing import Mapping

from ignitequant.factors import ClosedBars


def compute(bars_by_tf: Mapping[str, ClosedBars]) -> Mapping[str, float]:
    _ = bars_by_tf.get("5m")
    _ = bars_by_tf.get("60m")
    # TODO: own Granville / ADX / price-action code here — do not call a locked preset.
    return {
        "trend_bias_60m": 0.0,
        "price_behavior_5m": 0.0,
    }
