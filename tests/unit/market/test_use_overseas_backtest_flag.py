"""Strategy Lab ``use_overseas`` wiring (unit + smoke checklist).

Manual smoke (Workbench):
1. Select rb → 「使用外盘行情」disabled, helper text「该品种无外盘对照」.
2. Select au → switch enabled, default ON; toggle OFF and run short local backtest
   → decision uses domestic KQ.m@SHFE.au (no XAUUSD decision_symbol).
3. au + switch ON + short range → fills only when domestic session open;
   no ghost fills during 内盘休市.
"""

from __future__ import annotations

from ignitequant.market.symbols import instrument_by_id, resolve_signal_source


def test_resolve_respects_explicit_false_even_when_spec_overseas() -> None:
    au = instrument_by_id("au")
    assert au.pricing_basis == "overseas"
    forced = resolve_signal_source(au, use_overseas=False)
    assert forced.pricing_basis == "domestic"
    assert forced.decision_symbol == au.signal_symbol


def test_default_none_matches_lab_supported() -> None:
    assert resolve_signal_source(instrument_by_id("au"), use_overseas=None).pricing_basis == (
        "overseas"
    )
    assert resolve_signal_source(instrument_by_id("rb"), use_overseas=None).pricing_basis == (
        "domestic"
    )
