#!/usr/bin/env python3
"""Apply Supabase L3–L4 schema + seed from local migration SQL.

Requires DATABASE_URL in environment or .env (never commit secrets).
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
MIGRATION = ROOT / "supabase" / "migrations" / "20260727000000_ref_and_research.sql"


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
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    if not MIGRATION.is_file():
        print(f"ERROR: migration not found: {MIGRATION}", flush=True)
        return 1

    sql = MIGRATION.read_text(encoding="utf-8")
    if args.dry_run:
        print(f"DRY-RUN: would apply {MIGRATION} ({len(sql)} bytes)", flush=True)
        return 0

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: DATABASE_URL missing. Set it in .env then retry.", flush=True)
        print(f"Migration file ready at: {MIGRATION}", flush=True)
        return 1

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed. pip install psycopg2-binary", flush=True)
        return 1

    print(f"Applying {MIGRATION.name} …", flush=True)
    try:
        conn = psycopg2.connect(url, connect_timeout=20)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(
                "SELECT product_id, name FROM ref_instrument ORDER BY product_id"
            )
            rows = cur.fetchall()
        conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}", flush=True)
        return 2

    print(f"OK: seeded {len(rows)} instruments: {', '.join(r[0] for r in rows)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
