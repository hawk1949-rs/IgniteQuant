"""Signal source resolution for overseas-priced instruments."""

from __future__ import annotations

from ignitequant.market.symbols import (
    instrument_by_id,
    resolve_signal_source,
)


def test_au_ag_overseas_pricing() -> None:
    au = instrument_by_id("au")
    assert au.pricing_basis == "overseas"
    assert au.overseas_id == "gc"
    src = resolve_signal_source(au)
    assert src.pricing_basis == "overseas"
    assert src.decision_symbol == "XAUUSD"
    assert src.domestic_signal_symbol == "KQ.m@SHFE.au"
    assert src.yahoo_symbol == "XAUUSD=X"
    assert src.eastmoney_secid == "122.XAU"

    ag = resolve_signal_source(instrument_by_id("ag"))
    assert ag.decision_symbol == "XAGUSD"
    assert ag.eastmoney_secid == "122.XAG"


def test_rb_fg_remain_domestic() -> None:
    rb = resolve_signal_source(instrument_by_id("rb"))
    assert rb.pricing_basis == "domestic"
    assert rb.decision_symbol == "KQ.m@SHFE.rb"
    assert rb.overseas_id is None

    fg = resolve_signal_source(instrument_by_id("fg"))
    assert fg.pricing_basis == "domestic"
