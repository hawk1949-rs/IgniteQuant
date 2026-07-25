#!/usr/bin/env python
"""Verify Supabase / PostgreSQL connectivity from local .env (DATABASE_URL)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


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
    load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("ERROR: DATABASE_URL missing in .env", flush=True)
        return 1

    parsed = urlparse(url)
    host = parsed.hostname or "?"
    port = parsed.port or 5432
    db = (parsed.path or "/").lstrip("/") or "postgres"
    user = parsed.username or "?"
    print(f"Connecting: user={user} host={host} port={port} db={db}", flush=True)

    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary", flush=True)
        return 1

    try:
        conn = psycopg2.connect(url, connect_timeout=15)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("select version(), current_database(), current_user, now()")
            version, cur_db, cur_user, now = cur.fetchone()
            cur.execute(
                "select count(*) from information_schema.tables "
                "where table_schema not in ('pg_catalog', 'information_schema')"
            )
            (table_count,) = cur.fetchone()
        conn.close()
    except Exception as exc:  # noqa: BLE001 — connectivity probe
        print(f"FAIL: {type(exc).__name__}: {exc}", flush=True)
        print(
            "HINT: 公司网常见问题 — DNS 搜索域污染 / 仅 IPv6 直连不可达。"
            "请在 Supabase Dashboard → Project Settings → Database "
            "复制 Session pooler 连接串（通常含 pooler.supabase.com:6543，支持 IPv4），"
            "覆盖本地 .env 的 DATABASE_URL 后再跑本脚本。",
            flush=True,
        )
        return 2

    print(f"OK: database={cur_db} user={cur_user}", flush=True)
    print(f"OK: server_time={now}", flush=True)
    print(f"OK: user_tables={table_count}", flush=True)
    print(f"OK: version={version.split(',')[0]}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
