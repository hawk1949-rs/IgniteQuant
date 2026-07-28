"""High-level persistence session for runners (Phase 4)."""

from __future__ import annotations

import time
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
    sync_outbox_enabled: bool = True
    _last_heartbeat_outbox_mono: float = 0.0

    def _enqueue(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Best-effort outbox write; never fails the trading path."""
        if not self.sync_outbox_enabled:
            return
        conn = getattr(self.repo, "_conn", None)
        if conn is None:
            return
        try:
            from ignitequant.persistence.outbox import enqueue_outbox

            enqueue_outbox(
                conn,
                instance_id=self.instance_id,
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                payload=payload,
            )
        except Exception:
            # Outbox must not stop orders / decisions.
            pass

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
            factors = result.factors
            signal = result.signal
            risk = result.risk_decision
            self._enqueue(
                event_type="decision.appended",
                aggregate_type="decision",
                aggregate_id=result.bar_id,
                payload={
                    "strategy_id": self.strategy_id,
                    "decision_id": result.bar_id,
                    "bar_id": result.bar_id,
                    "symbol": result.target.symbol,
                    "applied_action": result.applied_action,
                    "target_before": result.target_before,
                    "target_after": result.target_after,
                    "legacy_signal": result.signal.legacy_signal,
                    "regime": factors.regime.value if factors.regime else None,
                    "factor_quality": factors.quality.value if factors.quality else None,
                    "factor_values": dict(factors.values) if factors.values else {},
                    "reason_codes": list(signal.reason_codes)
                    + list(result.target.reason_codes)
                    + list(risk.rule_hits),
                    "score_parts": list(result.legacy_score_parts)
                    if result.legacy_score_parts
                    else None,
                    "risk_action": risk.action.value if risk.action else None,
                    "requested_position": risk.requested_position,
                    "approved_position": risk.approved_position,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            self.healthy = True
        except Exception:
            self.healthy = False
            raise

    def record_ops_decision(
        self,
        *,
        decision_id: str,
        symbol: str,
        applied_action: str,
        target_before: int,
        target_after: int,
        legacy_signal: int = 0,
        payload: dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> bool:
        """Persist boot/resync actions so thinking-chain shows real 1→0 closes."""
        try:
            ok = self.repo.append_ops_decision(
                self.instance_id,
                decision_id=decision_id,
                symbol=symbol,
                applied_action=applied_action,
                target_before=target_before,
                target_after=target_after,
                legacy_signal=legacy_signal,
                payload=payload,
                created_at=created_at,
            )
            stamp = created_at or datetime.now(timezone.utc).isoformat()
            extra = dict(payload or {})
            self._enqueue(
                event_type="decision.appended",
                aggregate_type="decision",
                aggregate_id=decision_id,
                payload={
                    "strategy_id": self.strategy_id,
                    "decision_id": decision_id,
                    "bar_id": decision_id,
                    "symbol": symbol,
                    "applied_action": applied_action,
                    "target_before": target_before,
                    "target_after": target_after,
                    "legacy_signal": legacy_signal,
                    "regime": extra.get("regime"),
                    "factor_quality": extra.get("factor_quality"),
                    "factor_values": extra.get("factor_values") or {},
                    "reason_codes": extra.get("reason_codes") or ["OPS_DECISION"],
                    "score_parts": None,
                    "created_at": stamp,
                    "ops": True,
                },
            )
            self.healthy = True
            return ok
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
            side = intent.side
            if not side:
                delta = int(intent.desired_position) - int(intent.current_position)
                side = "BUY" if delta > 0 else "SELL" if delta < 0 else "FLAT"
            qty = (
                int(intent.qty)
                if intent.qty is not None
                else abs(int(intent.desired_position) - int(intent.current_position))
            )
            self.repo.append_broker_order_event(
                self.instance_id,
                intent_id=intent.intent_id,
                symbol=intent.symbol,
                side=side,
                offset=intent.offset or "",
                status=status,
                local_order_id=intent.intent_id,
                broker_order_id=intent.broker_order_id,
                remaining_qty=qty,
                filled_qty=0,
                message="intent_submitted",
                payload={"idempotency_key": intent.idempotency_key},
            )
            self.repo.append_audit(
                self.instance_id,
                actor="executor",
                action="order_intent",
                correlation_id=intent.decision_id,
                before={"net": intent.current_position},
                after={"desired": intent.desired_position, "key": intent.idempotency_key},
                reason="submit",
            )
            self._enqueue(
                event_type="intent.submitted",
                aggregate_type="order_intent",
                aggregate_id=intent.intent_id,
                payload={
                    "decision_id": intent.decision_id,
                    "intent_id": intent.intent_id,
                    "symbol": intent.symbol,
                    "current_position": intent.current_position,
                    "desired_position": intent.desired_position,
                    "idempotency_key": intent.idempotency_key,
                    "status": status,
                    "side": side,
                    "qty": qty,
                    "urgency": intent.urgency,
                    "reason_codes": list(intent.reason_codes),
                    "created_at": intent.created_at.isoformat()
                    if intent.created_at
                    else datetime.now(timezone.utc).isoformat(),
                    "strategy_id": self.strategy_id,
                },
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
            self.repo.append_broker_order_event(
                self.instance_id,
                intent_id=fill.intent_id,
                symbol=fill.symbol,
                side=fill.side,
                status=OrderStatus.FILLED.value,
                broker_order_id=fill.broker_order_id,
                filled_qty=fill.qty,
                remaining_qty=0,
                avg_price=fill.price,
                message="fill_confirmed",
                payload={"fill_id": fill.fill_id, "broker_trade_id": fill.broker_trade_id},
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
            self._enqueue(
                event_type="fill.confirmed",
                aggregate_type="trade_fill",
                aggregate_id=fill.fill_id,
                payload=fill.to_dict(),
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
        as_of = snap.as_of.isoformat() if snap.as_of else datetime.now(timezone.utc).isoformat()
        self._enqueue(
            event_type="position.snapshot",
            aggregate_type="position",
            aggregate_id=f"{snap.symbol}:{as_of}",
            payload={
                "strategy_id": self.strategy_id,
                "symbol": snap.symbol,
                "symbol_id": snap.symbol,
                "net_position": int(snap.net_position),
                "source": source,
                "as_of": as_of,
                "average_entry_price": snap.average_entry_price,
                "unrealized_pnl": snap.unrealized_pnl,
                "margin": float(getattr(snap, "margin", 0) or 0),
                "confirmed_net": int(snap.net_position),
            },
        )

    def snapshot_account(self, snap: AccountSnapshot) -> None:
        self.repo.append_account_snapshot(self.instance_id, snap)
        as_of = snap.as_of.isoformat() if snap.as_of else datetime.now(timezone.utc).isoformat()
        self._enqueue(
            event_type="account.snapshot",
            aggregate_type="account",
            aggregate_id=f"{snap.account_id}:{as_of}",
            payload={
                "strategy_id": self.strategy_id,
                "account_id": snap.account_id,
                "equity": float(snap.equity),
                "available": float(snap.available),
                "margin": float(snap.margin),
                "margin_ratio": float(snap.margin_ratio),
                "realized_pnl_today": float(snap.realized_pnl_today),
                "unrealized_pnl": float(snap.unrealized_pnl),
                "as_of": as_of,
            },
        )

    def record_heartbeat(
        self,
        *,
        last_price: float | None = None,
        confirmed_net: int | None = None,
        current_target: int | None = None,
        pending_desired: int | None = None,
        quote_as_of: str | None = None,
        session_open: bool | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.repo.append_heartbeat(
                self.instance_id,
                quote_as_of=quote_as_of,
                last_price=last_price,
                confirmed_net=confirmed_net,
                current_target=current_target,
                pending_desired=pending_desired,
                runtime_state=self.runtime.runtime_state,
                session_open=session_open,
                payload=payload,
            )
            now_mono = time.monotonic()
            if now_mono - self._last_heartbeat_outbox_mono >= 300:
                self._last_heartbeat_outbox_mono = now_mono
                self._enqueue(
                    event_type="heartbeat.tick",
                    aggregate_type="runtime_health",
                    aggregate_id=self.instance_id,
                    payload={
                        "last_price": last_price,
                        "confirmed_net": confirmed_net,
                        "current_target": current_target,
                        "pending_desired": pending_desired,
                        "runtime_state": self.runtime.runtime_state,
                        "session_open": session_open,
                        "strategy_id": self.strategy_id,
                        "symbol": self.symbol,
                    },
                )
            self.healthy = True
        except Exception:
            self.healthy = False
            raise

    def persist_market_bars(
        self,
        bars: list[dict[str, Any]],
        *,
        symbol: str,
        duration_sec: int = 300,
        source: str = "tqsdk_sim_live",
        keep_last: int = 2000,
    ) -> int:
        try:
            n = self.repo.upsert_market_bars(
                bars,
                symbol=symbol,
                duration_sec=duration_sec,
                source=source,
                instance_id=self.instance_id,
                keep_last=keep_last,
            )
            self.healthy = True
            return n
        except Exception:
            self.healthy = False
            raise

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
        try:
            self.repo.upsert_runtime_health(
                self.instance_id,
                persistence_healthy=False,
                runtime_state="DEGRADED",
                unknown_order_count=self.runtime.unknown_order_count,
                kill_switch_active=self.runtime.kill_switch_active,
            )
        except Exception:
            pass

    def close(self) -> None:
        self.repo.close()
