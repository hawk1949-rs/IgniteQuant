"""Execution adapters (Phase 3).

Lazy-load TargetPositionExecutor to avoid circular import:
execution → engine.state_machine → engine.__init__ → runtime_bridge → execution.
"""

from __future__ import annotations

from typing import Any

from ignitequant.execution.align_price import align_limit_price, is_gfd_day_end_cancel
from ignitequant.execution.roll import RollStateMachine

__all__ = [
    "RollStateMachine",
    "TargetPositionExecutor",
    "align_limit_price",
    "build_sl_tp",
    "is_gfd_day_end_cancel",
]


def __getattr__(name: str) -> Any:
    if name in {"TargetPositionExecutor", "build_sl_tp"}:
        from ignitequant.execution import target_position as _tp

        return getattr(_tp, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
