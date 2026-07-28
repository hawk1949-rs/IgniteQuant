"""Sim cockpit cloud read path unit tests (mocked PG)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException


def test_data_source_default_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIM_DATA_SOURCE", raising=False)
    from dashboard import sim_cloud_read

    assert sim_cloud_read.data_source() == "cloud"
    assert sim_cloud_read.is_cloud() is True


def test_data_source_local(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIM_DATA_SOURCE", "local")
    from dashboard import sim_cloud_read

    assert sim_cloud_read.data_source() == "local"
    assert sim_cloud_read.is_cloud() is False


def test_require_pg_url_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from dashboard import sim_cloud_read

    with pytest.raises(HTTPException) as exc:
        sim_cloud_read.require_pg_url()
    assert exc.value.status_code == 503


def test_decision_item_shape() -> None:
    from dashboard.sim_cloud_read import _decision_item

    item = _decision_item(
        {
            "decision_id": "bar-1",
            "bar_id": "bar-1",
            "symbol": "SHFE.au2608",
            "applied_action": "TARGET",
            "target_before": 0,
            "target_after": 1,
            "legacy_signal": 2,
            "occurred_at": datetime(2026, 7, 28, tzinfo=timezone.utc),
            "regime": "TREND_UP",
            "factor_quality": "READY",
            "factor_values_json": {"atr": 0.4},
            "reason_codes_json": ["SCORE"],
            "score_parts_json": [0, 1, 0],
            "risk_action": "PASS",
            "requested_position": 1,
            "approved_position": 1,
            "payload_json": {},
        }
    )
    assert item["decision_id"] == "bar-1"
    assert item["regime"] == "TREND_UP"
    assert item["risk"]["action"] == "PASS"
    assert item["factor_values"]["atr"] == 0.4


def test_metrics_from_fills_round_trip() -> None:
    from dashboard.sim_cloud_read import _metrics_from_fills

    fills = [
        {"side": "BUY", "qty": 1, "price": 800.0, "fee": 10.0},
        {"side": "SELL", "qty": 1, "price": 810.0, "fee": 10.0},
    ]
    m = _metrics_from_fills(fills, equity=1_010_000.0)
    assert m["trade_count"] == 1
    assert m["current_equity"] == 1_010_000.0
    assert m["approx"] is True
