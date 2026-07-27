#!/usr/bin/env python3
"""Push local sync_outbox rows into Supabase trading_event_inbox + upsert sim_instance.

SoT: trading events remain authoritative in local SQLite; this is one-way sync.

Usage:
  PYTHONPATH=src python tools/sync_outbox_to_supabase.py --db data/runtime/falcon_au_sim.sqlite
  PYTHONPATH=src python tools/sync_outbox_to_supabase.py --db data/runtime/falcon_au_sim.sqlite --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(ROOT / "data" / "runtime" / "falcon_au_sim.sqlite"),
        help="Local runtime SQLite path",
    )
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--instance-key",
        default=None,
        help="Override instance_key written to sim_instance (default: from outbox rows)",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    url = os.environ.get("DATABASE_URL", "").strip()
    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"ERROR: local db not found: {db_path}", flush=True)
        return 1

    sys.path.insert(0, str(ROOT / "src"))
    from ignitequant.persistence.outbox import list_pending, mark_failed, mark_synced
    from ignitequant.persistence.sqlite import open_sqlite

    conn = open_sqlite(db_path)
    pending = list_pending(conn, limit=args.limit)
    print(f"pending_outbox={len(pending)} db={db_path}", flush=True)
    if not pending:
        conn.close()
        return 0

    if args.dry_run:
        for row in pending[:10]:
            print(
                f"  would sync id={row['id']} type={row['event_type']} "
                f"agg={row['aggregate_type']}:{row['aggregate_id']}",
                flush=True,
            )
        if len(pending) > 10:
            print(f"  ... and {len(pending) - 10} more", flush=True)
        conn.close()
        return 0

    if not url:
        print("ERROR: DATABASE_URL missing", flush=True)
        conn.close()
        return 1

    try:
        import psycopg2
        from psycopg2.extras import Json
    except ImportError:
        print("ERROR: psycopg2 not installed", flush=True)
        conn.close()
        return 1

    pg = psycopg2.connect(url, connect_timeout=20)
    pg.autocommit = True
    synced = 0
    failed = 0
    instance_keys: set[str] = set()

    with pg.cursor() as cur:
        for row in pending:
            instance_key = args.instance_key or str(row["instance_id"])
            instance_keys.add(instance_key)
            try:
                payload = json.loads(row["payload_json"])
                cur.execute(
                    """
                    INSERT INTO trading_event_inbox(
                        instance_key, local_outbox_id, event_type, aggregate_type,
                        aggregate_id, payload_json, occurred_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (instance_key, local_outbox_id) DO NOTHING
                    """,
                    (
                        instance_key,
                        int(row["id"]),
                        row["event_type"],
                        row["aggregate_type"],
                        row["aggregate_id"],
                        Json(payload),
                        row["occurred_at"],
                    ),
                )
                # Upsert sim_instance projection on heartbeats / any event
                status = "running"
                runtime_state = payload.get("runtime_state")
                symbol_id = payload.get("symbol") or payload.get("symbol_id") or ""
                strategy_id = payload.get("strategy_id") or "falcon_v2"
                # Prefer short product id if payload has trade symbol only
                if isinstance(symbol_id, str) and "." in symbol_id:
                    # keep as-is; registry may store trade symbol
                    pass
                cur.execute(
                    """
                    INSERT INTO sim_instance(
                        instance_key, strategy_id, symbol_id, framework, status,
                        runtime_state, last_heartbeat_at, last_synced_at,
                        local_db_hint, payload_json, updated_at
                    ) VALUES (
                        %s, %s, %s, 'tq', %s, %s,
                        CASE WHEN %s = 'heartbeat.tick' THEN NOW() ELSE NULL END,
                        NOW(), %s, %s, NOW()
                    )
                    ON CONFLICT (instance_key) DO UPDATE SET
                        strategy_id = EXCLUDED.strategy_id,
                        symbol_id = COALESCE(NULLIF(EXCLUDED.symbol_id, ''), sim_instance.symbol_id),
                        status = EXCLUDED.status,
                        runtime_state = COALESCE(EXCLUDED.runtime_state, sim_instance.runtime_state),
                        last_heartbeat_at = COALESCE(EXCLUDED.last_heartbeat_at, sim_instance.last_heartbeat_at),
                        last_synced_at = NOW(),
                        local_db_hint = EXCLUDED.local_db_hint,
                        payload_json = sim_instance.payload_json || EXCLUDED.payload_json,
                        updated_at = NOW()
                    """,
                    (
                        instance_key,
                        strategy_id,
                        str(symbol_id or "au"),
                        status,
                        runtime_state,
                        row["event_type"],
                        str(db_path),
                        Json({"last_event_type": row["event_type"], **{k: payload[k] for k in list(payload)[:20]}}),
                    ),
                )
                mark_synced(conn, int(row["id"]))
                synced += 1
            except Exception as exc:  # noqa: BLE001
                mark_failed(conn, int(row["id"]), f"{type(exc).__name__}: {exc}")
                failed += 1
                print(f"FAIL id={row['id']}: {type(exc).__name__}: {exc}", flush=True)

    pg.close()
    conn.close()
    print(
        f"OK synced={synced} failed={failed} instances={sorted(instance_keys)}",
        flush=True,
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
