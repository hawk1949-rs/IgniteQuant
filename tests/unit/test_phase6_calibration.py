"""Phase 6 — profiles, calibration, go-live gate (legacy default unchanged)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ignitequant.config import (
    DEFAULT_PROFILE,
    default_decision_config,
    list_profiles,
    load_decision_config,
)
from ignitequant.engine import FalconDecisionPipeline
from ignitequant.research import GoLiveGate, compare_profiles, evaluate_bars

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "falcon_phase0" / "trend_up.csv"


def test_profiles_listed() -> None:
    names = list_profiles()
    assert DEFAULT_PROFILE in names
    assert "falcon_5m_sqrt_v1" in names
    assert "falcon_5m_lots_v1" in names


def test_legacy_profile_matches_code_default() -> None:
    code = default_decision_config()
    file_cfg = load_decision_config(DEFAULT_PROFILE)
    assert file_cfg.factor.ma_fast == code.factor.ma_fast
    assert file_cfg.factor.ma_slow == code.factor.ma_slow
    assert file_cfg.risk.cooldown_bars == code.risk.cooldown_bars
    assert file_cfg.risk.sl_atr_mult == code.risk.sl_atr_mult
    assert file_cfg.config_hash() == code.config_hash()


def test_candidate_profile_differs_from_legacy() -> None:
    legacy = load_decision_config(DEFAULT_PROFILE)
    sqrt = load_decision_config("falcon_5m_sqrt_v1")
    assert sqrt.factor.ma_slow > legacy.factor.ma_slow
    assert sqrt.risk.cooldown_bars > legacy.risk.cooldown_bars
    assert sqrt.config_hash() != legacy.config_hash()
    assert sqrt.decision_mode == "calibrated_5m"


def test_lots_profile_changes_sizing_only() -> None:
    legacy = load_decision_config(DEFAULT_PROFILE)
    lots = load_decision_config("falcon_5m_lots_v1")
    assert lots.factor.ma_fast == legacy.factor.ma_fast
    assert lots.sizing.lot_by_signal[3] == 3
    assert legacy.sizing.lot_by_signal[3] == 1


def test_adapter_respects_factor_periods() -> None:
    bars = pd.read_csv(FIXTURE)
    legacy = FalconDecisionPipeline(load_decision_config(DEFAULT_PROFILE))
    sqrt = FalconDecisionPipeline(load_decision_config("falcon_5m_sqrt_v1"))
    # Same bar window — factor values should differ when periods change
    r1 = legacy.on_bar_close(bars.iloc[:200], trade=False)
    r2 = sqrt.on_bar_close(bars.iloc[:200], trade=False)
    assert r1.factors.values.get("ma52") != r2.factors.values.get("ma52")


def test_offline_calibration_and_gate() -> None:
    bars = pd.read_csv(FIXTURE)
    legacy = load_decision_config(DEFAULT_PROFILE)
    m = evaluate_bars(bars, legacy, profile_id=DEFAULT_PROFILE)
    assert m.warm_bars > 0
    assert m.target_changes >= 0
    gate = GoLiveGate(min_warm_bars=100, require_positive_proxy_net=False, require_stress_survive=False)
    verdict = gate.evaluate(m)
    assert "passed" in verdict
    assert verdict["promote"] is False  # never auto-promote


def test_compare_profiles_smoke() -> None:
    bars = pd.read_csv(FIXTURE)
    report = compare_profiles(
        bars,
        {
            "legacy": load_decision_config(DEFAULT_PROFILE),
            "lots": load_decision_config("falcon_5m_lots_v1"),
        },
        gate=GoLiveGate(
            min_warm_bars=100,
            require_positive_proxy_net=False,
            require_stress_survive=False,
        ),
    )
    assert "legacy" in report["profiles"]
    assert "lots" in report["profiles"]
