#!/usr/bin/env python3
"""Apply Aliyun RDS schema (supabase/rds/*.sql) using RDS_DATABASE_URL.

Usage:
  PYTHONPATH=src python tools/apply_rds_schema.py
  PYTHONPATH=src python tools/apply_rds_schema.py --dry-run
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "supabase" / "rds"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def database_url() -> str:
    return (
        os.environ.get("RDS_DATABASE_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    files = sorted(SCHEMA_DIR.glob("*.sql"))
    if not files:
        print(f"ERROR: no SQL in {SCHEMA_DIR}", flush=True)
        return 1

    if args.dry_run:
        for f in files:
            print(f"DRY-RUN: {f.name} ({f.stat().st_size} bytes)", flush=True)
        return 0

    url = database_url()
    if not url:
        print(
            "ERROR: set RDS_DATABASE_URL (preferred) or DATABASE_URL in .env",
            flush=True,
        )
        return 1

    try:
        import psycopg2
    except ImportError:
        print("ERROR: pip install psycopg2-binary", flush=True)
        return 1

    # Refuse accidental apply against Supabase host when only DATABASE_URL is set.
    host_hint = url.split("@")[-1].split("/")[0].lower()
    if "supabase.co" in host_hint and not os.environ.get("RDS_DATABASE_URL", "").strip():
        print(
            "ERROR: DATABASE_URL points at Supabase. Set RDS_DATABASE_URL to the Aliyun RDS URL.",
            flush=True,
        )
        return 1

    print(f"Applying {len(files)} RDS schema file(s)…", flush=True)
    try:
        conn = psycopg2.connect(url, connect_timeout=30)
        conn.autocommit = True
        with conn.cursor() as cur:
            for path in files:
                sql = path.read_text(encoding="utf-8")
                print(f"  apply {path.name} …", flush=True)
                cur.execute(sql)
            cur.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )
            tables = [r[0] for r in cur.fetchall()]
        conn.close()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", flush=True)
        return 1

    print(f"OK: public tables ({len(tables)}): {', '.join(tables)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
