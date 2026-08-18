"""GMA signal templates: drive / pullback / range / acceleration / exits."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ignitequant.strategies.gma.config import GMAIndicatorConfig
from ignitequant.strategies.gma.indicators import (
    TenWState,
    is_accelerating,
    keltner_channel,
    last_valid,
    near_level,
    stochastic,
    tenw_state,
    volume_profile,
)
from ignitequant.strategies.gma.regime import Alignment, AlignmentSnapshot, classify_alignment
from ignitequant.strategies.gma.resample import resample_bundle


@dataclass(frozen=True)
class GMASignal:
    signal: int
    desired: int | None
    reasons: tuple[str, ...]
    close: float
    atr: float
    alignment: Alignment
    regime_direction: int
    m15_fast: float | None
    m15_slow: float | None
    h1_mid: float | None
    poc: float | None
    vah: float | None
    val: float | None


def _tf_ready(state: TenWState) -> bool:
    return state.fast is not None and state.slow is not None and state.fast_color != 0 and state.slow_color != 0


def _cross_ok(state: TenWState, direction: int) -> bool:
    if direction > 0:
        return state.golden_cross and state.single_drive
    if direction < 0:
        return state.death_cross and state.single_drive
    return False


def _broke_extreme(high: np.ndarray, low: np.ndarray, close: np.ndarray, direction: int, lookback: int) -> bool:
    if len(close) < lookback + 1:
        return False
    if direction > 0:
        prior = float(np.max(high[-lookback - 1 : -1]))
        return float(close[-1]) > prior
    prior = float(np.min(low[-lookback - 1 : -1]))
    return float(close[-1]) < prior


def _keltner_pack(df, length: int, times_atr: float):
    high = df.high.to_numpy(dtype=float)
    low = df.low.to_numpy(dtype=float)
    close = df.close.to_numpy(dtype=float)
    return keltner_channel(high, low, close, length=length, times_atr=times_atr) + (
        high,
        low,
        close,
    )


def generate_signal(
    bars_5m,
    *,
    indicators: GMAIndicatorConfig,
    current_target: int,
) -> GMASignal:
    bundle = resample_bundle(bars_5m)
    m5 = bundle["5m"]
    m15 = bundle["15m"]
    m30 = bundle["30m"]
    h1 = bundle["1h"]
    h4 = bundle["4h"]

    close5 = m5.close.to_numpy(dtype=float) if not m5.empty else np.array([])
    high5 = m5.high.to_numpy(dtype=float) if not m5.empty else np.array([])
    low5 = m5.low.to_numpy(dtype=float) if not m5.empty else np.array([])
    last_close = float(close5[-1]) if len(close5) else float("nan")

    if m15.empty or h1.empty or h4.empty or len(close5) < 8:
        return GMASignal(
            0, None, ("FACTOR_NOT_READY",), last_close, 0.0, Alignment.RANGE, 0,
            None, None, None, None, None, None,
        )

    s15 = tenw_state(m15.close.to_numpy(dtype=float), fast_period=indicators.fast_period, slow_period=indicators.slow_period)
    s1 = tenw_state(h1.close.to_numpy(dtype=float), fast_period=indicators.fast_period, slow_period=indicators.slow_period)
    s4 = tenw_state(h4.close.to_numpy(dtype=float), fast_period=indicators.fast_period, slow_period=indicators.slow_period)
    s5 = tenw_state(close5, fast_period=indicators.fast_period, slow_period=indicators.slow_period)
    if not (_tf_ready(s15) and _tf_ready(s1) and _tf_ready(s4)):
        return GMASignal(
            0, None, ("FACTOR_NOT_READY", "HTF_WARMING_UP"), last_close, 0.0, Alignment.RANGE, 0,
            s15.fast, s15.slow, None, None, None, None,
        )

    align = classify_alignment(s15, s1, s4)

    _mid15, _up15, _lo15, atr15, _hi15, _lw15, c15 = _keltner_pack(
        m15, indicators.keltner_length, indicators.keltner_inner_atr
    )
    mid1, up1, lo1, atr1, _hi1, _lw1, c1 = _keltner_pack(
        h1, indicators.keltner_length, indicators.keltner_inner_atr
    )
    atr = float(atr1[-1]) if np.isfinite(atr1[-1]) else float(atr15[-1] if np.isfinite(atr15[-1]) else 0.0)

    def _accel(df) -> tuple[bool, bool]:
        if df.empty or len(df) < 8:
            return False, False
        mid, *_rest, atr_k = keltner_channel(
            df.high.to_numpy(dtype=float),
            df.low.to_numpy(dtype=float),
            df.close.to_numpy(dtype=float),
            length=indicators.accel_length,
            times_atr=indicators.accel_atr,
        )
        k_stoch, _ = stochastic(
            df.high.to_numpy(dtype=float),
            df.low.to_numpy(dtype=float),
            df.close.to_numpy(dtype=float),
            k_period=indicators.stoch_k,
            d_period=indicators.stoch_d,
            slowing=indicators.stoch_slowing,
        )
        del atr_k
        return is_accelerating(
            df.close.to_numpy(dtype=float),
            mid,
            k_stoch,
            overbought=indicators.stoch_overbought,
            oversold=indicators.stoch_oversold,
        )

    a30u, a30d = _accel(m30)
    a1u, a1d = _accel(h1)
    a4u, a4d = _accel(h4)
    accel_up_n = int(a30u) + int(a1u) + int(a4u)
    accel_dn_n = int(a30d) + int(a1d) + int(a4d)
    accel_any = accel_up_n + accel_dn_n > 0

    vp = volume_profile(
        m15.high.to_numpy(dtype=float)[-indicators.vp_lookback_15m :],
        m15.low.to_numpy(dtype=float)[-indicators.vp_lookback_15m :],
        m15.close.to_numpy(dtype=float)[-indicators.vp_lookback_15m :],
        m15.volume.to_numpy(dtype=float)[-indicators.vp_lookback_15m :],
        bins=indicators.vp_bins,
        value_pct=indicators.vp_value_pct,
    )

    h4_fast = s4.fast
    bias_long = False
    bias_short = False
    if h4_fast is not None and atr > 0 and len(h4):
        dist_up = float(h4.high.iloc[-1]) - h4_fast
        dist_dn = h4_fast - float(h4.low.iloc[-1])
        limit = indicators.bias_atr_mult * float(np.nanmax(atr_series_safe(h4, indicators.keltner_length)))
        bias_long = dist_up >= limit
        bias_short = dist_dn >= limit

    reasons: list[str] = [align.reason]
    signal = 0
    desired: int | None = None

    # 乖离：不反向，也不在极端乖离处追新仓
    if align.direction > 0 and bias_long:
        reasons.append("BIAS_LONG")
    if align.direction < 0 and bias_short:
        reasons.append("BIAS_SHORT")

    def _enter(direction: int, strength: int, code: str) -> None:
        nonlocal signal, desired
        if direction == 0:
            return
        if direction > 0 and "BIAS_LONG" in reasons:
            reasons.append("ENTRY_BLOCKED_BIAS")
            return
        if direction < 0 and "BIAS_SHORT" in reasons:
            reasons.append("ENTRY_BLOCKED_BIAS")
            return
        signal = strength if direction > 0 else -strength
        desired = 1 if direction > 0 else -1
        reasons.append(code)

    # Exit: opposite two-level / drive
    if current_target > 0 and align.direction < 0 and align.alignment in {Alignment.DRIVE, Alignment.DIRECTION}:
        desired = 0
        signal = -2
        reasons.append("EXIT_REGIME_FLIP")
        return _pack(signal, desired, reasons, last_close, atr, align, s15, mid1, vp)
    if current_target < 0 and align.direction > 0 and align.alignment in {Alignment.DRIVE, Alignment.DIRECTION}:
        desired = 0
        signal = 2
        reasons.append("EXIT_REGIME_FLIP")
        return _pack(signal, desired, reasons, last_close, atr, align, s15, mid1, vp)

    # Template A — 三级一致驱动浪
    if align.alignment is Alignment.DRIVE and current_target == 0:
        d = align.direction
        valid_cross = _cross_ok(s15, d) or _cross_ok(s1, d)
        broke = _broke_extreme(
            m15.high.to_numpy(dtype=float),
            m15.low.to_numpy(dtype=float),
            m15.close.to_numpy(dtype=float),
            d,
            indicators.breakout_lookback,
        )
        if valid_cross and broke:
            _enter(d, 3, "ENTRY_DRIVE_BREAK")
        elif valid_cross:
            _enter(d, 2, "ENTRY_DRIVE_CROSS")

    # Template D — 多周期加速（优先于普通回踩加仓）
    if desired is None and current_target == 0:
        if accel_up_n >= 2 and s5.fast_color > 0 and near_level(
            last_close, s15.fast, pct=indicators.pullback_near_pct, atr=atr
        ):
            _enter(1, 3, "ENTRY_ACCEL_MULTI")
        elif accel_dn_n >= 2 and s5.fast_color < 0 and near_level(
            last_close, s15.fast, pct=indicators.pullback_near_pct, atr=atr
        ):
            _enter(-1, 3, "ENTRY_ACCEL_MULTI")
        elif accel_up_n == 1 and s5.fast_color > 0 and near_level(
            last_close, last_valid(mid1), pct=indicators.pullback_near_pct, atr=atr
        ):
            _enter(1, 2, "ENTRY_ACCEL_SINGLE")
        elif accel_dn_n == 1 and s5.fast_color < 0 and near_level(
            last_close, last_valid(mid1), pct=indicators.pullback_near_pct, atr=atr
        ):
            _enter(-1, 2, "ENTRY_ACCEL_SINGLE")

    # Template B — 两级一致回踩
    if desired is None and align.alignment is Alignment.DIRECTION and current_target == 0:
        d = align.direction
        pulled_15_slow = near_level(float(c15[-1]), s15.slow, pct=indicators.pullback_near_pct, atr=atr)
        pulled_1_fast = near_level(float(c1[-1]), s1.fast, pct=indicators.pullback_near_pct, atr=atr)
        hold_15 = (d > 0 and float(c15[-1]) >= float(s15.slow or c15[-1])) or (
            d < 0 and float(c15[-1]) <= float(s15.slow or c15[-1])
        )
        hold_1 = (d > 0 and float(c1[-1]) >= float(s1.fast or c1[-1])) or (
            d < 0 and float(c1[-1]) <= float(s1.fast or c1[-1])
        )
        confirm = (d > 0 and s5.fast_color > 0) or (d < 0 and s5.fast_color < 0)
        if confirm and ((pulled_15_slow and hold_15) or (pulled_1_fast and hold_1)):
            _enter(d, 2, "ENTRY_PULLBACK")

    # 趋势中期：已持仓，慢线确认加仓（变色龙第二笔）
    if desired is None and current_target != 0 and align.alignment in {Alignment.DRIVE, Alignment.DIRECTION}:
        if current_target > 0 and s1.slow_color > 0 and s5.fast_color > 0 and abs(current_target) < 2:
            signal = 3
            desired = 2
            reasons.append("ADD_SLOW_CONFIRM")
        elif current_target < 0 and s1.slow_color < 0 and s5.fast_color < 0 and abs(current_target) < 2:
            signal = -3
            desired = -2
            reasons.append("ADD_SLOW_CONFIRM")

    # Template C — 震荡：1H 波动轨高空低多（无加速）
    if desired is None and align.alignment is Alignment.RANGE and current_target == 0 and not accel_any:
        c1_last = float(c1[-1])
        lo_last = float(lo1[-1])
        up_last = float(up1[-1])
        if np.isfinite(lo_last) and c1_last <= lo_last and last_close > lo_last:
            _enter(1, 1, "ENTRY_RANGE_LOWER")
        elif np.isfinite(up_last) and c1_last >= up_last and last_close < up_last:
            _enter(-1, 1, "ENTRY_RANGE_UPPER")
        elif vp.val is not None and s5.fast_color > 0 and near_level(
            last_close, vp.val, pct=indicators.pullback_near_pct, atr=atr
        ):
            _enter(1, 1, "ENTRY_RANGE_VAL")
        elif vp.vah is not None and s5.fast_color < 0 and near_level(
            last_close, vp.vah, pct=indicators.pullback_near_pct, atr=atr
        ):
            _enter(-1, 1, "ENTRY_RANGE_VAH")

    if desired is None:
        reasons.append("HOLD")

    return _pack(signal, desired, reasons, last_close, atr, align, s15, mid1, vp)


def atr_series_safe(df, period: int) -> float:
    from ignitequant.strategies.gma.indicators import atr_series

    if df.empty:
        return 0.0
    atr = atr_series(
        df.high.to_numpy(dtype=float),
        df.low.to_numpy(dtype=float),
        df.close.to_numpy(dtype=float),
        period,
    )
    value = float(atr[-1])
    return value if np.isfinite(value) else 0.0


def _pack(
    signal: int,
    desired: int | None,
    reasons: list[str],
    close: float,
    atr: float,
    align: AlignmentSnapshot,
    s15: TenWState,
    mid1: np.ndarray,
    vp,
) -> GMASignal:
    return GMASignal(
        signal=signal,
        desired=desired,
        reasons=tuple(reasons),
        close=close,
        atr=atr,
        alignment=align.alignment,
        regime_direction=align.direction,
        m15_fast=s15.fast,
        m15_slow=s15.slow,
        h1_mid=last_valid(mid1),
        poc=vp.poc,
        vah=vp.vah,
        val=vp.val,
    )
