"""TargetPosTask lifecycle wrapper (大框架 §7.2)."""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from ignitequant.domain.enums import OrderStatus, PositionPhase
from ignitequant.domain.models import EntryContext, FillEvent, OrderIntent
from ignitequant.engine.state_machine import PositionStateMachine
from ignitequant.execution.roll import RollStateMachine


@dataclass
class ExecutorEvent:
    kind: str
    payload: dict[str, Any]


@dataclass
class TargetPositionExecutor:
    """One account × one real contract; exposes intents and fill confirmations."""

    api: Any
    symbol: str
    state: PositionStateMachine = field(default_factory=PositionStateMachine)
    roll: RollStateMachine = field(default_factory=RollStateMachine)
    active_intent: OrderIntent | None = None
    last_status: OrderStatus = OrderStatus.CREATED
    events: list[ExecutorEvent] = field(default_factory=list)
    _task: Any = None
    _id_seq: itertools.count = field(default_factory=lambda: itertools.count(1))
    _seen_keys: set[str] = field(default_factory=set)

    def _ensure_task(self) -> Any:
        if self._task is None:
            from tqsdk import TargetPosTask

            self._task = TargetPosTask(self.api, self.symbol)
            self.events.append(ExecutorEvent("task_created", {"symbol": self.symbol}))
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
    ) -> OrderIntent | None:
        if self.roll.in_progress and abs(desired) > abs(current_net):
            self.events.append(
                ExecutorEvent("blocked_by_roll", {"desired": desired, "net": current_net})
            )
            return None

        key = idempotency_key or f"{self.symbol}:{decision_id}:{desired}"
        if key in self._seen_keys and self.active_intent and self.active_intent.desired_position == desired:
            self.events.append(ExecutorEvent("duplicate_suppressed", {"key": key}))
            return self.active_intent

        intent = OrderIntent(
            intent_id=f"intent-{next(self._id_seq)}",
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

        fill = FillEvent(
            fill_id=f"fill-{uuid.uuid4().hex[:10]}",
            intent_id=intent.intent_id,
            symbol=self.symbol,
            price=float(last_price),
            qty=abs(intent.desired_position - intent.current_position) or abs(net),
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

    def destroy(self) -> None:
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
) -> tuple[float | None, float | None]:
    if side_lots == 0 or atr <= 0:
        return None, None
    if side_lots > 0:
        return fill_price - sl_mult * atr, fill_price + tp_mult * atr
    return fill_price + sl_mult * atr, fill_price - tp_mult * atr
