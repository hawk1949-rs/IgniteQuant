"""Unit tests for cloud projection upsert helpers."""

from __future__ import annotations

from ignitequant.persistence.cloud_projections import sim_instance_patch_from_payload


def test_sim_instance_patch_account_and_position() -> None:
    acct = sim_instance_patch_from_payload(
        "account.snapshot",
        {
            "equity": 1_000_100.0,
            "available": 900_000.0,
            "margin": 50_000.0,
            "margin_ratio": 0.05,
            "account_id": "local",
            "as_of": "2026-07-28T00:00:00+00:00",
        },
    )
    assert acct["equity"] == 1_000_100.0
    assert acct["account"]["equity"] == 1_000_100.0

    pos = sim_instance_patch_from_payload(
        "position.snapshot",
        {
            "symbol": "SHFE.au2608",
            "net_position": 2,
            "source": "broker",
            "average_entry_price": 875.5,
            "unrealized_pnl": 1_200.0,
            "margin": 45_000.0,
        },
    )
    assert pos["confirmed_net"] == 2
    assert pos["position"]["net_position"] == 2
    assert pos["position"]["average_entry_price"] == 875.5
    assert pos["position"]["margin"] == 45_000.0


def test_upsert_projection_sql_shape(monkeypatch) -> None:
    """Call upsert with a fake cursor that records SQL/params."""
    from ignitequant.persistence.cloud_projections import upsert_projection_for_event

    calls: list[tuple] = []

    class FakeCur:
        def execute(self, sql, params=None):
            calls.append((sql, params))

    cur = FakeCur()
    upsert_projection_for_event(
        cur,
        instance_key="falcon_au_sim",
        event_type="decision.appended",
        aggregate_id="bar-1",
        payload={
            "decision_id": "bar-1",
            "bar_id": "bar-1",
            "symbol": "SHFE.au2608",
            "applied_action": "TARGET",
            "target_before": 0,
            "target_after": 1,
            "legacy_signal": 1,
            "regime": "TREND_UP",
            "factor_quality": "READY",
            "factor_values": {"atr": 0.5},
            "reason_codes": ["SCORE"],
            "risk_action": "PASS",
            "requested_position": 1,
            "approved_position": 1,
        },
        occurred_at="2026-07-28T01:00:00+00:00",
        owner_id_value=None,
    )
    assert len(calls) == 1
    assert "sim_decision_projection" in calls[0][0]
    assert calls[0][1][2] == "bar-1"

    upsert_projection_for_event(
        cur,
        instance_key="falcon_au_sim",
        event_type="intent.submitted",
        aggregate_id="intent-1",
        payload={
            "intent_id": "intent-1",
            "decision_id": "bar-1",
            "symbol": "SHFE.au2608",
            "current_position": 0,
            "desired_position": 1,
            "status": "SUBMITTED",
            "qty": 1,
            "side": "BUY",
        },
        occurred_at="2026-07-28T01:00:01+00:00",
        owner_id_value=None,
    )
    assert "sim_intent_projection" in calls[1][0]

    upsert_projection_for_event(
        cur,
        instance_key="falcon_au_sim",
        event_type="fill.confirmed",
        aggregate_id="fill-1",
        payload={
            "fill_id": "fill-1",
            "intent_id": "intent-1",
            "symbol": "SHFE.au2608",
            "price": 880.0,
            "qty": 1,
            "fee": 10.0,
            "side": "BUY",
            "trade_time": "2026-07-28T01:00:02+00:00",
        },
        occurred_at="2026-07-28T01:00:02+00:00",
        owner_id_value=None,
    )
    assert "sim_fill_projection" in calls[2][0]
