"""PnL attribution helpers (大框架 §12.3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ignitequant.analytics.cost_model import CostModel, default_cost_model


@dataclass(frozen=True)
class TradeFillRecord:
    """Minimal fill for offline attribution (broker or simulated)."""

    trade_id: str
    symbol: str
    side: str  # BUY / SELL
    offset: str  # OPEN / CLOSE / CLOSETODAY / UNKNOWN
    price: float
    qty: int
    fee: float = 0.0
    signal_price: float | None = None
    regime: str | None = None
    is_roll: bool = False
    month: str | None = None
    trade_time: str | None = None
    applied_action: str | None = None
    legacy_signal: float | None = None


def fill_record_to_dict(fill: TradeFillRecord) -> dict[str, Any]:
    """JSON-friendly fill for backtest run archives / Strategy Lab."""
    return {
        "trade_id": fill.trade_id,
        "symbol": fill.symbol,
        "side": fill.side,
        "offset": fill.offset,
        "price": float(fill.price),
        "qty": int(fill.qty),
        "fee": float(fill.fee or 0),
        "signal_price": fill.signal_price,
        "regime": fill.regime,
        "is_roll": bool(fill.is_roll),
        "month": fill.month,
        "trade_time": fill.trade_time or fill.month,
        "applied_action": fill.applied_action,
        "legacy_signal": fill.legacy_signal,
    }


def stamp_fills_with_intent_log(
    fills: Sequence[TradeFillRecord],
    intents: Sequence[Mapping[str, Any]],
) -> list[TradeFillRecord]:
    """Attach applied_action / legacy_signal from ordered intent log onto fills.

    Each intent covers ``abs(desired - net_before)`` lots of subsequent fills.
    """
    if not fills:
        return []
    if not intents:
        return list(fills)

    out: list[TradeFillRecord] = []
    fill_i = 0
    for intent in intents:
        try:
            net_before = int(intent.get("net_before", 0))
            desired = int(intent.get("desired", net_before))
        except (TypeError, ValueError):
            continue
        need = abs(desired - net_before)
        if need <= 0:
            continue
        action = intent.get("applied_action")
        action_s = str(action) if action else None
        sig_raw = intent.get("legacy_signal")
        try:
            sig = float(sig_raw) if sig_raw is not None else None
        except (TypeError, ValueError):
            sig = None
        while need > 0 and fill_i < len(fills):
            f = fills[fill_i]
            out.append(
                TradeFillRecord(
                    trade_id=f.trade_id,
                    symbol=f.symbol,
                    side=f.side,
                    offset=f.offset,
                    price=f.price,
                    qty=f.qty,
                    fee=f.fee,
                    signal_price=f.signal_price,
                    regime=f.regime,
                    is_roll=f.is_roll,
                    month=f.month,
                    trade_time=f.trade_time,
                    applied_action=action_s or f.applied_action,
                    legacy_signal=sig if sig is not None else f.legacy_signal,
                )
            )
            need -= abs(int(f.qty))
            fill_i += 1
    while fill_i < len(fills):
        out.append(fills[fill_i])
        fill_i += 1
    return out

@dataclass
class AttributionReport:
    gross_pnl: float = 0.0
    fees: float = 0.0
    slippage_pnl: float = 0.0
    roll_pnl: float = 0.0
    execution_pnl: float = 0.0
    alpha_pnl: float = 0.0
    net_pnl: float = 0.0
    trade_count: int = 0
    long_pnl: float = 0.0
    short_pnl: float = 0.0
    by_regime: dict[str, float] = field(default_factory=dict)
    by_month: dict[str, float] = field(default_factory=dict)
    cost_model_version: str = ""
    cost_model_hash: str = ""
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "gross_pnl": round(self.gross_pnl, 2),
            "fees": round(self.fees, 2),
            "slippage_pnl": round(self.slippage_pnl, 2),
            "roll_pnl": round(self.roll_pnl, 2),
            "execution_pnl": round(self.execution_pnl, 2),
            "alpha_pnl": round(self.alpha_pnl, 2),
            "net_pnl": round(self.net_pnl, 2),
            "trade_count": self.trade_count,
            "long_pnl": round(self.long_pnl, 2),
            "short_pnl": round(self.short_pnl, 2),
            "by_regime": {k: round(v, 2) for k, v in self.by_regime.items()},
            "by_month": {k: round(v, 2) for k, v in self.by_month.items()},
            "cost_model_version": self.cost_model_version,
            "cost_model_hash": self.cost_model_hash,
            "notes": list(self.notes),
        }


def _is_buy(side: str) -> bool:
    return side.upper() in {"BUY", "LONG"}


def attribute_fills(
    fills: Sequence[TradeFillRecord],
    *,
    cost: CostModel | None = None,
) -> AttributionReport:
    """FIFO attribution with model fee/slippage overlay.

    Inventory: list of [signed_qty, entry_price].
    Closing against opposite inventory realizes gross PnL.
    """
    model = cost or default_cost_model()
    inventory: list[list[float]] = []
    gross = 0.0
    fees = 0.0
    slip = 0.0
    roll = 0.0
    long_pnl = 0.0
    short_pnl = 0.0
    by_regime: dict[str, float] = {}
    by_month: dict[str, float] = {}

    for fill in fills:
        qty = abs(int(fill.qty))
        if qty == 0:
            continue
        buy = _is_buy(fill.side)
        signed = float(qty if buy else -qty)
        offset = fill.offset.upper()

        # Determine open vs close from offset, else inventory sign
        if offset == "OPEN":
            is_open = True
        elif offset in {"CLOSE", "CLOSETODAY"}:
            is_open = False
        else:
            is_open = not inventory or (inventory[0][0] * signed > 0)

        model_fee = model.fee_for(
            qty=qty,
            is_open=is_open,
            close_today=offset == "CLOSETODAY",
        )
        fee = float(fill.fee) if fill.fee else model_fee
        fees += fee

        slip_ticks = model.roll_slippage_ticks if fill.is_roll else model.slippage_ticks
        if fill.signal_price is not None:
            if buy:
                slip_leg = (fill.signal_price - fill.price) * qty * model.multiplier
            else:
                slip_leg = (fill.price - fill.signal_price) * qty * model.multiplier
        else:
            slip_leg = -abs(slip_ticks * model.tick_size * qty * model.multiplier)

        if fill.is_roll:
            roll += slip_leg
        else:
            slip += slip_leg

        realized = 0.0
        remaining = signed
        if not is_open:
            while remaining != 0 and inventory and inventory[0][0] * remaining < 0:
                lot_qty, lot_px = inventory[0]
                close_qty = min(abs(remaining), abs(lot_qty))
                if lot_qty > 0:
                    # closing long with sell
                    leg = (fill.price - lot_px) * close_qty * model.multiplier
                    long_pnl += leg
                else:
                    # closing short with buy
                    leg = (lot_px - fill.price) * close_qty * model.multiplier
                    short_pnl += leg
                realized += leg
                if abs(lot_qty) == close_qty:
                    inventory.pop(0)
                else:
                    inventory[0][0] = lot_qty + (close_qty if lot_qty < 0 else -close_qty)
                remaining += close_qty if remaining < 0 else -close_qty

        if remaining != 0:
            inventory.append([remaining, float(fill.price)])

        gross += realized
        regime = fill.regime or "UNKNOWN"
        by_regime[regime] = by_regime.get(regime, 0.0) + realized - fee
        month = fill.month or "UNKNOWN"
        by_month[month] = by_month.get(month, 0.0) + realized - fee

    net = gross - fees + slip + roll
    return AttributionReport(
        gross_pnl=gross,
        fees=fees,
        slippage_pnl=slip,
        roll_pnl=roll,
        execution_pnl=slip + roll,
        alpha_pnl=gross - fees,
        net_pnl=net,
        trade_count=len(fills),
        long_pnl=long_pnl,
        short_pnl=short_pnl,
        by_regime=by_regime,
        by_month=by_month,
        cost_model_version=model.version,
        cost_model_hash=model.config_hash(),
        notes=("FIFO inventory; model fees when broker fee is 0",) if fills else ("no fills",),
    )


def _iter_tq_trades(trades: Any) -> list[tuple[str, Any]]:
    """Normalize TqSim trade_log trades (list or dict) → [(trade_id, row)]."""
    if trades is None:
        return []
    if isinstance(trades, dict):
        return [(str(k), v) for k, v in trades.items()]
    if isinstance(trades, (list, tuple)):
        out: list[tuple[str, Any]] = []
        for i, tr in enumerate(trades):
            if isinstance(tr, dict):
                tid = str(tr.get("trade_id") or tr.get("exchange_trade_id") or i)
            else:
                tid = str(getattr(tr, "trade_id", None) or getattr(tr, "exchange_trade_id", None) or i)
            out.append((tid, tr))
        return out
    return []


def _tq_field(tr: Any, *names: str, default: Any = None) -> Any:
    if isinstance(tr, dict):
        for name in names:
            if name in tr and tr[name] is not None:
                return tr[name]
        return default
    for name in names:
        if hasattr(tr, name):
            val = getattr(tr, name)
            if val is not None:
                return val
    return default


def _parse_tq_side(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return "BUY" if int(raw) >= 0 else "SELL"
    text = str(raw).strip().upper()
    if text in {"BUY", "LONG", "0"}:
        return "BUY"
    if text in {"SELL", "SHORT", "1"}:
        return "SELL"
    return None


def _parse_tq_offset(raw: Any) -> str:
    if raw is None:
        return "UNKNOWN"
    if isinstance(raw, (int, float)):
        return {0: "OPEN", 1: "OPEN", 2: "CLOSE", 3: "CLOSETODAY"}.get(
            int(raw), "UNKNOWN"
        )
    text = str(raw).strip().upper()
    if text in {"OPEN", "0"}:
        return "OPEN"
    if text in {"CLOSE", "2"}:
        return "CLOSE"
    if text in {"CLOSETODAY", "3"}:
        return "CLOSETODAY"
    # Legacy int-as-string "1" was OPEN in some docs; prefer OPEN for ambiguity.
    if text == "1":
        return "OPEN"
    return "UNKNOWN"


def _parse_tq_symbol(tr: Any, default_symbol: str) -> str:
    symbol = _tq_field(tr, "symbol", default=None)
    if symbol:
        return str(symbol)
    exchange = _tq_field(tr, "exchange_id", default="")
    instrument = _tq_field(tr, "instrument_id", default="")
    if exchange and instrument:
        return f"{exchange}.{instrument}"
    if instrument:
        return str(instrument)
    return default_symbol


def _parse_tq_trade_time(day: Any, tr: Any) -> str | None:
    ts = _tq_field(tr, "trade_date_time", default=None)
    if ts is not None:
        try:
            ns = int(ts)
            # ns since epoch → ISO date-time UTC-ish local display date
            from datetime import datetime, timezone

            dt = datetime.fromtimestamp(ns / 1_000_000_000, tz=timezone.utc)
            return dt.astimezone().isoformat(timespec="seconds")
        except Exception:
            pass
    return str(day) if day else None


def fills_from_tq_trade_log(
    trade_log: Mapping[str, Any] | None,
    *,
    default_symbol: str = "",
) -> list[TradeFillRecord]:
    """Best-effort parse of TqSim.trade_log into TradeFillRecord list.

    TqSim stores ``trades`` as a **list** of dicts with string direction/offset
    (BUY/SELL, OPEN/CLOSE). Older stubs used int codes + dict keyed by trade_id.
    """
    if not isinstance(trade_log, dict):
        return []
    out: list[TradeFillRecord] = []
    for day, payload in trade_log.items():
        if not isinstance(payload, dict):
            continue
        trades = payload.get("trades")
        month = str(day)[:7] if day else None
        for tid, tr in _iter_tq_trades(trades):
            try:
                side = _parse_tq_side(_tq_field(tr, "direction", default=None))
                if side is None:
                    continue
                offset = _parse_tq_offset(_tq_field(tr, "offset", default=None))
                price = float(_tq_field(tr, "price", default=0) or 0)
                volume = int(_tq_field(tr, "volume", default=0) or 0)
                fee = float(
                    _tq_field(tr, "commission", "fee", default=0) or 0
                )
                symbol = _parse_tq_symbol(tr, default_symbol)
            except (TypeError, ValueError):
                continue
            if volume <= 0 or price <= 0:
                continue
            out.append(
                TradeFillRecord(
                    trade_id=str(tid),
                    symbol=symbol or default_symbol,
                    side=side,
                    offset=offset,
                    price=price,
                    qty=volume,
                    fee=fee,
                    month=month,
                    trade_time=_parse_tq_trade_time(day, tr) or (str(day) if day else month),
                )
            )
    return out
