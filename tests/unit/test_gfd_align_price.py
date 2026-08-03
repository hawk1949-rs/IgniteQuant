"""Align limit must stay marketable so TqSim GFD day-end cancel does not fire."""

from __future__ import annotations

import math

from ignitequant.execution.align_price import align_limit_price, is_gfd_day_end_cancel


def test_align_prefers_pin_when_marketable() -> None:
    # BUY pin 800.02 >= ask 800.00 → keep pin (LocalSim-compatible).
    assert align_limit_price(
        "BUY", pinned_last=800.0, tick=0.02, ask=800.0, bid=799.98, last=800.0
    ) == 800.02
    # SELL pin 799.98 <= bid 800.00 → keep pin.
    assert align_limit_price(
        "SELL", pinned_last=800.0, tick=0.02, ask=800.02, bid=800.0, last=800.0
    ) == 799.98


def test_align_chases_book_when_pin_not_marketable() -> None:
    # BUY pin 800.02 < ask 800.10 → must bump to ask or order never fills.
    assert align_limit_price(
        "BUY", pinned_last=800.0, tick=0.02, ask=800.10, bid=800.08, last=800.0
    ) == 800.10
    assert align_limit_price(
        "SELL", pinned_last=800.0, tick=0.02, ask=799.96, bid=799.90, last=800.0
    ) == 799.90


def test_align_handles_nan_book() -> None:
    assert align_limit_price(
        "BUY",
        pinned_last=685.14,
        tick=0.02,
        ask=float("nan"),
        bid=None,
        last=685.14,
    ) == 685.16
    assert math.isfinite(
        align_limit_price(
            "SELL", pinned_last=None, tick=0.02, ask=None, bid=None, last=100.0
        )
    )


def test_align_high_urgency_chases_through_book() -> None:
    # HIGH BUY should sit above ask by chase ticks.
    assert align_limit_price(
        "BUY",
        pinned_last=800.0,
        tick=0.02,
        ask=800.10,
        bid=800.08,
        last=800.0,
        urgency="HIGH",
    ) == 800.16
    assert align_limit_price(
        "SELL",
        pinned_last=800.0,
        tick=0.02,
        ask=799.96,
        bid=799.90,
        last=800.0,
        urgency="HIGH",
    ) == 799.84


def test_is_gfd_day_end_cancel() -> None:
    exc = Exception(
        "遇到错单: SHFE.au2504 BUY CLOSETODAY 1手 685.160000 "
        "交易日结束，自动撤销当日有效的委托单（GFD）"
    )
    assert is_gfd_day_end_cancel(exc)
    assert not is_gfd_day_end_cancel(Exception("资金不足"))
