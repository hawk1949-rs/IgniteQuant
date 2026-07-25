"""ATR 止盈止损与冷却。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RiskAction(str, Enum):
    NONE = "NONE"
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"


@dataclass
class RiskState:
    entry_price: float | None = None
    entry_signal: int = 0
    stop_price: float | None = None
    take_price: float | None = None
    cooldown_left: int = 0


class RiskManager:
    def __init__(
        self,
        *,
        sl_atr_mult: float = 1.5,
        tp_atr_mult: float = 2.5,
        cooldown_bars: int = 3,
    ) -> None:
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.cooldown_bars = cooldown_bars
        self.state = RiskState()

    def on_flat(self) -> None:
        self.state.entry_price = None
        self.state.entry_signal = 0
        self.state.stop_price = None
        self.state.take_price = None

    def on_entry(self, side_lots: int, entry_price: float, atr: float, signal: int) -> None:
        if side_lots == 0 or atr <= 0 or entry_price != entry_price:
            self.on_flat()
            return
        self.state.entry_price = entry_price
        self.state.entry_signal = signal
        if side_lots > 0:
            self.state.stop_price = entry_price - self.sl_atr_mult * atr
            self.state.take_price = entry_price + self.tp_atr_mult * atr
        else:
            self.state.stop_price = entry_price + self.sl_atr_mult * atr
            self.state.take_price = entry_price - self.tp_atr_mult * atr

    def tick_cooldown(self) -> None:
        if self.state.cooldown_left > 0:
            self.state.cooldown_left -= 1

    @property
    def in_cooldown(self) -> bool:
        return self.state.cooldown_left > 0

    def check(self, side_lots: int, high: float, low: float, close: float) -> RiskAction:
        if side_lots == 0 or self.state.stop_price is None or self.state.take_price is None:
            return RiskAction.NONE

        if side_lots > 0:
            if low <= self.state.stop_price:
                return RiskAction.STOP_LOSS
            if high >= self.state.take_price:
                return RiskAction.TAKE_PROFIT
        else:
            if high >= self.state.stop_price:
                return RiskAction.STOP_LOSS
            if low <= self.state.take_price:
                return RiskAction.TAKE_PROFIT
        return RiskAction.NONE

    def trigger(self, action: RiskAction) -> None:
        self.on_flat()
        if action != RiskAction.NONE:
            self.state.cooldown_left = self.cooldown_bars
