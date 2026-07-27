#!/usr/bin/env python3
"""Download Supabase market_bar_archive rows into local data/market_cache CSV.

Examples:
  PYTHONPATH=src python3 tools/download_market_cache_from_supabase.py --status
  PYTHONPATH=src python3 tools/download_market_cache_from_supabase.py --ids au,ag,rb,fg
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ignitequant.market.cache import CACHE_ROOT, cache_path  # noqa: E402
from ignitequant.market.symbols import INSTRUMENTS  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _iso_to_ns(iso: str) -> int:
    text = iso.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def download_symbol(cur, *, signal_symbol: str, duration_sec: int) -> int:
    import pandas as pd

    cur.execute(
        """
        SELECT bar_start, bar_end, open, high, low, close, volume, open_oi, close_oi
        FROM market_bar_archive
        WHERE symbol = %s AND duration_sec = %s
        ORDER BY bar_end ASC
        """,
        (signal_symbol, int(duration_sec)),
    )
    rows = cur.fetchall()
    if not rows:
        return 0

    data = []
    for row in rows:
        end_ns = _iso_to_ns(str(row[1]))
        data.append(
            {
                "datetime": end_ns,
                "open": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "close": float(row[5]),
                "volume": float(row[6] or 0),
                "open_oi": float(row[7] or 0),
                "close_oi": float(row[8] or 0),
            }
        )
    df = pd.DataFrame(data)
    path = cache_path(signal_symbol, duration_seconds=duration_sec)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download market_bar_archive → market_cache")
    parser.add_argument("--status", action="store_true", help="print cloud row counts")
    parser.add_argument("--ids", default="", help="comma ids: au,ag,rb,fg")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--duration", type=int, default=300)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: DATABASE_URL missing", file=sys.stderr)
        return 2

    import psycopg2

    pg = psycopg2.connect(url, connect_timeout=12)
    try:
        with pg.cursor() as cur:
            if args.status:
                cur.execute(
                    """
                    SELECT symbol, duration_sec, COUNT(*) AS rows
                    FROM market_bar_archive
                    GROUP BY symbol, duration_sec
                    ORDER BY symbol, duration_sec
                    """
                )
                for sym, dur, count in cur.fetchall():
                    print(f"[OK] {sym} duration={dur} rows={count}")
                print(f"cache root: {CACHE_ROOT}")
                return 0

            ids: list[str] = []
            if args.all:
                ids = list(INSTRUMENTS.keys())
            if args.ids:
                ids.extend(x.strip().lower() for x in args.ids.split(",") if x.strip())
            if not ids:
                parser.error("specify --all or --ids")

            total = 0
            for sid in dict.fromkeys(ids):
                if sid not in INSTRUMENTS:
                    print(f"unknown id: {sid}", file=sys.stderr)
                    return 2
                sym = INSTRUMENTS[sid].signal_symbol
                n = download_symbol(cur, signal_symbol=sym, duration_sec=args.duration)
                print(f"[{sid}] {sym} → {n} rows")
                total += n
            print(f"done, total rows={total}")
    finally:
        pg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
