"""Attach decision-time signal / stop / take onto fill rows."""

from __future__ import annotations

from typing import Any


def finite_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        x = float(value)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def _first_finite(*values: Any) -> float | None:
    for value in values:
        x = finite_or_none(value)
        if x is not None:
            return x
    return None


# Exit fills keep action label only; SL/TP levels belong on the open fill.
EXIT_FILL_ACTIONS = frozenset({"STOP_LOSS", "TAKE_PROFIT"})


def is_exit_fill_action(action: Any) -> bool:
    return str(action or "").upper() in EXIT_FILL_ACTIONS


def enrichment_from_decision_payload(
    *,
    decision_id: str | None,
    legacy_signal: Any,
    applied_action: Any,
    payload: Any,
    risk_payload: Any = None,
) -> dict[str, Any]:
    """Build fill enrichment fields from decision (+ optional risk) payload.

    Prefer non-null stop/take/entry from any available source. Pretrade
    ``risk_decision_event`` often has null stops (RiskEngine does not copy
    them); the pipeline ``decision_event.payload.risk_decision`` usually has
    the armed ATR levels for TARGET opens.
    """
    payload = payload if isinstance(payload, dict) else {}
    risk_payload = risk_payload if isinstance(risk_payload, dict) else {}
    nested = payload.get("risk_decision") or payload.get("risk") or {}
    if not isinstance(nested, dict):
        nested = {}
    target = payload.get("target") if isinstance(payload.get("target"), dict) else {}
    signal_obj = payload.get("signal") if isinstance(payload.get("signal"), dict) else {}
    factors = payload.get("factors") if isinstance(payload.get("factors"), dict) else {}

    stop = _first_finite(
        risk_payload.get("stop_price"),
        nested.get("stop_price"),
        target.get("planned_stop_price"),
        payload.get("stop_price"),
    )
    take = _first_finite(
        risk_payload.get("take_price"),
        nested.get("take_price"),
        payload.get("take_price"),
    )
    entry = _first_finite(
        risk_payload.get("entry_price"),
        nested.get("entry_price"),
        target.get("planned_entry_price"),
        payload.get("entry_price"),
    )

    signal = legacy_signal
    if signal is None and signal_obj.get("legacy_signal") is not None:
        signal = signal_obj.get("legacy_signal")
    try:
        signal_i = int(signal) if signal is not None else None
    except (TypeError, ValueError):
        signal_i = None

    action = applied_action or payload.get("applied_action")
    regime = payload.get("regime") or factors.get("regime")
    reason_codes = payload.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = (
            signal_obj.get("reason_codes")
            if isinstance(signal_obj.get("reason_codes"), list)
            else None
        )

    # STOP_LOSS / TAKE_PROFIT rows: show the exit reason, not armed targets.
    if is_exit_fill_action(action):
        stop = None
        take = None
        entry = None

    return {
        "decision_id": decision_id or payload.get("decision_id") or payload.get("bar_id"),
        "legacy_signal": signal_i,
        "applied_action": str(action) if action else None,
        "regime": str(regime) if regime else None,
        "reason_codes": reason_codes,
        "stop_price": stop,
        "take_price": take,
        "entry_price": entry,
        "target_before": payload.get("target_before"),
        "target_after": payload.get("target_after"),
    }


def apply_entry_stop_fallback(
    items: list[dict[str, Any]],
    entry_levels: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fill missing stop/take from the latest prior armed entry levels.

    Only applies to non-exit fills (opens / adds). Exit rows must not inherit
    open-position targets — cockpit shows action label only.
    """
    if not items or not entry_levels:
        return items
    ordered = sorted(
        (e for e in entry_levels if e.get("as_of") and e.get("stop_price") is not None),
        key=lambda e: str(e.get("as_of")),
    )
    if not ordered:
        return items

    out: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        if is_exit_fill_action(row.get("applied_action")):
            row["stop_price"] = None
            row["take_price"] = None
            row["entry_price"] = None
            out.append(row)
            continue
        if row.get("stop_price") is not None and row.get("take_price") is not None:
            out.append(row)
            continue
        ts = str(row.get("trade_time") or row.get("created_at") or "")
        chosen: dict[str, Any] | None = None
        for level in ordered:
            if str(level.get("as_of")) <= ts:
                chosen = level
            else:
                break
        if chosen is None:
            out.append(row)
            continue
        if row.get("stop_price") is None:
            row["stop_price"] = chosen.get("stop_price")
        if row.get("take_price") is None:
            row["take_price"] = chosen.get("take_price")
        if row.get("entry_price") is None:
            row["entry_price"] = chosen.get("entry_price")
        out.append(row)
    return out
