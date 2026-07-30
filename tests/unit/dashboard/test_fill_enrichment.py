# -*- coding: utf-8 -*-
from __future__ import annotations

from dashboard.fill_enrichment import enrichment_from_decision_payload


def test_enrichment_prefers_risk_payload_stops() -> None:
    out = enrichment_from_decision_payload(
        decision_id="d1",
        legacy_signal=2,
        applied_action="TARGET",
        payload={
            "regime": "TREND_UP",
            "target": {"planned_entry_price": 880.0},
            "reason_codes": ["SCORE"],
        },
        risk_payload={"entry_price": 870.0, "stop_price": 860.0, "take_price": 900.0},
    )
    assert out["legacy_signal"] == 2
    assert out["stop_price"] == 860.0
    assert out["take_price"] == 900.0
    assert out["entry_price"] == 870.0
    assert out["regime"] == "TREND_UP"


def test_enrichment_reads_nested_risk_decision() -> None:
    out = enrichment_from_decision_payload(
        decision_id="d2",
        legacy_signal=None,
        applied_action=None,
        payload={
            "applied_action": "EXIT",
            "signal": {"legacy_signal": -1},
            "risk_decision": {
                "stop_price": 850.0,
                "take_price": 820.0,
                "entry_price": 840.0,
            },
        },
    )
    assert out["legacy_signal"] == -1
    assert out["applied_action"] == "EXIT"
    assert out["stop_price"] == 850.0


def test_enrichment_ignores_null_pretrade_and_uses_decision() -> None:
    """Pretrade risk rows are truthy dicts with null stops — must not block nested."""
    out = enrichment_from_decision_payload(
        decision_id="d3",
        legacy_signal=-1,
        applied_action="TARGET",
        payload={
            "risk_decision": {
                "stop_price": 885.37,
                "take_price": 882.64,
                "entry_price": 884.38,
            },
            "target": {"planned_stop_price": None, "planned_entry_price": 884.38},
        },
        risk_payload={
            "stop_price": None,
            "take_price": None,
            "entry_price": None,
            "action": "PASS",
        },
    )
    assert out["stop_price"] == 885.37
    assert out["take_price"] == 882.64
    assert out["entry_price"] == 884.38


def test_stop_loss_fill_hides_armed_levels() -> None:
    out = enrichment_from_decision_payload(
        decision_id="d4",
        legacy_signal=0,
        applied_action="STOP_LOSS",
        payload={
            "risk_decision": {
                "stop_price": 885.37,
                "take_price": 882.64,
                "entry_price": 884.38,
            },
        },
    )
    assert out["applied_action"] == "STOP_LOSS"
    assert out["stop_price"] is None
    assert out["take_price"] is None
    assert out["entry_price"] is None


def test_entry_stop_fallback_skips_exit_fills() -> None:
    from dashboard.fill_enrichment import apply_entry_stop_fallback

    items = [
        {
            "fill_id": "exit",
            "trade_time": "2026-07-28T06:35:00",
            "applied_action": "STOP_LOSS",
            "stop_price": None,
            "take_price": None,
            "entry_price": None,
        },
        {
            "fill_id": "open",
            "trade_time": "2026-07-28T06:25:00",
            "applied_action": "TARGET",
            "stop_price": None,
            "take_price": None,
            "entry_price": None,
        },
    ]
    levels = [
        {
            "as_of": "2026-07-28T06:25:00",
            "stop_price": 885.37,
            "take_price": 882.64,
            "entry_price": 884.38,
        }
    ]
    out = apply_entry_stop_fallback(items, levels)
    assert out[0]["stop_price"] is None
    assert out[0]["take_price"] is None
    assert out[1]["stop_price"] == 885.37
    assert out[1]["take_price"] == 882.64
