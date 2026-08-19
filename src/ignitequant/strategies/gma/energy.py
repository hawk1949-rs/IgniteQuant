"""GMA 2.0 energy distribution overlay (Volume Profile).

Maps the teaching PDF ``GMA指标-能量分布详解`` onto v1 10W templates:

- POC = highest-volume price (institution cost / magnet)
- VA = 70% value area, VAH / VAL = edges of that area
- 能量边缘 = session high / low of the profile window
- 成交量缺口 = histogram canyon (gap_high / gap_low)

v1 stays unchanged when ``energy_enabled`` is false.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum

import numpy as np

from ignitequant.strategies.gma.config import GMAIndicatorConfig
from ignitequant.strategies.gma.indicators import TenWState, VolumeProfile, near_level
from ignitequant.strategies.gma.regime import Alignment, AlignmentSnapshot
from ignitequant.strategies.gma.signal import GMASignal


class EnergyZone(str, Enum):
    ABOVE_VAH = "ABOVE_VAH"
    AT_VAH = "AT_VAH"
    IN_VALUE = "IN_VALUE"
    AT_POC = "AT_POC"
    AT_VAL = "AT_VAL"
    BELOW_VAL = "BELOW_VAL"
    UNKNOWN = "UNKNOWN"


def classify_energy_zone(
    price: float,
    vp: VolumeProfile,
    *,
    atr: float,
    near_pct: float,
) -> EnergyZone:
    if vp.poc is None or vp.vah is None or vp.val is None:
        return EnergyZone.UNKNOWN
    if not np.isfinite(price):
        return EnergyZone.UNKNOWN
    if near_level(price, vp.poc, pct=near_pct, atr=atr):
        return EnergyZone.AT_POC
    if near_level(price, vp.vah, pct=near_pct, atr=atr):
        return EnergyZone.AT_VAH
    if near_level(price, vp.val, pct=near_pct, atr=atr):
        return EnergyZone.AT_VAL
    if price > float(vp.vah):
        return EnergyZone.ABOVE_VAH
    if price < float(vp.val):
        return EnergyZone.BELOW_VAL
    return EnergyZone.IN_VALUE


def thin_extreme_divergence(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
) -> int:
    """Approximate 量价不结合: thin volume at a 5m extreme.

    Returns +1 (bullish at lows), -1 (bearish at highs), else 0.
    Tick-level consecutive identical prints are not available on 5m bars.
    """
    if len(close) < 8 or len(volume) < 8:
        return 0
    med = float(np.median(volume[-20:] if len(volume) >= 20 else volume))
    if not np.isfinite(med) or med <= 0:
        return 0
    recent = volume[-3:]
    if float(np.max(recent)) > 0.35 * med:
        return 0
    last = float(close[-1])
    if last <= float(np.min(low[-8:])) * 1.0008:
        return 1
    if last >= float(np.max(high[-8:])) * 0.9992:
        return -1
    return 0


def apply_energy_overlay(
    signal: GMASignal,
    *,
    vp: VolumeProfile,
    s5: TenWState,
    align: AlignmentSnapshot,
    current_target: int,
    high5: np.ndarray,
    low5: np.ndarray,
    close5: np.ndarray,
    volume5: np.ndarray,
    indicators: GMAIndicatorConfig,
) -> GMASignal:
    """Filter and add energy-based entries. Never overrides an explicit flatten."""
    if signal.desired == 0:
        return replace(signal, reasons=signal.reasons + ("ENERGY_KEEP_EXIT",))

    zone = classify_energy_zone(
        signal.close,
        vp,
        atr=signal.atr,
        near_pct=indicators.pullback_near_pct,
    )
    reasons = list(signal.reasons)
    reasons.append(f"ENERGY_{zone.value}")

    desired = signal.desired
    atr = float(signal.atr) if np.isfinite(signal.atr) else 0.0

    def _hold(code: str) -> GMASignal:
        return replace(signal, signal=0, desired=None, reasons=tuple(reasons + [code]))

    def _enter(direction: int, sig: int, code: str) -> GMASignal:
        return replace(
            signal,
            signal=sig if direction > 0 else -sig,
            desired=1 if direction > 0 else -1,
            reasons=tuple(reasons + [code]),
        )

    trend = align.alignment in {Alignment.DRIVE, Alignment.DIRECTION}
    rng = align.alignment is Alignment.RANGE
    d = int(align.direction)

    # 波段策略：10W 定方向后，多头只在 POC 及以下（VAL–能量边缘）进，空头对称。
    if current_target == 0 and desired is not None and desired > 0 and trend:
        if zone in {EnergyZone.ABOVE_VAH, EnergyZone.AT_VAH}:
            return _hold("ENERGY_BLOCK_CHASE")
        if vp.poc is not None and np.isfinite(signal.close) and signal.close > float(vp.poc) and zone is EnergyZone.IN_VALUE:
            if not near_level(signal.close, vp.poc, pct=indicators.pullback_near_pct, atr=atr):
                return _hold("ENERGY_BLOCK_CHASE")
    if current_target == 0 and desired is not None and desired < 0 and trend:
        if zone in {EnergyZone.BELOW_VAL, EnergyZone.AT_VAL}:
            return _hold("ENERGY_BLOCK_CHASE")
        if vp.poc is not None and np.isfinite(signal.close) and signal.close < float(vp.poc) and zone is EnergyZone.IN_VALUE:
            if not near_level(signal.close, vp.poc, pct=indicators.pullback_near_pct, atr=atr):
                return _hold("ENERGY_BLOCK_CHASE")

    # 震荡：抛离区（VA 外）才允许均值回归，价值区内的轨道单过滤掉。
    range_codes = {
        "ENTRY_RANGE_LOWER",
        "ENTRY_RANGE_UPPER",
        "ENTRY_RANGE_VAL",
        "ENTRY_RANGE_VAH",
    }
    if current_target == 0 and desired is not None and any(c in reasons for c in range_codes):
        if desired > 0 and zone not in {EnergyZone.BELOW_VAL, EnergyZone.AT_VAL}:
            return _hold("ENERGY_INSIDE_VA")
        if desired < 0 and zone not in {EnergyZone.ABOVE_VAH, EnergyZone.AT_VAH}:
            return _hold("ENERGY_INSIDE_VA")

    if desired is not None:
        return replace(signal, reasons=tuple(reasons + ["ENERGY_PASS"]))

    # HOLD → 能量补进场
    if current_target != 0:
        return replace(signal, reasons=tuple(reasons))

    # 回踩 POC（震荡之后的波段首枪）
    if trend and d != 0 and zone is EnergyZone.AT_POC:
        if (d > 0 and s5.fast_color > 0) or (d < 0 and s5.fast_color < 0):
            return _enter(d, 2, "ENTRY_ENERGY_POC")

    # 成交量缺口当阻力支撑
    if vp.gap_high is not None and near_level(signal.close, vp.gap_high, pct=indicators.pullback_near_pct, atr=atr):
        if rng or d <= 0 or s5.fast_color < 0:
            return _enter(-1, 2, "ENTRY_ENERGY_GAP")
    if vp.gap_low is not None and near_level(signal.close, vp.gap_low, pct=indicators.pullback_near_pct, atr=atr):
        if rng or d >= 0 or s5.fast_color > 0:
            return _enter(1, 2, "ENTRY_ENERGY_GAP")

    # 价值区外的震荡抛离（结合波动轨文档：VAH–边缘空，VAL–边缘多）
    if rng:
        if zone is EnergyZone.BELOW_VAL and s5.fast_color > 0:
            return _enter(1, 1, "ENTRY_ENERGY_VAL_EDGE")
        if zone is EnergyZone.ABOVE_VAH and s5.fast_color < 0:
            return _enter(-1, 1, "ENTRY_ENERGY_VAH_EDGE")

    thin = thin_extreme_divergence(high5, low5, close5, volume5)
    if thin > 0 and zone in {EnergyZone.BELOW_VAL, EnergyZone.AT_VAL, EnergyZone.AT_POC}:
        return _enter(1, 1, "ENTRY_ENERGY_THIN_VOL")
    if thin < 0 and zone in {EnergyZone.ABOVE_VAH, EnergyZone.AT_VAH, EnergyZone.AT_POC}:
        return _enter(-1, 1, "ENTRY_ENERGY_THIN_VOL")

    return replace(signal, reasons=tuple(reasons))
