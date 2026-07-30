"""Closed round-trip positions derived from trade fills (cockpit history tab)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

from ignitequant.market.margin_rates import multiplier_for_symbol

# Synthetic / repaired fills must not drive cockpit PnL (they never hit Tq equity).
EXCLUDED_FILL_SOURCES = frozenset(
    {
        "intent_chain_backfill",
    }
)


def _loads_payload(f: Mapping[str, Any]) -> dict[str, Any]:
    payload = f.get("payload")
    if isinstance(payload, dict):
        return payload
    raw = f.get("payload_json")
    if isinstance(raw, str) and raw.strip():
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def fill_source(f: Mapping[str, Any]) -> str | None:
    if f.get("fill_source"):
        return str(f.get("fill_source"))
    payload = _loads_payload(f)
    src = payload.get("source")
    return str(src) if src else None


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


def prepare_fills_for_rounds(
    fills: Sequence[Mapping[str, Any]],
    *,
    prior_net: int | None = None,
    prior_avg_price: float | None = None,
) -> list[dict[str, Any]]:
    """Drop synthetic fills and seed broker inventory so FIFO matches account life.

    Boot flatten often records a close while the open was never in the ledger.
    Without a seed open, that close is treated as a new short/long and poisons
    every subsequent round's realized PnL.
    """
    cleaned: list[dict[str, Any]] = []
    for f in fills:
        src = fill_source(f)
        if src in EXCLUDED_FILL_SOURCES:
            continue
        cleaned.append(dict(f))

    prior = int(prior_net or 0)
    if not cleaned or prior == 0:
        return cleaned

    first = cleaned[0]
    qty0 = abs(int(first.get("qty") or 0))
    if qty0 <= 0:
        return cleaned
    first_signed = _signed_qty(str(first.get("side") or ""), qty0)
    reduces_prior = (prior > 0 and first_signed < 0) or (prior < 0 and first_signed > 0)
    if not reduces_prior:
        return cleaned

    seed_price = (
        float(prior_avg_price)
        if prior_avg_price is not None and float(prior_avg_price) > 0
        else float(first.get("price") or 0)
    )
    if seed_price <= 0:
        return cleaned

    seed = {
        "symbol": _fill_symbol(first),
        "side": "BUY" if prior > 0 else "SELL",
        "qty": abs(prior),
        "price": seed_price,
        "fee": 0.0,
        "trade_time": _fill_time(first),
        "created_at": _fill_time(first),
        "payload": {
            "source": "broker_inventory_seed",
            "note": "补齐启动前券商持仓，避免 BOOT 平仓把 FIFO 相位打乱",
        },
        "fill_source": "broker_inventory_seed",
    }
    return [seed, *cleaned]


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


def account_realized_pnl(*, equity: float, init_balance: float, unrealized: float) -> float:
    """Broker-consistent realized ≈ equity − init − floating."""
    return float(equity) - float(init_balance) - float(unrealized or 0)


def _ts(value: Any) -> str:
    return str(value or "")


def _equity_near(
    accounts: Sequence[Mapping[str, Any]], ts: str, *, prefer: str = "after"
) -> float | None:
    """Pick equity snapshot nearest to ts (after preferred for open, before/after for close)."""
    if not accounts or not ts:
        return None
    dated: list[tuple[str, float]] = []
    for a in accounts:
        stamp = _ts(a.get("as_of") or a.get("created_at"))
        try:
            eq = float(a.get("equity"))
        except (TypeError, ValueError):
            continue
        if stamp:
            dated.append((stamp, eq))
    if not dated:
        return None
    dated.sort(key=lambda x: x[0])
    if prefer == "before":
        prev = None
        for stamp, eq in dated:
            if stamp <= ts:
                prev = eq
            else:
                break
        if prev is not None:
            return prev
        return dated[0][1]
    # after (default)
    for stamp, eq in dated:
        if stamp >= ts:
            return eq
    return dated[-1][1]


def _parse_ts(value: Any) -> datetime | None:
    text = _ts(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _live_fills_in_window(
    fills: Sequence[Mapping[str, Any]], opened_at: str, closed_at: str
) -> list[Mapping[str, Any]]:
    """Include live fills around the broker episode (ms skew between fill & snapshot)."""
    open_dt = _parse_ts(opened_at)
    close_dt = _parse_ts(closed_at)
    pad = timedelta(seconds=5)
    out: list[Mapping[str, Any]] = []
    for f in fills:
        if fill_source(f) in EXCLUDED_FILL_SOURCES:
            continue
        ts = _fill_time(f) or ""
        if not ts:
            continue
        fdt = _parse_ts(ts)
        if fdt is not None and open_dt is not None and close_dt is not None:
            if fdt < open_dt - pad or fdt > close_dt + pad:
                continue
        else:
            if opened_at and ts < opened_at:
                continue
            if closed_at and ts > closed_at:
                continue
        out.append(f)
    return out


def _vwap(fills: Sequence[Mapping[str, Any]]) -> float | None:
    notional = 0.0
    qty = 0
    for f in fills:
        q = abs(int(f.get("qty") or 0))
        if q <= 0:
            continue
        try:
            px = float(f.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if px <= 0:
            continue
        notional += px * q
        qty += q
    if qty <= 0:
        return None
    return notional / qty


# Restart / inventory probes are not real open→close trading episodes.
IGNORED_POSITION_SOURCES = frozenset(
    {
        "broker_startup",
        "broker_boot_flatten",
    }
)


def iter_closed_rounds_from_broker(
    position_snapshots: Sequence[Mapping[str, Any]],
    *,
    account_snapshots: Sequence[Mapping[str, Any]] | None = None,
    fills: Sequence[Mapping[str, Any]] | None = None,
    default_symbol: str = "",
) -> list[dict[str, Any]]:
    """Build closed rounds from 天勤 position net transitions (0 → held → 0).

    Row PnL is **price PnL** from live fills (open/close VWAP × lots × multiplier).
    Do NOT use holding-window equity delta as row PnL — those do not sum to
    account total (equity also moves while flat / overnight).

    Snapshots from ``broker_startup`` / ``broker_boot_flatten`` are ignored so a
    restart does not invent a zero-duration phantom round.
    """
    accounts = list(account_snapshots or [])
    fill_rows = list(fills or [])
    closed: list[dict[str, Any]] = []

    open_at: str | None = None
    open_net = 0
    peak_lots = 0
    symbol = default_symbol
    open_avg: float | None = None

    def _emit(closed_at: str, close_source: str | None) -> None:
        nonlocal open_at, open_net, peak_lots, symbol, open_avg
        if not open_at or open_net == 0 or peak_lots <= 0:
            open_at = None
            open_net = 0
            peak_lots = 0
            open_avg = None
            return
        side = "LONG" if open_net > 0 else "SHORT"
        window_fills = _live_fills_in_window(fill_rows, open_at, closed_at)
        entry_fills = []
        exit_fills = []
        for f in window_fills:
            signed = _signed_qty(str(f.get("side") or ""), abs(int(f.get("qty") or 0)))
            if open_net > 0:
                (entry_fills if signed > 0 else exit_fills).append(f)
            else:
                (entry_fills if signed < 0 else exit_fills).append(f)
        entry_px = _vwap(entry_fills)
        exit_px = _vwap(exit_fills)
        if entry_px is None and open_avg is not None:
            entry_px = float(open_avg)
        if entry_px is None and exit_px is not None:
            entry_px = exit_px
        if exit_px is None and entry_px is not None:
            exit_px = entry_px

        fees = sum(float(f.get("fee") or 0) for f in window_fills)
        mult = float(multiplier_for_symbol(symbol) or 1000.0)
        direction = 1 if open_net > 0 else -1
        if entry_px is not None and exit_px is not None:
            price_pnl = (exit_px - entry_px) * peak_lots * direction * mult - fees
        else:
            price_pnl = 0.0

        eq_open = _equity_near(accounts, open_at, prefer="after")
        eq_close = _equity_near(accounts, closed_at, prefer="after")
        equity_path = (
            float(eq_close) - float(eq_open)
            if eq_open is not None and eq_close is not None
            else None
        )

        closed.append(
            {
                "round_id": f"broker-{len(closed)}-{open_at}",
                "symbol": symbol or default_symbol,
                "side": side,
                "side_label": "多" if side == "LONG" else "空",
                "lots": int(peak_lots),
                "entry_price": float(entry_px) if entry_px is not None else 0.0,
                "exit_price": float(exit_px) if exit_px is not None else 0.0,
                "opened_at": open_at,
                "closed_at": closed_at,
                "realized_pnl": float(price_pnl),
                "fees": float(fees),
                "equity_path_pnl": equity_path,
                "source": "broker_position",
                "close_source": close_source,
            }
        )
        open_at = None
        open_net = 0
        peak_lots = 0
        open_avg = None

    for snap in position_snapshots:
        src = str(snap.get("source") or "")
        if src in IGNORED_POSITION_SOURCES:
            continue
        try:
            net = int(snap.get("net_position") or 0)
        except (TypeError, ValueError):
            continue
        ts = _ts(snap.get("as_of") or snap.get("created_at"))
        if not ts:
            continue
        sym = str(snap.get("symbol") or "") or symbol
        if sym:
            symbol = sym
        avg = snap.get("average_entry_price") or snap.get("avg_entry_price")
        try:
            avg_f = float(avg) if avg is not None else None
        except (TypeError, ValueError):
            avg_f = None

        if open_at is None:
            if net != 0:
                open_at = ts
                open_net = net
                peak_lots = abs(net)
                open_avg = avg_f
            continue

        peak_lots = max(peak_lots, abs(net))
        if avg_f is not None and open_avg is None:
            open_avg = avg_f
        if net == 0:
            _emit(ts, src or None)
        elif (open_net > 0 and net < 0) or (open_net < 0 and net > 0):
            # Flip: close old episode at this stamp, open residual opposite.
            _emit(ts, src or None)
            open_at = ts
            open_net = net
            peak_lots = abs(net)
            open_avg = avg_f

    return closed


def make_unattributed_close_leg(
    *,
    account_realized: float,
    rounds_price_pnl: float,
    as_of: str | None = None,
    tolerance: float = 0.5,
) -> dict[str, Any] | None:
    """One synthetic close row so history sum can equal 天勤账户已实现.

    Covers equity that moved without a locally reconstructable open/close
    (weekend gap, pre-restart trades, missing snapshots).
    """
    residual = float(account_realized) - float(rounds_price_pnl)
    if abs(residual) < float(tolerance):
        return None
    return {
        "leg_id": "unattributed-close",
        "round_id": "unattributed",
        "action": "CLOSE",
        "action_label": "结转",
        "symbol": "—",
        "side": "FLAT",
        "side_label": "—",
        "lots": 0,
        "price": None,
        "entry_price": None,
        "exit_price": None,
        "realized_pnl": float(residual),
        "fees": 0.0,
        "trade_time": as_of,
        "opened_at": None,
        "closed_at": as_of,
        "source": "account_residual",
        "note": (
            "天勤账户已实现中，本地无完整开平价差可还原的部分"
            "（重启前成交、周末权益变动、快照缺口等）"
        ),
    }


def rounds_to_open_close_legs(
    rounds: Sequence[Mapping[str, Any]],
    *,
    newest_first: bool = True,
) -> list[dict[str, Any]]:
    """Expand each closed round into 开仓(盈亏0) + 平仓(价差盈亏) two rows."""
    ordered = list(reversed(rounds)) if newest_first else list(rounds)
    legs: list[dict[str, Any]] = []
    for idx, r in enumerate(ordered):
        round_id = str(r.get("round_id") or f"round-{idx}")
        symbol = str(r.get("symbol") or "")
        side = str(r.get("side") or "LONG")
        side_label = str(r.get("side_label") or ("多" if side == "LONG" else "空"))
        lots = int(r.get("lots") or 0)
        entry = float(r.get("entry_price") or 0)
        exit_px = float(r.get("exit_price") or 0)
        pnl = float(r.get("realized_pnl") or 0)
        fees = float(r.get("fees") or 0)
        opened_at = r.get("opened_at")
        closed_at = r.get("closed_at")
        source = r.get("source") or "broker_position"

        close_leg = {
            "leg_id": f"{round_id}-close",
            "round_id": round_id,
            "action": "CLOSE",
            "action_label": "平仓",
            "symbol": symbol,
            "side": side,
            "side_label": side_label,
            "lots": lots,
            "price": exit_px,
            "entry_price": entry,
            "exit_price": exit_px,
            "realized_pnl": pnl,
            "fees": fees,
            "trade_time": closed_at,
            "opened_at": opened_at,
            "closed_at": closed_at,
            "source": source,
        }
        open_leg = {
            "leg_id": f"{round_id}-open",
            "round_id": round_id,
            "action": "OPEN",
            "action_label": "开仓",
            "symbol": symbol,
            "side": side,
            "side_label": side_label,
            "lots": lots,
            "price": entry,
            "entry_price": entry,
            "exit_price": None,
            "realized_pnl": 0.0,
            "fees": 0.0,
            "trade_time": opened_at,
            "opened_at": opened_at,
            "closed_at": None,
            "source": source,
        }
        if newest_first:
            # 平仓在上、开仓在下（同回合内先看到结果）
            legs.append(close_leg)
            legs.append(open_leg)
        else:
            legs.append(open_leg)
            legs.append(close_leg)
    return legs
