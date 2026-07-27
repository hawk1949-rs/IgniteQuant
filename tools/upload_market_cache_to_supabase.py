#!/usr/bin/env python3
"""Upload local data/market_cache 5m bars into Supabase market_bar_archive.

SoT: historical research bars belong on Supabase (C architecture).
Trading hot window stays local; this is bulk / catch-up import.

Examples:
  PYTHONPATH=src python3 tools/upload_market_cache_to_supabase.py --status
  PYTHONPATH=src python3 tools/upload_market_cache_to_supabase.py --ids au,ag,rb,fg
  PYTHONPATH=src python3 tools/upload_market_cache_to_supabase.py --all --duration 300
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

from ignitequant.market.cache import CACHE_ROOT, cache_path, load_bars  # noqa: E402
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


def _ns_to_iso(ns: int) -> str:
    return datetime.fromtimestamp(int(ns) / 1_000_000_000, tz=timezone.utc).isoformat()


def _bar_id(symbol: str, duration_sec: int, end_unix: int) -> str:
    return f"{symbol}:{duration_sec}:{end_unix}"


def upload_symbol(
    cur,
    *,
    signal_symbol: str,
    duration_sec: int,
    batch_size: int = 500,
    source: str = "market_cache",
) -> int:
    from psycopg2.extras import execute_values

    bars = load_bars(signal_symbol, duration_seconds=duration_sec)
    if bars.empty:
        return 0

    rows = []
    for _, r in bars.iterrows():
        end_ns = int(r["datetime"])
        end_unix = end_ns // 1_000_000_000
        start_unix = end_unix - int(duration_sec)
        start_ns = start_unix * 1_000_000_000
        rows.append(
            (
                signal_symbol,
                int(duration_sec),
                _bar_id(signal_symbol, duration_sec, end_unix),
                _ns_to_iso(start_ns),
                _ns_to_iso(end_ns),
                _ns_to_iso(end_ns),  # available_at ≈ bar end for historical finals
                float(r["open"]),
                float(r["high"]),
                float(r["low"]),
                float(r["close"]),
                float(r.get("volume") or 0),
                float(r.get("open_oi") or 0),
                float(r.get("close_oi") or 0),
                str(r.get("underlying_symbol") or ""),
                True,
                source,
                None,
            )
        )

    sql = """
        INSERT INTO market_bar_archive(
            symbol, duration_sec, bar_id, bar_start, bar_end, available_at,
            open, high, low, close, volume, open_oi, close_oi,
            underlying_symbol, is_final, source, instance_id
        ) VALUES %s
        ON CONFLICT (symbol, duration_sec, bar_end) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            open_oi = EXCLUDED.open_oi,
            close_oi = EXCLUDED.close_oi,
            underlying_symbol = EXCLUDED.underlying_symbol,
            is_final = EXCLUDED.is_final,
            source = EXCLUDED.source,
            bar_id = EXCLUDED.bar_id,
            available_at = EXCLUDED.available_at
    """
    total = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        execute_values(cur, sql, chunk, page_size=batch_size)
        total += len(chunk)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--ids", default="", help="comma ids: au,ag,rb,fg")
    parser.add_argument("--duration", type=int, default=300)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if args.ids:
        specs = []
        for sid in args.ids.split(","):
            sid = sid.strip().lower()
            if sid not in INSTRUMENTS:
                print(f"ERROR: unknown id {sid}", flush=True)
                return 1
            specs.append(INSTRUMENTS[sid])
    else:
        specs = list(INSTRUMENTS.values())

    if args.status or args.dry_run:
        print(f"cache root: {CACHE_ROOT}", flush=True)
        for spec in (specs or list(INSTRUMENTS.values())):
            path = cache_path(spec.signal_symbol, duration_seconds=args.duration)
            if not path.is_file():
                print(f"[MISS] {spec.id:4} {spec.signal_symbol} → {path}", flush=True)
                continue
            bars = load_bars(spec.signal_symbol, duration_seconds=args.duration)
            print(
                f"[OK]   {spec.id:4} {spec.signal_symbol} rows={len(bars)} file={path}",
                flush=True,
            )
        if args.status and not args.dry_run:
            return 0

    missing = []
    for spec in specs:
        path = cache_path(spec.signal_symbol, duration_seconds=args.duration)
        if not path.is_file():
            missing.append(spec.id)
    if missing:
        print(
            f"ERROR: missing local cache for: {', '.join(missing)}\n"
            f"  Pull first: python tools/download_market_cache.py --ids {','.join(missing)} "
            f"--start 2024-01-01 --end 2025-12-31\n"
            f"  Or copy CSV from your Windows data/market_cache into {CACHE_ROOT}",
            flush=True,
        )
        return 1

    if args.dry_run:
        print("DRY-RUN: cache present; no upload", flush=True)
        return 0

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: DATABASE_URL missing", flush=True)
        return 1

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed", flush=True)
        return 1

    conn = psycopg2.connect(url, connect_timeout=20)
    conn.autocommit = True
    uploaded = {}
    try:
        with conn.cursor() as cur:
            for spec in specs:
                n = upload_symbol(
                    cur,
                    signal_symbol=spec.signal_symbol,
                    duration_sec=args.duration,
                    batch_size=args.batch_size,
                )
                uploaded[spec.id] = n
                print(f"uploaded {spec.id}: {n} bars → {spec.signal_symbol}", flush=True)
            cur.execute(
                """
                SELECT symbol, COUNT(*) 
                FROM market_bar_archive
                WHERE duration_sec = %s
                GROUP BY symbol
                ORDER BY symbol
                """,
                (args.duration,),
            )
            print("archive_counts:", flush=True)
            for sym, cnt in cur.fetchall():
                print(f"  {sym}: {cnt}", flush=True)
    finally:
        conn.close()

    print(f"OK total_uploaded={sum(uploaded.values())}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
