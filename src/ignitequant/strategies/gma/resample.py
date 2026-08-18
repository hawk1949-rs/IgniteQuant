"""Resample completed 5m bars to higher GMA timeframes (no forming HTF bars)."""

from __future__ import annotations

from typing import Iterable

import pandas as pd

TF_MINUTES = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
}


def _to_shanghai(datetime_ns: pd.Series) -> pd.Series:
    ts = pd.to_datetime(datetime_ns.astype("int64"), unit="ns", utc=True)
    return ts.dt.tz_convert("Asia/Shanghai")


def resample_closed(
    bars: pd.DataFrame,
    minutes: int,
    *,
    source_minutes: int = 5,
) -> pd.DataFrame:
    """OHLCV resample; drop the last bucket if it has not closed."""
    if bars is None or bars.empty or minutes <= source_minutes:
        out = bars.copy() if bars is not None else pd.DataFrame()
        return out.reset_index(drop=True)

    frame = bars.copy()
    ts = _to_shanghai(frame["datetime"])
    frame = frame.set_index(ts)
    rule = f"{int(minutes)}min"
    agg: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    extra = {}
    if "open_oi" in frame.columns:
        extra["open_oi"] = "first"
    if "close_oi" in frame.columns:
        extra["close_oi"] = "last"
    if "underlying_symbol" in frame.columns:
        extra["underlying_symbol"] = "last"
    grouped = frame.resample(rule, label="left", closed="left").agg({**agg, **extra})
    grouped = grouped.dropna(subset=["open", "high", "low", "close"])
    if grouped.empty:
        return grouped.reset_index(drop=True)

    last_src = ts.iloc[-1]
    last_start = grouped.index[-1]
    bucket_end = last_start + pd.Timedelta(minutes=minutes)
    if last_src < bucket_end:
        grouped = grouped.iloc[:-1]
    if grouped.empty:
        return grouped.reset_index(drop=True)

    out = grouped.reset_index(drop=True)
    out.insert(0, "datetime", grouped.index.tz_convert("UTC").asi8)
    return out


def resample_bundle(
    bars_5m: pd.DataFrame,
    timeframes: Iterable[str] = ("5m", "15m", "30m", "1h", "4h"),
) -> dict[str, pd.DataFrame]:
    bundle: dict[str, pd.DataFrame] = {}
    for name in timeframes:
        minutes = TF_MINUTES[name]
        if minutes == 5:
            bundle[name] = bars_5m.reset_index(drop=True)
        else:
            bundle[name] = resample_closed(bars_5m, minutes)
    return bundle
