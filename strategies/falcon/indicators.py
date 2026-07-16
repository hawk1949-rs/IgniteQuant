"""Falcon 技术指标：MA / ATR / ADX / KDJ / 量能均线。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class IndicatorBundle:
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray
    ma7: np.ndarray
    ma14: np.ndarray
    ma52: np.ndarray
    atr: np.ndarray
    adx: np.ndarray
    k: np.ndarray
    d: np.ndarray
    j: np.ndarray
    vol_ma: np.ndarray


def _true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    return tr.astype(float)


def atr_series(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    tr = _true_range(high, low, close)
    return pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean().to_numpy(dtype=float)


def adx_series(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = 14,
) -> np.ndarray:
    """Wilder 风格 ADX（简化 EWM 实现）。"""
    up = high - np.roll(high, 1)
    down = np.roll(low, 1) - low
    up[0] = 0.0
    down[0] = 0.0

    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = _true_range(high, low, close)

    atr = pd.Series(tr).ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm).ewm(alpha=1 / period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0.0)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx.to_numpy(dtype=float)


def kdj_series(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    high_s = pd.Series(high)
    low_s = pd.Series(low)
    close_s = pd.Series(close)
    lowest = low_s.rolling(n, min_periods=1).min()
    highest = high_s.rolling(n, min_periods=1).max()
    rsv = ((close_s - lowest) / (highest - lowest).replace(0, np.nan) * 100).fillna(50.0)
    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    j = 3 * k - 2 * d
    return k.to_numpy(dtype=float), d.to_numpy(dtype=float), j.to_numpy(dtype=float)


def compute_indicators(
    klines: pd.DataFrame,
    *,
    ma_fast: int = 7,
    ma_mid: int = 14,
    ma_slow: int = 52,
    atr_period: int = 14,
    adx_period: int = 14,
    vol_ma_period: int = 20,
    kdj_n: int = 9,
) -> IndicatorBundle:
    close = klines.close.to_numpy(dtype=float)
    high = klines.high.to_numpy(dtype=float)
    low = klines.low.to_numpy(dtype=float)
    volume = klines.volume.to_numpy(dtype=float)

    ma7 = pd.Series(close).rolling(ma_fast).mean().to_numpy(dtype=float)
    ma14 = pd.Series(close).rolling(ma_mid).mean().to_numpy(dtype=float)
    ma52 = pd.Series(close).rolling(ma_slow).mean().to_numpy(dtype=float)
    atr = atr_series(high, low, close, atr_period)
    adx = adx_series(high, low, close, adx_period)
    k, d, j = kdj_series(high, low, close, n=kdj_n)
    vol_ma = pd.Series(volume).rolling(vol_ma_period).mean().to_numpy(dtype=float)

    return IndicatorBundle(
        close=close,
        high=high,
        low=low,
        volume=volume,
        ma7=ma7,
        ma14=ma14,
        ma52=ma52,
        atr=atr,
        adx=adx,
        k=k,
        d=d,
        j=j,
        vol_ma=vol_ma,
    )
