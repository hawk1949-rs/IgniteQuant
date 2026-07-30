"""Cockpit open-position row builder (local SQLite + cloud summary)."""

from __future__ import annotations

from typing import Any

from ignitequant.market.margin_rates import (
    estimate_margin_for_symbol,
    margin_rate_for_symbol,
    multiplier_for_symbol,
)


def open_positions_view(
    *,
    position: dict[str, Any] | None,
    account: dict[str, Any] | None,
    state_payload: dict[str, Any] | None,
    last_price: float | None,
    multiplier: float | None = None,
) -> list[dict[str, Any]]:
    """Single-symbol open position row for cockpit (net!=0)."""
    if not position:
        return []
    net = int(position.get("net_position") or 0)
    if net == 0:
        return []
    payload = state_payload if isinstance(state_payload, dict) else {}
    symbol = str(position.get("symbol") or "")
    avg = position.get("average_entry_price")
    if avg is None and payload.get("display_entry_price") is not None:
        try:
            avg = float(payload["display_entry_price"])
        except (TypeError, ValueError):
            avg = None
    if avg is None and payload.get("entry_price") is not None:
        try:
            avg = float(payload["entry_price"])
        except (TypeError, ValueError):
            avg = None
    mult = multiplier
    if mult is None:
        mult = multiplier_for_symbol(symbol) or 1000.0
    upnl = position.get("unrealized_pnl")
    if (upnl is None or float(upnl) == 0) and avg is not None and last_price is not None:
        direction = 1 if net > 0 else -1
        upnl = (float(last_price) - float(avg)) * abs(net) * float(mult) * direction

    margin_rate = margin_rate_for_symbol(symbol)
    margin = float(position.get("margin") or 0)
    px = float(last_price) if last_price is not None else (float(avg) if avg is not None else None)
    if px is not None and px > 0:
        est, rate, used_mult = estimate_margin_for_symbol(
            symbol, price=px, lots=net, multiplier=float(mult)
        )
        if est is not None:
            margin = float(est)
            margin_rate = rate
            mult = used_mult
    if margin <= 0 and account:
        margin = float(account.get("margin") or 0)

    return [
        {
            "symbol": symbol,
            "side": "LONG" if net > 0 else "SHORT",
            "side_label": "多" if net > 0 else "空",
            "lots": abs(net),
            "net_position": net,
            "average_entry_price": float(avg) if avg is not None else None,
            "last_price": float(last_price) if last_price is not None else None,
            "unrealized_pnl": float(upnl or 0),
            "margin": margin,
            "margin_rate": float(margin_rate) if margin_rate is not None else None,
            "margin_rate_pct": float(margin_rate) * 100.0 if margin_rate is not None else None,
            "margin_source": "ref_product_margin" if margin_rate is not None else "broker",
            "source": position.get("source"),
            "as_of": position.get("as_of") or position.get("created_at"),
            "stop_price": payload.get("display_stop_price", payload.get("stop_price")),
            "take_price": payload.get("display_take_price", payload.get("take_price")),
        }
    ]
