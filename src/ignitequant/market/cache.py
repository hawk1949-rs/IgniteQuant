"""CSV market cache aligned with Phase 0 fixture columns (+ underlying_symbol)."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ignitequant.market.symbols import INSTRUMENTS, InstrumentSpec, instrument_by_signal

ROOT = Path(__file__).resolve().parents[3]
CACHE_ROOT = ROOT / "data" / "market_cache"

BAR_COLUMNS = [
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_oi",
    "close_oi",
    "underlying_symbol",
]

REQUIRED_COLUMNS = {"datetime", "open", "high", "low", "close", "volume"}


def _safe_dir_name(signal_symbol: str) -> str:
    return re.sub(r"[^\w.@-]+", "_", signal_symbol)


def cache_dir(signal_symbol: str, *, root: Path | None = None) -> Path:
    base = root or CACHE_ROOT
    return base / _safe_dir_name(signal_symbol)


def cache_path(
    signal_symbol: str,
    *,
    duration_seconds: int = 300,
    root: Path | None = None,
) -> Path:
    return cache_dir(signal_symbol, root=root) / f"{int(duration_seconds)}.csv"


def meta_path(
    signal_symbol: str,
    *,
    duration_seconds: int = 300,
    root: Path | None = None,
) -> Path:
    return cache_dir(signal_symbol, root=root) / f"{int(duration_seconds)}.meta.json"


def _normalize_bars(frame: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"bars missing columns: {sorted(missing)}")
    out = frame.copy()
    for col in BAR_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col == "underlying_symbol" else 0
    out = out.loc[:, BAR_COLUMNS]
    out["datetime"] = pd.to_numeric(out["datetime"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume", "open_oi", "close_oi"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["underlying_symbol"] = out["underlying_symbol"].fillna("").astype(str)
    out = out.dropna(subset=["datetime", "open", "high", "low", "close"])
    out = out.sort_values("datetime")
    # Prefer richer snapshots when merging stub (vol=0, ohlc flat) with completed bars.
    out["_range"] = (out["high"] - out["low"]).abs()
    out = out.sort_values(["datetime", "volume", "_range"])
    out = out.drop_duplicates(subset=["datetime"], keep="last")
    out = out.drop(columns=["_range"])
    out = out.reset_index(drop=True)
    return out


def merge_and_save(
    signal_symbol: str,
    bars: pd.DataFrame,
    *,
    duration_seconds: int = 300,
    root: Path | None = None,
    source: str = "tqsdk",
) -> Path:
    path = cache_path(signal_symbol, duration_seconds=duration_seconds, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    incoming = _normalize_bars(bars)
    if path.is_file():
        existing = _normalize_bars(pd.read_csv(path))
        merged = _normalize_bars(pd.concat([existing, incoming], ignore_index=True))
    else:
        merged = incoming
    merged.to_csv(path, index=False)
    meta = {
        "signal_symbol": signal_symbol,
        "duration_seconds": int(duration_seconds),
        "rows": int(len(merged)),
        "start_dt": _ns_to_iso(int(merged["datetime"].iloc[0])) if len(merged) else None,
        "end_dt": _ns_to_iso(int(merged["datetime"].iloc[-1])) if len(merged) else None,
        "source": source,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    meta_path(signal_symbol, duration_seconds=duration_seconds, root=root).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def load_bars(
    signal_symbol: str,
    *,
    duration_seconds: int = 300,
    root: Path | None = None,
) -> pd.DataFrame:
    path = cache_path(signal_symbol, duration_seconds=duration_seconds, root=root)
    if not path.is_file():
        raise FileNotFoundError(
            f"market cache missing: {path}. "
            f"Run: python tools/download_market_cache.py --symbol {signal_symbol}"
        )
    return _normalize_bars(pd.read_csv(path))


def slice_bars(
    bars: pd.DataFrame,
    *,
    start: dt.date,
    end: dt.date,
    warmup_bars: int = 400,
) -> pd.DataFrame:
    """Include `warmup_bars` before start (for indicators), keep through end day."""
    if bars.empty:
        return bars.copy()
    start_ns = int(dt.datetime.combine(start, dt.time.min).timestamp() * 1_000_000_000)
    # end exclusive next day midnight
    end_exclusive = end + dt.timedelta(days=1)
    end_ns = int(dt.datetime.combine(end_exclusive, dt.time.min).timestamp() * 1_000_000_000)

    in_range = bars[(bars["datetime"] >= start_ns) & (bars["datetime"] < end_ns)]
    if in_range.empty:
        raise ValueError(f"no bars in [{start.isoformat()}, {end.isoformat()}]")

    first_idx = int(in_range.index[0])
    warm_start = max(0, first_idx - max(int(warmup_bars), 0))
    last_idx = int(in_range.index[-1])
    return bars.iloc[warm_start : last_idx + 1].reset_index(drop=True)


def coverage_ok(
    bars: pd.DataFrame,
    *,
    start: dt.date,
    end: dt.date,
    max_end_gap_days: int = 3,
    max_start_gap_days: int = 5,
    max_resume_gap_days: int = 20,
    max_internal_gap_days: int = 20,
) -> bool:
    """True when cache covers the requested window for trading purposes.

    Rules:
    1. At least one bar inside ``[start, end]``.
    2. First in-range bar is not much later than ``start`` (weekend / New Year).
    3. No multi-week hole inside the window (weekends/CNY OK; missing whole months not).
    4. Last in-range bar reaches near ``end``, **or** the cache resumes shortly
       after ``end`` (holiday gap — e.g. 2025 CNY 1/28–2/4 while January ends
       on 1/31). Bars that only resume months later do **not** count.
    """
    if bars.empty:
        return False
    start_ns = int(dt.datetime.combine(start, dt.time.min).timestamp() * 1_000_000_000)
    end_exclusive = end + dt.timedelta(days=1)
    end_ns = int(dt.datetime.combine(end_exclusive, dt.time.min).timestamp() * 1_000_000_000)
    in_range = bars[(bars["datetime"] >= start_ns) & (bars["datetime"] < end_ns)]
    if in_range.empty:
        return False

    first_day = dt.datetime.fromtimestamp(int(in_range["datetime"].iloc[0]) / 1_000_000_000).date()
    if first_day > start + dt.timedelta(days=max(0, int(max_start_gap_days))):
        return False

    # Reject large holes inside the window (e.g. Feb present, all of March missing
    # while end is Mar 31 — last_day alone is not enough when after_end is distant).
    days: list[dt.date] = []
    seen: set[dt.date] = set()
    for ns in in_range["datetime"].tolist():
        d = dt.datetime.fromtimestamp(int(ns) / 1_000_000_000).date()
        if d not in seen:
            seen.add(d)
            days.append(d)
    days.sort()
    max_internal = max(0, int(max_internal_gap_days))
    for prev, cur in zip(days, days[1:]):
        if (cur - prev).days > max_internal:
            return False

    last_day = days[-1]
    if last_day >= end - dt.timedelta(days=max(0, int(max_end_gap_days))):
        return True

    # Holiday: resume must be soon after end, not months later (broken cache gap).
    after_end = bars[bars["datetime"] >= end_ns]
    if after_end.empty:
        return False
    first_after = dt.datetime.fromtimestamp(
        int(after_end["datetime"].iloc[0]) / 1_000_000_000
    ).date()
    return first_after <= end + dt.timedelta(days=max(0, int(max_resume_gap_days)))


def ensure_cache(
    signal_symbol: str,
    *,
    start: dt.date,
    end: dt.date,
    duration_seconds: int = 300,
    root: Path | None = None,
    auto_download: bool = True,
    progress_cb=None,
    warmup_bars: int = 400,
) -> pd.DataFrame:
    """Load cache; optionally download missing coverage via tqsdk.

    ``warmup_bars`` defaults to 400 (Falcon MA52). Multi-TF strategies such as
    GMA must pass a larger value so HTF indicators are ready at ``start``.
    """
    lookback = max(int(warmup_bars), 0)
    path = cache_path(signal_symbol, duration_seconds=duration_seconds, root=root)
    if path.is_file():
        bars = load_bars(signal_symbol, duration_seconds=duration_seconds, root=root)
        # Require data through the requested end (weekend gaps allowed via max_end_gap_days=3).
        if coverage_ok(bars, start=start, end=end, max_end_gap_days=3):
            return slice_bars(bars, start=start, end=end, warmup_bars=lookback)
        if not auto_download:
            raise ValueError(
                f"cache for {signal_symbol} does not cover [{start.isoformat()}, {end.isoformat()}]"
            )
    elif not auto_download:
        raise FileNotFoundError(f"market cache missing: {path}")

    from ignitequant.market.download import download_klines

    # ~40 completed 5m bars per SHFE session-day; keep Falcon's 45-day floor.
    warm_days = max(45, int(lookback / 40) + 14)
    warm_start = start - dt.timedelta(days=warm_days)
    if progress_cb is not None:
        progress_cb(
            0.02,
            f"补拉行情（含指标预热 {warm_start}→{end}；回测区间仍为 {start}→{end}）",
        )

    def _download_progress(pct: float, msg: str) -> None:
        if progress_cb is None:
            return
        progress_cb(
            0.02 + 0.33 * max(0.0, min(float(pct), 1.0)),
            f"补拉预热 {msg}｜回测仍按 {start}→{end}",
        )

    download_klines(
        signal_symbol,
        start=warm_start,
        end=end,
        duration_seconds=duration_seconds,
        root=root,
        progress_cb=_download_progress,
    )
    if progress_cb is not None:
        progress_cb(0.36, f"缓存就绪，开始回测 {start}→{end}")
    bars = load_bars(signal_symbol, duration_seconds=duration_seconds, root=root)
    if not coverage_ok(bars, start=start, end=end, max_end_gap_days=3):
        raise RuntimeError(
            f"download finished but cache still missing coverage for "
            f"{signal_symbol} [{start.isoformat()}, {end.isoformat()}]"
        )
    return slice_bars(bars, start=start, end=end, warmup_bars=lookback)


def cache_status(*, root: Path | None = None) -> list[dict[str, Any]]:
    base = root or CACHE_ROOT
    rows: list[dict[str, Any]] = []
    for spec in INSTRUMENTS.values():
        path = cache_path(spec.signal_symbol, root=base)
        meta_file = meta_path(spec.signal_symbol, root=base)
        meta: dict[str, Any] = {}
        if meta_file.is_file():
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        rows.append(
            {
                "id": spec.id,
                "name": spec.name,
                "signal_symbol": spec.signal_symbol,
                "cached": path.is_file(),
                "path": str(path),
                "rows": meta.get("rows"),
                "start_dt": meta.get("start_dt"),
                "end_dt": meta.get("end_dt"),
            }
        )
    return rows


def resolve_instrument(signal_symbol: str) -> InstrumentSpec:
    spec = instrument_by_signal(signal_symbol)
    if spec is None:
        raise KeyError(f"no InstrumentSpec for {signal_symbol}")
    return spec


def _ns_to_iso(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns / 1_000_000_000, tz=dt.timezone.utc).isoformat()
