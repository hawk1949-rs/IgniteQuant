"""Roll state machine — forbid switching before old contract is flat."""

from __future__ import annotations

from dataclasses import dataclass, field

from ignitequant.domain.enums import RollPhase


@dataclass
class RollStateMachine:
    phase: RollPhase = RollPhase.IDLE
    old_symbol: str = ""
    new_symbol: str = ""
    events: list[str] = field(default_factory=list)

    @property
    def in_progress(self) -> bool:
        return self.phase not in {RollPhase.IDLE, RollPhase.READY}

    def detect(self, old_symbol: str, new_symbol: str) -> None:
        if not new_symbol or new_symbol == old_symbol:
            return
        if self.in_progress:
            return
        self.old_symbol = old_symbol
        self.new_symbol = new_symbol
        self.phase = RollPhase.FREEZE_NEW_RISK
        self.events.append(f"detect:{old_symbol}->{new_symbol}")

    def mark_flattening(self) -> None:
        if self.phase is RollPhase.FREEZE_NEW_RISK:
            self.phase = RollPhase.FLATTENING_OLD
            self.events.append("flattening")

    def on_old_position(self, net: int) -> None:
        if self.phase in {RollPhase.FLATTENING_OLD, RollPhase.WAIT_FLAT, RollPhase.FREEZE_NEW_RISK}:
            if net == 0:
                self.phase = RollPhase.SWITCHING
                self.events.append("old_flat")
            else:
                self.phase = RollPhase.WAIT_FLAT
                self.events.append(f"wait_flat:{net}")

    def complete_switch(self) -> str:
        if self.phase is not RollPhase.SWITCHING:
            raise RuntimeError(f"cannot switch in phase {self.phase}")
        symbol = self.new_symbol
        self.phase = RollPhase.READY
        self.events.append(f"switched:{symbol}")
        # READY means switch done; return to IDLE for next roll.
        self.phase = RollPhase.IDLE
        self.old_symbol = ""
        return symbol

    def abort_to_idle(self) -> None:
        self.phase = RollPhase.IDLE
        self.old_symbol = ""
        self.new_symbol = ""
        self.events.append("abort")
