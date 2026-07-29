"""Overseas 5m bar feed: cache + Eastmoney (CN) + Yahoo fallback.

Outputs Pipeline-compatible DataFrames (datetime ns, OHLC, volume).
Core decision modules must not import this for formulas — runners only.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ignitequant.market.cache import CACHE_ROOT, load_bars
from ignitequant.market.overseas import OverseasInstrumentSpec, overseas_by_id
from ignitequant.market.symbols import InstrumentSpec, SignalSource, resolve_signal_source

_CST = timezone(timedelta(hours=8))
_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_EASTMONEY_HOSTS = (
    "push2his.eastmoney.com",
    "push2delay.eastmoney.com",
    "79.push2.eastmoney.com",
)


def _http_get_text(url: str, *, headers: dict[str, str], timeout: float = 12) -> str | None:
    try:
        import requests

        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception:
        pass
    try:
        cmd = [
            "curl.exe",
            "-sL",
            "--fail",
            "--max-time",
            str(int(timeout)),
            "-A",
            headers.get("User-Agent") or _BROWSER_UA,
            "-H",
            f"Accept: {headers.get('Accept') or '*/*'}",
        ]
        if headers.get("Referer"):
            cmd.extend(["-H", f"Referer: {headers['Referer']}"])
        cmd.append(url)
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.returncode == 0 and completed.stdout:
            return completed.stdout
    except Exception:
        pass
    return None


def _aggregate_1m_to_5m(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    if not rows:
        return []
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        t = int(row["time"])
        bucket = t - (t % 300)
        buckets.setdefault(bucket, []).append(row)
    bars: list[dict[str, Any]] = []
    for bucket in sorted(buckets):
        chunk = buckets[bucket]
        bars.append(
            {
                "time": bucket,
                "open": float(chunk[0]["open"]),
                "high": max(float(x["high"]) for x in chunk),
                "low": min(float(x["low"]) for x in chunk),
                "close": float(chunk[-1]["close"]),
                "volume": sum(float(x.get("volume") or 0) for x in chunk),
            }
        )
    return bars[-limit:]


def fetch_eastmoney_trends_5m_bars(secid: str, *, limit: int = 400) -> list[dict[str, Any]]:
    if not secid:
        return []
    qs = urllib.parse.urlencode(
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ndays": "5",
            "iscr": "0",
            "iscca": "0",
        }
    )
    headers = {
        "User-Agent": _BROWSER_UA,
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    trends: list[str] = []
    for host in _EASTMONEY_HOSTS:
        url = f"https://{host}/api/qt/stock/trends2/get?{qs}"
        text = _http_get_text(url, headers=headers, timeout=12)
        if not text:
            continue
        try:
            candidate = json.loads(text)
        except json.JSONDecodeError:
            continue
        rows = ((candidate.get("data") or {}).get("trends")) or []
        if rows:
            trends = [str(x) for x in rows]
            break
    if not trends:
        return []
    minutes: list[dict[str, Any]] = []
    for row in trends:
        parts = row.split(",")
        if len(parts) < 6:
            continue
        try:
            dt = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=_CST)
            o, c, h, l = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
            vol = float(parts[5] or 0)
        except ValueError:
            continue
        minutes.append(
            {"time": int(dt.timestamp()), "open": o, "high": h, "low": l, "close": c, "volume": vol}
        )
    return _aggregate_1m_to_5m(minutes, limit=limit)


def fetch_eastmoney_5m_bars(secid: str, *, limit: int = 400) -> list[dict[str, Any]]:
    if not secid:
        return []
    qs = urllib.parse.urlencode(
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "5",
            "fqt": "1",
            "end": "20500101",
            "lmt": str(max(limit, 10)),
        }
    )
    headers = {
        "User-Agent": _BROWSER_UA,
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    payload: dict[str, Any] | None = None
    for host in _EASTMONEY_HOSTS:
        url = f"https://{host}/api/qt/stock/kline/get?{qs}"
        for _ in range(2):
            text = _http_get_text(url, headers=headers, timeout=12)
            if not text:
                continue
            try:
                candidate = json.loads(text)
            except json.JSONDecodeError:
                continue
            klines = ((candidate.get("data") or {}).get("klines")) or []
            if klines:
                payload = candidate
                break
        if payload is not None:
            break
    if payload is not None:
        klines = ((payload.get("data") or {}).get("klines")) or []
        bars: list[dict[str, Any]] = []
        for row in klines:
            parts = str(row).split(",")
            if len(parts) < 6:
                continue
            try:
                dt = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=_CST)
                o, c, h, l = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
                vol = float(parts[5] or 0)
            except ValueError:
                continue
            bars.append(
                {
                    "time": int(dt.timestamp()),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": vol,
                }
            )
        if bars:
            return bars[-limit:]
    return fetch_eastmoney_trends_5m_bars(secid, limit=limit)


def fetch_yahoo_5m_bars(yahoo_symbol: str, *, limit: int = 400) -> list[dict[str, Any]]:
    if not yahoo_symbol:
        return []
    qs = urllib.parse.urlencode(
        {"interval": "5m", "range": "5d", "includePrePost": "false"}
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}?{qs}"
    headers = {"User-Agent": _BROWSER_UA, "Accept": "application/json"}
    text = _http_get_text(url, headers=headers, timeout=10)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    try:
        result = payload["chart"]["result"][0]
        ts_list = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return []
    bars: list[dict[str, Any]] = []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    for i, ts in enumerate(ts_list):
        o = opens[i] if i < len(opens) else None
        h = highs[i] if i < len(highs) else None
        l = lows[i] if i < len(lows) else None
        c = closes[i] if i < len(closes) else None
        if None in (o, h, l, c):
            continue
        bars.append(
            {
                "time": int(ts),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(volumes[i] or 0) if i < len(volumes) else 0.0,
            }
        )
    return normalize_5m_bars(bars, limit=limit)


def normalize_5m_bars(
    bars: list[dict[str, Any]], *, limit: int = 400
) -> list[dict[str, Any]]:
    """Floor timestamps onto 5m opens and merge duplicates (Yahoo tip can be off-grid)."""
    if not bars:
        return []
    buckets: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for raw in bars:
        ts = int(raw["time"])
        bucket = ts - (ts % 300)
        if bucket not in buckets:
            order.append(bucket)
            buckets[bucket] = {
                "time": bucket,
                "open": float(raw["open"]),
                "high": float(raw["high"]),
                "low": float(raw["low"]),
                "close": float(raw["close"]),
                "volume": float(raw.get("volume") or 0),
            }
            continue
        cur = buckets[bucket]
        cur["high"] = max(cur["high"], float(raw["high"]))
        cur["low"] = min(cur["low"], float(raw["low"]))
        cur["close"] = float(raw["close"])
        cur["volume"] = float(cur.get("volume") or 0) + float(raw.get("volume") or 0)
    return [buckets[k] for k in order][-limit:]


def tip_age_seconds(bars: list[dict[str, Any]], *, now: float | None = None) -> float | None:
    """Seconds since last bar *open*. Includes the open 5m window itself."""
    if not bars:
        return None
    now = time.time() if now is None else float(now)
    return max(0.0, now - float(bars[-1]["time"]))


def drop_forming_5m_bar(
    bars: list[dict[str, Any]], *, now: float | None = None, lag_s: float = 2.0
) -> list[dict[str, Any]]:
    """Remove the in-progress 5m bucket (open → open+300).

    Previous logic used a 15s heuristic and kept almost-full forming bars as if
    complete, which made the decision clock / chart tip feel one bar behind.
    """
    if len(bars) < 2:
        return list(bars)
    now = time.time() if now is None else float(now)
    last_open = int(bars[-1]["time"])
    if now < last_open + 300 - lag_s:
        return list(bars[:-1])
    return list(bars)


def fetch_live_overseas_5m_bars(
    *,
    eastmoney_secid: str = "",
    yahoo_symbol: str = "",
    overseas_id: str = "",
    limit: int = 400,
) -> tuple[list[dict[str, Any]], str | None]:
    """Fetch both feeds; keep the fresher tip.

    Eastmoney COMEX continuous often comes from push2delay (~5–15m late). Always
    probing Yahoo avoids pinning the chart/decision tip on a stale EM last bar.
    ``overseas_id`` is accepted for call-site compatibility and ignored here.
    """
    del overseas_id  # unused; kept for stable kwargs
    em = normalize_5m_bars(
        fetch_eastmoney_5m_bars(eastmoney_secid, limit=limit), limit=limit
    )
    yh = fetch_yahoo_5m_bars(yahoo_symbol, limit=limit)
    if em and yh:
        em_tip = int(em[-1]["time"])
        yh_tip = int(yh[-1]["time"])
        # Prefer Yahoo when it leads by at least half a bar; otherwise keep EM
        # (usually denser history via trends2 in CN networks).
        if yh_tip >= em_tip + 150:
            return yh, "yahoo"
        return em, "eastmoney"
    if em:
        return em, "eastmoney"
    if yh:
        return yh, "yahoo"
    return [], None


def fetch_for_signal_source(
    source: SignalSource, *, limit: int = 400
) -> tuple[list[dict[str, Any]], str | None]:
    if source.pricing_basis != "overseas":
        return [], None
    return fetch_live_overseas_5m_bars(
        eastmoney_secid=source.eastmoney_secid or "",
        yahoo_symbol=source.yahoo_symbol or "",
        overseas_id=source.overseas_id or "",
        limit=limit,
    )


def bars_dicts_to_dataframe(
    bars: list[dict[str, Any]],
    *,
    underlying_symbol: str = "",
) -> pd.DataFrame:
    """Convert {time, open, high, low, close, volume} → Pipeline kline frame."""
    if not bars:
        return pd.DataFrame(
            columns=[
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
        )
    rows = []
    for b in bars:
        ts = int(b["time"])
        rows.append(
            {
                "datetime": ts * 1_000_000_000,
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume") or 0),
                "open_oi": 0,
                "close_oi": 0,
                "underlying_symbol": underlying_symbol,
            }
        )
    return pd.DataFrame(rows)


def load_overseas_cache_bars(
    overseas_signal_symbol: str,
    *,
    duration_seconds: int = 300,
    root: Path | None = None,
) -> pd.DataFrame:
    """Load archived overseas bars from data/market_cache (Yahoo download layout)."""
    try:
        return load_bars(
            overseas_signal_symbol,
            duration_seconds=duration_seconds,
            root=root or CACHE_ROOT,
        )
    except FileNotFoundError:
        return pd.DataFrame(
            columns=[
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
        )


def load_decision_bars_for_spec(
    spec: InstrumentSpec,
    *,
    start=None,
    end=None,
    duration_seconds: int = 300,
    auto_download: bool = False,
    progress_cb=None,
) -> tuple[pd.DataFrame, SignalSource]:
    """Bars used as Factor/Signal clock for this instrument."""
    from ignitequant.market.cache import ensure_cache, slice_bars

    source = resolve_signal_source(spec)
    if source.pricing_basis == "overseas" and source.overseas_signal_symbol:
        try:
            frame = load_overseas_cache_bars(
                source.overseas_signal_symbol, duration_seconds=duration_seconds
            )
        except Exception:
            frame = pd.DataFrame()
        if frame.empty and auto_download:
            # Fall back to live fetch window (shallow) for smoke tests only.
            live, _ = fetch_for_signal_source(source, limit=400)
            frame = bars_dicts_to_dataframe(
                live, underlying_symbol=source.overseas_signal_symbol
            )
        if start is not None and end is not None and not frame.empty:
            frame = slice_bars(frame, start=start, end=end)
        return frame, source

    frame = ensure_cache(
        spec.signal_symbol,
        start=start,
        end=end,
        duration_seconds=duration_seconds,
        auto_download=auto_download,
        progress_cb=progress_cb,
    )
    return frame, source


def overseas_spec_from_source(source: SignalSource) -> OverseasInstrumentSpec | None:
    if not source.overseas_id:
        return None
    return overseas_by_id(source.overseas_id)
