"""Phase 3 tests — RiskEngine (SOP5), executor, roll, state machine, fault injection."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ignitequant.config import DecisionConfig, default_decision_config
from ignitequant.domain import (
    DecisionAction,
    FactorQuality,
    Regime,
    RiskAction,
    ReasonCode,
    SignalAction,
)
from ignitequant.domain.models import (
    AccountSnapshot,
    ContractSnapshot,
    FactorSnapshot,
    MarketSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    RuntimeSnapshot,
    SignalEvent,
    TargetPosition,
)
from ignitequant.engine import FalconDecisionPipeline, PositionStateMachine
from ignitequant.execution import RollStateMachine, TargetPositionExecutor
from ignitequant.risk import RiskEngine


def _signal(*, confidence: float = 1.0, legacy: int = 1) -> SignalEvent:
    now = datetime.now(timezone.utc)
    return SignalEvent(
        signal_id="s1",
        factor_snapshot_id="f1",
        action=SignalAction.ENTER_LONG,
        direction=1 if legacy > 0 else (-1 if legacy < 0 else 0),
        alpha=legacy / 3.0,
        strength=abs(legacy) / 3.0,
        confidence=confidence,
        generated_at=now,
        effective_from=now,
        expires_at=now,
        confirmation_bars=1,
        reason_codes=(),
        model_version="legacy",
        legacy_signal=legacy,
    )


def _target(desired: int, current: int = 0) -> TargetPosition:
    return TargetPosition(
        target_id="t1",
        signal_id="s1",
        symbol="SHFE.au2608",
        decision_action=DecisionAction.TARGET if desired != current else DecisionAction.HOLD,
        current_position=current,
        desired_position=desired,
        delta=desired - current,
        planned_entry_price=800.0,
        planned_stop_price=None,
        stop_distance=None,
        risk_per_lot=None,
        requested_risk=Decimal("0"),
        sizing_method="legacy_fixed_lot",
        reason_codes=(),
        config_version="falcon_legacy_v1",
    )


def _ctx(
    *,
    desired: int = 1,
    current: int = 0,
    runtime: RuntimeSnapshot | None = None,
    confidence: float = 1.0,
    data_age: float = 0.0,
    limit_locked: bool = False,
    contract_valid: bool = True,
):
    return dict(
        target=_target(desired, current),
        signal=_signal(confidence=confidence),
        market=MarketSnapshot(
            symbol="SHFE.au2608",
            last_price=800.0,
            data_age_seconds=data_age,
            is_upper_limit_locked=limit_locked,
        ),
        contract=ContractSnapshot(symbol="SHFE.au2608", is_valid=contract_valid),
        position=PositionSnapshot(symbol="SHFE.au2608", net_position=current),
        account=AccountSnapshot(
            account_id="a",
            equity=1_000_000,
            available=1_000_000,
            margin=0,
            margin_ratio=0,
        ),
        portfolio=PortfolioSnapshot(),
        runtime=runtime
        or RuntimeSnapshot(
            reconciliation_matched=True,
            unknown_order_count=0,
            kill_switch_active=False,
        ),
    )


def test_rule_priority_kill_switch_halts() -> None:
    engine = RiskEngine()
    decision = engine.evaluate(
        **_ctx(runtime=RuntimeSnapshot(kill_switch_active=True))
    )
    assert decision.action is RiskAction.HALT
    assert ReasonCode.KILL_SWITCH_ACTIVE.value in decision.rule_hits


def test_risk_reducing_allowed_when_recon_mismatch() -> None:
    engine = RiskEngine()
    decision = engine.evaluate(
        **_ctx(
            desired=0,
            current=2,
            runtime=RuntimeSnapshot(reconciliation_matched=False),
        )
    )
    assert decision.action is RiskAction.PASS
    assert ReasonCode.RISK_REDUCING_ORDER.value in decision.rule_hits


def test_new_risk_rejected_when_recon_mismatch() -> None:
    engine = RiskEngine()
    decision = engine.evaluate(
        **_ctx(
            desired=2,
            current=0,
            runtime=RuntimeSnapshot(reconciliation_matched=False),
        )
    )
    assert decision.action is RiskAction.REJECT
    assert ReasonCode.RECONCILIATION_MISMATCH.value in decision.rule_hits


def test_resize_to_max_lots() -> None:
    engine = RiskEngine(DecisionConfig())
    decision = engine.evaluate(**_ctx(desired=9, current=0))
    assert decision.action is RiskAction.RESIZE
    assert decision.approved_position == 3
    assert ReasonCode.POSITION_LIMIT.value in decision.rule_hits


def test_stale_data_blocks_new_entries() -> None:
    engine = RiskEngine()
    decision = engine.evaluate(**_ctx(desired=1, current=0, data_age=120))
    assert decision.action is RiskAction.REJECT
    assert ReasonCode.DATA_STALE.value in decision.rule_hits


def test_executor_idempotent_and_fill_gate() -> None:
    class _DummyTask:
        def __init__(self) -> None:
            self.targets: list[int] = []

        def set_target_volume(self, volume: int) -> None:
            self.targets.append(volume)

    class _DummyApi:
        pass

    ex = TargetPositionExecutor(api=_DummyApi(), symbol="SHFE.au2608")
    ex._task = _DummyTask()  # bypass tqsdk import
    intent1 = ex.set_target(1, decision_id="b1", current_net=0, idempotency_key="k1")
    intent2 = ex.set_target(1, decision_id="b1", current_net=0, idempotency_key="k1")
    assert intent1 is not None and intent2 is not None
    assert intent1.intent_id == intent2.intent_id
    assert ex._task.targets == [1]  # duplicate suppressed

    assert ex.state.phase.value == "ENTRY_PENDING"
    fill = ex.poll_position(1, last_price=801.0, atr=1.5, signal=2, fill_price=799.5)
    assert fill is not None
    assert fill.price == 799.5
    assert ex.state.phase.value == "OPEN"
    assert ex.state.entry is not None
    assert ex.state.entry.confirmed is True
    assert ex.state.entry.fill_price == 799.5
    assert ex.state.entry.intent_price == 801.0


def test_roll_blocks_switch_until_flat() -> None:
    roll = RollStateMachine()
    roll.detect("SHFE.au2608", "SHFE.au2610")
    roll.mark_flattening()
    assert roll.in_progress
    roll.on_old_position(1)
    assert roll.phase.value == "WAIT_FLAT"
    with pytest.raises(RuntimeError):
        roll.complete_switch()
    roll.on_old_position(0)
    symbol = roll.complete_switch()
    assert symbol == "SHFE.au2610"
    assert not roll.in_progress


def test_unknown_order_blocks_new_risk() -> None:
    engine = RiskEngine()
    decision = engine.evaluate(
        **_ctx(runtime=RuntimeSnapshot(unknown_order_count=1))
    )
    assert decision.action is RiskAction.REJECT
    assert ReasonCode.UNKNOWN_ORDER_EXISTS.value in decision.rule_hits


def test_phase0_golden_still_green_via_pipeline() -> None:
    # Smoke: pipeline path unchanged for characterization.
    import json
    from pathlib import Path

    import pandas as pd

    root = Path(__file__).resolve().parents[2]
    bars = pd.read_csv(root / "tests/fixtures/falcon_phase0/trend_up.csv")
    golden = json.loads(
        (root / "tests/golden/falcon_phase0/trend_up.json").read_text(encoding="utf-8")
    )["records"]
    rows = FalconDecisionPipeline(default_decision_config()).characterization_rows(bars)
    assert rows == golden
