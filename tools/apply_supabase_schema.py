#!/usr/bin/env python3
"""Apply all SQL files under supabase/migrations/ in name order.

Requires DATABASE_URL in environment or .env.
Usage:
  python tools/apply_supabase_schema.py
  python tools/apply_supabase_schema.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "supabase" / "migrations"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--only",
        default="",
        help="Substring filter, e.g. product_tenant_outbox",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if args.only:
        files = [f for f in files if args.only in f.name]
    if not files:
        print(f"ERROR: no migrations in {MIGRATIONS_DIR}", flush=True)
        return 1

    if args.dry_run:
        for f in files:
            print(f"DRY-RUN: {f.name} ({f.stat().st_size} bytes)", flush=True)
        return 0

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: DATABASE_URL missing. Set it in .env then retry.", flush=True)
        return 1

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed. pip install psycopg2-binary", flush=True)
        return 1

    print(f"Connecting and applying {len(files)} migration(s)…", flush=True)
    try:
        conn = psycopg2.connect(url, connect_timeout=20)
        conn.autocommit = True
        with conn.cursor() as cur:
            for path in files:
                sql = path.read_text(encoding="utf-8")
                print(f"  apply {path.name} …", flush=True)
                cur.execute(sql)
            cur.execute(
                """
                select table_name from information_schema.tables
                where table_schema='public'
                order by table_name
                """
            )
            tables = [r[0] for r in cur.fetchall()]
        conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}", flush=True)
        return 2

    print(f"OK: public_tables={len(tables)}", flush=True)
    for name in ("profiles", "strategy_publication", "sim_instance", "trading_event_inbox"):
        mark = "yes" if name in tables else "MISSING"
        print(f"  {name}: {mark}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
