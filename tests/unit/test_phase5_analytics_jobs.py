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
