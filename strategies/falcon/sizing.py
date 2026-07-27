"""按信号强弱映射目标手数。

手数刻度兼顾资金利用率与风险度：
- 初始资金 100 万、沪金单手保证金约 4 万时，
  最大 1 手峰值风险度约 4%（与原 2000 万 / 20 手同量级）。
- 该「约 4 万」是早年天勤模拟/文档校准值；交易所实盘保证金率会随政策变化
  （例如 au 常见约 12%–16%+），不得当作当前交易所官方保证金。
- 若要整体再放大/缩小，可改 LOT_SCALE（作用于下方基准手数）。
"""

from __future__ import annotations

from .regime import Regime

# 相对基准手数的整体缩放（1 = 使用 BASE 原值）
LOT_SCALE = 1

# |signal| -> 基准手数（按 100 万账户校准；原 2000 万版为 {5,12,20}）
_BASE_LOTS = {1: 1, 2: 1, 3: 1}

LOT_BY_SIGNAL = {k: int(v * LOT_SCALE) for k, v in _BASE_LOTS.items()}


def lots_from_signal(
    signal: int,
    regime: Regime,
    *,
    lot_by_signal: dict[int, int] | None = None,
) -> int | None:
    """返回目标净持仓；None = 本根不因信号改仓。

    - signal==0：None
    - RANGE：忽略开仓信号（None）
    - 与趋势冲突：None
    """
    if signal == 0:
        return None

    strength = abs(int(signal))
    mapping = lot_by_signal if lot_by_signal is not None else LOT_BY_SIGNAL
    lots = mapping.get(strength)
    if lots is None:
        return None

    signed = lots if signal > 0 else -lots

    if regime == Regime.RANGE:
        return None
    if regime == Regime.TREND_UP and signed < 0:
        return None
    if regime == Regime.TREND_DOWN and signed > 0:
        return None

    return signed
