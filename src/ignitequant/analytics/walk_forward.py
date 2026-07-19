"""Walk-forward window planner (大框架 §9.3)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WalkForwardWindow:
    fold: int
    train_start: dt.date
    train_end: dt.date
    test_start: dt.date
    test_end: dt.date

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold": self.fold,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "test_start": self.test_start.isoformat(),
            "test_end": self.test_end.isoformat(),
        }


def plan_walk_forward(
    start: dt.date,
    end: dt.date,
    *,
    train_days: int = 40,
    test_days: int = 20,
    step_days: int | None = None,
) -> list[WalkForwardWindow]:
    """Anchored expanding / rolling walk-forward on calendar days.

    Default: rolling windows; step defaults to test_days (non-overlapping tests).
    """
    if end <= start:
        raise ValueError("end must be after start")
    if train_days < 1 or test_days < 1:
        raise ValueError("train_days and test_days must be >= 1")
    step = step_days if step_days is not None else test_days
    if step < 1:
        raise ValueError("step_days must be >= 1")

    windows: list[WalkForwardWindow] = []
    fold = 0
    cursor = start
    while True:
        train_start = cursor
        train_end = train_start + dt.timedelta(days=train_days - 1)
        test_start = train_end + dt.timedelta(days=1)
        test_end = test_start + dt.timedelta(days=test_days - 1)
        if test_end > end:
            break
        windows.append(
            WalkForwardWindow(
                fold=fold,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
        )
        fold += 1
        cursor = cursor + dt.timedelta(days=step)
    return windows
