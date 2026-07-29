"""Repository protocol and SQLite implementation (大框架 §8.1 + architecture L0–L4)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence

from ignitequant.domain.models import (
    AccountSnapshot,
    FillEvent,
    OrderIntent,
    PipelineResult,
    PositionSnapshot,
    RiskDecision,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(payload: Mapping[str, Any] | dict[str, Any] | list[Any] | tuple[Any, ...]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def _intent_side_offset_qty(intent: OrderIntent) -> tuple[str, str, int]:
    delta = int(intent.desired_position) - int(intent.current_position)
    qty = int(intent.qty) if intent.qty is not None else abs(delta)
    if intent.side:
        side = intent.side
    elif delta > 0:
        side = "BUY"
    elif delta < 0:
        side = "SELL"
    else:
        side = "FLAT"
    offset = intent.offset or ""
    return side, offset, qty


@dataclass
class StrategyStateRecord:
    instance_id: str
    strategy_id: str
    account_id: str
    symbol: str
    runtime_state: str
    payload: dict[str, Any]
    state_version: int = 1
    updated_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "strategy_id": self.strategy_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "runtime_state": self.runtime_state,
            "payload": self.payload,
            "state_version": self.state_version,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class AuditRecord:
    event_id: str
    actor: str
    action: str
    correlation_id: str
    before: Mapping[str, Any]
    after: Mapping[str, Any]
    reason: str
    prev_hash: str
    event_hash: str
    created_at: str


class TradingRepository(Protocol):
    def save_strategy_state(self, state: StrategyStateRecord) -> None: ...

    def load_strategy_state(self, instance_id: str) -> StrategyStateRecord | None: ...

    def append_decision(self, instance_id: str, result: PipelineResult) -> None: ...

    def append_ops_decision(
        self,
        instance_id: str,
        *,
        decision_id: str,
        symbol: str,
        applied_action: str,
        target_before: int,
        target_after: int,
        legacy_signal: int = 0,
        payload: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> bool: ...

    def append_risk_decision(
        self, instance_id: str, decision_id: str, decision: RiskDecision
    ) -> None: ...

    def append_order_intent(
        self, instance_id: str, intent: OrderIntent, *, status: str
    ) -> bool: ...

    def update_order_intent_status(
        self, instance_id: str, intent_id: str, status: str
    ) -> None: ...

    def append_fill(self, instance_id: str, fill: FillEvent) -> None: ...

    def append_position_snapshot(
        self, instance_id: str, snap: PositionSnapshot, *, source: str
    ) -> None: ...

    def append_account_snapshot(self, instance_id: str, snap: AccountSnapshot) -> None: ...

    def append_recon(
        self,
        instance_id: str,
        *,
        matched: bool,
        runtime_state: str,
        mismatches: list[dict[str, Any]],
        broker: Mapping[str, Any],
        local: Mapping[str, Any],
        severity: str | None = None,
    ) -> None: ...

    def append_data_quality(
        self,
        instance_id: str,
        *,
        code: str,
        severity: str,
        message: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None: ...

    def append_audit(
        self,
        instance_id: str,
        *,
        actor: str,
        action: str,
        correlation_id: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        reason: str,
    ) -> AuditRecord: ...

    def append_broker_order_event(
        self,
        instance_id: str,
        *,
        intent_id: str,
        symbol: str,
        side: str,
        status: str,
        event_id: str | None = None,
        local_order_id: str | None = None,
        broker_order_id: str | None = None,
        offset: str | None = None,
        filled_qty: int = 0,
        remaining_qty: int = 0,
        avg_price: float | None = None,
        message: str | None = None,
        event_time: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> str: ...

    def append_heartbeat(
        self,
        instance_id: str,
        *,
        as_of: str | None = None,
        quote_as_of: str | None = None,
        last_price: float | None = None,
        confirmed_net: int | None = None,
        current_target: int | None = None,
        pending_desired: int | None = None,
        runtime_state: str | None = None,
        session_open: bool | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None: ...

    def upsert_runtime_health(
        self,
        instance_id: str,
        *,
        last_heartbeat_at: str | None = None,
        last_bar_at: str | None = None,
        last_quote_at: str | None = None,
        unknown_order_count: int | None = None,
        kill_switch_active: bool | None = None,
        persistence_healthy: bool | None = None,
        runtime_state: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None: ...

    def upsert_market_bars(
        self,
        bars: Sequence[Mapping[str, Any]],
        *,
        symbol: str,
        duration_sec: int,
        source: str = "tqsdk_sim_live",
        instance_id: str | None = None,
        keep_last: int = 2000,
    ) -> int: ...

    def list_market_bars(
        self,
        symbol: str,
        *,
        duration_sec: int = 300,
        limit: int = 400,
        finals_only: bool = False,
    ) -> list[dict[str, Any]]: ...

    def list_idempotency_keys(self, instance_id: str) -> set[str]: ...

    def latest_open_intent(self, instance_id: str) -> dict[str, Any] | None: ...

    def close(self) -> None: ...


class SqliteTradingRepository:
    """Append-only trading events + mutable strategy_state / runtime_health projections."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_strategy_state(self, state: StrategyStateRecord) -> None:
        state.updated_at = _utc_now()
        self._conn.execute(
            """
            INSERT INTO strategy_state(
                instance_id, strategy_id, account_id, symbol, runtime_state,
                payload_json, state_version, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
                strategy_id=excluded.strategy_id,
                account_id=excluded.account_id,
                symbol=excluded.symbol,
                runtime_state=excluded.runtime_state,
                payload_json=excluded.payload_json,
                state_version=excluded.state_version,
                updated_at=excluded.updated_at
            """,
            (
                state.instance_id,
                state.strategy_id,
                state.account_id,
                state.symbol,
                state.runtime_state,
                _dumps(state.payload),
                state.state_version,
                state.updated_at,
            ),
        )
        self._conn.commit()

    def load_strategy_state(self, instance_id: str) -> StrategyStateRecord | None:
        row = self._conn.execute(
            "SELECT * FROM strategy_state WHERE instance_id = ?",
            (instance_id,),
        ).fetchone()
        if row is None:
            return None
        return StrategyStateRecord(
            instance_id=row["instance_id"],
            strategy_id=row["strategy_id"],
            account_id=row["account_id"],
            symbol=row["symbol"],
            runtime_state=row["runtime_state"],
            payload=json.loads(row["payload_json"]),
            state_version=int(row["state_version"]),
            updated_at=row["updated_at"],
        )

    def _upsert_signal_state(self, instance_id: str, result: PipelineResult) -> None:
        prev = self._conn.execute(
            "SELECT * FROM signal_state WHERE instance_id = ?",
            (instance_id,),
        ).fetchone()
        long_bars = int(prev["consecutive_long_bars"]) if prev else 0
        short_bars = int(prev["consecutive_short_bars"]) if prev else 0
        direction = int(result.signal.direction)
        if direction > 0:
            long_bars += 1
            short_bars = 0
        elif direction < 0:
            short_bars += 1
            long_bars = 0
        else:
            long_bars = 0
            short_bars = 0
        self._conn.execute(
            """
            INSERT INTO signal_state(
                instance_id, previous_alpha, consecutive_long_bars, consecutive_short_bars,
                previous_action, last_signal_id, updated_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(instance_id) DO UPDATE SET
                previous_alpha=excluded.previous_alpha,
                consecutive_long_bars=excluded.consecutive_long_bars,
                consecutive_short_bars=excluded.consecutive_short_bars,
                previous_action=excluded.previous_action,
                last_signal_id=excluded.last_signal_id,
                updated_at=excluded.updated_at,
                payload_json=excluded.payload_json
            """,
            (
                instance_id,
                float(result.signal.alpha),
                long_bars,
                short_bars,
                result.signal.action.value,
                result.signal.signal_id,
                _utc_now(),
                _dumps({"legacy_signal": result.signal.legacy_signal}),
            ),
        )

    def append_decision(self, instance_id: str, result: PipelineResult) -> None:
        """Dual-write: factor/signal/target tables + decision_event (payload retained)."""
        now = _utc_now()
        factors = result.factors
        signal = result.signal
        target = result.target
        risk = result.risk_decision

        self._conn.execute(
            """
            INSERT OR IGNORE INTO factor_snapshot(
                instance_id, factor_snapshot_id, bar_id, symbol, data_as_of,
                regime, quality, factor_version, values_json, reason_codes_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                factors.factor_snapshot_id,
                factors.bar_id,
                factors.symbol,
                factors.data_as_of.isoformat(),
                factors.regime.value,
                factors.quality.value,
                factors.factor_version,
                _dumps(dict(factors.values)),
                _dumps(list(factors.reason_codes)),
                now,
            ),
        )
        self._conn.execute(
            """
            INSERT OR IGNORE INTO signal_event(
                instance_id, signal_id, factor_snapshot_id, action, direction,
                alpha, strength, confidence, legacy_signal, generated_at,
                effective_from, expires_at, model_version, reason_codes_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                signal.signal_id,
                signal.factor_snapshot_id,
                signal.action.value,
                int(signal.direction),
                float(signal.alpha),
                float(signal.strength),
                float(signal.confidence),
                int(signal.legacy_signal),
                signal.generated_at.isoformat(),
                signal.effective_from.isoformat(),
                signal.expires_at.isoformat(),
                signal.model_version,
                _dumps(list(signal.reason_codes)),
                now,
            ),
        )
        self._conn.execute(
            """
            INSERT OR IGNORE INTO target_position_event(
                instance_id, target_id, signal_id, symbol, current_position,
                desired_position, delta, planned_stop_price, stop_distance,
                sizing_method, requested_risk, config_version, reason_codes_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                target.target_id,
                target.signal_id,
                target.symbol,
                int(target.current_position),
                int(target.desired_position),
                int(target.delta),
                target.planned_stop_price,
                target.stop_distance,
                target.sizing_method,
                str(target.requested_risk),
                target.config_version,
                _dumps(list(target.reason_codes)),
                now,
            ),
        )
        self._upsert_signal_state(instance_id, result)
        reason_codes = list(signal.reason_codes) + list(target.reason_codes) + list(risk.rule_hits)
        self._conn.execute(
            """
            INSERT OR IGNORE INTO decision_event(
                instance_id, decision_id, bar_id, symbol, applied_action,
                target_before, target_after, legacy_signal, payload_json, created_at,
                bar_end_at, factor_snapshot_id, signal_id, target_id, risk_decision_id,
                config_hash, model_version, reason_codes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                result.bar_id,
                result.bar_id,
                result.target.symbol,
                result.applied_action,
                result.target_before,
                result.target_after,
                result.signal.legacy_signal,
                _dumps(result.to_dict()),
                now,
                factors.data_as_of.isoformat(),
                factors.factor_snapshot_id,
                signal.signal_id,
                target.target_id,
                risk.risk_decision_id,
                target.config_version,
                signal.model_version,
                _dumps(reason_codes),
            ),
        )
        self.upsert_runtime_health(
            instance_id,
            last_bar_at=factors.data_as_of.isoformat(),
            runtime_state=None,
            commit=False,
        )
        self._conn.commit()

    def append_ops_decision(
        self,
        instance_id: str,
        *,
        decision_id: str,
        symbol: str,
        applied_action: str,
        target_before: int,
        target_after: int,
        legacy_signal: int = 0,
        payload: Mapping[str, Any] | None = None,
        created_at: str | None = None,
    ) -> bool:
        """Record an operational decision (boot flatten / resync) for cockpit audit."""
        now = created_at or _utc_now()
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO decision_event(
                instance_id, decision_id, bar_id, symbol, applied_action,
                target_before, target_after, legacy_signal, payload_json, created_at,
                reason_codes_json, model_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                decision_id,
                decision_id,
                symbol,
                applied_action,
                int(target_before),
                int(target_after),
                int(legacy_signal),
                _dumps(dict(payload or {})),
                now,
                _dumps(list((payload or {}).get("reason_codes") or [applied_action])),
                "ops",
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def append_risk_decision(
        self, instance_id: str, decision_id: str, decision: RiskDecision
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO risk_decision_event(
                instance_id, risk_decision_id, decision_id, action,
                requested_position, approved_position, rule_hits_json,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                decision.risk_decision_id,
                decision_id,
                decision.action.value,
                decision.requested_position,
                decision.approved_position,
                _dumps(list(decision.rule_hits)),
                _dumps(decision.to_dict()),
                _utc_now(),
            ),
        )
        self._conn.commit()

    def append_order_intent(
        self, instance_id: str, intent: OrderIntent, *, status: str
    ) -> bool:
        """Return False if idempotency key already exists (duplicate suppressed)."""
        side, offset, qty = _intent_side_offset_qty(intent)
        now = _utc_now()
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO order_intent_event(
                instance_id, intent_id, decision_id, symbol, current_position,
                desired_position, urgency, idempotency_key, status,
                reason_codes_json, payload_json, created_at,
                side, offset, qty, broker_order_id, updated_at, terminal_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                intent.intent_id,
                intent.decision_id,
                intent.symbol,
                intent.current_position,
                intent.desired_position,
                intent.urgency,
                intent.idempotency_key,
                status,
                _dumps(list(intent.reason_codes)),
                _dumps(intent.to_dict()),
                now,
                side,
                offset,
                qty,
                intent.broker_order_id,
                now,
                None,
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_order_intent_status(
        self, instance_id: str, intent_id: str, status: str
    ) -> None:
        now = _utc_now()
        terminal = status in {
            "FILLED",
            "CANCELLED",
            "REJECTED",
            "FAILED",
            "EXPIRED",
        }
        self._conn.execute(
            """
            UPDATE order_intent_event
            SET status = ?, updated_at = ?, terminal_at = CASE
                WHEN ? THEN COALESCE(terminal_at, ?)
                ELSE terminal_at
            END
            WHERE instance_id = ? AND intent_id = ?
            """,
            (status, now, 1 if terminal else 0, now, instance_id, intent_id),
        )
        self._conn.commit()

    def append_fill(self, instance_id: str, fill: FillEvent) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO trade_fill_event(
                instance_id, fill_id, intent_id, symbol, price, qty, fee,
                side, trade_time, payload_json, created_at,
                broker_order_id, broker_trade_id, multiplier, realized_pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                fill.fill_id,
                fill.intent_id,
                fill.symbol,
                fill.price,
                fill.qty,
                fill.fee,
                fill.side,
                fill.trade_time.isoformat(),
                _dumps(fill.to_dict()),
                _utc_now(),
                fill.broker_order_id,
                fill.broker_trade_id,
                fill.multiplier,
                fill.realized_pnl,
            ),
        )
        self._conn.commit()

    def append_position_snapshot(
        self, instance_id: str, snap: PositionSnapshot, *, source: str
    ) -> None:
        as_of = snap.as_of.isoformat() if snap.as_of else _utc_now()
        try:
            upnl = float(snap.unrealized_pnl or 0)
        except (TypeError, ValueError):
            upnl = 0.0
        if upnl != upnl:  # NaN
            upnl = 0.0
        try:
            margin = float(getattr(snap, "margin", 0) or 0)
        except (TypeError, ValueError):
            margin = 0.0
        if margin != margin:
            margin = 0.0
        self._conn.execute(
            """
            INSERT INTO position_snapshot_event(
                instance_id, symbol, net_position, source, as_of, payload_json, created_at,
                long_today, long_yesterday, short_today, short_yesterday,
                avg_entry_price, unrealized_pnl, margin
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                snap.symbol,
                snap.net_position,
                source,
                as_of,
                _dumps(snap.to_dict()),
                _utc_now(),
                int(snap.long_today),
                int(snap.long_yesterday),
                int(snap.short_today),
                int(snap.short_yesterday),
                snap.average_entry_price,
                upnl,
                margin,
            ),
        )
        self._conn.commit()

    def append_account_snapshot(self, instance_id: str, snap: AccountSnapshot) -> None:
        as_of = snap.as_of.isoformat() if snap.as_of else _utc_now()
        self._conn.execute(
            """
            INSERT INTO account_snapshot_event(
                instance_id, account_id, equity, available, margin, margin_ratio,
                as_of, payload_json, created_at,
                realized_pnl_today, unrealized_pnl, strategy_drawdown_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                snap.account_id,
                snap.equity,
                snap.available,
                snap.margin,
                snap.margin_ratio,
                as_of,
                _dumps(snap.to_dict()),
                _utc_now(),
                float(snap.realized_pnl_today),
                float(snap.unrealized_pnl),
                float(snap.strategy_drawdown_pct),
            ),
        )
        self._conn.commit()

    def append_recon(
        self,
        instance_id: str,
        *,
        matched: bool,
        runtime_state: str,
        mismatches: list[dict[str, Any]],
        broker: Mapping[str, Any],
        local: Mapping[str, Any],
        severity: str | None = None,
    ) -> None:
        sev = severity or ("info" if matched else "warning")
        self._conn.execute(
            """
            INSERT INTO recon_event(
                instance_id, matched, runtime_state, mismatches_json,
                broker_json, local_json, created_at, severity, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                1 if matched else 0,
                runtime_state,
                _dumps(mismatches),
                _dumps(dict(broker)),
                _dumps(dict(local)),
                _utc_now(),
                sev,
                _utc_now() if matched else None,
            ),
        )
        self._conn.commit()

    def append_data_quality(
        self,
        instance_id: str,
        *,
        code: str,
        severity: str,
        message: str,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO data_quality_event(
                instance_id, code, severity, message, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                code,
                severity,
                message,
                _dumps(dict(payload or {})),
                _utc_now(),
            ),
        )
        self._conn.commit()

    def append_audit(
        self,
        instance_id: str,
        *,
        actor: str,
        action: str,
        correlation_id: str,
        before: Mapping[str, Any],
        after: Mapping[str, Any],
        reason: str,
    ) -> AuditRecord:
        prev = self._conn.execute(
            """
            SELECT event_hash FROM audit_event
            WHERE instance_id = ?
            ORDER BY seq DESC LIMIT 1
            """,
            (instance_id,),
        ).fetchone()
        prev_hash = prev["event_hash"] if prev else ("0" * 64)
        event_id = f"audit-{uuid.uuid4().hex[:12]}"
        created_at = _utc_now()
        material = _dumps(
            {
                "event_id": event_id,
                "actor": actor,
                "action": action,
                "correlation_id": correlation_id,
                "before": dict(before),
                "after": dict(after),
                "reason": reason,
                "prev_hash": prev_hash,
                "created_at": created_at,
            }
        )
        event_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
        self._conn.execute(
            """
            INSERT INTO audit_event(
                instance_id, event_id, actor, action, correlation_id,
                before_json, after_json, reason, prev_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                event_id,
                actor,
                action,
                correlation_id,
                _dumps(dict(before)),
                _dumps(dict(after)),
                reason,
                prev_hash,
                event_hash,
                created_at,
            ),
        )
        self._conn.commit()
        return AuditRecord(
            event_id=event_id,
            actor=actor,
            action=action,
            correlation_id=correlation_id,
            before=before,
            after=after,
            reason=reason,
            prev_hash=prev_hash,
            event_hash=event_hash,
            created_at=created_at,
        )

    def append_broker_order_event(
        self,
        instance_id: str,
        *,
        intent_id: str,
        symbol: str,
        side: str,
        status: str,
        event_id: str | None = None,
        local_order_id: str | None = None,
        broker_order_id: str | None = None,
        offset: str | None = None,
        filled_qty: int = 0,
        remaining_qty: int = 0,
        avg_price: float | None = None,
        message: str | None = None,
        event_time: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> str:
        eid = event_id or f"boe-{uuid.uuid4().hex}"
        et = event_time or _utc_now()
        self._conn.execute(
            """
            INSERT OR IGNORE INTO broker_order_event(
                instance_id, event_id, intent_id, local_order_id, broker_order_id,
                symbol, side, offset, status, filled_qty, remaining_qty,
                avg_price, message, event_time, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                eid,
                intent_id,
                local_order_id,
                broker_order_id,
                symbol,
                side,
                offset,
                status,
                int(filled_qty),
                int(remaining_qty),
                avg_price,
                message,
                et,
                _dumps(dict(payload or {})),
                _utc_now(),
            ),
        )
        if broker_order_id:
            self._conn.execute(
                """
                UPDATE order_intent_event
                SET broker_order_id = COALESCE(broker_order_id, ?), updated_at = ?
                WHERE instance_id = ? AND intent_id = ?
                """,
                (broker_order_id, _utc_now(), instance_id, intent_id),
            )
        self._conn.commit()
        return eid

    def append_heartbeat(
        self,
        instance_id: str,
        *,
        as_of: str | None = None,
        quote_as_of: str | None = None,
        last_price: float | None = None,
        confirmed_net: int | None = None,
        current_target: int | None = None,
        pending_desired: int | None = None,
        runtime_state: str | None = None,
        session_open: bool | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        stamp = as_of or _utc_now()
        self._conn.execute(
            """
            INSERT INTO heartbeat_event(
                instance_id, as_of, quote_as_of, last_price, confirmed_net,
                current_target, pending_desired, runtime_state, session_open,
                payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                stamp,
                quote_as_of,
                last_price,
                confirmed_net,
                current_target,
                pending_desired,
                runtime_state,
                None if session_open is None else (1 if session_open else 0),
                _dumps(dict(payload or {})),
                _utc_now(),
            ),
        )
        self.upsert_runtime_health(
            instance_id,
            last_heartbeat_at=stamp,
            last_quote_at=quote_as_of or stamp,
            runtime_state=runtime_state,
            persistence_healthy=True,
            commit=False,
        )
        self._conn.commit()

    def upsert_runtime_health(
        self,
        instance_id: str,
        *,
        last_heartbeat_at: str | None = None,
        last_bar_at: str | None = None,
        last_quote_at: str | None = None,
        unknown_order_count: int | None = None,
        kill_switch_active: bool | None = None,
        persistence_healthy: bool | None = None,
        runtime_state: str | None = None,
        payload: Mapping[str, Any] | None = None,
        commit: bool = True,
    ) -> None:
        existing = self._conn.execute(
            "SELECT * FROM runtime_health WHERE instance_id = ?",
            (instance_id,),
        ).fetchone()
        if existing is None:
            self._conn.execute(
                """
                INSERT INTO runtime_health(
                    instance_id, last_heartbeat_at, last_bar_at, last_quote_at,
                    unknown_order_count, kill_switch_active, persistence_healthy,
                    runtime_state, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instance_id,
                    last_heartbeat_at,
                    last_bar_at,
                    last_quote_at,
                    int(unknown_order_count or 0),
                    1 if kill_switch_active else 0,
                    0 if persistence_healthy is False else 1,
                    runtime_state or "IDLE",
                    _dumps(dict(payload or {})),
                    _utc_now(),
                ),
            )
        else:
            self._conn.execute(
                """
                UPDATE runtime_health SET
                    last_heartbeat_at = COALESCE(?, last_heartbeat_at),
                    last_bar_at = COALESCE(?, last_bar_at),
                    last_quote_at = COALESCE(?, last_quote_at),
                    unknown_order_count = COALESCE(?, unknown_order_count),
                    kill_switch_active = COALESCE(?, kill_switch_active),
                    persistence_healthy = COALESCE(?, persistence_healthy),
                    runtime_state = COALESCE(?, runtime_state),
                    payload_json = COALESCE(?, payload_json),
                    updated_at = ?
                WHERE instance_id = ?
                """,
                (
                    last_heartbeat_at,
                    last_bar_at,
                    last_quote_at,
                    unknown_order_count,
                    None
                    if kill_switch_active is None
                    else (1 if kill_switch_active else 0),
                    None
                    if persistence_healthy is None
                    else (1 if persistence_healthy else 0),
                    runtime_state,
                    None if payload is None else _dumps(dict(payload)),
                    _utc_now(),
                    instance_id,
                ),
            )
        if commit:
            self._conn.commit()

    def upsert_market_bars(
        self,
        bars: Sequence[Mapping[str, Any]],
        *,
        symbol: str,
        duration_sec: int,
        source: str = "tqsdk_sim_live",
        instance_id: str | None = None,
        keep_last: int = 2000,
    ) -> int:
        """Upsert OHLC bars. ``bars`` items use unix ``time`` seconds + OHLC fields."""
        if not bars:
            return 0
        now = _utc_now()
        n = 0
        for i, b in enumerate(bars):
            end_unix = int(b.get("time") or 0)
            if end_unix <= 0:
                continue
            bar_end = datetime.fromtimestamp(end_unix, tz=timezone.utc).isoformat()
            bar_start_unix = end_unix - int(duration_sec)
            bar_start = datetime.fromtimestamp(bar_start_unix, tz=timezone.utc).isoformat()
            bar_id = str(b.get("bar_id") or f"{symbol}:{duration_sec}:{end_unix}")
            is_final = b.get("is_final")
            if is_final is None:
                # last bar may be forming unless caller marks it
                is_final = i < len(bars) - 1 or bool(b.get("force_final"))
            self._conn.execute(
                """
                INSERT INTO market_bar(
                    symbol, duration_sec, bar_id, bar_start, bar_end, available_at,
                    open, high, low, close, volume, open_oi, close_oi,
                    underlying_symbol, is_final, source, instance_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, duration_sec, bar_end) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume,
                    open_oi=excluded.open_oi,
                    close_oi=excluded.close_oi,
                    underlying_symbol=excluded.underlying_symbol,
                    is_final=excluded.is_final,
                    source=excluded.source,
                    instance_id=COALESCE(excluded.instance_id, market_bar.instance_id),
                    available_at=excluded.available_at
                """,
                (
                    symbol,
                    int(duration_sec),
                    bar_id,
                    bar_start,
                    bar_end,
                    now,
                    float(b["open"]),
                    float(b["high"]),
                    float(b["low"]),
                    float(b["close"]),
                    float(b.get("volume") or 0),
                    float(b.get("open_oi") or 0),
                    float(b.get("close_oi") or 0),
                    str(b.get("underlying_symbol") or ""),
                    1 if is_final else 0,
                    source,
                    instance_id,
                    now,
                ),
            )
            n += 1
        if keep_last > 0:
            self._conn.execute(
                """
                DELETE FROM market_bar
                WHERE symbol = ? AND duration_sec = ?
                  AND seq NOT IN (
                    SELECT seq FROM market_bar
                    WHERE symbol = ? AND duration_sec = ?
                    ORDER BY bar_end DESC LIMIT ?
                  )
                """,
                (symbol, int(duration_sec), symbol, int(duration_sec), int(keep_last)),
            )
        self._conn.commit()
        return n

    def list_market_bars(
        self,
        symbol: str,
        *,
        duration_sec: int = 300,
        limit: int = 400,
        finals_only: bool = False,
    ) -> list[dict[str, Any]]:
        where_final = "AND is_final = 1" if finals_only else ""
        rows = self._conn.execute(
            f"""
            SELECT * FROM market_bar
            WHERE symbol = ? AND duration_sec = ? {where_final}
            ORDER BY bar_end DESC
            LIMIT ?
            """,
            (symbol, int(duration_sec), int(limit)),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in reversed(rows):
            end = datetime.fromisoformat(r["bar_end"])
            out.append(
                {
                    "time": int(end.timestamp()),
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"] or 0),
                    "open_oi": float(r["open_oi"] or 0),
                    "close_oi": float(r["close_oi"] or 0),
                    "underlying_symbol": r["underlying_symbol"] or "",
                    "is_final": bool(r["is_final"]),
                    "bar_id": r["bar_id"],
                }
            )
        return out

    def list_idempotency_keys(self, instance_id: str) -> set[str]:
        rows = self._conn.execute(
            "SELECT idempotency_key FROM order_intent_event WHERE instance_id = ?",
            (instance_id,),
        ).fetchall()
        return {str(r["idempotency_key"]) for r in rows}

    def latest_open_intent(self, instance_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT * FROM order_intent_event
            WHERE instance_id = ? AND status IN ('SUBMITTED', 'ACKNOWLEDGED', 'PARTIALLY_FILLED', 'UNKNOWN')
            ORDER BY seq DESC LIMIT 1
            """,
            (instance_id,),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def load_runtime_health(self, instance_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM runtime_health WHERE instance_id = ?",
            (instance_id,),
        ).fetchone()
        return dict(row) if row else None

    def verify_audit_chain(self, instance_id: str) -> bool:
        rows = self._conn.execute(
            """
            SELECT event_id, actor, action, correlation_id, before_json, after_json,
                   reason, prev_hash, event_hash, created_at
            FROM audit_event WHERE instance_id = ? ORDER BY seq ASC
            """,
            (instance_id,),
        ).fetchall()
        prev = "0" * 64
        for row in rows:
            if row["prev_hash"] != prev:
                return False
            material = _dumps(
                {
                    "event_id": row["event_id"],
                    "actor": row["actor"],
                    "action": row["action"],
                    "correlation_id": row["correlation_id"],
                    "before": json.loads(row["before_json"]),
                    "after": json.loads(row["after_json"]),
                    "reason": row["reason"],
                    "prev_hash": row["prev_hash"],
                    "created_at": row["created_at"],
                }
            )
            expected = hashlib.sha256(material.encode("utf-8")).hexdigest()
            if expected != row["event_hash"]:
                return False
            prev = row["event_hash"]
        return True

    def close(self) -> None:
        self._conn.close()
