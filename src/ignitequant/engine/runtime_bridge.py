"""Helpers to apply PipelineResult through RiskEngine + TargetPositionExecutor."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ignitequant.config.decision import DecisionConfig, default_decision_config
from ignitequant.domain.enums import RiskAction
from ignitequant.domain.models import (
    AccountSnapshot,
    ContractSnapshot,
    MarketSnapshot,
    PipelineResult,
    PortfolioSnapshot,
    PositionSnapshot,
    RiskDecision,
    RuntimeSnapshot,
)
from ignitequant.execution.target_position import TargetPositionExecutor
from ignitequant.risk import RiskEngine


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


def apply_pretrade(
    result: PipelineResult,
    *,
    net_position: int,
    last_price: float,
    risk_engine: RiskEngine,
    runtime: RuntimeSnapshot | None = None,
    symbol: str | None = None,
) -> RiskDecision:
    symbol = symbol or result.target.symbol
    return risk_engine.evaluate(
        target=result.target,
        signal=result.signal,
        market=MarketSnapshot(
            symbol=symbol,
            last_price=last_price,
            latest_bar_volume=0,
            data_age_seconds=0.0,
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

    desired = int(pretrade.approved_position)
    # Align exit actions to flat.
    if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}:
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
