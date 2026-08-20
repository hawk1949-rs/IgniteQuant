"""GMA indicators: reconstructed 10W (HMA), Keltner bands, RKK, volume profile.

The closed-source ``GMA10W多空.ex4`` is not available. Fast/slow lines follow the
documented (20, 90) chart inputs using Hull MA slope for color and a golden/death
cross for trend confirmation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

def _true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    return np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    ).astype(float)


def atr_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = _true_range(high, low, close)
    return pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().to_numpy(dtype=float)


def _wma(values: pd.Series, period: int) -> pd.Series:
    period = max(int(period), 1)
    arr = values.to_numpy(dtype=float)
    weights = np.arange(1, period + 1, dtype=float)
    denom = float(weights.sum())
    kernel = weights[::-1] / denom
    conv = np.convolve(np.nan_to_num(arr, nan=0.0), kernel, mode="full")[: len(arr)]
    valid = np.convolve(np.isfinite(arr).astype(float), np.ones(period), mode="full")[: len(arr)]
    out = np.full(len(arr), np.nan)
    mask = valid >= period
    out[mask] = conv[mask]
    return pd.Series(out, index=values.index)


def hull_ma(close: np.ndarray, period: int) -> np.ndarray:
    series = pd.Series(close, dtype=float)
    period = max(int(period), 2)
    half = max(period // 2, 1)
    sqrt_n = max(int(round(math.sqrt(period))), 1)
    raw = 2.0 * _wma(series, half) - _wma(series, period)
    return _wma(raw, sqrt_n).to_numpy(dtype=float)


def line_color(values: np.ndarray) -> np.ndarray:
    """+1 rising (bull color), -1 falling (bear color), 0 unknown."""
    out = np.zeros(len(values), dtype=float)
    if len(values) < 2:
        return out
    delta = np.diff(values, prepend=values[0])
    out[1:] = np.where(delta[1:] > 0, 1.0, np.where(delta[1:] < 0, -1.0, 0.0))
    # persist last non-zero color through flats
    last = 0.0
    for i, value in enumerate(out):
        if value != 0:
            last = value
        elif last != 0:
            out[i] = last
    return out


def stochastic(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    k_period: int = 5,
    d_period: int = 3,
    slowing: int = 2,
) -> tuple[np.ndarray, np.ndarray]:
    high_s = pd.Series(high)
    low_s = pd.Series(low)
    close_s = pd.Series(close)
    lowest = low_s.rolling(k_period, min_periods=1).min()
    highest = high_s.rolling(k_period, min_periods=1).max()
    raw_k = ((close_s - lowest) / (highest - lowest).replace(0, np.nan) * 100).fillna(50.0)
    k = raw_k.rolling(max(slowing, 1), min_periods=1).mean()
    d = k.rolling(max(d_period, 1), min_periods=1).mean()
    return k.to_numpy(dtype=float), d.to_numpy(dtype=float)


def keltner_channel(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    length: int = 14,
    times_atr: float = 1.5,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    mid = pd.Series(close).rolling(length, min_periods=length).mean().to_numpy(dtype=float)
    atr = atr_series(high, low, close, length)
    upper = mid + times_atr * atr
    lower = mid - times_atr * atr
    return mid, upper, lower, atr


def rkk_fisher(high: np.ndarray, low: np.ndarray, period: int = 21) -> np.ndarray:
    """Faithful port of docs RKK.mq4 Fisher transform (period 21)."""
    n = len(high)
    fish = np.full(n, np.nan, dtype=float)
    prev_v1 = 0.0
    prev_fish = 0.0
    mid = (high + low) / 2.0
    for i in range(n):
        start = max(0, i - period + 1)
        hh = float(np.max(high[start : i + 1]))
        ll = float(np.min(low[start : i + 1]))
        denom = hh - ll
        if denom <= 1e-12:
            v1 = prev_v1
        else:
            v1 = 0.66 * ((mid[i] - ll) / denom - 0.5) + 0.67 * prev_v1
        v1 = min(max(v1, -0.999), 0.999)
        fish_i = math.log((v1 + 1.0) / (1.0 - v1)) / 2.0 + prev_fish / 2.0
        fish[i] = fish_i
        prev_v1 = v1
        prev_fish = fish_i
    return fish


def donchian(high: np.ndarray, low: np.ndarray, period: int) -> tuple[np.ndarray, np.ndarray]:
    upper = pd.Series(high).rolling(period, min_periods=1).max().to_numpy(dtype=float)
    lower = pd.Series(low).rolling(period, min_periods=1).min().to_numpy(dtype=float)
    return upper, lower


@dataclass(frozen=True)
class TenWState:
    fast: float | None
    slow: float | None
    fast_color: int
    slow_color: int
    fast_above_slow: bool
    golden_cross: bool
    death_cross: bool
    single_drive: bool
    single_direction: bool
    single_conflict: bool


def tenw_series(close: np.ndarray, *, fast_period: int, slow_period: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    fast = hull_ma(close, fast_period)
    slow = hull_ma(close, slow_period)
    return fast, slow, line_color(fast), line_color(slow)


def tenw_state(close: np.ndarray, *, fast_period: int, slow_period: int) -> TenWState:
    if len(close) < 3:
        return TenWState(None, None, 0, 0, False, False, False, False, False, True)
    fast, slow, fast_c, slow_c = tenw_series(close, fast_period=fast_period, slow_period=slow_period)
    f0, s0 = float(fast[-1]), float(slow[-1])
    f1, s1 = float(fast[-2]), float(slow[-2])
    if not all(math.isfinite(x) for x in (f0, s0, f1, s1)):
        return TenWState(None, None, 0, 0, False, False, False, False, False, True)
    fc = int(fast_c[-1])
    sc = int(slow_c[-1])
    above = f0 > s0
    golden = f1 <= s1 and f0 > s0
    death = f1 >= s1 and f0 < s0
    drive = fc == sc != 0 and ((fc > 0 and above) or (fc < 0 and not above))
    direction = fc == sc != 0
    conflict = fc != 0 and sc != 0 and fc != sc
    return TenWState(
        fast=f0,
        slow=s0,
        fast_color=fc,
        slow_color=sc,
        fast_above_slow=above,
        golden_cross=golden,
        death_cross=death,
        single_drive=drive,
        single_direction=direction,
        single_conflict=conflict,
    )


@dataclass(frozen=True)
class VolumeBin:
    price_low: float
    price_high: float
    volume: float


@dataclass(frozen=True)
class VolumeProfile:
    poc: float | None
    vah: float | None
    val: float | None
    edge_high: float | None
    edge_low: float | None
    gap_high: float | None
    gap_low: float | None
    histogram: tuple[VolumeBin, ...] = ()


def volume_profile(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    *,
    bins: int = 50,
    value_pct: float = 0.70,
) -> VolumeProfile:
    """Visible-window Volume Profile (能量分布): POC / 70% VA / histogram gaps.

    Teaching defaults: Visible Bars window, ~50 price rows, VA=70%.
    """
    empty: tuple[VolumeBin, ...] = ()
    if len(close) == 0:
        return VolumeProfile(None, None, None, None, None, None, None, empty)
    lo = float(np.nanmin(low))
    hi = float(np.nanmax(high))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        last = float(close[-1])
        return VolumeProfile(last, last, last, last, last, None, None, empty)
    edges = np.linspace(lo, hi, bins + 1)
    hist = np.zeros(bins, dtype=float)
    for h, l, v in zip(high, low, volume):
        if not math.isfinite(h) or not math.isfinite(l) or h < l:
            continue
        vol = float(v) if math.isfinite(v) and v > 0 else 0.0
        left = int(np.clip(np.searchsorted(edges, l, side="right") - 1, 0, bins - 1))
        right = int(np.clip(np.searchsorted(edges, h, side="right") - 1, 0, bins - 1))
        span = max(right - left + 1, 1)
        hist[left : right + 1] += vol / span
    if hist.sum() <= 0:
        last = float(close[-1])
        return VolumeProfile(last, last, last, hi, lo, None, None, empty)
    poc_i = int(np.argmax(hist))
    centers = (edges[:-1] + edges[1:]) / 2.0
    poc = float(centers[poc_i])
    target = float(hist.sum()) * value_pct
    acc = float(hist[poc_i])
    left = right = poc_i
    while acc < target and (left > 0 or right < bins - 1):
        take_left = hist[left - 1] if left > 0 else -1.0
        take_right = hist[right + 1] if right < bins - 1 else -1.0
        if take_right > take_left:
            right += 1
            acc += float(hist[right])
        else:
            left -= 1
            acc += float(hist[left])
    vah = float(edges[right + 1])
    val = float(edges[left])
    gap_high = gap_low = None
    if poc_i + 2 < bins:
        rel = hist[poc_i:] / max(float(hist[poc_i]), 1e-9)
        valley = int(np.argmin(rel))
        if 0 < valley < len(rel) - 1 and rel[valley] < 0.25:
            gap_high = float(centers[poc_i + valley])
    if poc_i >= 2:
        rel = hist[: poc_i + 1] / max(float(hist[poc_i]), 1e-9)
        valley = int(np.argmin(rel))
        if 0 < valley < len(rel) - 1 and rel[valley] < 0.25:
            gap_low = float(centers[valley])
    histogram = tuple(
        VolumeBin(
            price_low=float(edges[i]),
            price_high=float(edges[i + 1]),
            volume=float(hist[i]),
        )
        for i in range(bins)
        if hist[i] > 0
    )
    return VolumeProfile(poc, vah, val, hi, lo, gap_high, gap_low, histogram)


def last_valid(values: np.ndarray) -> float | None:
    if values is None or len(values) == 0:
        return None
    value = float(values[-1])
    return value if math.isfinite(value) else None


def is_accelerating(
    close: np.ndarray,
    mid: np.ndarray,
    stoch_k: np.ndarray,
    *,
    overbought: float,
    oversold: float,
) -> tuple[bool, bool]:
    if len(close) < 4:
        return False, False
    c0, m0, k0 = float(close[-1]), float(mid[-1]), float(stoch_k[-1])
    m3 = float(mid[-4])
    if not all(math.isfinite(x) for x in (c0, m0, k0, m3)):
        return False, False
    slope = m0 - m3
    up = k0 >= overbought and c0 > m0 and slope > 0
    down = k0 <= oversold and c0 < m0 and slope < 0
    return up, down


def near_level(price: float, level: float | None, *, pct: float, atr: float | None) -> bool:
    if level is None or not math.isfinite(price) or not math.isfinite(level):
        return False
    tol = max(abs(level) * pct, 0.25 * float(atr or 0.0), 1e-9)
    return abs(price - level) <= tol
