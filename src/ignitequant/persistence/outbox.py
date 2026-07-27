"""Local sync outbox — trading truth stays local; cloud receives via push.

SoT rules (C architecture):
- Research / publications / ref_* / backtest_*: Supabase authority
- Trading events (decision/intent/order/fill/heartbeat): local authority + outbox
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Mapping


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(payload: Mapping[str, Any] | dict[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)


def enqueue_outbox(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: Mapping[str, Any],
    occurred_at: str | None = None,
    commit: bool = True,
) -> int:
    """Append one pending sync row. Never raises into trading path if commit fails caller handles."""
    cur = conn.execute(
        """
        INSERT INTO sync_outbox(
            instance_id, event_type, aggregate_type, aggregate_id,
            payload_json, occurred_at, created_at, sync_status, attempts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0)
        """,
        (
            instance_id,
            event_type,
            aggregate_type,
            aggregate_id,
            _dumps(payload),
            occurred_at or _utc_now(),
            _utc_now(),
        ),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def list_pending(conn: sqlite3.Connection, *, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM sync_outbox
        WHERE sync_status = 'pending'
        ORDER BY id ASC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_synced(conn: sqlite3.Connection, outbox_id: int) -> None:
    conn.execute(
        """
        UPDATE sync_outbox
        SET sync_status = 'synced', synced_at = ?, sync_error = NULL
        WHERE id = ?
        """,
        (_utc_now(), int(outbox_id)),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, outbox_id: int, error: str) -> None:
    conn.execute(
        """
        UPDATE sync_outbox
        SET attempts = attempts + 1,
            sync_error = ?,
            sync_status = CASE WHEN attempts + 1 >= 8 THEN 'dead' ELSE 'pending' END
        WHERE id = ?
        """,
        (error[:2000], int(outbox_id)),
    )
    conn.commit()
