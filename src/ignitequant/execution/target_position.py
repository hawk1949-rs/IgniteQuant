"""TargetPosTask lifecycle wrapper (大框架 §7.2)."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from ignitequant.domain.enums import OrderStatus
from ignitequant.domain.models import EntryContext, FillEvent, OrderIntent
from ignitequant.engine.state_machine import PositionStateMachine
from ignitequant.execution.align_price import align_limit_price, is_gfd_day_end_cancel
from ignitequant.execution.roll import RollStateMachine

__all__ = [
    "ExecutorEvent",
    "TargetPositionExecutor",
    "align_limit_price",
    "build_sl_tp",
    "is_gfd_day_end_cancel",
]


@dataclass
class ExecutorEvent:
    kind: str
    payload: dict[str, Any]


@dataclass
class TargetPositionExecutor:
    """One account × one real contract; exposes intents and fill confirmations.

    ``align_tq_kline=True`` (default for Falcon backtest): prefer decision-bar
    open ± tick, but bump to ask/bid when the pin is not marketable so orders fill
    before TqSim day-end GFD cancels (which TargetPosTask surfaces as 错单).
    """

    api: Any
    symbol: str
    state: PositionStateMachine = field(default_factory=PositionStateMachine)
    roll: RollStateMachine = field(default_factory=RollStateMachine)
    active_intent: OrderIntent | None = None
    last_status: OrderStatus = OrderStatus.CREATED
    events: list[ExecutorEvent] = field(default_factory=list)
    align_tq_kline: bool = True
    price_tick: float = 0.02
    _task: Any = None
    _seen_keys: set[str] = field(default_factory=set)
    _pinned_last: float | None = None

    def pin_last(self, last_price: float) -> None:
        """Pin the next order to ``last ± tick`` (call on each decision bar)."""
        self._pinned_last = float(last_price)

    def _quote_book(self) -> tuple[float | None, float | None, float | None]:
        quote = self.api.get_quote(self.symbol)

        def _f(name: str) -> float | None:
            v = getattr(quote, name, None)
            try:
                x = float(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
            return x if math.isfinite(x) else None

        return _f("ask_price1"), _f("bid_price1"), _f("last_price")

    def _align_price_fn(self) -> Callable[[str], float]:
        tick = float(self.price_tick)

        def _price(direction: str) -> float:
            ask, bid, last = self._quote_book()
            return align_limit_price(
                direction,
                pinned_last=self._pinned_last,
                tick=tick,
                ask=ask,
                bid=bid,
                last=last,
            )

        return _price

    def _ensure_task(self) -> Any:
        if self._task is None:
            from tqsdk import TargetPosTask

            if self.align_tq_kline:
                self._task = TargetPosTask(
                    self.api, self.symbol, price=self._align_price_fn()
                )
            else:
                self._task = TargetPosTask(self.api, self.symbol)
            self.events.append(
                ExecutorEvent(
                    "task_created",
                    {"symbol": self.symbol, "align_tq_kline": self.align_tq_kline},
                )
            )
        return self._task

    def set_target(
        self,
        desired: int,
        *,
        decision_id: str,
        current_net: int,
        urgency: str = "NORMAL",
        reason_codes: tuple[str, ...] = (),
        idempotency_key: str | None = None,
        decision_price: float | None = None,
    ) -> OrderIntent | None:
        if self.roll.in_progress and abs(desired) > abs(current_net):
            self.events.append(
                ExecutorEvent("blocked_by_roll", {"desired": desired, "net": current_net})
            )
            return None

        if decision_price is not None:
            self.pin_last(decision_price)

        key = idempotency_key or f"{self.symbol}:{decision_id}:{desired}"
        if key in self._seen_keys and self.active_intent and self.active_intent.desired_position == desired:
            self.events.append(ExecutorEvent("duplicate_suppressed", {"key": key}))
            return self.active_intent

        # UUID avoids UNIQUE(instance_id, intent_id) collisions after process restart
        # (sequential intent-1/2 reused and silently dropped by INSERT OR IGNORE).
        intent = OrderIntent(
            intent_id=f"intent-{uuid.uuid4().hex[:12]}",
            decision_id=decision_id,
            symbol=self.symbol,
            current_position=current_net,
            desired_position=desired,
            urgency=urgency,
            idempotency_key=key,
            created_at=datetime.now(timezone.utc),
            reason_codes=reason_codes,
        )
        self._seen_keys.add(key)
        self.active_intent = intent
        self.last_status = OrderStatus.SUBMITTED
        self.state.on_target_submitted(desired, current_net)
        task = self._ensure_task()
        task.set_target_volume(desired)
        self.events.append(
            ExecutorEvent(
                "target_submitted",
                {"intent_id": intent.intent_id, "desired": desired, "urgency": urgency},
            )
        )
        return intent

    def poll_position(self, net: int, *, last_price: float, atr: float, signal: int) -> FillEvent | None:
        """Confirm fill when net matches active intent (Phase 3 fill gate)."""
        intent = self.active_intent
        if intent is None:
            return None
        if net != intent.desired_position:
            if self.last_status is OrderStatus.SUBMITTED:
                self.last_status = OrderStatus.ACKNOWLEDGED
            return None

        qty = abs(int(intent.desired_position) - int(intent.current_position))
        if qty <= 0:
            qty = abs(int(net))
        # Net already matched desired with zero delta (e.g. ghost STOP while flat):
        # clear intent without inventing a qty=0 ledger fill.
        if qty <= 0:
            self.last_status = OrderStatus.FILLED
            self.active_intent = None
            self.events.append(
                ExecutorEvent(
                    "intent_cleared_flat",
                    {"net": net, "desired": intent.desired_position},
                )
            )
            return None

        fill = FillEvent(
            fill_id=f"fill-{uuid.uuid4().hex[:10]}",
            intent_id=intent.intent_id,
            symbol=self.symbol,
            price=float(last_price),
            qty=qty,
            fee=0.0,
            side="BUY" if intent.desired_position > intent.current_position else "SELL",
            trade_time=datetime.now(timezone.utc),
        )
        self.last_status = OrderStatus.FILLED
        entry = EntryContext(
            symbol=self.symbol,
            side_lots=net,
            signal=signal,
            intent_price=last_price,
            intent_atr=atr,
            fill_price=float(last_price),
            stop_price=None,
            take_price=None,
            confirmed=True,
            opened_at=fill.trade_time,
        )
        self.state.on_fill_confirmed(fill, entry)
        self.events.append(
            ExecutorEvent("fill_confirmed", {"net": net, "price": last_price, "intent": intent.intent_id})
        )
        self.active_intent = None
        return fill

    def mark_unknown(self) -> None:
        self.last_status = OrderStatus.UNKNOWN
        self.events.append(ExecutorEvent("unknown", {"symbol": self.symbol}))

    def mark_rejected(self, current_net: int) -> None:
        self.last_status = OrderStatus.REJECTED
        self.state.on_cancel_or_reject(current_net)
        self.active_intent = None
        self.events.append(ExecutorEvent("rejected", {"net": current_net}))

    def restore_idempotency_keys(self, keys: set[str]) -> None:
        """Reload keys after restart so duplicate intents stay suppressed."""
        self._seen_keys |= set(keys)

    def recover_after_gfd_cancel(
        self,
        *,
        current_net: int,
        decision_price: float | None = None,
        desired: int | None = None,
    ) -> OrderIntent | None:
        """Rebuild TargetPosTask after TqSim day-end GFD cancel killed the async task."""
        intent = self.active_intent
        if desired is None:
            desired = intent.desired_position if intent is not None else current_net
        decision_id = intent.decision_id if intent is not None else f"gfd:{self.symbol}"
        reasons = tuple(intent.reason_codes) if intent is not None else ()
        self.destroy()
        self.events.append(
            ExecutorEvent(
                "gfd_recover",
                {"desired": desired, "net": current_net, "decision_id": decision_id},
            )
        )
        if desired == current_net:
            return None
        return self.set_target(
            desired,
            decision_id=f"gfd-recover:{decision_id}",
            current_net=current_net,
            urgency="HIGH",
            reason_codes=reasons + ("GFD_DAY_END_RECOVER",),
            idempotency_key=f"gfd-recover:{decision_id}:{desired}:{current_net}",
            decision_price=decision_price,
        )

    def destroy(self) -> None:
        # Drop singleton so the next contract can rebuild with a fresh price fn.
        try:
            from tqsdk.lib.target_pos_task import TargetPosTaskSingleton

            account = self.api._account._check_valid(None)
            key = self.api._account._get_account_key(account) + "#" + self.symbol
            TargetPosTaskSingleton._instances.pop(key, None)
        except Exception:
            pass
        self._task = None
        self.active_intent = None
        self.events.append(ExecutorEvent("destroyed", {"symbol": self.symbol}))


def build_sl_tp(
    side_lots: int,
    fill_price: float,
    atr: float,
    *,
    sl_mult: float,
    tp_mult: float,
    overseas_close: float | None = None,
) -> tuple[float | None, float | None]:
    """Build stop/take around fill_price.

    When ``overseas_close`` is set, ``atr`` is treated as overseas ATR and scaled
    onto the domestic fill via relative volatility (atr/overseas_close).
    """
    if side_lots == 0 or atr <= 0:
        return None, None
    use_atr = atr
    if overseas_close is not None and overseas_close > 0:
        from ignitequant.portfolio.stop_scale import scale_atr_to_entry

        use_atr = scale_atr_to_entry(atr, overseas_close, fill_price)
        if use_atr <= 0:
            return None, None
    if side_lots > 0:
        return fill_price - sl_mult * use_atr, fill_price + tp_mult * use_atr
    return fill_price + sl_mult * use_atr, fill_price - tp_mult * use_atr
