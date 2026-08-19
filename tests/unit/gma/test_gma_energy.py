"""GMA 2.0 energy overlay: chase filter, POC pullback, v1 unchanged by default."""

from __future__ import annotations

import numpy as np

from ignitequant.domain.enums import Regime
from ignitequant.strategies.gma.config import GMAIndicatorConfig, load_gma_runtime
from ignitequant.strategies.gma.energy import (
    EnergyZone,
    apply_energy_overlay,
    classify_energy_zone,
)
from ignitequant.strategies.gma.indicators import TenWState, VolumeProfile
from ignitequant.strategies.gma.regime import Alignment, AlignmentSnapshot
from ignitequant.strategies.gma.signal import GMASignal, generate_signal


def _vp(**kwargs) -> VolumeProfile:
    base = dict(
        poc=100.0,
        vah=102.0,
        val=98.0,
        edge_high=105.0,
        edge_low=95.0,
        gap_high=None,
        gap_low=None,
    )
    base.update(kwargs)
    return VolumeProfile(**base)


def _tenw(color: int = 1) -> TenWState:
    return TenWState(
        fast=100.0,
        slow=99.0,
        fast_color=color,
        slow_color=color,
        fast_above_slow=color > 0,
        golden_cross=False,
        death_cross=False,
        single_drive=True,
        single_direction=True,
        single_conflict=False,
    )


def _align(kind: Alignment, direction: int) -> AlignmentSnapshot:
    state = _tenw(direction or 1)
    return AlignmentSnapshot(
        alignment=kind,
        direction=direction,
        regime=Regime.TREND_UP if direction > 0 else (Regime.TREND_DOWN if direction < 0 else Regime.RANGE),
        m15=state,
        h1=state,
        h4=state,
        drive_15_1_4=kind is Alignment.DRIVE,
        direction_1_4=kind is Alignment.DIRECTION,
        conflict_1_4=False,
        reason=f"ALIGN_{kind.value}",
    )


def _sig(*, close: float, desired: int | None, reasons: tuple[str, ...], alignment: Alignment) -> GMASignal:
    return GMASignal(
        signal=2 if desired and desired > 0 else (-2 if desired and desired < 0 else 0),
        desired=desired,
        reasons=reasons,
        close=close,
        atr=1.0,
        alignment=alignment,
        regime_direction=1 if alignment is not Alignment.RANGE else 0,
        m15_fast=100.0,
        m15_slow=99.0,
        h1_mid=100.0,
        poc=100.0,
        vah=102.0,
        val=98.0,
    )


def _overlay(
    sig: GMASignal,
    *,
    align: AlignmentSnapshot,
    s5: TenWState | None = None,
    vp: VolumeProfile | None = None,
) -> GMASignal:
    zeros = np.zeros(12)
    return apply_energy_overlay(
        sig,
        vp=vp or _vp(),
        s5=s5 or _tenw(1),
        align=align,
        current_target=0,
        high5=zeros + 101,
        low5=zeros + 99,
        close5=zeros + 100,
        volume5=zeros + 50,
        indicators=GMAIndicatorConfig(energy_enabled=True),
    )


def test_zone_poc_and_edges() -> None:
    vp = _vp()
    assert classify_energy_zone(100.0, vp, atr=1.0, near_pct=0.002) is EnergyZone.AT_POC
    assert classify_energy_zone(104.0, vp, atr=1.0, near_pct=0.002) is EnergyZone.ABOVE_VAH
    assert classify_energy_zone(96.0, vp, atr=1.0, near_pct=0.002) is EnergyZone.BELOW_VAL


def test_trend_long_chase_above_vah_blocked() -> None:
    out = _overlay(
        _sig(close=104.0, desired=1, reasons=("ALIGN_DRIVE", "ENTRY_DRIVE_CROSS"), alignment=Alignment.DRIVE),
        align=_align(Alignment.DRIVE, 1),
    )
    assert out.desired is None
    assert "ENERGY_BLOCK_CHASE" in out.reasons


def test_trend_long_below_val_passes() -> None:
    out = _overlay(
        _sig(close=96.5, desired=1, reasons=("ALIGN_DRIVE", "ENTRY_DRIVE_CROSS"), alignment=Alignment.DRIVE),
        align=_align(Alignment.DRIVE, 1),
    )
    assert out.desired == 1
    assert "ENERGY_PASS" in out.reasons


def test_range_inside_value_area_blocked() -> None:
    out = _overlay(
        _sig(close=100.5, desired=1, reasons=("ALIGN_RANGE", "ENTRY_RANGE_VAL"), alignment=Alignment.RANGE),
        align=_align(Alignment.RANGE, 0),
    )
    assert out.desired is None
    assert "ENERGY_INSIDE_VA" in out.reasons


def test_poc_pullback_can_enter_when_v1_holds() -> None:
    out = _overlay(
        _sig(close=100.0, desired=None, reasons=("ALIGN_DIRECTION", "HOLD"), alignment=Alignment.DIRECTION),
        align=_align(Alignment.DIRECTION, 1),
        s5=_tenw(1),
    )
    assert out.desired == 1
    assert "ENTRY_ENERGY_POC" in out.reasons


def test_explicit_flat_not_overridden() -> None:
    out = _overlay(
        _sig(close=104.0, desired=0, reasons=("ALIGN_DRIVE", "EXIT_REGIME_FLIP"), alignment=Alignment.DRIVE),
        align=_align(Alignment.DRIVE, -1),
    )
    assert out.desired == 0
    assert "ENERGY_KEEP_EXIT" in out.reasons


def test_v2_profile_enables_energy() -> None:
    runtime = load_gma_runtime("gma_v2")
    assert runtime.indicators.energy_enabled is True
    assert runtime.decision.config_version == "gma_v2"
    v1 = load_gma_runtime("gma_v1")
    assert v1.indicators.energy_enabled is False


def test_energy_disabled_matches_v1_generate_signal() -> None:
    from tests.unit.gma.test_gma_core import _bars

    bars = _bars(900, drift=0.03)
    off = GMAIndicatorConfig(energy_enabled=False)
    a = generate_signal(bars, indicators=off, current_target=0)
    b = generate_signal(bars, indicators=GMAIndicatorConfig(), current_target=0)
    assert a == b
