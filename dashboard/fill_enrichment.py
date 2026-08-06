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


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# Exit fills keep action label only; SL/TP levels belong on the open fill.
EXIT_FILL_ACTIONS = frozenset(
    {
        "STOP_LOSS",
        "TAKE_PROFIT",
        "BOOT_FLATTEN",
        "EXIT",
        "FLAT",
        "FLAT_EXIT",
    }
)


def is_exit_fill_action(action: Any) -> bool:
    return str(action or "").upper() in EXIT_FILL_ACTIONS


def levels_scale_compatible(
    fill_price: Any,
    *levels: Any,
    max_ratio: float = 1.5,
    min_ratio: float = 0.67,
) -> bool:
    """Reject attaching overseas (~4k) levels onto domestic (~880) fills (and vice versa)."""
    px = finite_or_none(fill_price)
    if px is None or px <= 0:
        return True
    for raw in levels:
        level = finite_or_none(raw)
        if level is None or level <= 0:
            continue
        ratio = level / px
        if ratio > max_ratio or ratio < min_ratio:
            return False
    return True


def prefer_display_levels(payload: Any) -> dict[str, float | None]:
    """Domestic display_* from fill/strategy payload when present."""
    payload = payload if isinstance(payload, dict) else {}
    return {
        "entry_price": _first_finite(
            payload.get("display_entry_price"),
            payload.get("display_entry"),
        ),
        "stop_price": _first_finite(
            payload.get("display_stop_price"),
            payload.get("display_stop"),
        ),
        "take_price": _first_finite(
            payload.get("display_take_price"),
            payload.get("display_take"),
        ),
    }


def infer_exit_action(
    *,
    applied_action: Any,
    desired_position: Any = None,
    current_position: Any = None,
    reason_codes: Any = None,
) -> str | None:
    """Prefer explicit exit actions; flatten intents must not look like HOLD."""
    action = str(applied_action or "").upper() or None
    if action and is_exit_fill_action(action):
        return action
    try:
        desired = int(desired_position) if desired_position is not None else None
        current = int(current_position) if current_position is not None else None
    except (TypeError, ValueError):
        desired = None
        current = None
    reasons = reason_codes if isinstance(reason_codes, (list, tuple)) else ()
    reason_u = {str(r).upper() for r in reasons}
    if desired == 0 and current is not None and current != 0:
        if "STOP_LOSS" in reason_u or action == "STOP_LOSS":
            return "STOP_LOSS"
        if "TAKE_PROFIT" in reason_u or action == "TAKE_PROFIT":
            return "TAKE_PROFIT"
        if "BOOT_FLATTEN" in reason_u or "BOOT_FLATTEN_PENDING" in reason_u:
            return "BOOT_FLATTEN"
        if action in {None, "", "HOLD", "COOLDOWN_HOLD", "TARGET"}:
            return "FLAT_EXIT"
    return action


def enrichment_from_decision_payload(
    *,
    decision_id: str | None,
    legacy_signal: Any,
    applied_action: Any,
    payload: Any,
    risk_payload: Any = None,
    fill_price: Any = None,
    fill_payload: Any = None,
    desired_position: Any = None,
    current_position: Any = None,
    intent_reason_codes: Any = None,
) -> dict[str, Any]:
    """Build fill enrichment fields from decision (+ optional risk) payload.

    Prefer non-null stop/take/entry from any available source. Pretrade
    ``risk_decision_event`` often has null stops (RiskEngine does not copy
    them); the pipeline ``decision_event.payload.risk_decision`` usually has
    the armed ATR levels for TARGET opens.

    Levels are signal-space (overseas when pricing_basis=overseas). Domestic
    fill rows must not inherit overseas levels when the scale diverges.
    """
    payload = payload if isinstance(payload, dict) else {}
    risk_payload = risk_payload if isinstance(risk_payload, dict) else {}
    fill_payload = fill_payload if isinstance(fill_payload, dict) else {}
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

    # Prefer explicit domestic display levels from fill payload when present.
    display = prefer_display_levels(fill_payload)
    if display["entry_price"] is not None:
        entry = display["entry_price"]
    if display["stop_price"] is not None:
        stop = display["stop_price"]
    if display["take_price"] is not None:
        take = display["take_price"]
    price_basis = str(
        fill_payload.get("price_basis")
        or payload.get("price_basis")
        or ("domestic_display" if display["stop_price"] is not None else "signal")
    )

    signal = legacy_signal
    if signal is None and signal_obj.get("legacy_signal") is not None:
        signal = signal_obj.get("legacy_signal")
    try:
        signal_i = int(signal) if signal is not None else None
    except (TypeError, ValueError):
        signal_i = None

    reason_codes = payload.get("reason_codes")
    if not isinstance(reason_codes, list):
        reason_codes = (
            signal_obj.get("reason_codes")
            if isinstance(signal_obj.get("reason_codes"), list)
            else None
        )
    if intent_reason_codes and isinstance(intent_reason_codes, (list, tuple)):
        merged = list(intent_reason_codes)
        if reason_codes:
            merged.extend(reason_codes)
        reason_codes = merged

    action = infer_exit_action(
        applied_action=applied_action or payload.get("applied_action"),
        desired_position=desired_position
        if desired_position is not None
        else target.get("desired_position"),
        current_position=current_position
        if current_position is not None
        else target.get("current_position"),
        reason_codes=reason_codes,
    )
    regime = payload.get("regime") or factors.get("regime")

    # Exit rows: show the exit reason, not armed open targets.
    if is_exit_fill_action(action):
        stop = None
        take = None
        entry = None
    elif str(action or "").upper() in {"HOLD", "COOLDOWN_HOLD", ""} and not levels_scale_compatible(
        fill_price, entry, stop, take
    ):
        # Stale HOLD carrying overseas levels onto a domestic flatten/resync fill.
        stop = None
        take = None
        entry = None
        price_basis = "scale_mismatch"
    elif str(action or "").upper() == "TARGET":
        # Open fills: keep signal-space (overseas) SL/TP even when fill.price is domestic.
        price_basis = "signal" if display["stop_price"] is None else price_basis

    return {
        "decision_id": decision_id or payload.get("decision_id") or payload.get("bar_id"),
        "legacy_signal": signal_i,
        "applied_action": str(action) if action else None,
        "regime": str(regime) if regime else None,
        "reason_codes": reason_codes,
        "stop_price": stop,
        "take_price": take,
        "entry_price": entry,
        "price_basis": price_basis,
        "target_before": payload.get("target_before")
        if payload.get("target_before") is not None
        else _coerce_int(
            current_position if current_position is not None else target.get("current_position")
        ),
        "target_after": payload.get("target_after")
        if payload.get("target_after") is not None
        else _coerce_int(
            desired_position if desired_position is not None else target.get("desired_position")
        ),
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
        action = infer_exit_action(
            applied_action=row.get("applied_action"),
            desired_position=row.get("desired_position"),
            current_position=row.get("current_position"),
            reason_codes=row.get("reason_codes"),
        )
        if action:
            row["applied_action"] = action
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
        cand_stop = chosen.get("stop_price")
        cand_take = chosen.get("take_price")
        cand_entry = chosen.get("entry_price")
        if not levels_scale_compatible(row.get("price"), cand_entry, cand_stop, cand_take):
            out.append(row)
            continue
        if row.get("stop_price") is None:
            row["stop_price"] = cand_stop
        if row.get("take_price") is None:
            row["take_price"] = cand_take
        if row.get("entry_price") is None:
            row["entry_price"] = cand_entry
        out.append(row)
    return out
