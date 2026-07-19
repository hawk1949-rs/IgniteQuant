"""Phase 0 characterization tests against approved Falcon Golden Masters.

These tests freeze current behavior. They must not change strategy formulas.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from tests.characterization.legacy_harness import (
    FLOAT_DIGITS,
    RISK_PARAMETERS,
    run_legacy_characterization,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "falcon_phase0"
GOLDEN_DIR = ROOT / "tests" / "golden" / "falcon_phase0"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"

SCENARIOS = ("trend_up", "trend_down", "sideways_transition")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST_PATH.is_file(), "Phase 0 manifest missing; capture fixtures first"
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_fixture_checksum_matches_manifest(manifest: dict, scenario: str) -> None:
    meta = manifest["scenarios"][scenario]
    fixture = ROOT / meta["file"]
    assert fixture.is_file()
    assert _sha256(fixture) == meta["input_sha256"]
    assert meta["bars"] == 400


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_golden_checksum_matches_manifest(manifest: dict, scenario: str) -> None:
    meta = manifest["scenarios"][scenario]
    golden = ROOT / meta["golden_file"]
    assert golden.is_file()
    assert _sha256(golden) == meta["golden_sha256"]
    assert meta["golden_records"] == 349


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_bar_by_bar_matches_golden_master(manifest: dict, scenario: str) -> None:
    meta = manifest["scenarios"][scenario]
    bars = pd.read_csv(ROOT / meta["file"])
    golden = json.loads((ROOT / meta["golden_file"]).read_text(encoding="utf-8"))

    assert golden["scenario"] == scenario
    assert golden["input_sha256"] == meta["input_sha256"]
    assert golden["float_digits"] == FLOAT_DIGITS
    assert golden["risk_parameters"] == RISK_PARAMETERS

    actual = run_legacy_characterization(bars)
    expected = golden["records"]
    assert len(actual) == len(expected) == meta["golden_records"]

    for i, (got, want) in enumerate(zip(actual, expected)):
        assert got == want, f"{scenario} mismatch at record {i} bar_index={want.get('bar_index')}"


def test_characterization_is_deterministic(manifest: dict) -> None:
    meta = manifest["scenarios"]["trend_up"]
    bars = pd.read_csv(ROOT / meta["file"])
    first = run_legacy_characterization(bars)
    second = run_legacy_characterization(bars)
    assert first == second


def test_hold_none_and_flat_zero_semantics() -> None:
    """Document current sizing contract used by Golden Master."""
    from strategies.falcon.regime import Regime
    from strategies.falcon.sizing import lots_from_signal

    assert lots_from_signal(0, Regime.TREND_UP) is None  # HOLD
    assert lots_from_signal(1, Regime.RANGE) is None  # HOLD (no new entry)
    assert lots_from_signal(-2, Regime.TREND_UP) is None  # HOLD (conflict)
    assert lots_from_signal(1, Regime.TREND_UP) == 1
    assert lots_from_signal(-3, Regime.TREND_DOWN) == -1


def test_risk_manager_defaults_differ_from_entry_parameters() -> None:
    """Known debt: class defaults != production entry kwargs."""
    from strategies.falcon.risk import RiskManager

    defaults = RiskManager()
    assert defaults.sl_atr_mult == 1.5
    assert defaults.tp_atr_mult == 2.5
    assert defaults.cooldown_bars == 3

    production = RiskManager(**RISK_PARAMETERS)
    assert production.sl_atr_mult == 1.3
    assert production.tp_atr_mult == 2.3
    assert production.cooldown_bars == 4


def test_golden_covers_all_applied_actions(manifest: dict) -> None:
    actions: set[str] = set()
    regimes: set[str] = set()
    for scenario in SCENARIOS:
        golden = json.loads(
            (ROOT / manifest["scenarios"][scenario]["golden_file"]).read_text(encoding="utf-8")
        )
        for row in golden["records"]:
            actions.add(row["applied_action"])
            regimes.add(row["regime"])

    # Evidence that fixtures exercise the decision surface (not a profitability claim).
    assert "HOLD" in actions
    assert regimes >= {"TREND_UP", "TREND_DOWN", "RANGE"}
