"""RiskEngine with deterministic rule priority (小框架 SOP 5)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ignitequant.config.decision import DecisionConfig, default_decision_config
from ignitequant.domain.enums import ReasonCode, RiskAction
from ignitequant.domain.models import (
    AccountSnapshot,
    ContractSnapshot,
    MarketSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
    RiskDecision,
    RuntimeSnapshot,
    SignalEvent,
    TargetPosition,
)
from ignitequant.risk.rules import RiskContext, RiskRule, default_legacy_rules


class RiskEngine:
    def __init__(
        self,
        config: DecisionConfig | None = None,
        rules: list[RiskRule] | None = None,
    ) -> None:
        self.config = config or default_decision_config()
        max_lots = int(self.config.risk.max_symbol_lots)
        self.rules = sorted(
            rules or default_legacy_rules(max_symbol_lots=max_lots),
            key=lambda rule: rule.priority,
        )

    def evaluate(
        self,
        target: TargetPosition,
        signal: SignalEvent,
        market: MarketSnapshot,
        contract: ContractSnapshot,
        position: PositionSnapshot,
        account: AccountSnapshot,
        portfolio: PortfolioSnapshot,
        runtime: RuntimeSnapshot,
        now: datetime | None = None,
    ) -> RiskDecision:
        now = now or datetime.now(timezone.utc)
        context = RiskContext(
            target=target,
            signal=signal,
            market=market,
            contract=contract,
            position=position,
            account=account,
            portfolio=portfolio,
            runtime=runtime,
        )
        hits: list[str] = []
        warnings: list[str] = []
        action = RiskAction.PASS
        approved = target.desired_position

        for rule in self.rules:
            result = rule.evaluate(context)
            if result is None:
                continue
            hits.append(result.rule_code)
            if result.message:
                warnings.append(result.message)
            if (
                result.action is RiskAction.PASS
                and result.rule_code == ReasonCode.RISK_REDUCING_ORDER.value
            ):
                approved = result.approved_position
                continue
            action = result.action
            approved = result.approved_position
            break

        return RiskDecision(
            risk_decision_id=f"pretrade:{target.target_id}",
            target_id=target.target_id,
            action=action,
            requested_position=target.desired_position,
            approved_position=approved,
            requested_risk=target.requested_risk,
            approved_risk=Decimal("0"),
            rule_hits=tuple(hits),
            warnings=tuple(warnings),
            evaluated_at=now,
            risk_config_version=self.config.config_version,
            risk_snapshot_id=f"runtime:{runtime.runtime_state}",
        )
