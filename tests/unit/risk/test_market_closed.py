"""MARKET_CLOSED risk gate: signal may exist; no order; position unchanged."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ignitequant.domain.enums import DecisionAction, ReasonCode, RiskAction, SignalAction
from ignitequant.domain.models import (
    AccountSnapshot,
    ContractSnapshot,
    MarketSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    RuntimeSnapshot,
    SignalEvent,
    TargetPosition,
)
from ignitequant.market.session import (
    TRADE_STATUS_CLOSED,
    TRADE_STATUS_OPEN,
    shfe_precious_session_open,
)
from ignitequant.risk import RiskEngine


def _signal() -> SignalEvent:
    now = datetime.now(timezone.utc)
    return SignalEvent(
        signal_id="s1",
        factor_snapshot_id="f1",
        action=SignalAction.ENTER_LONG,
        direction=1,
        alpha=0.5,
        strength=0.5,
        confidence=1.0,
        generated_at=now,
        effective_from=now,
        expires_at=now,
        confirmation_bars=1,
        reason_codes=("gv=1",),
        model_version="legacy",
        legacy_signal=2,
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


def _eval(*, desired: int, current: int, trade_status: str):
    engine = RiskEngine()
    return engine.evaluate(
        target=_target(desired, current),
        signal=_signal(),
        market=MarketSnapshot(
            symbol="SHFE.au2608",
            last_price=800.0,
            trade_status=trade_status,
            data_age_seconds=0.0,
        ),
        contract=ContractSnapshot(symbol="SHFE.au2608", is_valid=True),
        position=PositionSnapshot(symbol="SHFE.au2608", net_position=current),
        account=AccountSnapshot(
            account_id="a",
            equity=1_000_000,
            available=1_000_000,
            margin=0,
            margin_ratio=0,
        ),
        portfolio=PortfolioSnapshot(),
        runtime=RuntimeSnapshot(
            reconciliation_matched=True,
            unknown_order_count=0,
            kill_switch_active=False,
        ),
    )


def test_market_closed_rejects_new_entry() -> None:
    d = _eval(desired=1, current=0, trade_status=TRADE_STATUS_CLOSED)
    assert d.action is RiskAction.REJECT
    assert ReasonCode.MARKET_CLOSED.value in d.rule_hits
    assert d.approved_position == 0


def test_market_closed_rejects_even_risk_reducing() -> None:
    """2A: closed session → no order at all; hold existing position."""
    d = _eval(desired=0, current=2, trade_status=TRADE_STATUS_CLOSED)
    assert d.action is RiskAction.REJECT
    assert ReasonCode.MARKET_CLOSED.value in d.rule_hits
    assert d.approved_position == 2


def test_market_open_allows_entry() -> None:
    d = _eval(desired=1, current=0, trade_status=TRADE_STATUS_OPEN)
    assert d.action is RiskAction.PASS
    assert ReasonCode.MARKET_CLOSED.value not in d.rule_hits


def test_session_helper_has_trade_status() -> None:
    s = shfe_precious_session_open()
    assert "trade_status" in s
    assert s["trade_status"] in {TRADE_STATUS_OPEN, TRADE_STATUS_CLOSED}
    assert s["open"] == (s["trade_status"] == TRADE_STATUS_OPEN)
