"""Push local sync_outbox → Supabase trading_event_inbox + sim_instance.

Safe to call from the trading loop: failures are swallowed by callers.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def database_url(*, root: Path | None = None) -> str:
    if root is not None:
        _load_dotenv(root / ".env")
    return os.environ.get("DATABASE_URL", "").strip()


def owner_id(*, root: Path | None = None) -> str | None:
    if root is not None:
        _load_dotenv(root / ".env")
    value = os.environ.get("SUPABASE_OWNER_ID", "").strip()
    return value or None


def _map_sim_status(runtime_state: str | None, event_type: str) -> str:
    state = (runtime_state or "").upper()
    if state in {"HALT", "SHUTDOWN"}:
        return "error"
    if state in {"DEGRADED", "STALE"}:
        return "stale"
    if event_type == "heartbeat.tick":
        return "running"
    return "running"


def push_outbox_once(
    conn: sqlite3.Connection,
    *,
    database_url: str,
    db_hint: str = "",
    limit: int = 200,
    instance_key_override: str | None = None,
    owner_id_value: str | None = None,
) -> dict[str, Any]:
    """Push pending outbox rows. Returns counts; raises only on hard import/connect errors
    that callers may choose to catch.
    """
    from ignitequant.persistence.outbox import list_pending, mark_failed, mark_synced, prune_synced

    if not database_url:
        return {"synced": 0, "failed": 0, "pending": 0, "skipped": "no_database_url"}

    pending = list_pending(conn, limit=limit)
    if not pending:
        return {"synced": 0, "failed": 0, "pending": 0}

    import psycopg2
    from psycopg2.extras import Json

    pg = psycopg2.connect(database_url, connect_timeout=8)
    pg.autocommit = False
    synced = 0
    failed = 0
    instance_keys: set[str] = set()

    try:
        with pg.cursor() as cur:
            for row in pending:
                instance_key = instance_key_override or str(row["instance_id"])
                instance_keys.add(instance_key)
                try:
                    payload = json.loads(row["payload_json"])
                    status = _map_sim_status(
                        payload.get("runtime_state"),
                        str(row["event_type"]),
                    )
                    cur.execute(
                        """
                        INSERT INTO trading_event_inbox(
                            instance_key, local_outbox_id, event_type, aggregate_type,
                            aggregate_id, payload_json, occurred_at, owner_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                            owner_id_value,
                        ),
                    )
                    symbol_id = payload.get("symbol") or payload.get("symbol_id") or "au"
                    strategy_id = payload.get("strategy_id") or "falcon_v2"
                    runtime_state = payload.get("runtime_state")
                    cur.execute(
                        """
                        INSERT INTO sim_instance(
                            instance_key, strategy_id, symbol_id, framework, status,
                            runtime_state, last_heartbeat_at, last_synced_at,
                            local_db_hint, payload_json, updated_at, owner_id
                        ) VALUES (
                            %s, %s, %s, 'tq', %s, %s,
                            CASE WHEN %s = 'heartbeat.tick' THEN NOW() ELSE NULL END,
                            NOW(), %s, %s, NOW(), %s
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
                            updated_at = NOW(),
                            owner_id = COALESCE(sim_instance.owner_id, EXCLUDED.owner_id)
                        """,
                        (
                            instance_key,
                            strategy_id,
                            str(symbol_id),
                            status,
                            runtime_state,
                            row["event_type"],
                            db_hint,
                            Json(
                                {
                                    "last_event_type": row["event_type"],
                                    **{
                                        k: payload[k]
                                        for k in (
                                            "confirmed_net",
                                            "current_target",
                                            "last_price",
                                            "pending_desired",
                                        )
                                        if k in payload
                                    },
                                }
                            ),
                            owner_id_value,
                        ),
                    )
                    pg.commit()
                    mark_synced(conn, int(row["id"]))
                    synced += 1
                except Exception as exc:  # noqa: BLE001
                    pg.rollback()
                    mark_failed(conn, int(row["id"]), f"{type(exc).__name__}: {exc}")
                    failed += 1
    finally:
        pg.close()

    try:
        prune_synced(conn, keep_days=7)
    except Exception:
        pass

    return {
        "synced": synced,
        "failed": failed,
        "pending": len(pending),
        "instances": sorted(instance_keys),
    }


def try_push_outbox(
    conn: sqlite3.Connection | None,
    *,
    root: Path | None = None,
    db_hint: str = "",
    limit: int = 200,
    instance_key: str | None = None,
) -> dict[str, Any]:
    """Best-effort wrapper for runners. Never raises."""
    if conn is None:
        return {"synced": 0, "failed": 0, "pending": 0, "skipped": "no_conn"}
    try:
        url = database_url(root=root)
        return push_outbox_once(
            conn,
            database_url=url,
            db_hint=db_hint,
            limit=limit,
            instance_key_override=instance_key,
            owner_id_value=owner_id(root=root),
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "synced": 0,
            "failed": 0,
            "pending": -1,
            "skipped": f"{type(exc).__name__}: {exc}",
        }
