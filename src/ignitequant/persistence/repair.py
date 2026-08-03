"""Repair helpers for local trading SQLite (async fill backfill)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(raw: str | None) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _decision_close_price(
    conn: sqlite3.Connection, instance_id: str, decision_id: str
) -> float | None:
    row = conn.execute(
        """
        SELECT payload_json FROM decision_event
        WHERE instance_id = ? AND (decision_id = ? OR bar_id = ?)
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_id, decision_id, decision_id),
    ).fetchone()
    if row is None:
        return None
    payload = _loads(row["payload_json"])
    factors = payload.get("factors") if isinstance(payload, dict) else None
    values = (factors or {}).get("values") if isinstance(factors, dict) else None
    close = (values or {}).get("close") if isinstance(values, dict) else None
    try:
        price = float(close)
        return price if price > 0 else None
    except (TypeError, ValueError):
        return None


def _latest_avg_entry_price(
    conn: sqlite3.Connection, instance_id: str, *, desired_net: int
) -> float | None:
    """Prefer broker avg entry when backfilling fills (avoid overseas decision close)."""
    row = conn.execute(
        """
        SELECT avg_entry_price, net_position FROM position_snapshot_event
        WHERE instance_id = ? AND net_position = ?
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_id, int(desired_net)),
    ).fetchone()
    if row is None or row["avg_entry_price"] is None:
        return None
    try:
        price = float(row["avg_entry_price"])
        return price if price > 0 else None
    except (TypeError, ValueError):
        return None


def _fill_price_for_repair(
    conn: sqlite3.Connection,
    instance_id: str,
    *,
    decision_id: str,
    desired_net: int,
) -> float | None:
    avg = _latest_avg_entry_price(conn, instance_id, desired_net=desired_net)
    close = _decision_close_price(conn, instance_id, decision_id)
    if avg is not None and close is not None and close > 0:
        # Domestic AU ~800–1000 vs overseas ~4000: prefer avg when scales diverge.
        if abs(close / avg - 1.0) > 0.2:
            return avg
    if avg is not None:
        return avg
    return close


def repair_missing_fills(db_path: Path | str, instance_id: str) -> int:
    """Persist fills for intents that clearly reached desired net (async TargetPosTask)."""
    path = Path(db_path)
    if not path.is_file():
        return 0
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    repaired = 0
    try:
        intents = conn.execute(
            """
            SELECT intent_id, decision_id, symbol, current_position, desired_position,
                   status, created_at
            FROM order_intent_event
            WHERE instance_id = ?
            ORDER BY seq ASC
            """,
            (instance_id,),
        ).fetchall()
        filled_ids = {
            str(r["intent_id"])
            for r in conn.execute(
                "SELECT intent_id FROM trade_fill_event WHERE instance_id = ?",
                (instance_id,),
            ).fetchall()
        }
        latest_pos = conn.execute(
            """
            SELECT net_position FROM position_snapshot_event
            WHERE instance_id = ?
            ORDER BY seq DESC LIMIT 1
            """,
            (instance_id,),
        ).fetchone()
        latest_net = int(latest_pos["net_position"]) if latest_pos is not None else None
        if latest_net is None:
            state = conn.execute(
                "SELECT payload_json FROM strategy_state WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            if state is not None:
                payload = _loads(state["payload_json"])
                try:
                    latest_net = int(payload.get("confirmed_net"))
                except (TypeError, ValueError):
                    latest_net = None

        for i, intent in enumerate(intents):
            intent_id = str(intent["intent_id"])
            if intent_id in filled_ids:
                continue
            status = str(intent["status"] or "")
            if status == "FILLED":
                continue
            cur = int(intent["current_position"])
            desired = int(intent["desired_position"])
            if cur == desired:
                continue
            reached = False
            trade_time = str(intent["created_at"] or "")
            if i + 1 < len(intents):
                nxt = intents[i + 1]
                if int(nxt["current_position"]) == desired:
                    reached = True
                    trade_time = str(nxt["created_at"] or trade_time)
            elif latest_net is not None and latest_net == desired:
                reached = True
            if not reached:
                continue

            price = _fill_price_for_repair(
                conn,
                instance_id,
                decision_id=str(intent["decision_id"] or ""),
                desired_net=desired,
            )
            if price is None:
                continue
            qty = abs(desired - cur)
            side = "BUY" if desired > cur else "SELL"
            fill_id = f"fill-backfill-{intent_id}"
            now = _utc_now()
            conn.execute(
                """
                INSERT OR IGNORE INTO trade_fill_event(
                    instance_id, fill_id, intent_id, symbol, price, qty, fee,
                    side, trade_time, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instance_id,
                    fill_id,
                    intent_id,
                    str(intent["symbol"] or ""),
                    float(price),
                    int(qty),
                    0.0,
                    side,
                    trade_time or now,
                    json.dumps(
                        {
                            "source": "intent_chain_backfill",
                            "intent_id": intent_id,
                            "note": "异步成交补记：意图后持仓已到达目标",
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE order_intent_event
                SET status = ?
                WHERE instance_id = ? AND intent_id = ?
                """,
                ("FILLED", instance_id, intent_id),
            )
            repaired += 1
        if repaired:
            conn.commit()
    finally:
        conn.close()
    return repaired
