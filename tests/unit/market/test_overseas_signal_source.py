"""Signal source resolution for overseas-priced instruments."""

from __future__ import annotations

from dashboard.catalog import SYMBOLS
from ignitequant.market.overseas import lab_overseas_supported
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


def test_use_overseas_false_forces_domestic_for_au() -> None:
    src = resolve_signal_source(instrument_by_id("au"), use_overseas=False)
    assert src.pricing_basis == "domestic"
    assert src.decision_symbol == "KQ.m@SHFE.au"
    assert src.overseas_id is None


def test_use_overseas_true_loads_overseas_for_au() -> None:
    src = resolve_signal_source(instrument_by_id("au"), use_overseas=True)
    assert src.pricing_basis == "overseas"
    assert src.decision_symbol == "XAUUSD"


def test_use_overseas_true_ignored_for_rb() -> None:
    src = resolve_signal_source(instrument_by_id("rb"), use_overseas=True)
    assert src.pricing_basis == "domestic"
    assert src.decision_symbol == "KQ.m@SHFE.rb"


def test_lab_catalog_overseas_supported_only_au_ag() -> None:
    assert lab_overseas_supported("au")
    assert lab_overseas_supported("ag")
    assert not lab_overseas_supported("rb")
    assert not lab_overseas_supported("fg")
    assert SYMBOLS["au"].overseas_supported is True
    assert SYMBOLS["ag"].overseas_supported is True
    assert SYMBOLS["rb"].overseas_supported is False
    assert SYMBOLS["fg"].overseas_supported is False
    assert SYMBOLS["au"].overseas_pair is not None
    assert SYMBOLS["au"].overseas_pair["display_symbol"] in {"XAUUSD", "GC"}
    assert SYMBOLS["rb"].overseas_pair is None


def test_rb_fg_remain_domestic() -> None:
    rb = resolve_signal_source(instrument_by_id("rb"))
    assert rb.pricing_basis == "domestic"
    assert rb.decision_symbol == "KQ.m@SHFE.rb"
    assert rb.overseas_id is None

    fg = resolve_signal_source(instrument_by_id("fg"))
    assert fg.pricing_basis == "domestic"
