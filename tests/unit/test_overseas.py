"""Overseas instrument catalog tests."""

from __future__ import annotations

from ignitequant.market.overseas import (
    cockpit_overseas_pair,
    overseas_by_id,
    overseas_pair_for_domestic,
)


def test_cockpit_pairs_au_ag() -> None:
    au = cockpit_overseas_pair("au")
    assert au is not None
    assert au["yahoo_symbol"] == "XAUUSD=X"
    assert au["eastmoney_secid"] == "122.XAU"
    assert au["display_symbol"] == "XAUUSD"
    ag = cockpit_overseas_pair("ag")
    assert ag is not None
    assert ag["yahoo_symbol"] == "XAGUSD=X"
    assert ag["eastmoney_secid"] == "122.XAG"
    assert cockpit_overseas_pair("rb") is None


def test_overseas_specs() -> None:
    gc = overseas_by_id("gc")
    assert gc.signal_symbol == "XAUUSD"
    assert gc.eastmoney_secid == "122.XAU"
    assert gc.exchange == "OTC"
    pair = overseas_pair_for_domestic("au")
    assert pair is not None
    assert pair["id"] == "gc"
