"""Closed round-trip positions derived from trade fills (cockpit history tab)."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ignitequant.market.margin_rates import multiplier_for_symbol


def _signed_qty(side: str, qty: int) -> int:
    s = str(side or "").upper()
    q = abs(int(qty))
    if s in {"SELL", "SHORT"}:
        return -q
    if s in {"BUY", "LONG"}:
        return q
    if "SELL" in s or "SHORT" in s:
        return -q
    return q


def _fill_time(f: Mapping[str, Any]) -> str | None:
    for key in ("trade_time", "created_at", "occurred_at", "as_of"):
        v = f.get(key)
        if v:
            return str(v)
    return None


def _fill_symbol(f: Mapping[str, Any], fallback: str = "") -> str:
    for key in ("symbol", "trade_symbol", "instrument"):
        v = f.get(key)
        if v:
            return str(v)
    return fallback


def iter_closed_rounds(
    fills: Sequence[Mapping[str, Any]],
    *,
    default_symbol: str = "",
    default_multiplier: float | None = None,
) -> list[dict[str, Any]]:
    """Walk fills ASC; emit one row each time net position returns to flat.

    Partial scale-outs accumulate into the same round until inventory is flat.
    Flips close the prior round then open a new residual side.
    """
    pos = 0
    avg = 0.0
    opened_at: str | None = None
    open_lots = 0  # peak lots opened in this round (for display)
    side_sign = 0  # +1 long / -1 short for the open round
    exit_notional = 0.0  # sum(price * close_qty) for VWAP exit
    exit_qty = 0
    round_gross = 0.0  # price PnL only
    round_fees = 0.0
    round_symbol = default_symbol
    closed: list[dict[str, Any]] = []

    def _mult(sym: str) -> float:
        if default_multiplier is not None:
            return float(default_multiplier)
        return float(multiplier_for_symbol(sym) or 1000.0)

    def _emit(exit_price: float, closed_at: str | None) -> None:
        nonlocal pos, avg, opened_at, open_lots, side_sign
        nonlocal exit_notional, exit_qty, round_gross, round_fees, round_symbol
        if open_lots <= 0 or side_sign == 0:
            return
        exit_vwap = (exit_notional / exit_qty) if exit_qty else exit_price
        closed.append(
            {
                "symbol": round_symbol or default_symbol,
                "side": "LONG" if side_sign > 0 else "SHORT",
                "side_label": "多" if side_sign > 0 else "空",
                "lots": int(exit_qty) if exit_qty else int(open_lots),
                "entry_price": float(avg),
                "exit_price": float(exit_vwap),
                "opened_at": opened_at,
                "closed_at": closed_at,
                "realized_pnl": float(round_gross - round_fees),
                "fees": float(round_fees),
            }
        )
        pos = 0
        avg = 0.0
        opened_at = None
        open_lots = 0
        side_sign = 0
        exit_notional = 0.0
        exit_qty = 0
        round_gross = 0.0
        round_fees = 0.0
        round_symbol = default_symbol

    for f in fills:
        side = str(f.get("side") or "").upper()
        qty = abs(int(f.get("qty") or 0))
        if qty <= 0:
            continue
        price = float(f.get("price") or 0)
        fee = float(f.get("fee") or 0)
        ts = _fill_time(f)
        sym = _fill_symbol(f, round_symbol or default_symbol)
        signed = _signed_qty(side, qty)
        mult = _mult(sym)

        if pos == 0:
            pos = signed
            avg = price
            opened_at = ts
            open_lots = abs(signed)
            side_sign = 1 if signed > 0 else -1
            round_fees = fee
            round_gross = 0.0
            round_symbol = sym
            exit_notional = 0.0
            exit_qty = 0
            continue

        # Reducing or flipping
        if (pos > 0 and signed < 0) or (pos < 0 and signed > 0):
            close_qty = min(abs(pos), abs(signed))
            direction = 1 if pos > 0 else -1
            fee_alloc = fee * (close_qty / max(qty, 1))
            round_gross += (price - avg) * close_qty * direction * mult
            round_fees += fee_alloc
            exit_notional += price * close_qty
            exit_qty += close_qty

            if abs(signed) < abs(pos):
                pos = pos + signed
                continue

            if abs(signed) == abs(pos):
                _emit(price, ts)
                continue

            # Flip: close old round, open residual opposite
            _emit(price, ts)
            remain = abs(signed) - close_qty
            remain_fee = fee * (remain / max(qty, 1))
            pos = remain if signed > 0 else -remain
            avg = price
            opened_at = ts
            open_lots = remain
            side_sign = 1 if signed > 0 else -1
            round_fees = remain_fee
            round_gross = 0.0
            round_symbol = sym
            exit_notional = 0.0
            exit_qty = 0
        else:
            # Adding same direction — update average entry
            new_abs = abs(pos) + qty
            avg = (avg * abs(pos) + price * qty) / max(new_abs, 1)
            pos = pos + signed
            open_lots = max(open_lots, abs(pos))
            round_fees += fee
            if sym:
                round_symbol = sym

    return closed


def closed_rounds_summary(rounds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pnls = [float(r.get("realized_pnl") or 0) for r in rounds]
    wins = sum(1 for p in pnls if p > 0)
    losses = sum(1 for p in pnls if p <= 0)
    n = len(pnls)
    return {
        "trade_count": n,
        "wins": wins,
        "losses": losses,
        "win_rate": (wins / n) if n else 0.0,
        "realized_pnl_proxy": sum(pnls),
    }
