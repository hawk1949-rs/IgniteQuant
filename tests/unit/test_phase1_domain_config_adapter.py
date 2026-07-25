"""Phase 1 unit tests: domain contracts, config, legacy adapter."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ignitequant.config import DecisionConfig, default_decision_config
from ignitequant.domain import (
    DecisionAction,
    FactorSnapshot,
    Regime,
    SignalEvent,
    TargetPosition,
)
from ignitequant.strategies.falcon import LegacyDecisionAdapter
from tests.characterization.legacy_harness import RISK_PARAMETERS, run_legacy_characterization

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "falcon_phase0" / "trend_up.csv"
GOLDEN = ROOT / "tests" / "golden" / "falcon_phase0" / "trend_up.json"


def test_default_config_matches_production_risk_kwargs() -> None:
    cfg = default_decision_config()
    assert cfg.decision_mode == "legacy_compatible"
    assert cfg.risk_kwargs() == RISK_PARAMETERS
    assert cfg.risk_kwargs() == {
        "sl_atr_mult": 1.3,
        "tp_atr_mult": 2.3,
        "cooldown_bars": 4,
    }
    assert cfg.sizing.lot_by_signal == {1: 1, 2: 1, 3: 1}
    assert cfg.factor.kline_seconds == 300


def test_config_hash_is_stable() -> None:
    a = default_decision_config().config_hash()
    b = DecisionConfig().config_hash()
    assert a == b
    assert len(a) == 64


def test_sanitized_snapshot_has_no_secrets() -> None:
    snap = default_decision_config().sanitized_snapshot()
    blob = json.dumps(snap)
    for needle in ("TQ_PASS", "password", "TOKEN", "secret"):
        assert needle.lower() not in blob.lower()
    assert "config_hash" in snap


def test_domain_objects_are_json_serializable() -> None:
    from datetime import date, datetime, timezone
    from decimal import Decimal

    from ignitequant.domain import FactorQuality, SignalAction

    factor = FactorSnapshot(
        factor_snapshot_id="f1",
        symbol="KQ.m@SHFE.au",
        bar_id="b1",
        data_as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
        values={"ma52": 1.0, "atr": None},
        regime=Regime.TREND_UP,
        quality=FactorQuality.READY,
        factor_version="v1",
    )
    signal = SignalEvent(
        signal_id="s1",
        factor_snapshot_id="f1",
        action=SignalAction.HOLD,
        direction=0,
        alpha=0.0,
        strength=0.0,
        confidence=1.0,
        generated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        effective_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        confirmation_bars=1,
        reason_codes=("x",),
        model_version="m1",
        legacy_signal=0,
    )
    target = TargetPosition(
        target_id="t1",
        signal_id="s1",
        symbol="KQ.m@SHFE.au",
        decision_action=DecisionAction.HOLD,
        current_position=0,
        desired_position=0,
        delta=0,
        planned_entry_price=None,
        planned_stop_price=None,
        stop_distance=None,
        risk_per_lot=None,
        requested_risk=Decimal("0"),
        sizing_method="legacy_fixed_lot",
        reason_codes=(),
        config_version="c1",
    )
    payload = {
        "factor": factor.to_dict(),
        "signal": signal.to_dict(),
        "target": target.to_dict(),
        "day": date(2025, 1, 1).isoformat(),
    }
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "TREND_UP" in encoded
    assert json.loads(encoded)["factor"]["values"]["atr"] is None


@pytest.mark.parametrize(
    "scenario",
    ["trend_up", "trend_down", "sideways_transition"],
)
def test_legacy_adapter_matches_golden_master(scenario: str) -> None:
    fixture = ROOT / "tests" / "fixtures" / "falcon_phase0" / f"{scenario}.csv"
    golden_path = ROOT / "tests" / "golden" / "falcon_phase0" / f"{scenario}.json"
    bars = pd.read_csv(fixture)
    expected = json.loads(golden_path.read_text(encoding="utf-8"))["records"]

    adapter_rows = LegacyDecisionAdapter().characterization_rows(bars)
    harness_rows = run_legacy_characterization(bars)

    assert adapter_rows == expected
    assert harness_rows == expected


def test_legacy_adapter_rejects_non_legacy_mode() -> None:
    cfg = DecisionConfig(decision_mode="candidate")
    with pytest.raises(ValueError, match="legacy_compatible"):
        LegacyDecisionAdapter(cfg)
