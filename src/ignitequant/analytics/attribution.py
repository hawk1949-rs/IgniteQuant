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


def fills_from_tq_trade_log(
    trade_log: Mapping[str, Any] | None,
    *,
    default_symbol: str = "",
) -> list[TradeFillRecord]:
    """Best-effort parse of TqSim.trade_log into TradeFillRecord list."""
    if not isinstance(trade_log, dict):
        return []
    out: list[TradeFillRecord] = []
    for day, payload in trade_log.items():
        trades = (payload or {}).get("trades") or {}
        if not isinstance(trades, dict):
            continue
        month = str(day)[:7] if day else None
        for tid, tr in trades.items():
            try:
                if isinstance(tr, dict):
                    direction = int(tr.get("direction", 0))
                    offset_raw = int(tr.get("offset", 0))
                    price = float(tr.get("price", 0))
                    volume = int(tr.get("volume", 0))
                    fee = float(tr.get("commission") or 0)
                    symbol = str(tr.get("symbol") or default_symbol)
                else:
                    direction = int(getattr(tr, "direction", 0))
                    offset_raw = int(getattr(tr, "offset", 0))
                    price = float(getattr(tr, "price", 0))
                    volume = int(getattr(tr, "volume", 0))
                    fee = float(getattr(tr, "commission", 0) or 0)
                    symbol = str(getattr(tr, "symbol", default_symbol) or default_symbol)
            except Exception:
                continue
            side = "BUY" if direction >= 0 else "SELL"
            off = {1: "OPEN", 2: "CLOSE", 3: "CLOSETODAY"}.get(offset_raw, "UNKNOWN")
            out.append(
                TradeFillRecord(
                    trade_id=str(tid),
                    symbol=symbol or default_symbol,
                    side=side,
                    offset=off,
                    price=price,
                    qty=volume,
                    fee=fee,
                    month=month,
                )
            )
    return out
