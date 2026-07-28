#!/usr/bin/env python3
"""Backfill local SQLite history into Supabase sim_*_projection + sim_instance.

Use once after enabling cockpit cloud read, so a home PC without local sqlite
can see past decisions/intents/fills/account summary.

Usage:
  PYTHONPATH=src python tools/backfill_sim_projections_to_supabase.py \\
    --db data/runtime/falcon_au_sim.sqlite
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _loads(raw: Any) -> Any:
    if raw is None:
        return {}
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(ROOT / "data" / "runtime" / "falcon_au_sim.sqlite"),
    )
    parser.add_argument("--instance-key", default=None, help="Override instance_key (default: from DB)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=50_000)
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT / "src"))
    from ignitequant.persistence.cloud_projections import (
        sim_instance_patch_from_payload,
        upsert_projection_for_event,
    )
    from ignitequant.persistence.cloud_sync import database_url, owner_id
    from ignitequant.persistence.sqlite import open_sqlite

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"ERROR: local db not found: {db_path}", flush=True)
        return 1

    url = database_url(root=ROOT)
    if not url:
        print("ERROR: DATABASE_URL missing", flush=True)
        return 1
    oid = owner_id(root=ROOT)

    conn = open_sqlite(db_path)
    state = conn.execute(
        "SELECT instance_id, strategy_id, symbol, runtime_state, payload_json FROM strategy_state LIMIT 1"
    ).fetchone()
    if state is None:
        print("ERROR: no strategy_state", flush=True)
        conn.close()
        return 1
    instance_key = args.instance_key or str(state["instance_id"])
    strategy_id = state["strategy_id"] or "falcon_v2"
    symbol = state["symbol"] or "au"

    decisions = conn.execute(
        """
        SELECT decision_id, bar_id, symbol, applied_action, target_before, target_after,
               legacy_signal, payload_json, created_at
        FROM decision_event WHERE instance_id = ?
        ORDER BY seq ASC LIMIT ?
        """,
        (instance_key, args.limit),
    ).fetchall()
    risk_by_decision: dict[str, Any] = {}
    for r in conn.execute(
        """
        SELECT decision_id, action, requested_position, approved_position, seq
        FROM risk_decision_event WHERE instance_id = ?
        ORDER BY seq ASC
        """,
        (instance_key,),
    ).fetchall():
        risk_by_decision[str(r["decision_id"])] = r
    intents = conn.execute(
        """
        SELECT intent_id, decision_id, symbol, current_position, desired_position,
               urgency, idempotency_key, status, reason_codes_json, payload_json, created_at
        FROM order_intent_event WHERE instance_id = ?
        ORDER BY seq ASC LIMIT ?
        """,
        (instance_key, args.limit),
    ).fetchall()
    fills = conn.execute(
        """
        SELECT fill_id, intent_id, symbol, price, qty, fee, side, trade_time,
               payload_json, created_at
        FROM trade_fill_event WHERE instance_id = ?
        ORDER BY seq ASC LIMIT ?
        """,
        (instance_key, args.limit),
    ).fetchall()
    account = conn.execute(
        """
        SELECT account_id, equity, available, margin, margin_ratio, as_of, created_at
        FROM account_snapshot_event WHERE instance_id = ?
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_key,),
    ).fetchone()
    position = conn.execute(
        """
        SELECT symbol, net_position, source, as_of, created_at
        FROM position_snapshot_event WHERE instance_id = ?
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_key,),
    ).fetchone()
    conn.close()

    print(
        f"backfill instance={instance_key} decisions={len(decisions)} "
        f"intents={len(intents)} fills={len(fills)}",
        flush=True,
    )
    if args.dry_run:
        return 0

    import psycopg2
    from psycopg2.extras import Json

    pg = psycopg2.connect(url, connect_timeout=20)
    pg.autocommit = False
    try:
        with pg.cursor() as cur:
            for d in decisions:
                payload_full = _loads(d["payload_json"])
                factors = payload_full.get("factors") or {}
                signal = payload_full.get("signal") or {}
                risk_row = risk_by_decision.get(str(d["decision_id"]))
                risk = payload_full.get("risk") or {}
                payload = {
                    "strategy_id": strategy_id,
                    "decision_id": d["decision_id"],
                    "bar_id": d["bar_id"],
                    "symbol": d["symbol"],
                    "applied_action": d["applied_action"],
                    "target_before": d["target_before"],
                    "target_after": d["target_after"],
                    "legacy_signal": d["legacy_signal"],
                    "regime": factors.get("regime"),
                    "factor_quality": factors.get("quality"),
                    "factor_values": factors.get("values") or {},
                    "reason_codes": factors.get("reason_codes")
                    or signal.get("reason_codes")
                    or [],
                    "score_parts": payload_full.get("legacy_score_parts"),
                    "risk_action": (risk_row["action"] if risk_row else None)
                    or (risk.get("action") if isinstance(risk, dict) else None),
                    "requested_position": (
                        risk_row["requested_position"] if risk_row else None
                    )
                    or (risk.get("requested_position") if isinstance(risk, dict) else None),
                    "approved_position": (
                        risk_row["approved_position"] if risk_row else None
                    )
                    or (risk.get("approved_position") if isinstance(risk, dict) else None),
                    "created_at": d["created_at"],
                }
                upsert_projection_for_event(
                    cur,
                    instance_key=instance_key,
                    event_type="decision.appended",
                    aggregate_id=str(d["decision_id"]),
                    payload=payload,
                    occurred_at=str(d["created_at"]),
                    owner_id_value=oid,
                )

            for it in intents:
                side = None
                qty = abs(int(it["desired_position"]) - int(it["current_position"]))
                payload = {
                    "strategy_id": strategy_id,
                    "intent_id": it["intent_id"],
                    "decision_id": it["decision_id"],
                    "symbol": it["symbol"],
                    "current_position": it["current_position"],
                    "desired_position": it["desired_position"],
                    "urgency": it["urgency"],
                    "idempotency_key": it["idempotency_key"],
                    "status": it["status"],
                    "side": side,
                    "qty": qty,
                    "reason_codes": _loads(it["reason_codes_json"]) or [],
                    "created_at": it["created_at"],
                }
                upsert_projection_for_event(
                    cur,
                    instance_key=instance_key,
                    event_type="intent.submitted",
                    aggregate_id=str(it["intent_id"]),
                    payload=payload,
                    occurred_at=str(it["created_at"]),
                    owner_id_value=oid,
                )

            for f in fills:
                payload = {
                    "strategy_id": strategy_id,
                    "fill_id": f["fill_id"],
                    "intent_id": f["intent_id"],
                    "symbol": f["symbol"],
                    "price": f["price"],
                    "qty": f["qty"],
                    "fee": f["fee"],
                    "side": f["side"],
                    "trade_time": f["trade_time"],
                }
                upsert_projection_for_event(
                    cur,
                    instance_key=instance_key,
                    event_type="fill.confirmed",
                    aggregate_id=str(f["fill_id"]),
                    payload=payload,
                    occurred_at=str(f["created_at"] or f["trade_time"]),
                    owner_id_value=oid,
                )

            patch: dict[str, Any] = {
                "last_event_type": "backfill",
                "symbol": symbol,
            }
            state_payload = _loads(state["payload_json"])
            for k in ("confirmed_net", "current_target", "last_price", "pending_desired"):
                if k in state_payload:
                    patch[k] = state_payload[k]
            if account is not None:
                patch.update(
                    sim_instance_patch_from_payload(
                        "account.snapshot",
                        {
                            "account_id": account["account_id"],
                            "equity": account["equity"],
                            "available": account["available"],
                            "margin": account["margin"],
                            "margin_ratio": account["margin_ratio"],
                            "as_of": account["as_of"],
                        },
                    )
                )
            if position is not None:
                patch.update(
                    sim_instance_patch_from_payload(
                        "position.snapshot",
                        {
                            "symbol": position["symbol"],
                            "net_position": position["net_position"],
                            "source": position["source"],
                            "as_of": position["as_of"],
                        },
                    )
                )

            symbol_id = "au"
            sl = str(symbol).lower()
            if "ag" in sl:
                symbol_id = "ag"
            elif "rb" in sl:
                symbol_id = "rb"
            elif "fg" in sl:
                symbol_id = "fg"

            cur.execute(
                """
                INSERT INTO sim_instance(
                    instance_key, strategy_id, symbol_id, framework, status,
                    runtime_state, last_synced_at, local_db_hint, payload_json,
                    updated_at, owner_id
                ) VALUES (
                    %s, %s, %s, 'tq', 'running', %s, NOW(), %s, %s, NOW(), %s
                )
                ON CONFLICT (instance_key) DO UPDATE SET
                    strategy_id = EXCLUDED.strategy_id,
                    symbol_id = COALESCE(NULLIF(EXCLUDED.symbol_id, ''), sim_instance.symbol_id),
                    runtime_state = COALESCE(EXCLUDED.runtime_state, sim_instance.runtime_state),
                    last_synced_at = NOW(),
                    local_db_hint = EXCLUDED.local_db_hint,
                    payload_json = sim_instance.payload_json || EXCLUDED.payload_json,
                    updated_at = NOW(),
                    owner_id = COALESCE(sim_instance.owner_id, EXCLUDED.owner_id)
                """,
                (
                    instance_key,
                    strategy_id,
                    symbol_id,
                    state["runtime_state"],
                    str(db_path),
                    Json(patch),
                    oid,
                ),
            )
        pg.commit()
    except Exception as exc:  # noqa: BLE001
        pg.rollback()
        print(f"FAIL: {type(exc).__name__}: {exc}", flush=True)
        pg.close()
        return 2
    finally:
        pg.close()

    print(f"OK backfilled projections for {instance_key}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
