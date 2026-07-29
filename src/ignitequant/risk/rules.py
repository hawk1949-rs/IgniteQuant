"""Risk rule protocol, results, and reason-code helpers (小框架 SOP 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ignitequant.domain.enums import ReasonCode, RiskAction
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


@dataclass(frozen=True)
class RuleResult:
    action: RiskAction
    approved_position: int
    rule_code: str
    message: str = ""


@dataclass(frozen=True)
class RiskContext:
    target: TargetPosition
    signal: SignalEvent
    market: MarketSnapshot
    contract: ContractSnapshot
    position: PositionSnapshot
    account: AccountSnapshot
    portfolio: PortfolioSnapshot
    runtime: RuntimeSnapshot

    @property
    def is_risk_reducing(self) -> bool:
        return abs(self.target.desired_position) < abs(self.position.net_position)


class RiskRule(Protocol):
    priority: int
    rule_code: str

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        """Return a RuleResult to stop the chain, or None to continue."""


def _pass(context: RiskContext, code: str = "") -> RuleResult:
    return RuleResult(
        action=RiskAction.PASS,
        approved_position=context.target.desired_position,
        rule_code=code,
    )


@dataclass
class KillSwitchRule:
    priority: int = 10
    rule_code: str = ReasonCode.KILL_SWITCH_ACTIVE.value

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        if context.runtime.kill_switch_active:
            return RuleResult(
                action=RiskAction.HALT,
                approved_position=context.position.net_position,
                rule_code=self.rule_code,
                message="kill switch active",
            )
        return None


@dataclass
class ReconciliationRule:
    priority: int = 20
    rule_code: str = ReasonCode.RECONCILIATION_MISMATCH.value

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        if context.runtime.reconciliation_matched and context.runtime.unknown_order_count == 0:
            return None
        if context.is_risk_reducing:
            return RuleResult(
                action=RiskAction.PASS,
                approved_position=context.target.desired_position,
                rule_code=ReasonCode.RISK_REDUCING_ORDER.value,
                message="allow risk-reducing while degraded",
            )
        code = (
            ReasonCode.UNKNOWN_ORDER_EXISTS.value
            if context.runtime.unknown_order_count > 0
            else self.rule_code
        )
        return RuleResult(
            action=RiskAction.REJECT,
            approved_position=context.position.net_position,
            rule_code=code,
            message="runtime reconciliation blocked new risk",
        )


@dataclass
class GatewayHealthRule:
    priority: int = 25
    rule_code: str = "GATEWAY_UNHEALTHY"

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        rt = context.runtime
        if rt.market_gateway_healthy and rt.trade_gateway_healthy and rt.persistence_healthy:
            return None
        if context.is_risk_reducing and rt.trade_gateway_healthy:
            return RuleResult(
                action=RiskAction.PASS,
                approved_position=context.target.desired_position,
                rule_code=ReasonCode.RISK_REDUCING_ORDER.value,
            )
        return RuleResult(
            action=RiskAction.HALT if not rt.trade_gateway_healthy else RiskAction.REJECT,
            approved_position=context.position.net_position,
            rule_code=self.rule_code,
            message="gateway/persistence unhealthy",
        )


@dataclass
class DataFreshnessRule:
    priority: int = 30
    rule_code: str = ReasonCode.DATA_STALE.value
    max_bar_delay_seconds: float = 30.0

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        if context.market.data_age_seconds <= self.max_bar_delay_seconds:
            return None
        if context.is_risk_reducing:
            return RuleResult(
                action=RiskAction.PASS,
                approved_position=context.target.desired_position,
                rule_code=ReasonCode.RISK_REDUCING_ORDER.value,
            )
        return RuleResult(
            action=RiskAction.REJECT,
            approved_position=context.position.net_position,
            rule_code=self.rule_code,
            message=f"data_age={context.market.data_age_seconds}",
        )


@dataclass
class FactorReadyRule:
    priority: int = 35
    rule_code: str = ReasonCode.FACTOR_NOT_READY.value

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        # Signal confidence 0 used as not-ready proxy in legacy adapter.
        if context.signal.confidence > 0:
            return None
        if context.is_risk_reducing or context.target.desired_position == context.position.net_position:
            return None
        return RuleResult(
            action=RiskAction.REJECT,
            approved_position=context.position.net_position,
            rule_code=self.rule_code,
        )


@dataclass
class MarketClosedRule:
    """Domestic session closed: keep position; do not submit any order (2A)."""

    priority: int = 37
    rule_code: str = ReasonCode.MARKET_CLOSED.value

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        status = (context.market.trade_status or "").strip().upper()
        if status in {"", "CONTINUOUS", "OPEN", "TRADING", "AUCTION"}:
            return None
        if context.target.desired_position == context.position.net_position:
            return None
        return RuleResult(
            action=RiskAction.REJECT,
            approved_position=context.position.net_position,
            rule_code=self.rule_code,
            message="domestic market closed; signal recorded, no order",
        )


@dataclass
class RollInProgressRule:
    priority: int = 40
    rule_code: str = ReasonCode.ROLL_IN_PROGRESS.value

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        if not context.runtime.roll_in_progress:
            return None
        if context.is_risk_reducing:
            return RuleResult(
                action=RiskAction.PASS,
                approved_position=context.target.desired_position,
                rule_code=ReasonCode.RISK_REDUCING_ORDER.value,
            )
        return RuleResult(
            action=RiskAction.REJECT,
            approved_position=context.position.net_position,
            rule_code=self.rule_code,
        )


@dataclass
class ContractValidityRule:
    priority: int = 45
    rule_code: str = ReasonCode.CONTRACT_INVALID.value

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        if context.contract.is_valid:
            return None
        return RuleResult(
            action=RiskAction.REJECT,
            approved_position=context.position.net_position,
            rule_code=self.rule_code,
        )


@dataclass
class PriceLimitRule:
    priority: int = 50
    rule_code: str = ReasonCode.PRICE_LIMIT_LOCKED.value

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        mkt = context.market
        increasing = abs(context.target.desired_position) > abs(context.position.net_position)
        if not increasing:
            return None
        if mkt.is_upper_limit_locked or mkt.is_lower_limit_locked:
            return RuleResult(
                action=RiskAction.REJECT,
                approved_position=context.position.net_position,
                rule_code=self.rule_code,
            )
        return None


@dataclass
class PositionLimitRule:
    priority: int = 70
    rule_code: str = ReasonCode.POSITION_LIMIT.value
    max_symbol_lots: int = 3

    def evaluate(self, context: RiskContext) -> RuleResult | None:
        desired = context.target.desired_position
        if abs(desired) <= self.max_symbol_lots:
            return None
        capped = max(-self.max_symbol_lots, min(self.max_symbol_lots, desired))
        if capped == context.position.net_position:
            return RuleResult(
                action=RiskAction.REJECT,
                approved_position=capped,
                rule_code=self.rule_code,
            )
        return RuleResult(
            action=RiskAction.RESIZE,
            approved_position=capped,
            rule_code=self.rule_code,
            message=f"capped to {capped}",
        )


def default_legacy_rules(*, max_symbol_lots: int = 3) -> list[RiskRule]:
    """Ordered rule chain for Phase 3 legacy_compatible mode."""
    return [
        KillSwitchRule(),
        ReconciliationRule(),
        GatewayHealthRule(),
        DataFreshnessRule(),
        FactorReadyRule(),
        MarketClosedRule(),
        RollInProgressRule(),
        ContractValidityRule(),
        PriceLimitRule(),
        PositionLimitRule(max_symbol_lots=max_symbol_lots),
    ]
