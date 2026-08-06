"""Phase 5 — cost model, attribution, walk-forward, stress, async jobs."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from ignitequant.analytics import (
    TradeFillRecord,
    attribute_fills,
    default_cost_model,
    plan_walk_forward,
    run_cost_stress,
    stress_summary,
)
from dashboard.jobs import BacktestJobQueue


def test_cost_model_hash_stable() -> None:
    a = default_cost_model()
    b = default_cost_model()
    assert a.config_hash() == b.config_hash()
    assert a.scaled(fee_mult=2).open_fee_per_lot == a.open_fee_per_lot * 2


def test_stamp_fills_with_intent_log() -> None:
    from ignitequant.analytics import TradeFillRecord, stamp_fills_with_intent_log

    fills = [
        TradeFillRecord("1", "SHFE.rb", "BUY", "OPEN", 3200.0, 1),
        TradeFillRecord("2", "SHFE.rb", "SELL", "CLOSE", 3210.0, 1),
    ]
    intents = [
        {"applied_action": "TARGET", "legacy_signal": 2, "net_before": 0, "desired": 1},
        {"applied_action": "STOP_LOSS", "legacy_signal": 1, "net_before": 1, "desired": 0},
    ]
    out = stamp_fills_with_intent_log(fills, intents)
    assert out[0].applied_action == "TARGET"
    assert out[0].legacy_signal == 2
    assert out[1].applied_action == "STOP_LOSS"
    assert out[1].legacy_signal == 1


def test_fills_from_tq_trade_log_list_string_enums() -> None:
    """TqSim.trade_log uses list + BUY/OPEN strings (not int-keyed dict)."""
    from ignitequant.analytics import fills_from_tq_trade_log

    trade_log = {
        "2025-05-12": {
            "trades": [
                {
                    "trade_id": "T1",
                    "exchange_id": "SHFE",
                    "instrument_id": "rb2505",
                    "direction": "BUY",
                    "offset": "OPEN",
                    "price": 3200.0,
                    "volume": 1,
                    "commission": 3.0,
                    "trade_date_time": 1_746_998_400_000_000_000,
                },
                {
                    "trade_id": "T2",
                    "exchange_id": "SHFE",
                    "instrument_id": "rb2505",
                    "direction": "SELL",
                    "offset": "CLOSE",
                    "price": 3210.0,
                    "volume": 1,
                    "commission": 3.0,
                },
            ],
            "account": {"balance": 1_000_000},
        }
    }
    fills = fills_from_tq_trade_log(trade_log, default_symbol="SHFE.rb2505")
    assert len(fills) == 2
    assert fills[0].side == "BUY"
    assert fills[0].offset == "OPEN"
    assert fills[0].symbol == "SHFE.rb2505"
    assert fills[0].qty == 1
    assert fills[1].side == "SELL"
    assert fills[1].offset == "CLOSE"


def test_fills_from_tq_trade_log_legacy_dict_ints() -> None:
    from ignitequant.analytics import fills_from_tq_trade_log

    trade_log = {
        "2025-01-02": {
            "trades": {
                "a": {
                    "direction": 0,
                    "offset": 1,
                    "price": 800.0,
                    "volume": 1,
                    "commission": 1.0,
                    "symbol": "SHFE.au2608",
                },
                "b": {
                    "direction": -1,
                    "offset": 2,
                    "price": 810.0,
                    "volume": 1,
                    "commission": 1.0,
                    "symbol": "SHFE.au2608",
                },
            }
        }
    }
    fills = fills_from_tq_trade_log(trade_log)
    assert len(fills) == 2
    assert fills[0].side == "BUY" and fills[0].offset == "OPEN"
    assert fills[1].side == "SELL" and fills[1].offset == "CLOSE"


def test_attribute_long_roundtrip() -> None:
    fills = [
        TradeFillRecord("1", "SHFE.au2608", "BUY", "OPEN", 800.0, 1, fee=0),
        TradeFillRecord("2", "SHFE.au2608", "SELL", "CLOSE", 810.0, 1, fee=0),
    ]
    cost = default_cost_model()
    report = attribute_fills(fills, cost=cost)
    # 10 yuan/g * 1000 multiplier = 10000 gross; 2 * 10 fee
    assert report.gross_pnl == 10.0 * 1000
    assert report.fees == cost.open_fee_per_lot + cost.close_fee_per_lot
    assert report.long_pnl == 10_000
    assert report.trade_count == 2
    assert report.net_pnl < report.gross_pnl  # fees + model slip


def test_walk_forward_windows() -> None:
    windows = plan_walk_forward(
        dt.date(2025, 1, 1),
        dt.date(2025, 6, 30),
        train_days=40,
        test_days=20,
    )
    assert len(windows) >= 2
    assert windows[0].train_start == dt.date(2025, 1, 1)
    assert windows[0].test_end >= windows[0].test_start
    for w in windows:
        assert w.test_end <= dt.date(2025, 6, 30)


def test_cost_stress_survives_or_not() -> None:
    fills = [
        TradeFillRecord("1", "SHFE.au", "BUY", "OPEN", 800.0, 1),
        TradeFillRecord("2", "SHFE.au", "SELL", "CLOSE", 800.05, 1),
    ]
    rows = run_cost_stress(fills)
    summary = stress_summary(rows)
    assert summary["scenarios"] == 5
    assert summary["worst_net"] <= summary["best_net"]


def test_job_queue_idempotent(tmp_path: Path) -> None:
    results: list[str] = []

    def handler(req, progress):
        progress(0.5, "half")
        results.append(req["symbol_ids"][0])
        return {"run_ids": ["run-abc"]}

    q = BacktestJobQueue(tmp_path / "jobs.sqlite", max_workers=1, handler=handler)
    payload = {
        "strategy_id": "falcon_v2",
        "symbol_ids": ["au"],
        "start": "2025-01-01",
        "end": "2025-02-01",
        "init_balance": 1_000_000,
    }
    j1 = q.enqueue(payload)
    j2 = q.enqueue(payload)
    assert j1["job_id"] == j2["job_id"]
    assert j1["idempotency_key"] == j2["idempotency_key"]

    # wait for completion
    import time

    for _ in range(50):
        job = q.get(j1["job_id"])
        assert job is not None
        if job["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(0.05)
    job = q.get(j1["job_id"])
    assert job is not None
    assert job["status"] == "SUCCEEDED"
    assert job["result_run_ids"] == ["run-abc"]
    assert results == ["au"]  # handler ran once
