#!/usr/bin/env python
"""Download 5m continuous klines (+ underlying) into data/market_cache/.

Examples:
  python tools/download_market_cache.py --all --start 2024-01-01 --end 2025-06-30
  python tools/download_market_cache.py --ids au,ag,rb,fg --start 2025-01-01 --end 2025-03-01
  python tools/download_market_cache.py --status
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ignitequant.market.cache import CACHE_ROOT, cache_status  # noqa: E402
from ignitequant.market.download import download_klines  # noqa: E402
from ignitequant.market.symbols import INSTRUMENTS  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Falcon market cache (tqsdk)")
    parser.add_argument("--status", action="store_true", help="print cache coverage")
    parser.add_argument("--all", action="store_true", help="download all 4 instruments")
    parser.add_argument("--ids", default="", help="comma ids: au,ag,rb,fg")
    parser.add_argument("--symbol", default="", help="raw signal symbol e.g. KQ.m@SHFE.au")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2025-06-30")
    parser.add_argument("--duration", type=int, default=300)
    args = parser.parse_args()

    if args.status:
        for row in cache_status():
            flag = "OK" if row["cached"] else "MISS"
            print(
                f"[{flag}] {row['id']:4} {row['signal_symbol']:20} "
                f"rows={row.get('rows')} {row.get('start_dt')} → {row.get('end_dt')}"
            )
        print(f"cache root: {CACHE_ROOT}")
        return 0

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    symbols: list[str] = []
    if args.symbol:
        symbols.append(args.symbol.strip())
    if args.all:
        symbols.extend(s.signal_symbol for s in INSTRUMENTS.values())
    if args.ids:
        for sid in args.ids.split(","):
            sid = sid.strip().lower()
            if not sid:
                continue
            if sid not in INSTRUMENTS:
                print(f"unknown id: {sid}", file=sys.stderr)
                return 2
            symbols.append(INSTRUMENTS[sid].signal_symbol)

    # dedupe preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            ordered.append(s)
    if not ordered:
        parser.error("specify --all / --ids / --symbol")

    for i, sym in enumerate(ordered, 1):
        print(f"[{i}/{len(ordered)}] downloading {sym} {start} → {end} …")

        def _cb(pct: float, msg: str, _sym=sym) -> None:
            print(f"  {_sym}: {pct*100:5.1f}% {msg}")

        path = download_klines(
            sym,
            start=start,
            end=end,
            duration_seconds=args.duration,
            progress_cb=_cb,
        )
        print(f"  saved → {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
