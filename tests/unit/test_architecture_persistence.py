"""Architecture L0–L4 persistence tests (broker/heartbeat/decision dual-write/bars/ref)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from ignitequant.domain.enums import (
    DecisionAction,
    FactorQuality,
    Regime,
    RiskAction,
    SignalAction,
)
from ignitequant.domain.models import (
    FactorSnapshot,
    FillEvent,
    OrderIntent,
    PipelineResult,
    RiskDecision,
    SignalEvent,
    TargetPosition,
)
from ignitequant.persistence import PersistenceSession, SCHEMA_VERSION, open_sqlite
from ignitequant.persistence.ref_cache import load_ref_instrument, seed_ref_tables
from ignitequant.persistence.schema import V2_ADD_COLUMNS
from ignitequant.persistence.sqlite import migrate


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pipeline(bar_id: str = "bar-100") -> PipelineResult:
    now = _now()
    factors = FactorSnapshot(
        factor_snapshot_id=f"fs-{bar_id}",
        symbol="SHFE.au2608",
        bar_id=bar_id,
        data_as_of=now,
        values={"atr": 1.2, "score": 2.0},
        regime=Regime.TREND_UP,
        quality=FactorQuality.READY,
        factor_version="v1",
        reason_codes=("OK",),
    )
    signal = SignalEvent(
        signal_id=f"sig-{bar_id}",
        factor_snapshot_id=factors.factor_snapshot_id,
        action=SignalAction.ENTER_LONG,
        direction=1,
        alpha=1.5,
        strength=0.8,
        confidence=0.7,
        generated_at=now,
        effective_from=now,
        expires_at=now,
        confirmation_bars=1,
        reason_codes=("SCORE",),
        model_version="legacy",
        legacy_signal=2,
    )
    target = TargetPosition(
        target_id=f"tgt-{bar_id}",
        signal_id=signal.signal_id,
        symbol="SHFE.au2608",
        decision_action=DecisionAction.TARGET,
        current_position=0,
        desired_position=1,
        delta=1,
        planned_entry_price=800.0,
        planned_stop_price=790.0,
        stop_distance=10.0,
        risk_per_lot=None,
        requested_risk=Decimal("0"),
        sizing_method="legacy",
        reason_codes=("SIZE",),
        config_version="cfg1",
    )
    risk = RiskDecision(
        risk_decision_id=f"risk-{bar_id}",
        target_id=target.target_id,
        action=RiskAction.PASS,
        requested_position=1,
        approved_position=1,
        requested_risk=Decimal("0"),
        approved_risk=Decimal("0"),
        rule_hits=(),
        warnings=(),
        evaluated_at=now,
        risk_config_version="r1",
        risk_snapshot_id="rs1",
    )
    return PipelineResult(
        bar_id=bar_id,
        factors=factors,
        signal=signal,
        target=target,
        risk_decision=risk,
        applied_action="TARGET",
        target_before=0,
        target_after=1,
        sizing_target=1,
        legacy_score_parts=(1, 1, 0, 0),
    )


def test_schema_version_is_v2(tmp_path: Path) -> None:
    conn = open_sqlite(tmp_path / "v.sqlite")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    assert int(row["v"]) >= SCHEMA_VERSION
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for required in (
        "broker_order_event",
        "heartbeat_event",
        "runtime_health",
        "factor_snapshot",
        "signal_event",
        "target_position_event",
        "signal_state",
        "market_bar",
        "ref_instrument",
        "backtest_run",
    ):
        assert required in tables
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(decision_event)").fetchall()}
    for name, _ in V2_ADD_COLUMNS["decision_event"]:
        assert name in cols
    conn.close()


def test_upgrade_from_legacy_v1_shape(tmp_path: Path) -> None:
    """Simulate a v1 DB (narrow columns) and ensure migrate adds L0/L1 columns."""
    import sqlite3

    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES (1, datetime('now'));
        CREATE TABLE decision_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            bar_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            applied_action TEXT NOT NULL,
            target_before INTEGER NOT NULL,
            target_after INTEGER NOT NULL,
            legacy_signal INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(instance_id, decision_id)
        );
        CREATE TABLE order_intent_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            intent_id TEXT NOT NULL,
            decision_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            current_position INTEGER NOT NULL,
            desired_position INTEGER NOT NULL,
            urgency TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            status TEXT NOT NULL,
            reason_codes_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(instance_id, intent_id),
            UNIQUE(instance_id, idempotency_key)
        );
        CREATE TABLE trade_fill_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            fill_id TEXT NOT NULL,
            intent_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            qty INTEGER NOT NULL,
            fee REAL NOT NULL DEFAULT 0,
            side TEXT NOT NULL,
            trade_time TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(instance_id, fill_id)
        );
        CREATE TABLE position_snapshot_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            net_position INTEGER NOT NULL,
            source TEXT NOT NULL,
            as_of TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE account_snapshot_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            account_id TEXT NOT NULL,
            equity REAL NOT NULL,
            available REAL NOT NULL,
            margin REAL NOT NULL,
            margin_ratio REAL NOT NULL,
            as_of TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE recon_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            instance_id TEXT NOT NULL,
            matched INTEGER NOT NULL,
            runtime_state TEXT NOT NULL,
            mismatches_json TEXT NOT NULL,
            broker_json TEXT NOT NULL,
            local_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    migrate(conn)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    assert int(row["v"]) >= 2
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(order_intent_event)").fetchall()}
    assert "side" in cols and "qty" in cols and "broker_order_id" in cols
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE name='broker_order_event'"
    ).fetchone()
    conn.close()


def test_broker_order_and_heartbeat(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "b.sqlite", instance_id="i1")
    intent = OrderIntent(
        intent_id="intent-1",
        decision_id="bar-1",
        symbol="SHFE.au2608",
        current_position=0,
        desired_position=1,
        urgency="NORMAL",
        idempotency_key="k-1",
        created_at=_now(),
    )
    assert session.record_intent(intent) is True
    rows = session.repo._conn.execute(  # noqa: SLF001 — test peek
        "SELECT status, side, remaining_qty FROM broker_order_event WHERE intent_id=?",
        ("intent-1",),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["status"] == "SUBMITTED"
    assert rows[0]["side"] == "BUY"

    fill = FillEvent(
        fill_id="fill-1",
        intent_id="intent-1",
        symbol="SHFE.au2608",
        price=801.0,
        qty=1,
        fee=0.0,
        side="BUY",
        trade_time=_now(),
        broker_trade_id="t-1",
    )
    session.record_fill(fill)
    statuses = [
        r["status"]
        for r in session.repo._conn.execute(  # noqa: SLF001
            "SELECT status FROM broker_order_event WHERE intent_id=? ORDER BY seq",
            ("intent-1",),
        ).fetchall()
    ]
    assert "FILLED" in statuses

    session.record_heartbeat(
        last_price=801.0,
        confirmed_net=1,
        current_target=1,
        session_open=True,
    )
    hb = session.repo._conn.execute(  # noqa: SLF001
        "SELECT confirmed_net, last_price FROM heartbeat_event WHERE instance_id='i1'"
    ).fetchone()
    assert hb["confirmed_net"] == 1
    health = session.repo.load_runtime_health("i1")
    assert health is not None
    assert health["last_heartbeat_at"]
    session.close()


def test_decision_dual_write(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "d.sqlite", instance_id="i1")
    result = _pipeline("bar-200")
    session.record_decision(result)
    session.record_risk(result.bar_id, result.risk_decision)

    conn = session.repo._conn  # noqa: SLF001
    assert conn.execute(
        "SELECT factor_snapshot_id FROM factor_snapshot WHERE bar_id='bar-200'"
    ).fetchone()
    assert conn.execute(
        "SELECT signal_id FROM signal_event WHERE signal_id='sig-bar-200'"
    ).fetchone()
    assert conn.execute(
        "SELECT target_id FROM target_position_event WHERE target_id='tgt-bar-200'"
    ).fetchone()
    dec = conn.execute(
        "SELECT factor_snapshot_id, signal_id, target_id, config_hash FROM decision_event "
        "WHERE decision_id='bar-200'"
    ).fetchone()
    assert dec["factor_snapshot_id"] == "fs-bar-200"
    assert dec["signal_id"] == "sig-bar-200"
    assert dec["config_hash"] == "cfg1"
    st = conn.execute("SELECT consecutive_long_bars FROM signal_state WHERE instance_id='i1'").fetchone()
    assert int(st["consecutive_long_bars"]) == 1
    session.close()


def test_market_bar_upsert_and_list(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "m.sqlite", instance_id="sim")
    bars = [
        {
            "time": 1_700_000_000 + i * 300,
            "open": 800 + i,
            "high": 801 + i,
            "low": 799 + i,
            "close": 800.5 + i,
            "volume": 10,
            "underlying_symbol": "SHFE.au2608",
            "force_final": True,
        }
        for i in range(5)
    ]
    n = session.persist_market_bars(bars, symbol="KQ.m@SHFE.au", duration_sec=300)
    assert n == 5
    listed = session.repo.list_market_bars("KQ.m@SHFE.au", duration_sec=300, limit=10)
    assert len(listed) == 5
    assert listed[0]["open"] == 800
    # idempotent upsert
    n2 = session.persist_market_bars(bars, symbol="KQ.m@SHFE.au", duration_sec=300)
    assert n2 == 5
    assert len(session.repo.list_market_bars("KQ.m@SHFE.au", duration_sec=300)) == 5
    session.close()


def test_ref_seed(tmp_path: Path) -> None:
    conn = open_sqlite(tmp_path / "ref.sqlite")
    assert seed_ref_tables(conn) == 4
    au = load_ref_instrument(conn, "au")
    assert au is not None
    assert au["name"] == "沪金"
    assert au["signal_symbol"] == "KQ.m@SHFE.au"
    fees = conn.execute(
        "SELECT open_fee FROM ref_fee_schedule WHERE product_id='au'"
    ).fetchone()
    assert float(fees["open_fee"]) == 10.0
    conn.close()
