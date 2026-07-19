"""Download continuous klines + per-bar underlying via TqBacktest into local cache."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Callable

import pandas as pd

from ignitequant.market.cache import BAR_COLUMNS, ROOT, merge_and_save


ProgressCb = Callable[[float, str], None]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _iter_chunks(start: dt.date, end: dt.date, *, months: int = 6) -> list[tuple[dt.date, dt.date]]:
    """Split [start, end] into inclusive date windows for resume-friendly downloads."""
    chunks: list[tuple[dt.date, dt.date]] = []
    cur = start
    while cur < end:
        # advance by `months`
        year = cur.year + (cur.month + months - 1) // 12
        month = (cur.month + months - 1) % 12 + 1
        boundary = dt.date(year, month, 1)
        chunk_end = min(boundary, end)
        if chunk_end <= cur:
            chunk_end = end
        chunks.append((cur, chunk_end))
        cur = chunk_end
    return chunks


def _download_chunk(
    signal_symbol: str,
    *,
    start: dt.date,
    end: dt.date,
    duration_seconds: int,
    progress_cb: ProgressCb | None,
    progress_base: float,
    progress_span: float,
    global_start: dt.date,
    global_end: dt.date,
) -> pd.DataFrame:
    from tqsdk import BacktestFinished, TqApi, TqAuth, TqBacktest, TqSim

    # Keep serial modest; we accumulate every closed bar into `records`.
    data_length = 8_000
    api = TqApi(
        TqSim(init_balance=1_000_000),
        backtest=TqBacktest(start_dt=start, end_dt=end),
        web_gui=False,
        auth=TqAuth(
            os.environ["TQ_USER"].strip(),
            os.environ["TQ_PASS"].strip(),
        ),
    )
    quote = api.get_quote(signal_symbol)
    klines = api.get_kline_serial(signal_symbol, duration_seconds, data_length=data_length)

    records: list[dict] = []
    last_dt: int | None = None
    last_progress_day: dt.date | None = None

    try:
        while True:
            api.wait_update()
            if not api.is_changing(klines.iloc[-1], "datetime"):
                continue
            row = klines.iloc[-1]
            bar_ns = int(row["datetime"])
            if last_dt is not None and bar_ns <= last_dt:
                continue
            last_dt = bar_ns
            underlying = str(getattr(quote, "underlying_symbol", "") or "")
            records.append(
                {
                    "datetime": bar_ns,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume", 0) or 0),
                    "open_oi": float(row.get("open_oi", 0) or 0),
                    "close_oi": float(row.get("close_oi", 0) or 0),
                    "underlying_symbol": underlying,
                }
            )
            bar_day = dt.datetime.fromtimestamp(bar_ns / 1_000_000_000).date()
            if progress_cb is not None and bar_day != last_progress_day:
                last_progress_day = bar_day
                span = max((global_end - global_start).days, 1)
                done = max((bar_day - global_start).days, 0)
                pct = progress_base + progress_span * min(done / span, 1.0)
                progress_cb(min(pct, 0.99), f"缓存 {bar_day} {underlying or signal_symbol}")
    except BacktestFinished:
        pass
    finally:
        api.close()

    if not records:
        return pd.DataFrame(columns=BAR_COLUMNS)
    return pd.DataFrame(records)


def download_klines(
    signal_symbol: str,
    *,
    start: dt.date,
    end: dt.date,
    duration_seconds: int = 300,
    root: Path | None = None,
    progress_cb: ProgressCb | None = None,
    chunk_months: int = 6,
) -> Path:
    """Pull bars through TqBacktest and persist CSV with underlying_symbol for rolls.

    Uses incremental bar capture (not the rolling kline serial alone) so long
    ranges are not truncated to ~10k bars. Downloads in date chunks and merges.
    """
    _load_dotenv(ROOT / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise RuntimeError("缺少 TQ_USER / TQ_PASS，无法下载行情缓存")
    os.environ["TQ_USER"] = user
    os.environ["TQ_PASS"] = password

    if end <= start:
        raise ValueError("end must be after start")

    chunks = _iter_chunks(start, end, months=chunk_months)
    n = max(len(chunks), 1)
    frames: list[pd.DataFrame] = []

    for i, (c_start, c_end) in enumerate(chunks):
        if progress_cb is not None:
            progress_cb(i / n, f"分段 {c_start}→{c_end} ({i + 1}/{n})")
        part = _download_chunk(
            signal_symbol,
            start=c_start,
            end=c_end,
            duration_seconds=duration_seconds,
            progress_cb=progress_cb,
            progress_base=i / n,
            progress_span=1.0 / n,
            global_start=start,
            global_end=end,
        )
        if not part.empty:
            frames.append(part)
            # Merge after each chunk so crash mid-way still keeps progress.
            merge_and_save(
                signal_symbol,
                part,
                duration_seconds=duration_seconds,
                root=root,
                source="tqsdk_tqbacktest_chunk",
            )

    if not frames:
        raise RuntimeError(f"download produced no bars for {signal_symbol}")

    frame = pd.concat(frames, ignore_index=True)
    if progress_cb is not None:
        progress_cb(1.0, f"已写入完整缓存 ({len(frame)} bars 本轮)")
    # Final merge ensures meta.json reflects full file.
    return merge_and_save(
        signal_symbol,
        frame,
        duration_seconds=duration_seconds,
        root=root,
        source="tqsdk_tqbacktest",
    )
