"""Simplified local account/sim — TqSim-like equity + FIFO fills (no tqsdk)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from ignitequant.analytics.attribution import TradeFillRecord
from ignitequant.analytics.cost_model import CostModel


@dataclass
class _Lot:
    qty: int  # signed
    price: float


@dataclass
class LocalSimAccount:
    """Cash + per-symbol inventory with model fees/slippage and daily equity log."""

    init_balance: float
    cost: CostModel
    cash: float = 0.0
    inventory: dict[str, list[_Lot]] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)
    fills: list[TradeFillRecord] = field(default_factory=list)
    daily_balances: dict[str, float] = field(default_factory=dict)
    trade_seq: int = 0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    win_trades: int = 0
    loss_trades: int = 0
    gross_wins: float = 0.0
    gross_losses: float = 0.0

    def __post_init__(self) -> None:
        if self.cash == 0.0:
            self.cash = float(self.init_balance)

    def net_pos(self, symbol: str) -> int:
        return int(sum(lot.qty for lot in self.inventory.get(symbol, [])))

    def mark(self, symbol: str, price: float) -> None:
        if symbol:
            self.marks[symbol] = float(price)

    def equity(self) -> float:
        unreal = 0.0
        for symbol, lots in self.inventory.items():
            mark = self.marks.get(symbol)
            if mark is None:
                continue
            for lot in lots:
                unreal += (mark - lot.price) * lot.qty * self.cost.multiplier
        return self.cash + unreal

    def record_day(self, day: dt.date) -> None:
        self.daily_balances[day.isoformat()] = float(self.equity())

    def fill_to_target(
        self,
        *,
        symbol: str,
        desired: int,
        signal_price: float,
        regime: str | None = None,
        is_roll: bool = False,
        month: str | None = None,
    ) -> list[TradeFillRecord]:
        """Instant fill at model slip price to reach desired net (absolute target)."""
        current = self.net_pos(symbol)
        delta = int(desired) - current
        if delta == 0 or not symbol:
            return []
        return self._apply_delta(
            symbol=symbol,
            delta=delta,
            signal_price=signal_price,
            regime=regime,
            is_roll=is_roll,
            month=month,
        )

    def _apply_delta(
        self,
        *,
        symbol: str,
        delta: int,
        signal_price: float,
        regime: str | None,
        is_roll: bool,
        month: str | None,
    ) -> list[TradeFillRecord]:
        created: list[TradeFillRecord] = []
        remaining = int(delta)
        while remaining != 0:
            pos = self.net_pos(symbol)
            # Closing if reducing absolute exposure toward zero or flipping.
            if pos != 0 and (remaining > 0) != (pos > 0):
                close_qty = min(abs(remaining), abs(pos))
                side = "BUY" if remaining > 0 else "SELL"
                fill = self._close_lots(
                    symbol=symbol,
                    qty=close_qty,
                    side=side,
                    signal_price=signal_price,
                    regime=regime,
                    is_roll=is_roll,
                    month=month,
                )
                created.append(fill)
                remaining -= close_qty if remaining > 0 else -close_qty
            else:
                open_qty = abs(remaining)
                side = "BUY" if remaining > 0 else "SELL"
                fill = self._open_lot(
                    symbol=symbol,
                    qty=open_qty,
                    side=side,
                    signal_price=signal_price,
                    regime=regime,
                    is_roll=is_roll,
                    month=month,
                )
                created.append(fill)
                remaining = 0
        return created

    def _open_lot(
        self,
        *,
        symbol: str,
        qty: int,
        side: str,
        signal_price: float,
        regime: str | None,
        is_roll: bool,
        month: str | None,
    ) -> TradeFillRecord:
        price = self.cost.slip_price(side, signal_price, roll=is_roll)
        fee = self.cost.fee_for(qty=qty, is_open=True)
        signed = qty if side == "BUY" else -qty
        self.inventory.setdefault(symbol, []).append(_Lot(qty=signed, price=price))
        self.cash -= fee
        self.fees_paid += fee
        self.marks[symbol] = signal_price
        return self._record_fill(
            symbol=symbol,
            side=side,
            offset="OPEN",
            price=price,
            qty=qty,
            fee=fee,
            signal_price=signal_price,
            regime=regime,
            is_roll=is_roll,
            month=month,
        )

    def _close_lots(
        self,
        *,
        symbol: str,
        qty: int,
        side: str,
        signal_price: float,
        regime: str | None,
        is_roll: bool,
        month: str | None,
    ) -> TradeFillRecord:
        price = self.cost.slip_price(side, signal_price, roll=is_roll)
        fee = self.cost.fee_for(qty=qty, is_open=False)
        left = qty
        lots = self.inventory.setdefault(symbol, [])
        realized = 0.0
        while left > 0 and lots:
            lot = lots[0]
            take = min(abs(lot.qty), left)
            # PnL: long lot closed by SELL → (exit-entry)*qty*mult
            if lot.qty > 0:
                leg = (price - lot.price) * take * self.cost.multiplier
            else:
                leg = (lot.price - price) * take * self.cost.multiplier
            realized += leg
            if lot.qty > 0:
                lot.qty -= take
            else:
                lot.qty += take
            left -= take
            if lot.qty == 0:
                lots.pop(0)
        self.cash += realized - fee
        self.fees_paid += fee
        self.realized_pnl += realized
        if realized >= 0:
            self.win_trades += 1
            self.gross_wins += realized
        else:
            self.loss_trades += 1
            self.gross_losses += abs(realized)
        self.marks[symbol] = signal_price
        return self._record_fill(
            symbol=symbol,
            side=side,
            offset="CLOSE",
            price=price,
            qty=qty,
            fee=fee,
            signal_price=signal_price,
            regime=regime,
            is_roll=is_roll,
            month=month,
        )

    def _record_fill(
        self,
        *,
        symbol: str,
        side: str,
        offset: str,
        price: float,
        qty: int,
        fee: float,
        signal_price: float,
        regime: str | None,
        is_roll: bool,
        month: str | None,
    ) -> TradeFillRecord:
        self.trade_seq += 1
        fill = TradeFillRecord(
            trade_id=f"L{self.trade_seq}",
            symbol=symbol,
            side=side,
            offset=offset,
            price=price,
            qty=qty,
            fee=fee,
            signal_price=signal_price,
            regime=regime,
            is_roll=is_roll,
            month=month,
        )
        self.fills.append(fill)
        return fill

    def metrics(
        self,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> dict[str, Any]:
        final = float(self.equity())
        ror = (final - self.init_balance) / self.init_balance if self.init_balance else 0.0
        balances = [self.daily_balances[k] for k in sorted(self.daily_balances.keys())]
        max_dd = _max_drawdown(balances) if balances else _max_drawdown([self.init_balance, final])
        annual = None
        if start and end and end > start:
            years = max((end - start).days / 365.25, 1 / 365.25)
            annual = (1.0 + ror) ** (1.0 / years) - 1.0
        wins = self.win_trades
        losses = self.loss_trades
        closed = wins + losses
        winning_rate = wins / closed if closed else None
        pl_ratio = None
        if self.gross_losses > 1e-12 and wins and losses:
            pl_ratio = (self.gross_wins / wins) / (self.gross_losses / losses)
        elif self.gross_losses <= 1e-12 and self.gross_wins > 0:
            pl_ratio = 10.0
        return {
            "init_balance": self.init_balance,
            "trade_count": len(self.fills),
            "ror": ror,
            "annual_yield": annual,
            "max_drawdown": max_dd,
            "sharpe": None,  # filled by runner helper
            "winning_rate": winning_rate,
            "profit_loss_ratio": pl_ratio,
            "final_balance": final,
            "realized_pnl": self.realized_pnl,
            "fees_paid": self.fees_paid,
        }

    def trade_log_like(self) -> dict[str, Any]:
        """Shape similar enough for sharpe helper (day → account.balance)."""
        out: dict[str, Any] = {}
        for day, bal in self.daily_balances.items():
            out[day] = {"account": {"balance": bal}, "trades": {}}
        return out


def _max_drawdown(balances: list[float]) -> float:
    if not balances:
        return 0.0
    peak = balances[0]
    max_dd = 0.0
    for bal in balances:
        peak = max(peak, bal)
        if peak > 0:
            max_dd = max(max_dd, (peak - bal) / peak)
    return max_dd
