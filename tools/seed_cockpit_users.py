#!/usr/bin/env python3
"""Create/update cockpit_users rows (hashed passwords) on Aliyun RDS.

Usage:
  PYTHONPATH=src python tools/seed_cockpit_users.py
  PYTHONPATH=src python tools/seed_cockpit_users.py --username hawk1949 --password 123456
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_USERS = (
    ("hawk1949", "123456", "Hawk"),
    ("jem083", "123456", "Jem"),
)


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


def ensure_table(conn) -> None:
    sql_path = ROOT / "supabase" / "rds" / "002_cockpit_users.sql"
    with conn.cursor() as cur:
        cur.execute(sql_path.read_text(encoding="utf-8"))
    conn.commit()


def upsert_user(conn, username: str, password: str, display_name: str | None) -> None:
    from dashboard.auth import hash_password

    pwd_hash = hash_password(password)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.cockpit_users (username, password_hash, display_name, is_active)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (username) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                display_name = COALESCE(EXCLUDED.display_name, public.cockpit_users.display_name),
                is_active = TRUE,
                updated_at = NOW()
            """,
            (username, pwd_hash, display_name),
        )
    conn.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username")
    parser.add_argument("--password")
    parser.add_argument("--display-name", default=None)
    parser.add_argument(
        "--defaults",
        action="store_true",
        help="seed hawk1949 + jem083 (default when no --username)",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    url = database_url()
    if not url:
        print("ERROR: set DATABASE_URL or RDS_DATABASE_URL", flush=True)
        return 1

    import psycopg2

    conn = psycopg2.connect(url, connect_timeout=30)
    try:
        ensure_table(conn)
        users: list[tuple[str, str, str | None]]
        if args.username:
            if not args.password:
                print("ERROR: --password required with --username", flush=True)
                return 1
            users = [(args.username, args.password, args.display_name)]
        else:
            users = [(u, p, d) for u, p, d in DEFAULT_USERS]

        for username, password, display in users:
            upsert_user(conn, username, password, display)
            print(f"upserted {username}", flush=True)

        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, is_active, updated_at FROM public.cockpit_users ORDER BY username"
            )
            rows = cur.fetchall()
        print(f"cockpit_users count={len(rows)}", flush=True)
        for row in rows:
            print(f"  {row[0]} active={row[1]} updated={row[2]}", flush=True)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
