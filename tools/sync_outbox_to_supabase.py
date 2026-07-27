#!/usr/bin/env python3
"""Push local sync_outbox rows into Supabase (CLI wrapper).

Sim runners already auto-sync on heartbeat; use this for catch-up / debug.

Usage:
  PYTHONPATH=src python tools/sync_outbox_to_supabase.py --db data/runtime/falcon_au_sim.sqlite
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(ROOT / "data" / "runtime" / "falcon_au_sim.sqlite"),
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--instance-key", default=None)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from ignitequant.persistence.cloud_sync import database_url, push_outbox_once, try_push_outbox
    from ignitequant.persistence.outbox import list_pending
    from ignitequant.persistence.sqlite import open_sqlite

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"ERROR: local db not found: {db_path}", flush=True)
        return 1

    conn = open_sqlite(db_path)
    pending = list_pending(conn, limit=args.limit)
    print(f"pending_outbox={len(pending)} db={db_path}", flush=True)
    if args.dry_run:
        for row in pending[:10]:
            print(
                f"  would sync id={row['id']} type={row['event_type']} "
                f"agg={row['aggregate_type']}:{row['aggregate_id']}",
                flush=True,
            )
        conn.close()
        return 0

    url = database_url(root=ROOT)
    if not url:
        print("ERROR: DATABASE_URL missing", flush=True)
        conn.close()
        return 1

    try:
        result = push_outbox_once(
            conn,
            database_url=url,
            db_hint=str(db_path),
            limit=args.limit,
            instance_key_override=args.instance_key,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}", flush=True)
        conn.close()
        return 2

    conn.close()
    print(
        f"OK synced={result.get('synced', 0)} failed={result.get('failed', 0)} "
        f"instances={result.get('instances', [])}",
        flush=True,
    )
    return 0 if int(result.get("failed") or 0) == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
