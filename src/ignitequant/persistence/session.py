"""High-level persistence session for runners (Phase 4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ignitequant.domain.enums import OrderStatus
from ignitequant.domain.models import (
    AccountSnapshot,
    FillEvent,
    OrderIntent,
    PipelineResult,
    PositionSnapshot,
    RiskDecision,
    RuntimeSnapshot,
)
from ignitequant.engine.reconciliation import (
    BrokerFacts,
    LocalProjection,
    RecoveryResult,
    periodic_reconcile,
    startup_recover,
)
from ignitequant.persistence.repositories import (
    SqliteTradingRepository,
    StrategyStateRecord,
    TradingRepository,
)
from ignitequant.persistence.sqlite import open_sqlite


@dataclass
class PersistenceSession:
    """Owns repository + runtime flags for one strategy instance."""

    instance_id: str
    strategy_id: str
    repo: TradingRepository
    account_id: str = "local"
    symbol: str = ""
    runtime: RuntimeSnapshot = field(
        default_factory=lambda: RuntimeSnapshot(runtime_state="IDLE")
    )
    recovery: RecoveryResult | None = None
    healthy: bool = True
    _db_path: str | None = None

    @classmethod
    def open(
        cls,
        db_path: str | Path,
        *,
        instance_id: str,
        strategy_id: str = "falcon_v2",
        account_id: str = "local",
    ) -> PersistenceSession:
        conn = open_sqlite(db_path)
        repo = SqliteTradingRepository(conn)
        return cls(
            instance_id=instance_id,
            strategy_id=strategy_id,
            account_id=account_id,
            repo=repo,
            _db_path=str(db_path),
        )

    def recover(self, broker: BrokerFacts) -> RecoveryResult:
        try:
            result = startup_recover(self.repo, instance_id=self.instance_id, broker=broker)
            self.recovery = result
            self.symbol = broker.symbol
            self.runtime = result.report.to_runtime(persistence_healthy=True)
            self.runtime = RuntimeSnapshot(
                runtime_state=result.runtime_state,
                reconciliation_matched=result.report.matched,
                unknown_order_count=result.report.unknown_order_count,
                persistence_healthy=True,
                market_gateway_healthy=True,
                trade_gateway_healthy=True,
                kill_switch_active=False,
                roll_in_progress=False,
                as_of=datetime.now(timezone.utc),
            )
            self.healthy = True
            return result
        except Exception:
            self.healthy = False
            self.runtime = RuntimeSnapshot(
                runtime_state="DEGRADED",
                reconciliation_matched=False,
                unknown_order_count=0,
                persistence_healthy=False,
                market_gateway_healthy=True,
                trade_gateway_healthy=True,
                kill_switch_active=False,
            )
            raise

    def record_decision(self, result: PipelineResult) -> None:
        try:
            self.repo.append_decision(self.instance_id, result)
            self.healthy = True
        except Exception:
            self.healthy = False
            raise

    def record_risk(self, decision_id: str, decision: RiskDecision) -> None:
        try:
            self.repo.append_risk_decision(self.instance_id, decision_id, decision)
        except Exception:
            self.healthy = False
            raise

    def record_intent(self, intent: OrderIntent, *, status: str = OrderStatus.SUBMITTED.value) -> bool:
        """Return False if duplicate idempotency key."""
        try:
            inserted = self.repo.append_order_intent(self.instance_id, intent, status=status)
            if not inserted:
                return False
            self.repo.append_audit(
                self.instance_id,
                actor="executor",
                action="order_intent",
                correlation_id=intent.decision_id,
                before={"net": intent.current_position},
                after={"desired": intent.desired_position, "key": intent.idempotency_key},
                reason="submit",
            )
            return True
        except Exception:
            self.healthy = False
            raise

    def record_fill(self, fill: FillEvent) -> None:
        try:
            self.repo.append_fill(self.instance_id, fill)
            self.repo.update_order_intent_status(
                self.instance_id, fill.intent_id, OrderStatus.FILLED.value
            )
            self.repo.append_audit(
                self.instance_id,
                actor="executor",
                action="fill",
                correlation_id=fill.intent_id,
                before={},
                after=fill.to_dict(),
                reason="confirmed",
            )
        except Exception:
            self.healthy = False
            raise

    def save_state(
        self,
        *,
        symbol: str,
        current_target: int,
        confirmed_net: int,
        cooldown_left: int = 0,
        entry_price: float | None = None,
        stop_price: float | None = None,
        take_price: float | None = None,
        entry_signal: int | None = None,
        pending_desired: int | None = None,
        last_bar_id: str = "",
        config_hash: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "current_target": current_target,
            "confirmed_net": confirmed_net,
            "cooldown_left": cooldown_left,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "take_price": take_price,
            "entry_signal": entry_signal,
            "pending_desired": pending_desired,
            "last_bar_id": last_bar_id,
            "config_hash": config_hash,
        }
        if extra:
            payload.update(extra)
        state = StrategyStateRecord(
            instance_id=self.instance_id,
            strategy_id=self.strategy_id,
            account_id=self.account_id,
            symbol=symbol,
            runtime_state=self.runtime.runtime_state,
            payload=payload,
        )
        try:
            self.repo.save_strategy_state(state)
            self.symbol = symbol
            self.healthy = True
        except Exception:
            self.healthy = False
            raise

    def snapshot_position(self, snap: PositionSnapshot, *, source: str = "broker") -> None:
        self.repo.append_position_snapshot(self.instance_id, snap, source=source)

    def snapshot_account(self, snap: AccountSnapshot) -> None:
        self.repo.append_account_snapshot(self.instance_id, snap)

    def reconcile_now(self, local: LocalProjection, broker: BrokerFacts) -> RuntimeSnapshot:
        report = periodic_reconcile(
            self.repo,
            instance_id=self.instance_id,
            local=local,
            broker=broker,
        )
        self.runtime = report.to_runtime(persistence_healthy=self.healthy)
        if not report.matched:
            self.runtime = RuntimeSnapshot(
                runtime_state="DEGRADED",
                reconciliation_matched=False,
                unknown_order_count=report.unknown_order_count,
                persistence_healthy=self.healthy,
                market_gateway_healthy=True,
                trade_gateway_healthy=True,
                kill_switch_active=False,
                as_of=datetime.now(timezone.utc),
            )
        return self.runtime

    def mark_persistence_unhealthy(self) -> None:
        self.healthy = False
        self.runtime = RuntimeSnapshot(
            runtime_state="DEGRADED",
            reconciliation_matched=self.runtime.reconciliation_matched,
            unknown_order_count=self.runtime.unknown_order_count,
            persistence_healthy=False,
            market_gateway_healthy=self.runtime.market_gateway_healthy,
            trade_gateway_healthy=self.runtime.trade_gateway_healthy,
            kill_switch_active=self.runtime.kill_switch_active,
            roll_in_progress=self.runtime.roll_in_progress,
            as_of=datetime.now(timezone.utc),
        )

    def close(self) -> None:
        self.repo.close()
