"""Download overseas futures bars (Yahoo Finance) into data/market_cache.

Yahoo limits (approx): 5m≈60d, 1h≈2y, 1d≈5y+. Eastmoney is used by cockpit
for live CN access but historical depth is shallow; archive prefers Yahoo.

Examples:
  PYTHONPATH=src python tools/download_overseas_cache.py --ids gc,si --intervals 5m,1h,1d
  PYTHONPATH=src python tools/download_overseas_cache.py --all --status
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ignitequant.market.cache import merge_and_save  # noqa: E402
from ignitequant.market.overseas import OVERSEAS_INSTRUMENTS, overseas_by_id  # noqa: E402

INTERVAL_TO_DURATION = {
    "5m": 300,
    "1h": 3600,
    "1d": 86400,
}

# Yahoo range caps that usually succeed for futures continuous.
DEFAULT_RANGE = {
    "5m": "60d",
    "1h": "2y",
    "1d": "5y",
}

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _curl_bins() -> list[str]:
    # Prefer platform-native curl; keep curl.exe for Windows shells.
    if sys.platform.startswith("win"):
        return ["curl.exe", "curl"]
    return ["curl", "curl.exe"]


def _http_get(url: str, *, timeout: int = 30) -> str:
    try:
        import urllib.request

        req = urllib.request.Request(
            url,
            headers={"User-Agent": _BROWSER_UA, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            if text and not text.lstrip().startswith("<!DOCTYPE"):
                return text
    except Exception:
        pass
    # CN networks: curl often succeeds when urllib is blocked/challenged.
    for bin_name in _curl_bins():
        try:
            completed = subprocess.run(
                [
                    bin_name,
                    "-sL",
                    "--max-time",
                    str(timeout),
                    "-A",
                    _BROWSER_UA,
                    "-H",
                    "Accept: application/json",
                    url,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            text = completed.stdout or ""
            if text and not text.lstrip().startswith("<!DOCTYPE"):
                return text
        except Exception:
            continue
    return ""


# Do not archive COMEX/NYMEX continuous (GC=F / SI=F) into the XAUUSD/XAGUSD
# cache folders — those are futures and trade at a premium to London spot.
# Yahoo spot tickers (XAUUSD=X) are often empty; 5m then uses Eastmoney 122.XAU.
YAHOO_ARCHIVE_FALLBACK: dict[str, str] = {}


def fetch_yahoo_bars(
    yahoo_symbol: str,
    *,
    interval: str,
    range_: str,
) -> list[dict[str, Any]]:
    qs = urllib.parse.urlencode(
        {
            "interval": interval,
            "range": range_,
            "includePrePost": "false",
        }
    )
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(yahoo_symbol)}?{qs}"
    )
    text = _http_get(url)
    if not text:
        return []
    try:
        payload = json.loads(text)
        result = payload["chart"]["result"][0]
        ts_list = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    bars: list[dict[str, Any]] = []
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
    return bars


def bars_to_frame(bars: list[dict[str, Any]], *, underlying: str) -> pd.DataFrame:
    rows = []
    for b in bars:
        end_unix = int(b["time"])
        rows.append(
            {
                "datetime": end_unix * 1_000_000_000,
                "open": b["open"],
                "high": b["high"],
                "low": b["low"],
                "close": b["close"],
                "volume": b["volume"],
                "open_oi": 0,
                "close_oi": 0,
                "underlying_symbol": underlying,
            }
        )
    return pd.DataFrame(rows)


def _yahoo_symbols_for(product_id: str, primary: str) -> list[str]:
    ordered: list[str] = []
    for sym in (primary, YAHOO_ARCHIVE_FALLBACK.get(product_id, "")):
        s = (sym or "").strip()
        if s and s not in ordered:
            ordered.append(s)
    return ordered


def download_one(product_id: str, *, intervals: list[str]) -> dict[str, int]:
    spec = overseas_by_id(product_id)
    out: dict[str, int] = {}
    for interval in intervals:
        duration = INTERVAL_TO_DURATION[interval]
        range_ = DEFAULT_RANGE[interval]
        bars: list[dict[str, Any]] = []
        used_symbol = ""
        source = ""
        for ys in _yahoo_symbols_for(product_id, spec.yahoo_symbol):
            bars = fetch_yahoo_bars(ys, interval=interval, range_=range_)
            if bars:
                used_symbol = ys
                source = f"yahoo_{ys}_{interval}_{range_}"
                break
        if not bars and interval == "5m" and spec.eastmoney_secid:
            # CN / blocked-Yahoo fallback: shallow Eastmoney history (smoke only).
            try:
                from ignitequant.market.overseas_bars import fetch_eastmoney_5m_bars

                bars = fetch_eastmoney_5m_bars(spec.eastmoney_secid, limit=20_000)
            except Exception:
                bars = []
            if bars:
                used_symbol = spec.eastmoney_secid
                source = f"eastmoney_{spec.eastmoney_secid}_5m"
        if not bars:
            print(
                f"[MISS] {spec.id} {interval}/{range_} empty "
                f"(tried yahoo={_yahoo_symbols_for(product_id, spec.yahoo_symbol)}"
                f"{'+eastmoney' if interval == '5m' and spec.eastmoney_secid else ''})",
                flush=True,
            )
            out[interval] = 0
            continue
        frame = bars_to_frame(bars, underlying=spec.signal_symbol)
        path = merge_and_save(
            spec.signal_symbol,
            frame,
            duration_seconds=duration,
            source=source or f"yahoo_{interval}_{range_}",
        )
        start = datetime.fromtimestamp(bars[0]["time"], tz=timezone.utc)
        end = datetime.fromtimestamp(bars[-1]["time"], tz=timezone.utc)
        print(
            f"[OK] {spec.id:3} {interval:3} rows={len(bars)} via={used_symbol} "
            f"{start.date()}→{end.date()} → {path}",
            flush=True,
        )
        out[interval] = len(bars)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--ids", default="gc,si", help="comma ids: gc,si,hg,cl")
    parser.add_argument(
        "--intervals",
        default="5m,1h,1d",
        help="comma intervals among 5m,1h,1d",
    )
    args = parser.parse_args()

    if args.ids.strip().lower() == "all" or args.all:
        ids = list(OVERSEAS_INSTRUMENTS.keys())
    else:
        ids = [x.strip().lower() for x in args.ids.split(",") if x.strip()]
    intervals = [x.strip() for x in args.intervals.split(",") if x.strip()]
    for iv in intervals:
        if iv not in INTERVAL_TO_DURATION:
            print(f"ERROR: unsupported interval {iv}", flush=True)
            return 1

    if args.status:
        from ignitequant.market.cache import cache_path, load_bars

        for pid in ids:
            spec = overseas_by_id(pid)
            for iv in intervals:
                dur = INTERVAL_TO_DURATION[iv]
                path = cache_path(spec.signal_symbol, duration_seconds=dur)
                if not path.is_file():
                    print(f"[MISS] {pid} {iv} {path}", flush=True)
                    continue
                bars = load_bars(spec.signal_symbol, duration_seconds=dur)
                print(f"[OK]   {pid} {iv} rows={len(bars)} {path}", flush=True)
        return 0

    for pid in ids:
        download_one(pid, intervals=intervals)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
