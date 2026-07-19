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
    out = out.sort_values("datetime").drop_duplicates(subset=["datetime"], keep="last")
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


def ensure_cache(
    signal_symbol: str,
    *,
    start: dt.date,
    end: dt.date,
    duration_seconds: int = 300,
    root: Path | None = None,
    auto_download: bool = True,
    progress_cb=None,
) -> pd.DataFrame:
    """Load cache; optionally download missing coverage via tqsdk."""
    path = cache_path(signal_symbol, duration_seconds=duration_seconds, root=root)
    if path.is_file():
        bars = load_bars(signal_symbol, duration_seconds=duration_seconds, root=root)
        try:
            return slice_bars(bars, start=start, end=end, warmup_bars=400)
        except ValueError:
            if not auto_download:
                raise
    elif not auto_download:
        raise FileNotFoundError(f"market cache missing: {path}")

    from ignitequant.market.download import download_klines

    if progress_cb is not None:
        progress_cb(0.02, f"下载缓存 {signal_symbol}")
    download_klines(
        signal_symbol,
        start=start - dt.timedelta(days=45),  # warmup buffer
        end=end,
        duration_seconds=duration_seconds,
        root=root,
        progress_cb=progress_cb,
    )
    bars = load_bars(signal_symbol, duration_seconds=duration_seconds, root=root)
    return slice_bars(bars, start=start, end=end, warmup_bars=400)


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
