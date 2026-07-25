"""Startup and periodic reconciliation (大框架 §11)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ignitequant.domain.models import RuntimeSnapshot
from ignitequant.persistence.repositories import (
    StrategyStateRecord,
    TradingRepository,
)


@dataclass(frozen=True)
class BrokerFacts:
    """Counterparty / exchange truth — never invent from local target alone."""

    symbol: str
    net_position: int
    equity: float | None = None
    available: float | None = None
    margin: float | None = None
    open_order_count: int = 0
    unknown_order_count: int = 0
    as_of: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "net_position": self.net_position,
            "equity": self.equity,
            "available": self.available,
            "margin": self.margin,
            "open_order_count": self.open_order_count,
            "unknown_order_count": self.unknown_order_count,
            "as_of": self.as_of.isoformat() if self.as_of else None,
        }


@dataclass(frozen=True)
class LocalProjection:
    symbol: str
    expected_net: int
    current_target: int
    pending_desired: int | None = None
    cooldown_left: int = 0
    entry_price: float | None = None
    runtime_state: str = "IDLE"

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "expected_net": self.expected_net,
            "current_target": self.current_target,
            "pending_desired": self.pending_desired,
            "cooldown_left": self.cooldown_left,
            "entry_price": self.entry_price,
            "runtime_state": self.runtime_state,
        }


@dataclass(frozen=True)
class ReconMismatch:
    field: str
    local: Any
    broker: Any
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "local": self.local,
            "broker": self.broker,
            "message": self.message,
        }


@dataclass
class ReconReport:
    matched: bool
    mismatches: list[ReconMismatch] = field(default_factory=list)
    runtime_state: str = "RUNNING"
    unknown_order_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_runtime(self, *, persistence_healthy: bool = True) -> RuntimeSnapshot:
        return RuntimeSnapshot(
            runtime_state=self.runtime_state,
            reconciliation_matched=self.matched,
            unknown_order_count=self.unknown_order_count,
            persistence_healthy=persistence_healthy,
            market_gateway_healthy=True,
            trade_gateway_healthy=True,
            kill_switch_active=False,
            roll_in_progress=False,
            as_of=self.created_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "matched": self.matched,
            "mismatches": [m.to_dict() for m in self.mismatches],
            "runtime_state": self.runtime_state,
            "unknown_order_count": self.unknown_order_count,
            "created_at": self.created_at.isoformat(),
        }


def local_from_state(state: StrategyStateRecord | None, *, symbol: str = "") -> LocalProjection:
    if state is None:
        return LocalProjection(
            symbol=symbol,
            expected_net=0,
            current_target=0,
            runtime_state="IDLE",
        )
    payload = state.payload
    pending = payload.get("pending_desired")
    expected = int(payload.get("confirmed_net", payload.get("current_target", 0)))
    return LocalProjection(
        symbol=state.symbol or symbol,
        expected_net=expected,
        current_target=int(payload.get("current_target", 0)),
        pending_desired=int(pending) if pending is not None else None,
        cooldown_left=int(payload.get("cooldown_left", 0)),
        entry_price=payload.get("entry_price"),
        runtime_state=state.runtime_state,
    )


def reconcile(
    local: LocalProjection,
    broker: BrokerFacts,
    *,
    position_tol: int = 0,
    equity_tol: float | None = None,
) -> ReconReport:
    """Compare local projection with broker facts.

    Rules (大框架 §11):
    - Never treat local target as broker position.
    - Pending intent may explain temporary position gap.
    - Unknown orders force DEGRADED.
    """
    mismatches: list[ReconMismatch] = []

    if local.symbol and broker.symbol and local.symbol != broker.symbol:
        mismatches.append(
            ReconMismatch(
                field="symbol",
                local=local.symbol,
                broker=broker.symbol,
                message="symbol mismatch",
            )
        )

    gap = abs(local.expected_net - broker.net_position)
    if gap > position_tol:
        pending = local.pending_desired
        explained = pending is not None and broker.net_position == pending
        # Also allow broker already at local current_target while pending clears.
        explained = explained or (
            pending is not None and abs(broker.net_position) <= abs(pending)
            and (
                (local.expected_net <= broker.net_position <= pending)
                or (pending <= broker.net_position <= local.expected_net)
            )
        )
        if not explained:
            mismatches.append(
                ReconMismatch(
                    field="net_position",
                    local=local.expected_net,
                    broker=broker.net_position,
                    message="position projection mismatch",
                )
            )

    if broker.unknown_order_count > 0:
        mismatches.append(
            ReconMismatch(
                field="unknown_orders",
                local=0,
                broker=broker.unknown_order_count,
                message="unknown broker orders present",
            )
        )

    if (
        equity_tol is not None
        and broker.equity is not None
        and local.runtime_state not in {"IDLE", "RECOVERING"}
    ):
        # Equity check is optional; local may not track equity — skip if absent.
        pass

    matched = len(mismatches) == 0 and broker.unknown_order_count == 0
    if matched:
        runtime_state = "RUNNING"
    elif broker.unknown_order_count > 0:
        runtime_state = "DEGRADED"
    else:
        runtime_state = "DEGRADED"

    return ReconReport(
        matched=matched,
        mismatches=mismatches,
        runtime_state=runtime_state,
        unknown_order_count=broker.unknown_order_count,
    )


@dataclass
class RecoveryResult:
    runtime_state: str
    report: ReconReport
    state: StrategyStateRecord | None
    idempotency_keys: set[str] = field(default_factory=set)
    restore_payload: dict[str, Any] = field(default_factory=dict)
    allow_new_risk: bool = False
    message: str = ""


def startup_recover(
    repo: TradingRepository,
    *,
    instance_id: str,
    broker: BrokerFacts,
) -> RecoveryResult:
    """Load persisted state, reconcile with broker, decide READY/DEGRADED."""
    state = repo.load_strategy_state(instance_id)
    local = local_from_state(state, symbol=broker.symbol)
    # During recovery, if no confirmed_net, use broker as truth and only check pending.
    if state is None:
        report = ReconReport(matched=True, runtime_state="READY", unknown_order_count=broker.unknown_order_count)
        if broker.unknown_order_count > 0:
            report = ReconReport(
                matched=False,
                mismatches=[
                    ReconMismatch("unknown_orders", 0, broker.unknown_order_count, "unknown orders")
                ],
                runtime_state="DEGRADED",
                unknown_order_count=broker.unknown_order_count,
            )
        keys = repo.list_idempotency_keys(instance_id)
        repo.append_recon(
            instance_id,
            matched=report.matched,
            runtime_state=report.runtime_state,
            mismatches=[m.to_dict() for m in report.mismatches],
            broker=broker.to_dict(),
            local=local.to_dict(),
        )
        repo.append_audit(
            instance_id,
            actor="system",
            action="startup_recover",
            correlation_id=instance_id,
            before={},
            after={"runtime_state": report.runtime_state, "broker": broker.to_dict()},
            reason="cold_start",
        )
        return RecoveryResult(
            runtime_state=report.runtime_state,
            report=report,
            state=None,
            idempotency_keys=keys,
            restore_payload={
                "current_target": broker.net_position,
                "confirmed_net": broker.net_position,
                "cooldown_left": 0,
            },
            allow_new_risk=report.matched,
            message="cold start — adopt broker position",
        )

    # Prefer broker net as confirmed when restarting with open position.
    payload = dict(state.payload)
    confirmed = int(payload.get("confirmed_net", payload.get("current_target", 0)))
    pending = payload.get("pending_desired")
    local = LocalProjection(
        symbol=state.symbol or broker.symbol,
        expected_net=confirmed,
        current_target=int(payload.get("current_target", confirmed)),
        pending_desired=int(pending) if pending is not None else None,
        cooldown_left=int(payload.get("cooldown_left", 0)),
        entry_price=payload.get("entry_price"),
        runtime_state="RECOVERING",
    )
    report = reconcile(local, broker)
    keys = repo.list_idempotency_keys(instance_id)

    # If broker already matches pending, treat as filled during downtime.
    if (
        not report.matched
        and pending is not None
        and broker.net_position == int(pending)
    ):
        payload["confirmed_net"] = broker.net_position
        payload["current_target"] = broker.net_position
        payload["pending_desired"] = None
        report = ReconReport(matched=True, runtime_state="READY", unknown_order_count=0)
        message = "adopted pending fill that completed offline"
    elif report.matched:
        # Align confirmed to broker (truth).
        payload["confirmed_net"] = broker.net_position
        if abs(int(payload.get("current_target", 0))) != abs(broker.net_position):
            # Keep strategy target if risk-reducing pending; else sync.
            if pending is None:
                payload["current_target"] = broker.net_position
        report = ReconReport(matched=True, runtime_state="READY", unknown_order_count=0)
        message = "reconciliation matched"
    else:
        message = "reconciliation mismatch — DEGRADED, no new risk"
        report.runtime_state = "DEGRADED"

    updated = StrategyStateRecord(
        instance_id=state.instance_id,
        strategy_id=state.strategy_id,
        account_id=state.account_id,
        symbol=broker.symbol or state.symbol,
        runtime_state=report.runtime_state,
        payload=payload,
        state_version=state.state_version + 1,
    )
    repo.save_strategy_state(updated)
    repo.append_recon(
        instance_id,
        matched=report.matched,
        runtime_state=report.runtime_state,
        mismatches=[m.to_dict() for m in report.mismatches],
        broker=broker.to_dict(),
        local=local.to_dict(),
    )
    repo.append_audit(
        instance_id,
        actor="system",
        action="startup_recover",
        correlation_id=instance_id,
        before=state.to_dict(),
        after=updated.to_dict(),
        reason=message,
    )
    return RecoveryResult(
        runtime_state=report.runtime_state,
        report=report,
        state=updated,
        idempotency_keys=keys,
        restore_payload=payload,
        allow_new_risk=report.matched,
        message=message,
    )


def periodic_reconcile(
    repo: TradingRepository,
    *,
    instance_id: str,
    local: LocalProjection,
    broker: BrokerFacts,
) -> ReconReport:
    report = reconcile(local, broker)
    repo.append_recon(
        instance_id,
        matched=report.matched,
        runtime_state=report.runtime_state,
        mismatches=[m.to_dict() for m in report.mismatches],
        broker=broker.to_dict(),
        local=local.to_dict(),
    )
    if not report.matched:
        repo.append_data_quality(
            instance_id,
            code="RECONCILIATION_MISMATCH",
            severity="HIGH",
            message="periodic reconcile failed",
            payload=report.to_dict(),
        )
        repo.append_audit(
            instance_id,
            actor="system",
            action="periodic_reconcile",
            correlation_id=instance_id,
            before=local.to_dict(),
            after=broker.to_dict(),
            reason="mismatch",
        )
    return report
