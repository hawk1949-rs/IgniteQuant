#!/usr/bin/env python3
"""Upload overseas market_cache bars into Supabase market_bar_archive + seed ref tables.

Examples:
  PYTHONPATH=src python tools/upload_overseas_cache_to_supabase.py --status
  PYTHONPATH=src python tools/upload_overseas_cache_to_supabase.py --ids gc,si --durations 300,3600,86400
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ignitequant.market.cache import cache_path, load_bars  # noqa: E402
from ignitequant.market.overseas import (  # noqa: E402
    OVERSEAS_INSTRUMENTS,
    OVERSEAS_PAIRS,
    overseas_by_id,
)
from ignitequant.persistence.cloud_sync import database_url  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from upload_market_cache_to_supabase import upload_symbol  # noqa: E402


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def seed_ref_tables(cur) -> None:
    """Upsert overseas instruments + domestic↔overseas pairs."""
    for spec in OVERSEAS_INSTRUMENTS.values():
        payload = {
            "yahoo_symbol": spec.yahoo_symbol,
            "eastmoney_secid": spec.eastmoney_secid,
            "display_symbol": spec.display_symbol,
            "note": spec.note,
            "venue": "overseas",
        }
        cur.execute(
            """
            INSERT INTO ref_instrument(
                product_id, exchange_id, name, multiplier, price_tick,
                default_margin_rate, currency, signal_symbol, active,
                payload_json, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                NULL, %s, %s, TRUE,
                %s::jsonb, NOW()
            )
            ON CONFLICT (product_id) DO UPDATE SET
                exchange_id = EXCLUDED.exchange_id,
                name = EXCLUDED.name,
                multiplier = EXCLUDED.multiplier,
                price_tick = EXCLUDED.price_tick,
                currency = EXCLUDED.currency,
                signal_symbol = EXCLUDED.signal_symbol,
                payload_json = ref_instrument.payload_json || EXCLUDED.payload_json,
                active = TRUE,
                updated_at = NOW()
            """,
            (
                spec.id,
                spec.exchange,
                spec.name,
                float(spec.multiplier),
                float(spec.tick_size),
                spec.currency,
                spec.signal_symbol,
                json.dumps(payload, ensure_ascii=False),
            ),
        )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS public.ref_overseas_pair (
            domestic_product_id TEXT NOT NULL,
            overseas_product_id TEXT NOT NULL,
            note TEXT,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (domestic_product_id, overseas_product_id)
        )
        """
    )
    for domestic_id, pair in OVERSEAS_PAIRS.items():
        cur.execute(
            """
            INSERT INTO ref_overseas_pair(
                domestic_product_id, overseas_product_id, note, payload_json, updated_at
            ) VALUES (%s, %s, %s, '{}'::jsonb, NOW())
            ON CONFLICT (domestic_product_id, overseas_product_id) DO UPDATE SET
                note = EXCLUDED.note,
                updated_at = NOW()
            """,
            (
                domestic_id,
                pair.overseas_id,
                f"{domestic_id} ↔ {pair.overseas_id}",
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--ids", default="gc,si", help="comma ids: gc,si,hg,cl")
    parser.add_argument(
        "--durations",
        default="300,3600,86400",
        help="comma duration seconds",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--seed-only", action="store_true", help="only upsert ref tables")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    if args.all:
        ids = list(OVERSEAS_INSTRUMENTS.keys())
    else:
        ids = [x.strip().lower() for x in args.ids.split(",") if x.strip()]
    durations = [int(x) for x in args.durations.split(",") if x.strip()]

    for pid in ids:
        overseas_by_id(pid)

    if args.status or args.dry_run:
        for pid in ids:
            spec = overseas_by_id(pid)
            for dur in durations:
                path = cache_path(spec.signal_symbol, duration_seconds=dur)
                if not path.is_file():
                    print(f"[MISS] {pid} {dur}s {path}", flush=True)
                    continue
                bars = load_bars(spec.signal_symbol, duration_seconds=dur)
                print(f"[OK]   {pid} {dur}s rows={len(bars)} {path}", flush=True)
        if args.status and not args.dry_run:
            return 0

    if args.dry_run:
        print("DRY-RUN: no upload", flush=True)
        return 0

    url = database_url(root=ROOT)
    if not url:
        print("ERROR: DATABASE_URL missing", flush=True)
        return 1

    import psycopg2

    conn = psycopg2.connect(url, connect_timeout=20)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            seed_ref_tables(cur)
            print("seeded ref_instrument + ref_overseas_pair", flush=True)
            if args.seed_only:
                return 0
            for pid in ids:
                spec = overseas_by_id(pid)
                for dur in durations:
                    path = cache_path(spec.signal_symbol, duration_seconds=dur)
                    if not path.is_file():
                        print(f"[SKIP] missing cache {pid} {dur}s", flush=True)
                        continue
                    n = upload_symbol(
                        cur,
                        signal_symbol=spec.signal_symbol,
                        duration_sec=dur,
                        batch_size=args.batch_size,
                        source="yahoo_overseas",
                    )
                    print(f"[UP] {pid} {dur}s upserted≈{n}", flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
