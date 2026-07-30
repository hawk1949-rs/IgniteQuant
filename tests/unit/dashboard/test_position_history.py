"""Closed round-trip derivation from fills."""

from __future__ import annotations

from dashboard.position_history import closed_rounds_summary, iter_closed_rounds


def test_buy_sell_emits_one_round() -> None:
    fills = [
        {
            "symbol": "SHFE.au2610",
            "side": "BUY",
            "qty": 1,
            "price": 600.0,
            "fee": 10.0,
            "trade_time": "2026-07-01T10:00:00+08:00",
        },
        {
            "symbol": "SHFE.au2610",
            "side": "SELL",
            "qty": 1,
            "price": 610.0,
            "fee": 10.0,
            "trade_time": "2026-07-01T11:00:00+08:00",
        },
    ]
    rounds = iter_closed_rounds(fills, default_multiplier=1000.0)
    assert len(rounds) == 1
    r = rounds[0]
    assert r["side"] == "LONG"
    assert r["lots"] == 1
    assert r["entry_price"] == 600.0
    assert r["exit_price"] == 610.0
    # (610-600)*1*1000 - 20 fees
    assert abs(r["realized_pnl"] - 9980.0) < 1e-6
    assert abs(r["fees"] - 20.0) < 1e-6
    summary = closed_rounds_summary(rounds)
    assert summary["trade_count"] == 1
    assert summary["wins"] == 1


def test_open_position_not_in_history() -> None:
    fills = [
        {
            "symbol": "SHFE.au2610",
            "side": "BUY",
            "qty": 2,
            "price": 600.0,
            "fee": 0,
            "trade_time": "2026-07-01T10:00:00+08:00",
        },
    ]
    assert iter_closed_rounds(fills, default_multiplier=1000.0) == []


def test_partial_close_waits_until_flat() -> None:
    fills = [
        {
            "symbol": "SHFE.au2610",
            "side": "BUY",
            "qty": 2,
            "price": 600.0,
            "fee": 0,
            "trade_time": "t1",
        },
        {
            "symbol": "SHFE.au2610",
            "side": "SELL",
            "qty": 1,
            "price": 610.0,
            "fee": 0,
            "trade_time": "t2",
        },
        {
            "symbol": "SHFE.au2610",
            "side": "SELL",
            "qty": 1,
            "price": 620.0,
            "fee": 0,
            "trade_time": "t3",
        },
    ]
    rounds = iter_closed_rounds(fills, default_multiplier=1000.0)
    assert len(rounds) == 1
    assert rounds[0]["lots"] == 2
    # exit VWAP = (610+620)/2 = 615; pnl = (615-600)*2*1000 = 30000
    assert abs(rounds[0]["exit_price"] - 615.0) < 1e-6
    assert abs(rounds[0]["realized_pnl"] - 30_000.0) < 1e-6


def test_short_round() -> None:
    fills = [
        {"symbol": "SHFE.au2610", "side": "SELL", "qty": 1, "price": 610.0, "fee": 0, "trade_time": "a"},
        {"symbol": "SHFE.au2610", "side": "BUY", "qty": 1, "price": 600.0, "fee": 0, "trade_time": "b"},
    ]
    rounds = iter_closed_rounds(fills, default_multiplier=1000.0)
    assert len(rounds) == 1
    assert rounds[0]["side"] == "SHORT"
    assert abs(rounds[0]["realized_pnl"] - 10_000.0) < 1e-6


def test_metrics_trade_count_matches_history_len(tmp_path) -> None:
    import sqlite3
    from datetime import datetime, timezone

    from dashboard import sim_api
    from ignitequant.persistence.schema import DDL

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    db_path = runtime / "falcon_au_sim.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    now = datetime.now(timezone.utc).isoformat()
    for i, (side, price) in enumerate([("BUY", 600.0), ("SELL", 610.0)], start=1):
        conn.execute(
            """
            INSERT INTO trade_fill_event(
                instance_id, fill_id, intent_id, symbol, price, qty, fee, side,
                trade_time, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "falcon_au_sim",
                f"f{i}",
                f"i{i}",
                "SHFE.au2610",
                price,
                1,
                0.0,
                side,
                now,
                "{}",
                now,
            ),
        )
    conn.commit()
    hist = sim_api._position_history_from_conn(conn, "falcon_au_sim", limit=50)
    metrics = sim_api._compute_metrics(conn, "falcon_au_sim")
    conn.close()
    assert hist["count"] == 1
    assert len(hist["positions"]) == 1
    assert metrics["trade_count"] == hist["count"]
    assert metrics["wins"] == 1
