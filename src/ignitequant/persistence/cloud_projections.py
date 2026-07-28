"""Upsert sim cockpit projection rows into Supabase (used by cloud_sync + backfill)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from psycopg2.extras import Json


def _as_iso(value: Any, fallback: str | None = None) -> str:
    if value is None or value == "":
        return fallback or datetime.now(timezone.utc).isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or (fallback or datetime.now(timezone.utc).isoformat())


def upsert_projection_for_event(
    cur,
    *,
    instance_key: str,
    event_type: str,
    aggregate_id: str,
    payload: Mapping[str, Any],
    occurred_at: str,
    owner_id_value: str | None,
) -> None:
    """Write typed projection row(s) for a single outbox event."""
    stamp = _as_iso(occurred_at)
    if event_type == "decision.appended":
        decision_id = str(payload.get("decision_id") or aggregate_id)
        cur.execute(
            """
            INSERT INTO sim_decision_projection(
                owner_id, instance_key, decision_id, bar_id, symbol,
                applied_action, target_before, target_after, legacy_signal,
                regime, factor_quality, factor_values_json, reason_codes_json,
                score_parts_json, risk_action, requested_position, approved_position,
                payload_json, occurred_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, NOW()
            )
            ON CONFLICT (instance_key, decision_id) DO UPDATE SET
                bar_id = EXCLUDED.bar_id,
                symbol = EXCLUDED.symbol,
                applied_action = EXCLUDED.applied_action,
                target_before = EXCLUDED.target_before,
                target_after = EXCLUDED.target_after,
                legacy_signal = EXCLUDED.legacy_signal,
                regime = COALESCE(EXCLUDED.regime, sim_decision_projection.regime),
                factor_quality = COALESCE(EXCLUDED.factor_quality, sim_decision_projection.factor_quality),
                factor_values_json = EXCLUDED.factor_values_json,
                reason_codes_json = EXCLUDED.reason_codes_json,
                score_parts_json = EXCLUDED.score_parts_json,
                risk_action = COALESCE(EXCLUDED.risk_action, sim_decision_projection.risk_action),
                requested_position = COALESCE(EXCLUDED.requested_position, sim_decision_projection.requested_position),
                approved_position = COALESCE(EXCLUDED.approved_position, sim_decision_projection.approved_position),
                payload_json = sim_decision_projection.payload_json || EXCLUDED.payload_json,
                occurred_at = EXCLUDED.occurred_at,
                updated_at = NOW(),
                owner_id = COALESCE(sim_decision_projection.owner_id, EXCLUDED.owner_id)
            """,
            (
                owner_id_value,
                instance_key,
                decision_id,
                payload.get("bar_id") or decision_id,
                payload.get("symbol"),
                payload.get("applied_action"),
                payload.get("target_before"),
                payload.get("target_after"),
                payload.get("legacy_signal"),
                payload.get("regime"),
                payload.get("factor_quality"),
                Json(payload.get("factor_values") or {}),
                Json(payload.get("reason_codes") or []),
                Json(payload.get("score_parts")) if payload.get("score_parts") is not None else None,
                payload.get("risk_action"),
                payload.get("requested_position"),
                payload.get("approved_position"),
                Json(dict(payload)),
                stamp,
            ),
        )
        return

    if event_type == "intent.submitted":
        intent_id = str(payload.get("intent_id") or aggregate_id)
        cur.execute(
            """
            INSERT INTO sim_intent_projection(
                owner_id, instance_key, intent_id, decision_id, symbol,
                current_position, desired_position, urgency, status, side, qty,
                idempotency_key, reason_codes_json, payload_json, occurred_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (instance_key, intent_id) DO UPDATE SET
                decision_id = EXCLUDED.decision_id,
                symbol = EXCLUDED.symbol,
                current_position = EXCLUDED.current_position,
                desired_position = EXCLUDED.desired_position,
                urgency = EXCLUDED.urgency,
                status = EXCLUDED.status,
                side = EXCLUDED.side,
                qty = EXCLUDED.qty,
                idempotency_key = EXCLUDED.idempotency_key,
                reason_codes_json = EXCLUDED.reason_codes_json,
                payload_json = sim_intent_projection.payload_json || EXCLUDED.payload_json,
                occurred_at = EXCLUDED.occurred_at,
                updated_at = NOW(),
                owner_id = COALESCE(sim_intent_projection.owner_id, EXCLUDED.owner_id)
            """,
            (
                owner_id_value,
                instance_key,
                intent_id,
                payload.get("decision_id"),
                payload.get("symbol"),
                payload.get("current_position"),
                payload.get("desired_position"),
                payload.get("urgency"),
                payload.get("status"),
                payload.get("side"),
                payload.get("qty"),
                payload.get("idempotency_key"),
                Json(payload.get("reason_codes") or []),
                Json(dict(payload)),
                stamp,
            ),
        )
        return

    if event_type == "fill.confirmed":
        fill_id = str(payload.get("fill_id") or aggregate_id)
        trade_time = _as_iso(payload.get("trade_time"), stamp)
        cur.execute(
            """
            INSERT INTO sim_fill_projection(
                owner_id, instance_key, fill_id, intent_id, symbol,
                price, qty, fee, side, trade_time, payload_json, occurred_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT (instance_key, fill_id) DO UPDATE SET
                intent_id = EXCLUDED.intent_id,
                symbol = EXCLUDED.symbol,
                price = EXCLUDED.price,
                qty = EXCLUDED.qty,
                fee = EXCLUDED.fee,
                side = EXCLUDED.side,
                trade_time = EXCLUDED.trade_time,
                payload_json = sim_fill_projection.payload_json || EXCLUDED.payload_json,
                occurred_at = EXCLUDED.occurred_at,
                updated_at = NOW(),
                owner_id = COALESCE(sim_fill_projection.owner_id, EXCLUDED.owner_id)
            """,
            (
                owner_id_value,
                instance_key,
                fill_id,
                payload.get("intent_id"),
                payload.get("symbol"),
                payload.get("price"),
                payload.get("qty"),
                payload.get("fee") or 0,
                payload.get("side"),
                trade_time,
                Json(dict(payload)),
                stamp,
            ),
        )
        return


def sim_instance_patch_from_payload(
    event_type: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Fields merged into sim_instance.payload_json for summary views."""
    patch: dict[str, Any] = {"last_event_type": event_type}
    for key in (
        "confirmed_net",
        "current_target",
        "last_price",
        "pending_desired",
        "runtime_state",
        "equity",
        "available",
        "margin",
        "margin_ratio",
        "net_position",
        "account_id",
    ):
        if key in payload and payload[key] is not None:
            patch[key] = payload[key]
    if event_type == "position.snapshot" and "net_position" in payload:
        patch["confirmed_net"] = payload["net_position"]
    if event_type == "account.snapshot":
        patch["account"] = {
            "equity": payload.get("equity"),
            "available": payload.get("available"),
            "margin": payload.get("margin"),
            "margin_ratio": payload.get("margin_ratio"),
            "realized_pnl_today": payload.get("realized_pnl_today"),
            "unrealized_pnl": payload.get("unrealized_pnl"),
            "as_of": payload.get("as_of"),
            "account_id": payload.get("account_id"),
        }
    if event_type == "position.snapshot":
        patch["position"] = {
            "symbol": payload.get("symbol"),
            "net_position": payload.get("net_position"),
            "source": payload.get("source"),
            "as_of": payload.get("as_of"),
            "average_entry_price": payload.get("average_entry_price"),
            "unrealized_pnl": payload.get("unrealized_pnl"),
            "margin": payload.get("margin"),
        }
    return patch
