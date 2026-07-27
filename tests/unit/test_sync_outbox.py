"""Local sync_outbox + schema v3 tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from ignitequant.domain.models import FillEvent, OrderIntent
from ignitequant.persistence import PersistenceSession, SCHEMA_VERSION, open_sqlite
from ignitequant.persistence.outbox import list_pending


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_schema_version_has_outbox(tmp_path: Path) -> None:
    assert SCHEMA_VERSION >= 3
    conn = open_sqlite(tmp_path / "o.sqlite")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    assert int(row["v"]) >= 3
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE name='sync_outbox'"
    ).fetchone()
    conn.close()


def test_session_enqueues_intent_and_fill(tmp_path: Path) -> None:
    session = PersistenceSession.open(tmp_path / "s.sqlite", instance_id="sim1")
    intent = OrderIntent(
        intent_id="intent-x",
        decision_id="bar-x",
        symbol="SHFE.au2608",
        current_position=0,
        desired_position=1,
        urgency="NORMAL",
        idempotency_key="k-x",
        created_at=_now(),
    )
    assert session.record_intent(intent) is True
    session.record_fill(
        FillEvent(
            fill_id="fill-x",
            intent_id="intent-x",
            symbol="SHFE.au2608",
            price=800.0,
            qty=1,
            fee=0.0,
            side="BUY",
            trade_time=_now(),
        )
    )
    pending = list_pending(session.repo._conn)  # noqa: SLF001
    types = {p["event_type"] for p in pending}
    assert "intent.submitted" in types
    assert "fill.confirmed" in types
    session.close()
