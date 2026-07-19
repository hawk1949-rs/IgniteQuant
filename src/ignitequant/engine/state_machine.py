"""Position decision state machine (大框架 §4.3 / Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ignitequant.domain.enums import PositionPhase
from ignitequant.domain.models import EntryContext, FillEvent


@dataclass
class PositionStateMachine:
    phase: PositionPhase = PositionPhase.FLAT
    entry: EntryContext | None = None
    pending_target: int = 0
    cooldown_left: int = 0
    history: list[str] = field(default_factory=list)

    def _log(self, event: str) -> None:
        self.history.append(f"{self.phase.value}:{event}")

    def on_target_submitted(self, desired: int, current_net: int) -> None:
        if desired == current_net:
            return
        if current_net == 0 and desired != 0:
            self.phase = PositionPhase.ENTRY_PENDING
            self.pending_target = desired
            self._log("target_entry")
        elif desired == 0 and current_net != 0:
            self.phase = PositionPhase.EXIT_PENDING
            self.pending_target = 0
            self._log("target_exit")
        else:
            self.phase = PositionPhase.REBALANCE_PENDING
            self.pending_target = desired
            self._log("target_rebalance")

    def on_fill_confirmed(self, fill: FillEvent, entry: EntryContext) -> None:
        self.entry = entry
        if entry.side_lots == 0:
            self.phase = PositionPhase.COOLDOWN if self.cooldown_left > 0 else PositionPhase.FLAT
            self.pending_target = 0
            self._log("flat_confirmed")
        else:
            self.phase = PositionPhase.OPEN
            self._log("open_confirmed")

    def on_cancel_or_reject(self, current_net: int) -> None:
        self.pending_target = current_net
        self.phase = PositionPhase.OPEN if current_net != 0 else PositionPhase.FLAT
        self._log("cancel_or_reject")

    def begin_cooldown(self, bars: int) -> None:
        self.cooldown_left = max(0, int(bars))
        self.phase = PositionPhase.COOLDOWN
        self.entry = None
        self._log(f"cooldown:{bars}")

    def tick_cooldown(self) -> None:
        if self.cooldown_left > 0:
            self.cooldown_left -= 1
            if self.cooldown_left == 0 and self.phase is PositionPhase.COOLDOWN:
                self.phase = PositionPhase.FLAT
                self._log("cooldown_done")

    @property
    def allows_new_risk(self) -> bool:
        return self.phase in {PositionPhase.FLAT, PositionPhase.OPEN} and self.cooldown_left == 0
