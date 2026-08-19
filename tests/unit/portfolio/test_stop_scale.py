"""Domestic fill ↔ overseas signal-space mapping for SL/TP."""

from __future__ import annotations

from ignitequant.portfolio.stop_scale import map_fill_to_signal_price, scale_atr_to_entry
from ignitequant.strategies.gma.pipeline import GMADecisionPipeline
from strategies.falcon.risk import RiskAction as LegacyRiskAction


def test_map_fill_to_signal_price_scales_xauusd_vs_shfe() -> None:
    mapped = map_fill_to_signal_price(
        675.0,
        domestic_mark=675.0,
        overseas_close=2900.0,
    )
    assert abs(mapped - 2900.0) < 1e-9


def test_map_fill_to_signal_price_noop_when_same_scale() -> None:
    mapped = map_fill_to_signal_price(
        675.0,
        domestic_mark=675.0,
        overseas_close=676.0,
    )
    assert mapped == 675.0


def test_unmapped_domestic_stop_fires_on_overseas_high() -> None:
    """Reproduction: arm in yuan, check against XAUUSD high → every short is SL."""
    pipe = GMADecisionPipeline()
    pipe.current_target = -1
    pipe.confirm_local_fill(price=675.0, atr=5.0, signal=-2)
    assert pipe.risk.state.stop_price is not None
    assert pipe.risk.state.stop_price < 700.0
    fired = pipe.risk.check(-1, 2905.0, 2898.0, 2902.0)
    assert fired == LegacyRiskAction.STOP_LOSS


def test_mapped_overseas_stop_does_not_instant_stop_short() -> None:
    pipe = GMADecisionPipeline()
    pipe.current_target = -1
    arm = map_fill_to_signal_price(675.0, domestic_mark=675.0, overseas_close=2900.0)
    pipe.confirm_local_fill(price=arm, atr=5.0, signal=-2)
    assert pipe.risk.state.stop_price is not None
    assert pipe.risk.state.stop_price > 2900.0
    quiet = pipe.risk.check(-1, 2905.0, 2898.0, 2902.0)
    assert quiet == LegacyRiskAction.NONE
    hit = pipe.risk.check(-1, 2915.0, 2898.0, 2910.0)
    assert hit == LegacyRiskAction.STOP_LOSS


def test_mapped_overseas_take_does_not_instant_take_long() -> None:
    pipe = GMADecisionPipeline()
    pipe.current_target = 1
    arm = map_fill_to_signal_price(675.0, domestic_mark=675.0, overseas_close=2900.0)
    pipe.confirm_local_fill(price=arm, atr=5.0, signal=2)
    quiet = pipe.risk.check(1, 2905.0, 2898.0, 2902.0)
    assert quiet == LegacyRiskAction.NONE


def test_scale_atr_to_entry_preserves_fraction() -> None:
    scaled = scale_atr_to_entry(10.0, 2900.0, 675.0)
    assert abs(scaled - 675.0 * 10.0 / 2900.0) < 1e-9
