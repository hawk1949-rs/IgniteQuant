"""Repository protocol and SQLite implementation (大框架 §8.1)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

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

    def list_idempotency_keys(self, instance_id: str) -> set[str]: ...

    def latest_open_intent(self, instance_id: str) -> dict[str, Any] | None: ...

    def close(self) -> None: ...


class SqliteTradingRepository:
    """Append-only trading events + mutable strategy_state projection."""

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

    def append_decision(self, instance_id: str, result: PipelineResult) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO decision_event(
                instance_id, decision_id, bar_id, symbol, applied_action,
                target_before, target_after, legacy_signal, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _utc_now(),
            ),
        )
        self._conn.commit()

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
        cur = self._conn.execute(
            """
            INSERT OR IGNORE INTO order_intent_event(
                instance_id, intent_id, decision_id, symbol, current_position,
                desired_position, urgency, idempotency_key, status,
                reason_codes_json, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                _utc_now(),
            ),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def update_order_intent_status(
        self, instance_id: str, intent_id: str, status: str
    ) -> None:
        self._conn.execute(
            """
            UPDATE order_intent_event
            SET status = ?
            WHERE instance_id = ? AND intent_id = ?
            """,
            (status, instance_id, intent_id),
        )
        self._conn.commit()

    def append_fill(self, instance_id: str, fill: FillEvent) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO trade_fill_event(
                instance_id, fill_id, intent_id, symbol, price, qty, fee,
                side, trade_time, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
        self._conn.commit()

    def append_position_snapshot(
        self, instance_id: str, snap: PositionSnapshot, *, source: str
    ) -> None:
        as_of = snap.as_of.isoformat() if snap.as_of else _utc_now()
        self._conn.execute(
            """
            INSERT INTO position_snapshot_event(
                instance_id, symbol, net_position, source, as_of, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                snap.symbol,
                snap.net_position,
                source,
                as_of,
                _dumps(snap.to_dict()),
                _utc_now(),
            ),
        )
        self._conn.commit()

    def append_account_snapshot(self, instance_id: str, snap: AccountSnapshot) -> None:
        as_of = snap.as_of.isoformat() if snap.as_of else _utc_now()
        self._conn.execute(
            """
            INSERT INTO account_snapshot_event(
                instance_id, account_id, equity, available, margin, margin_ratio,
                as_of, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO recon_event(
                instance_id, matched, runtime_state, mismatches_json,
                broker_json, local_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                1 if matched else 0,
                runtime_state,
                _dumps(mismatches),
                _dumps(dict(broker)),
                _dumps(dict(local)),
                _utc_now(),
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
