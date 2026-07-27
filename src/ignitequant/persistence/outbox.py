"""Local sync outbox — trading truth stays local; cloud receives via push.

SoT rules (C architecture):
- Research / publications / ref_* / backtest_*: Supabase authority
- Trading events (decision/intent/order/fill/heartbeat): local authority + outbox
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(payload: Mapping[str, Any] | dict[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, default=str)


def _retry_delay_seconds(attempts: int) -> int:
    """Exponential backoff capped at 1 hour."""
    return min(3600, 30 * (2 ** min(max(attempts, 0), 6)))


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
            payload_json, occurred_at, created_at, sync_status, attempts, next_retry_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL)
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
          AND (
            next_retry_at IS NULL
            OR next_retry_at <= datetime('now')
          )
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
        SET sync_status = 'synced', synced_at = ?, sync_error = NULL, next_retry_at = NULL
        WHERE id = ?
        """,
        (_utc_now(), int(outbox_id)),
    )
    conn.commit()


def mark_failed(conn: sqlite3.Connection, outbox_id: int, error: str) -> None:
    row = conn.execute(
        "SELECT attempts FROM sync_outbox WHERE id = ?",
        (int(outbox_id),),
    ).fetchone()
    attempts = int(row["attempts"] or 0) if row is not None else 0
    next_attempts = attempts + 1
    delay = _retry_delay_seconds(next_attempts)
    next_retry = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
    status = "dead" if next_attempts >= 8 else "pending"
    conn.execute(
        """
        UPDATE sync_outbox
        SET attempts = ?,
            sync_error = ?,
            sync_status = ?,
            next_retry_at = CASE WHEN ? = 'pending' THEN ? ELSE NULL END
        WHERE id = ?
        """,
        (
            next_attempts,
            error[:2000],
            status,
            status,
            next_retry,
            int(outbox_id),
        ),
    )
    conn.commit()


def prune_synced(conn: sqlite3.Connection, *, keep_days: int = 7) -> int:
    """Delete old synced rows to keep outbox bounded."""
    cur = conn.execute(
        """
        DELETE FROM sync_outbox
        WHERE sync_status = 'synced'
          AND synced_at IS NOT NULL
          AND synced_at < datetime('now', ?)
        """,
        (f"-{int(keep_days)} days",),
    )
    conn.commit()
    return int(cur.rowcount)
