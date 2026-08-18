"""GMA multi-timeframe alignment: 三级一致 / 两级一致 / 震荡."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ignitequant.domain.enums import Regime
from ignitequant.strategies.gma.indicators import TenWState


class Alignment(str, Enum):
    DRIVE = "DRIVE"  # 三级一致驱动浪
    DIRECTION = "DIRECTION"  # 两级一致有方向
    RANGE = "RANGE"  # 上下级不一致震荡


@dataclass(frozen=True)
class AlignmentSnapshot:
    alignment: Alignment
    direction: int  # +1 long, -1 short, 0 none
    regime: Regime
    m15: TenWState
    h1: TenWState
    h4: TenWState
    drive_15_1_4: bool
    direction_1_4: bool
    conflict_1_4: bool
    reason: str


def _dir_of(state: TenWState) -> int:
    if state.fast_color > 0 and state.slow_color > 0:
        return 1
    if state.fast_color < 0 and state.slow_color < 0:
        return -1
    return 0


def _confirmed_dir(state: TenWState) -> int:
    if not state.single_drive:
        return 0
    return 1 if state.fast_above_slow else -1


def classify_alignment(m15: TenWState, h1: TenWState, h4: TenWState) -> AlignmentSnapshot:
    d15 = _dir_of(m15)
    d1 = _dir_of(h1)
    d4 = _dir_of(h4)
    c15 = _confirmed_dir(m15)
    c1 = _confirmed_dir(h1)
    c4 = _confirmed_dir(h4)

    drive = d15 != 0 and d15 == d1 == d4 and c15 == c1 == c4 == d15
    direction = (not drive) and d1 != 0 and d1 == d4
    conflict = h1.single_conflict or h4.single_conflict or (d1 != 0 and d4 != 0 and d1 != d4)

    if drive:
        alignment = Alignment.DRIVE
        direction_i = d4
        regime = Regime.TREND_UP if d4 > 0 else Regime.TREND_DOWN
        reason = "ALIGN_DRIVE"
    elif direction:
        alignment = Alignment.DIRECTION
        direction_i = d4
        regime = Regime.TREND_UP if d4 > 0 else Regime.TREND_DOWN
        reason = "ALIGN_DIRECTION"
    else:
        alignment = Alignment.RANGE
        direction_i = 0
        regime = Regime.RANGE
        reason = "ALIGN_RANGE"

    return AlignmentSnapshot(
        alignment=alignment,
        direction=direction_i,
        regime=regime,
        m15=m15,
        h1=h1,
        h4=h4,
        drive_15_1_4=drive,
        direction_1_4=direction,
        conflict_1_4=conflict,
        reason=reason,
    )
