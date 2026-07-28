"""Unit tests for product margin rate lookup and estimation."""

from __future__ import annotations

from ignitequant.market.margin_rates import (
    apply_ref_margin_to_account,
    estimate_margin,
    margin_rate_for_symbol,
    parse_exchange_product,
)


def test_parse_and_au_rate() -> None:
    assert parse_exchange_product("SHFE.au2608") == ("SHFE", "au")
    assert parse_exchange_product("KQ.m@SHFE.au") == ("SHFE", "au")
    assert margin_rate_for_symbol("SHFE.au2610") == 0.16
    assert margin_rate_for_symbol("SHFE.ag2506") == 0.19
    assert margin_rate_for_symbol("SHFE.rb2510") == 0.07


def test_estimate_au_margin() -> None:
    # 1 lot au @ 880, multiplier 1000, 16% → 140_800
    m = estimate_margin(price=880.0, lots=1, multiplier=1000.0, margin_rate=0.16)
    assert m == 140_800.0
    ref = apply_ref_margin_to_account(
        equity=1_000_000.0,
        symbol="SHFE.au2608",
        net_position=1,
        last_price=880.0,
    )
    assert ref["margin_source"] == "ref_product_margin"
    assert ref["margin"] == 140_800.0
    assert ref["margin_ratio"] == 0.1408
    assert ref["margin_rate_pct"] == 16.0
