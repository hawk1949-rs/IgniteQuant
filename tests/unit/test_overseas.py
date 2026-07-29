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
    assert au["yahoo_symbol"] == "GC=F"
    assert au["eastmoney_secid"] == "101.GC00Y"
    ag = cockpit_overseas_pair("ag")
    assert ag is not None
    assert ag["yahoo_symbol"] == "SI=F"
    assert cockpit_overseas_pair("rb") is None


def test_overseas_specs() -> None:
    gc = overseas_by_id("gc")
    assert gc.signal_symbol == "GC=F"
    assert gc.exchange == "COMEX"
    pair = overseas_pair_for_domestic("au")
    assert pair is not None
    assert pair["id"] == "gc"
