"""Phase 4 tests — persistence, audit chain, reconciliation, restart recovery."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from ignitequant.config import default_decision_config
from ignitequant.domain.enums import DecisionAction, RiskAction, SignalAction
from ignitequant.domain.models import (
    FillEvent,
    OrderIntent,
    SignalEvent,
    TargetPosition,
)
from ignitequant.engine import (
    BrokerFacts,
    FalconDecisionPipeline,
    LocalProjection,
    reconcile,
)
from ignitequant.persistence import PersistenceSession, SqliteTradingRepository, open_sqlite
from ignitequant.risk import RiskEngine


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _intent(key: str = "k1", desired: int = 1) -> OrderIntent:
    return OrderIntent(
        intent_id="intent-1",
        decision_id="bar-1",
        symbol="SHFE.au2608",
        current_position=0,
        desired_position=desired,
        urgency="NORMAL",
        idempotency_key=key,
        created_at=_now(),
        reason_codes=(),
    )


def test_sqlite_persist_and_reload_state(tmp_path: Path) -> None:
    db = tmp_path / "t.sqlite"
    session = PersistenceSession.open(db, instance_id="i1")
    session.save_state(
        symbol="SHFE.au2608",
        current_target=1,
        confirmed_net=1,
        cooldown_left=3,
        entry_price=800.0,
        stop_price=790.0,
        take_price=820.0,
        entry_signal=2,
        last_bar_id="b1",
        config_hash="abc",
    )
    session.close()

    session2 = PersistenceSession.open(db, instance_id="i1")
    state = session2.repo.load_strategy_state("i1")
    assert state is not None
    assert state.payload["confirmed_net"] == 1
    assert state.payload["cooldown_left"] == 3
    assert state.payload["entry_price"] == 800.0
    session2.close()


def test_audit_chain_append_only(tmp_path: Path) -> None:
    db = tmp_path / "a.sqlite"
    repo = SqliteTradingRepository(open_sqlite(db))
    a1 = repo.append_audit(
        "i1",
        actor="sys",
        action="boot",
        correlation_id="c1",
        before={},
        after={"x": 1},
        reason="start",
    )
    a2 = repo.append_audit(
        "i1",
        actor="sys",
        action="trade",
        correlation_id="c2",
        before={"x": 1},
        after={"x": 2},
        reason="fill",
    )
    assert a2.prev_hash == a1.event_hash
    assert repo.verify_audit_chain("i1")
    repo.close()


def test_idempotent_order_intent(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "o.sqlite", instance_id="i1")
    intent = _intent("dup-key")
    assert session.record_intent(intent) is True
    # same key different intent_id still blocked by UNIQUE(idempotency_key)
    intent2 = OrderIntent(
        intent_id="intent-2",
        decision_id="bar-2",
        symbol="SHFE.au2608",
        current_position=0,
        desired_position=1,
        urgency="NORMAL",
        idempotency_key="dup-key",
        created_at=_now(),
    )
    assert session.record_intent(intent2) is False
    keys = session.repo.list_idempotency_keys("i1")
    assert "dup-key" in keys
    session.close()


def test_reconcile_position_mismatch_degrades() -> None:
    local = LocalProjection(
        symbol="SHFE.au2608",
        expected_net=1,
        current_target=1,
    )
    broker = BrokerFacts(symbol="SHFE.au2608", net_position=0)
    report = reconcile(local, broker)
    assert report.matched is False
    assert report.runtime_state == "DEGRADED"
    rt = report.to_runtime()
    assert rt.reconciliation_matched is False


def test_reconcile_pending_explains_gap() -> None:
    local = LocalProjection(
        symbol="SHFE.au2608",
        expected_net=0,
        current_target=1,
        pending_desired=1,
    )
    broker = BrokerFacts(symbol="SHFE.au2608", net_position=1)
    report = reconcile(local, broker)
    assert report.matched is True


def test_contract_roll_symbol_not_degraded() -> None:
    from ignitequant.engine.reconciliation import contract_product_key, is_contract_roll

    assert contract_product_key("SHFE.au2608") == "shfe.au"
    assert contract_product_key("SHFE.au2610") == "shfe.au"
    assert contract_product_key("KQ.m@SHFE.au") == "shfe.au"
    assert is_contract_roll("SHFE.au2608", "SHFE.au2610") is True
    assert is_contract_roll("SHFE.au2608", "SHFE.ag2610") is False

    local = LocalProjection(
        symbol="SHFE.au2608",
        expected_net=0,
        current_target=0,
    )
    broker = BrokerFacts(symbol="SHFE.au2610", net_position=0)
    report = reconcile(local, broker)
    assert report.matched is True
    assert report.runtime_state == "RUNNING"


def test_startup_recover_contract_roll_allows_new_risk(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "roll.sqlite", instance_id="sim1")
    session.save_state(
        symbol="SHFE.au2608",
        current_target=0,
        confirmed_net=0,
        cooldown_left=0,
    )
    recovery = session.recover(BrokerFacts(symbol="SHFE.au2610", net_position=0))
    assert recovery.report.matched is True
    assert recovery.allow_new_risk is True
    assert recovery.state is not None
    assert recovery.state.symbol == "SHFE.au2610"
    assert "contract roll" in recovery.message
    session.close()


def test_startup_recover_open_position(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "r.sqlite", instance_id="sim1")
    session.save_state(
        symbol="SHFE.au2608",
        current_target=1,
        confirmed_net=1,
        cooldown_left=2,
        entry_price=801.0,
        stop_price=790.0,
        take_price=820.0,
        entry_signal=3,
        last_bar_id="old",
        config_hash="h",
    )
    session.record_intent(_intent("old-key", desired=1))
    session.close()

    session2 = PersistenceSession.open(tmp_path / "r.sqlite", instance_id="sim1")
    recovery = session2.recover(
        BrokerFacts(symbol="SHFE.au2608", net_position=1, equity=1_000_000)
    )
    assert recovery.report.matched is True
    assert recovery.allow_new_risk is True
    assert recovery.restore_payload["cooldown_left"] == 2
    assert recovery.restore_payload["entry_price"] == 801.0
    assert "old-key" in recovery.idempotency_keys

    pipe = FalconDecisionPipeline(default_decision_config())
    pipe.restore_runtime(
        current_target=int(recovery.restore_payload["current_target"]),
        cooldown_left=int(recovery.restore_payload["cooldown_left"]),
        entry_price=recovery.restore_payload["entry_price"],
        stop_price=recovery.restore_payload["stop_price"],
        take_price=recovery.restore_payload["take_price"],
        entry_signal=recovery.restore_payload["entry_signal"],
    )
    assert pipe.current_target == 1
    assert pipe.risk.state.cooldown_left == 2
    assert pipe.risk.state.entry_price == 801.0
    session2.close()


def test_startup_recover_mismatch_blocks_new_risk(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "m.sqlite", instance_id="sim1")
    session.save_state(
        symbol="SHFE.au2608",
        current_target=1,
        confirmed_net=1,
        cooldown_left=0,
        entry_price=800.0,
    )
    recovery = session.recover(BrokerFacts(symbol="SHFE.au2608", net_position=0))
    assert recovery.report.matched is False
    assert recovery.allow_new_risk is False
    assert recovery.runtime_state == "DEGRADED"

    # RiskEngine should reject new risk when runtime says mismatch.
    engine = RiskEngine(default_decision_config())
    from ignitequant.domain.models import (
        AccountSnapshot,
        ContractSnapshot,
        MarketSnapshot,
        PortfolioSnapshot,
        PositionSnapshot,
        RuntimeSnapshot,
    )

    now = _now()
    decision = engine.evaluate(
        target=TargetPosition(
            target_id="t",
            signal_id="s",
            symbol="SHFE.au2608",
            decision_action=DecisionAction.TARGET,
            current_position=0,
            desired_position=1,
            delta=1,
            planned_entry_price=800.0,
            planned_stop_price=None,
            stop_distance=None,
            risk_per_lot=None,
            requested_risk=Decimal("0"),
            sizing_method="legacy",
            reason_codes=(),
            config_version="v1",
        ),
        signal=SignalEvent(
            signal_id="s",
            factor_snapshot_id="f",
            action=SignalAction.ENTER_LONG,
            direction=1,
            alpha=1.0,
            strength=1.0,
            confidence=1.0,
            generated_at=now,
            effective_from=now,
            expires_at=now,
            confirmation_bars=1,
            reason_codes=(),
            model_version="legacy",
            legacy_signal=1,
        ),
        market=MarketSnapshot(symbol="SHFE.au2608", last_price=800.0),
        contract=ContractSnapshot(symbol="SHFE.au2608"),
        position=PositionSnapshot(symbol="SHFE.au2608", net_position=0),
        account=AccountSnapshot(
            account_id="a", equity=1e6, available=1e6, margin=0, margin_ratio=0
        ),
        portfolio=PortfolioSnapshot(),
        runtime=recovery.report.to_runtime(),
    )
    assert decision.action is RiskAction.REJECT
    session.close()


def test_restart_does_not_resubmit_same_idempotency(tmp_path: Path) -> None:
    """Exit gate: restart mid-flight must not create a second intent for same key."""
    db = tmp_path / "restart.sqlite"
    session = PersistenceSession.open(db, instance_id="sim1")
    session.save_state(
        symbol="SHFE.au2608",
        current_target=1,
        confirmed_net=0,
        pending_desired=1,
        entry_price=800.0,
    )
    key = "bar-99:1:TARGET"
    assert session.record_intent(_intent(key, desired=1)) is True
    session.close()

    # Simulated process restart
    session2 = PersistenceSession.open(db, instance_id="sim1")
    recovery = session2.recover(BrokerFacts(symbol="SHFE.au2608", net_position=1))
    assert recovery.report.matched is True  # pending completed offline
    assert key in recovery.idempotency_keys
    # Attempting to re-record same key fails
    assert session2.record_intent(_intent(key, desired=1)) is False
    session2.close()


def test_fill_persistence(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "f.sqlite", instance_id="i1")
    intent = _intent()
    session.record_intent(intent)
    fill = FillEvent(
        fill_id="fill-1",
        intent_id=intent.intent_id,
        symbol="SHFE.au2608",
        price=800.5,
        qty=1,
        fee=0.0,
        side="BUY",
        trade_time=_now(),
    )
    session.record_fill(fill)
    open_intent = session.repo.latest_open_intent("i1")
    assert open_intent is None  # status updated to FILLED
    session.close()
