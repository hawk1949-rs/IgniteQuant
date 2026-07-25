"""行情状态：TREND_UP / TREND_DOWN / RANGE。"""

from __future__ import annotations

from enum import Enum

import numpy as np

from .indicators import IndicatorBundle


class Regime(str, Enum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"


def detect_regime(
    ind: IndicatorBundle,
    *,
    adx_threshold: float = 25.0,
) -> Regime:
    adx = ind.adx[-1]
    close = ind.close[-1]
    ma52_0 = ind.ma52[-1]
    ma52_1 = ind.ma52[-2]

    if any(np.isnan(x) for x in (adx, close, ma52_0, ma52_1)):
        return Regime.RANGE

    if adx < adx_threshold:
        return Regime.RANGE

    ma52_up = ma52_0 > ma52_1
    ma52_down = ma52_0 < ma52_1
    if close > ma52_0 and ma52_up:
        return Regime.TREND_UP
    if close < ma52_0 and ma52_down:
        return Regime.TREND_DOWN
    return Regime.RANGE
