"""cloud_sync best-effort helpers."""

from __future__ import annotations

from pathlib import Path

from ignitequant.persistence.cloud_sync import try_push_outbox
from ignitequant.persistence.outbox import enqueue_outbox
from ignitequant.persistence.sqlite import open_sqlite


def test_try_push_without_url_skips(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    conn = open_sqlite(tmp_path / "c.sqlite")
    enqueue_outbox(
        conn,
        instance_id="sim1",
        event_type="heartbeat.tick",
        aggregate_type="runtime_health",
        aggregate_id="sim1",
        payload={"confirmed_net": 0},
    )
    result = try_push_outbox(conn, root=tmp_path, db_hint=str(tmp_path / "c.sqlite"))
    assert result.get("skipped") == "no_database_url"
    conn.close()
