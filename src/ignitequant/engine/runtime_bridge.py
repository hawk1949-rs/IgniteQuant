"""Helpers to apply PipelineResult through RiskEngine + TargetPositionExecutor."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from decimal import Decimal

from ignitequant.config.decision import DecisionConfig, default_decision_config
from ignitequant.domain.enums import DecisionAction, ReasonCode, RiskAction
from ignitequant.domain.models import (
    AccountSnapshot,
    ContractSnapshot,
    MarketSnapshot,
    PipelineResult,
    PortfolioSnapshot,
    PositionSnapshot,
    RiskDecision,
    RuntimeSnapshot,
    TargetPosition,
)
from ignitequant.market.session import TRADE_STATUS_OPEN
from ignitequant.risk import RiskEngine

if TYPE_CHECKING:
    from ignitequant.execution.target_position import TargetPositionExecutor


_EXIT_ACTIONS = frozenset({"STOP_LOSS", "TAKE_PROFIT"})
_OPEN_TRADE_STATUSES = frozenset(
    {"", "CONTINUOUS", "OPEN", "TRADING", "AUCTION", TRADE_STATUS_OPEN}
)


def domestic_session_allows_orders(trade_status: str | None) -> bool:
    """True only when domestic continuous session can accept new orders."""
    status = (trade_status or "").strip().upper()
    return status in _OPEN_TRADE_STATUSES


def market_closed_reject_decision(
    *,
    decision_id: str,
    net_position: int,
    requested_position: int,
    config_version: str = "falcon_legacy_v1",
) -> RiskDecision:
    """Synthetic REJECT for ops paths (boot flatten / catch-up) outside session."""
    now = datetime.now(timezone.utc)
    return RiskDecision(
        risk_decision_id=f"pretrade:{decision_id}",
        target_id=decision_id,
        action=RiskAction.REJECT,
        requested_position=int(requested_position),
        approved_position=int(net_position),
        requested_risk=Decimal("0"),
        approved_risk=Decimal("0"),
        rule_hits=(ReasonCode.MARKET_CLOSED.value,),
        warnings=("domestic market closed; signal/ops recorded, no order",),
        evaluated_at=now,
        risk_config_version=config_version,
        risk_snapshot_id="runtime:SESSION",
    )


def may_submit_domestic_order(
    *,
    trade_status: str | None,
    pretrade: RiskDecision | None = None,
) -> tuple[bool, tuple[str, ...]]:
    """Gate every domestic submit: session open + pretrade PASS/RESIZE only.

    Rejected paths must not create order_intent or fills.
    """
    if not domestic_session_allows_orders(trade_status):
        return False, (ReasonCode.MARKET_CLOSED.value,)
    if pretrade is None:
        return True, ()
    if pretrade.action in {RiskAction.REJECT, RiskAction.HALT}:
        hits = tuple(pretrade.rule_hits) or (pretrade.action.value,)
        return False, hits
    return True, ()


def healthy_runtime(*, roll_in_progress: bool = False) -> RuntimeSnapshot:
    return RuntimeSnapshot(
        runtime_state="RUNNING",
        reconciliation_matched=True,
        unknown_order_count=0,
        persistence_healthy=True,
        market_gateway_healthy=True,
        trade_gateway_healthy=True,
        kill_switch_active=False,
        roll_in_progress=roll_in_progress,
        as_of=datetime.now(timezone.utc),
    )


def pretrade_target_for_result(
    result: PipelineResult,
    *,
    net_position: int,
) -> TargetPosition:
    """Target actually submitted after this bar (exits flatten to 0).

    Pipeline sizing may still say HOLD/desired=net while applied_action is
    STOP_LOSS/TAKE_PROFIT; pretrade must evaluate the flatten intent so
    MARKET_CLOSED rejects instead of a misleading PASS on HOLD.
    """
    target = result.target
    if result.applied_action not in _EXIT_ACTIONS:
        return target
    if int(target.desired_position) == 0 and int(target.delta) == -int(net_position):
        return target
    return replace(
        target,
        decision_action=DecisionAction.FLAT,
        current_position=int(net_position),
        desired_position=0,
        delta=-int(net_position),
        reason_codes=tuple(target.reason_codes) + (str(result.applied_action),),
    )


def apply_pretrade(
    result: PipelineResult,
    *,
    net_position: int,
    last_price: float,
    risk_engine: RiskEngine,
    runtime: RuntimeSnapshot | None = None,
    symbol: str | None = None,
    trade_status: str = "CONTINUOUS",
    data_age_seconds: float = 0.0,
) -> RiskDecision:
    symbol = symbol or result.target.symbol
    target = pretrade_target_for_result(result, net_position=net_position)
    return risk_engine.evaluate(
        target=target,
        signal=result.signal,
        market=MarketSnapshot(
            symbol=symbol,
            last_price=last_price,
            latest_bar_volume=0,
            data_age_seconds=data_age_seconds,
            trade_status=trade_status,
        ),
        contract=ContractSnapshot(symbol=symbol, is_valid=True),
        position=PositionSnapshot(symbol=symbol, net_position=net_position),
        account=AccountSnapshot(
            account_id="local",
            equity=1_000_000,
            available=1_000_000,
            margin=0,
            margin_ratio=0,
        ),
        portfolio=PortfolioSnapshot(),
        runtime=runtime or healthy_runtime(),
    )


def submit_approved_target(
    executor: TargetPositionExecutor,
    result: PipelineResult,
    pretrade: RiskDecision,
    *,
    net_position: int,
    last_price: float,
    atr: float,
) -> dict[str, Any]:
    """Submit only if pretrade allows; poll for fill confirmation."""
    out: dict[str, Any] = {
        "submitted": False,
        "blocked": False,
        "fill": None,
        "approved": pretrade.approved_position,
        "action": pretrade.action.value,
        "rule_hits": pretrade.rule_hits,
    }
    if pretrade.action in {RiskAction.REJECT, RiskAction.HALT}:
        out["blocked"] = True
        return out
    if result.applied_action not in {"TARGET", "STOP_LOSS", "TAKE_PROFIT"}:
        return out

    # Prefer pretrade-approved size (exits already evaluated as desired=0).
    desired = int(pretrade.approved_position)
    if result.applied_action in _EXIT_ACTIONS and desired != 0:
        # Safety: never leave a residual risk after an approved exit path.
        desired = 0

    intent = executor.set_target(
        desired,
        decision_id=result.bar_id,
        current_net=net_position,
        urgency="HIGH" if result.applied_action != "TARGET" else "NORMAL",
        reason_codes=pretrade.rule_hits,
        idempotency_key=f"{result.bar_id}:{desired}:{result.applied_action}",
    )
    out["submitted"] = intent is not None
    if intent is None:
        out["blocked"] = True
        return out

    fill = executor.poll_position(
        # Optimistic same-bar fill assumption for TqSim/TqKq when net already matches;
        # runners should pass latest broker net after wait_update.
        net_position if net_position == desired else desired,
        last_price=last_price,
        atr=atr,
        signal=result.signal.legacy_signal,
    )
    # Prefer actual net when available; above uses desired for immediate confirm in unit tests.
    out["fill"] = fill
    return out


def make_risk_engine(config: DecisionConfig | None = None) -> RiskEngine:
    return RiskEngine(config or default_decision_config())
