"""apply_pretrade must gate STOP/TAKE with MARKET_CLOSED (not PASS on HOLD)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ignitequant.domain.enums import (
    DecisionAction,
    FactorQuality,
    ReasonCode,
    Regime,
    RiskAction,
    SignalAction,
)
from ignitequant.domain.models import (
    FactorSnapshot,
    PipelineResult,
    RiskDecision,
    SignalEvent,
    TargetPosition,
)
from ignitequant.engine.runtime_bridge import apply_pretrade, make_risk_engine
from ignitequant.market.session import TRADE_STATUS_CLOSED, TRADE_STATUS_OPEN


def _result(*, applied_action: str, desired: int, current: int) -> PipelineResult:
    now = datetime.now(timezone.utc)
    signal = SignalEvent(
        signal_id="s1",
        factor_snapshot_id="f1",
        action=SignalAction.HOLD,
        direction=0,
        alpha=0.0,
        strength=0.0,
        confidence=1.0,
        generated_at=now,
        effective_from=now,
        expires_at=now,
        confirmation_bars=1,
        reason_codes=("gv=0",),
        model_version="legacy",
        legacy_signal=0,
    )
    target = TargetPosition(
        target_id="t1",
        signal_id="s1",
        symbol="SHFE.au2610",
        decision_action=DecisionAction.HOLD,
        current_position=current,
        desired_position=desired,
        delta=desired - current,
        planned_entry_price=900.0,
        planned_stop_price=None,
        stop_distance=None,
        risk_per_lot=None,
        requested_risk=Decimal("0"),
        sizing_method="legacy_fixed_lot",
        reason_codes=("LEGACY_FIXED_LOT",),
        config_version="falcon_legacy_v1",
    )
    risk = RiskDecision(
        risk_decision_id="r1",
        target_id="t1",
        action=RiskAction.PASS,
        requested_position=desired,
        approved_position=desired,
        requested_risk=Decimal("0"),
        approved_risk=Decimal("0"),
        rule_hits=(),
        warnings=(),
        evaluated_at=now,
        risk_config_version="falcon_legacy_v1",
        risk_snapshot_id="rt",
    )
    factors = FactorSnapshot(
        factor_snapshot_id="f1",
        symbol="SHFE.au2610",
        bar_id="b1",
        data_as_of=now,
        values={},
        regime=Regime.TREND_UP,
        quality=FactorQuality.READY,
        factor_version="legacy",
    )
    return PipelineResult(
        bar_id="b1",
        factors=factors,
        signal=signal,
        target=target,
        risk_decision=risk,
        applied_action=applied_action,
        target_before=current,
        target_after=0 if applied_action in {"STOP_LOSS", "TAKE_PROFIT"} else desired,
        sizing_target=desired,
        legacy_score_parts=(0, 0, 0, 0),
    )


def test_take_profit_closed_rejects_market_closed() -> None:
    # Sizing still HOLD desired=1 (the bug that used to show PASS).
    result = _result(applied_action="TAKE_PROFIT", desired=1, current=1)
    pre = apply_pretrade(
        result,
        net_position=1,
        last_price=936.0,
        risk_engine=make_risk_engine(),
        trade_status=TRADE_STATUS_CLOSED,
        symbol="SHFE.au2610",
    )
    assert pre.action is RiskAction.REJECT
    assert ReasonCode.MARKET_CLOSED.value in pre.rule_hits
    assert pre.approved_position == 1
    assert pre.requested_position == 0


def test_take_profit_open_allows_flatten() -> None:
    result = _result(applied_action="TAKE_PROFIT", desired=1, current=1)
    pre = apply_pretrade(
        result,
        net_position=1,
        last_price=936.0,
        risk_engine=make_risk_engine(),
        trade_status=TRADE_STATUS_OPEN,
        symbol="SHFE.au2610",
    )
    assert pre.action is RiskAction.PASS
    assert ReasonCode.MARKET_CLOSED.value not in pre.rule_hits
    assert pre.approved_position == 0


def test_hold_closed_still_passes_no_order() -> None:
    result = _result(applied_action="HOLD", desired=1, current=1)
    # HOLD is not an exit action; target unchanged → no order needed.
    pre = apply_pretrade(
        result,
        net_position=1,
        last_price=936.0,
        risk_engine=make_risk_engine(),
        trade_status=TRADE_STATUS_CLOSED,
        symbol="SHFE.au2610",
    )
    assert pre.action is RiskAction.PASS
    assert pre.approved_position == 1
