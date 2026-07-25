"""多指标信号评分：格兰维尔 + 成交量 + KDJ → [-3, 3]。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .indicators import IndicatorBundle


NEAR_MA_PCT = 0.002
VOL_SPIKE_RATIO = 1.2
KDJ_OVERBUY = 80.0
KDJ_OVERSELL = 20.0


@dataclass
class ScoreDetail:
    signal: int
    granville: int
    volume: int
    kdj: int
    conflict_penalty: int

    @property
    def parts(self) -> str:
        return (
            f"gv={self.granville} vol={self.volume} kdj={self.kdj} "
            f"pen={self.conflict_penalty} => {self.signal}"
        )


def _near(a: float, b: float, pct: float = NEAR_MA_PCT) -> bool:
    if b == 0 or np.isnan(a) or np.isnan(b):
        return False
    return abs(a - b) / abs(b) <= pct


def _granville_score(ind: IndicatorBundle) -> int:
    c0, c1 = ind.close[-1], ind.close[-2]
    f0, f1 = ind.ma7[-1], ind.ma7[-2]
    m0 = ind.ma14[-1]
    s0, s1, s2 = ind.ma52[-1], ind.ma52[-2], ind.ma52[-3]
    if any(np.isnan(x) for x in (c0, c1, f0, f1, m0, s0, s1, s2)):
        return 0

    ma52_turn_up = s1 <= s2 and s0 > s1
    ma52_turn_down = s1 >= s2 and s0 < s1
    cross_up_ma52 = c1 <= s1 and c0 > s0
    cross_down_ma52 = c1 >= s1 and c0 < s0
    pullback_hold = c0 > s0 and _near(min(c0, c1), s0) and c0 > c1
    bounce_fail = c0 < s0 and _near(max(c0, c1), s0) and c0 < c1
    bull_align = f0 > m0 > s0
    bear_align = f0 < m0 < s0
    reclaim_ma7 = c1 <= f1 and c0 > f0
    lose_ma7 = c1 >= f1 and c0 < f0

    bull = 0
    bear = 0

    if ma52_turn_up and cross_up_ma52 and f0 > m0:
        bull += 1
    elif pullback_hold and f0 > m0:
        bull += 1
    elif bull_align and reclaim_ma7:
        bull += 1

    if ma52_turn_down and cross_down_ma52 and f0 < m0:
        bear += 1
    elif bounce_fail and f0 < m0:
        bear += 1
    elif bear_align and lose_ma7:
        bear += 1

    if bull > 0 and bull_align:
        bull += 1
    if bear > 0 and bear_align:
        bear += 1

    if bull > 0 and bear > 0:
        return 0
    if bull > 0:
        return min(bull, 2)
    if bear > 0:
        return -min(bear, 2)
    return 0


def _volume_score(ind: IndicatorBundle, direction: int) -> int:
    if direction == 0:
        return 0
    v0, vma = ind.volume[-1], ind.vol_ma[-1]
    if np.isnan(v0) or np.isnan(vma) or vma <= 0:
        return 0
    if v0 > vma * VOL_SPIKE_RATIO:
        return 1 if direction > 0 else -1
    return 0


def _kdj_score(ind: IndicatorBundle) -> int:
    k0, k1 = ind.k[-1], ind.k[-2]
    d0, d1 = ind.d[-1], ind.d[-2]
    j0 = ind.j[-1]
    if any(np.isnan(x) for x in (k0, k1, d0, d1, j0)):
        return 0

    cross_up = k1 <= d1 and k0 > d0
    cross_down = k1 >= d1 and k0 < d0

    if cross_up and j0 < KDJ_OVERBUY:
        return 1
    if cross_down and j0 > KDJ_OVERSELL:
        return -1
    return 0


def score_signal(ind: IndicatorBundle) -> ScoreDetail:
    gv = _granville_score(ind)
    kdj = _kdj_score(ind)

    direction = 0
    if gv > 0:
        direction = 1
    elif gv < 0:
        direction = -1
    elif kdj != 0:
        direction = 1 if kdj > 0 else -1

    vol = _volume_score(ind, direction)

    conflict_penalty = 0
    if gv > 0 and kdj < 0:
        conflict_penalty = -1
    elif gv < 0 and kdj > 0:
        conflict_penalty = 1

    raw = gv + vol + kdj + conflict_penalty
    signal = int(np.clip(raw, -3, 3))
    return ScoreDetail(
        signal=signal,
        granville=gv,
        volume=vol,
        kdj=kdj,
        conflict_penalty=conflict_penalty,
    )
