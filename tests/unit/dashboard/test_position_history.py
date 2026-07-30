"""Closed round-trip derivation from fills."""

from __future__ import annotations

import pytest

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
    assert hist.get("round_count") == 1
    assert hist["round_count"] == 1
    # open+close (+ optional 结转 when account equity default != round pnl)
    assert len(hist["positions"]) >= 2
    opens = [p for p in hist["positions"] if p.get("action") == "OPEN"]
    closes = [p for p in hist["positions"] if p.get("action") == "CLOSE"]
    assert len(opens) == 1
    assert opens[0]["realized_pnl"] == 0.0
    assert any(abs(float(p["realized_pnl"]) - 10_000.0) < 1e-6 for p in closes)
    assert sum(float(p["realized_pnl"]) for p in closes) == pytest.approx(
        float(hist.get("account_realized_pnl") or 0.0)
    )
    assert metrics["trade_count"] == hist["round_count"]
    assert metrics["wins"] == 1
    assert hist["count"] == len(hist["positions"])


def test_broker_ignores_startup_boot_flatten_phantom() -> None:
    from dashboard.position_history import iter_closed_rounds_from_broker

    positions = [
        {"symbol": "SHFE.au2610", "net_position": 0, "as_of": "t0", "source": "broker_startup"},
        {"symbol": "SHFE.au2610", "net_position": 1, "as_of": "t1", "source": "broker_startup"},
        {
            "symbol": "SHFE.au2610",
            "net_position": 0,
            "as_of": "t1",
            "source": "broker_boot_flatten",
        },
        {
            "symbol": "SHFE.au2610",
            "net_position": 1,
            "as_of": "t2",
            "source": "broker_fill",
            "avg_entry_price": 900.0,
        },
        {"symbol": "SHFE.au2610", "net_position": 0, "as_of": "t3", "source": "broker_fill"},
    ]
    fills = [
        {
            "symbol": "SHFE.au2610",
            "side": "BUY",
            "qty": 1,
            "price": 900.0,
            "fee": 0,
            "trade_time": "t2",
            "payload": {},
        },
        {
            "symbol": "SHFE.au2610",
            "side": "SELL",
            "qty": 1,
            "price": 901.0,
            "fee": 0,
            "trade_time": "t3",
            "payload": {},
        },
    ]
    rounds = iter_closed_rounds_from_broker(positions, fills=fills)
    assert len(rounds) == 1
    assert rounds[0]["opened_at"] == "t2"
    assert rounds[0]["realized_pnl"] == pytest.approx(1000.0)


def test_unattributed_close_leg_reconciles_account() -> None:
    from dashboard.position_history import make_unattributed_close_leg

    leg = make_unattributed_close_leg(
        account_realized=160.0, rounds_price_pnl=-4180.0, as_of="now"
    )
    assert leg is not None
    assert leg["action_label"] == "结转"
    assert leg["realized_pnl"] == pytest.approx(4340.0)
    assert make_unattributed_close_leg(account_realized=100.0, rounds_price_pnl=100.0) is None


def test_broker_position_rounds_use_price_pnl() -> None:
    from dashboard.position_history import (
        closed_rounds_summary,
        iter_closed_rounds_from_broker,
    )

    positions = [
        {"symbol": "SHFE.au2610", "net_position": 0, "as_of": "t0", "source": "broker_startup"},
        {
            "symbol": "SHFE.au2610",
            "net_position": 1,
            "as_of": "t1",
            "source": "broker_fill",
            "avg_entry_price": 900.0,
        },
        {"symbol": "SHFE.au2610", "net_position": 0, "as_of": "t2", "source": "broker_fill"},
    ]
    accounts = [
        {"equity": 1_000_000.0, "as_of": "t0"},
        {"equity": 1_001_000.0, "as_of": "t1"},
        {"equity": 1_002_500.0, "as_of": "t2"},
    ]
    fills = [
        {
            "symbol": "SHFE.au2610",
            "side": "BUY",
            "qty": 1,
            "price": 900.0,
            "fee": 0,
            "trade_time": "t1",
            "payload": {},
        },
        {
            "symbol": "SHFE.au2610",
            "side": "SELL",
            "qty": 1,
            "price": 901.5,
            "fee": 0,
            "trade_time": "t2",
            "payload": {},
        },
    ]
    rounds = iter_closed_rounds_from_broker(
        positions, account_snapshots=accounts, fills=fills
    )
    assert len(rounds) == 1
    assert rounds[0]["side"] == "LONG"
    assert rounds[0]["lots"] == 1
    assert rounds[0]["entry_price"] == 900.0
    assert rounds[0]["exit_price"] == 901.5
    # Equity moved +1500 during the hold window; price PnL matches here.
    assert rounds[0]["realized_pnl"] == pytest.approx(1500.0)
    assert rounds[0]["source"] == "broker_position"
    assert closed_rounds_summary(rounds)["wins"] == 1


def test_rounds_expand_to_open_close_legs() -> None:
    from dashboard.position_history import rounds_to_open_close_legs

    rounds = [
        {
            "round_id": "r1",
            "symbol": "SHFE.au2610",
            "side": "LONG",
            "side_label": "多",
            "lots": 1,
            "entry_price": 900.0,
            "exit_price": 910.0,
            "opened_at": "t1",
            "closed_at": "t2",
            "realized_pnl": 10_000.0,
            "fees": 20.0,
        }
    ]
    legs = rounds_to_open_close_legs(rounds, newest_first=True)
    assert len(legs) == 2
    assert legs[0]["action"] == "CLOSE"
    assert legs[0]["realized_pnl"] == 10_000.0
    assert legs[0]["price"] == 910.0
    assert legs[1]["action"] == "OPEN"
    assert legs[1]["realized_pnl"] == 0.0
    assert legs[1]["price"] == 900.0


def test_prepare_fills_drops_backfill_and_seeds_prior_inventory() -> None:
    from dashboard.position_history import (
        account_realized_pnl,
        closed_rounds_summary,
        iter_closed_rounds,
        prepare_fills_for_rounds,
    )

    fills = [
        {
            "symbol": "SHFE.au2610",
            "side": "SELL",
            "qty": 1,
            "price": 900.0,
            "fee": 0,
            "trade_time": "t0",
            "payload": {"source": "intent_chain_backfill"},
        },
        {
            "symbol": "SHFE.au2610",
            "side": "SELL",
            "qty": 1,
            "price": 895.7,
            "fee": 0,
            "trade_time": "t1",
            "payload": {},
        },
        {
            "symbol": "SHFE.au2610",
            "side": "BUY",
            "qty": 1,
            "price": 895.5,
            "fee": 0,
            "trade_time": "t2",
            "payload": {},
        },
    ]
    prepared = prepare_fills_for_rounds(fills, prior_net=1, prior_avg_price=895.7)
    assert prepared[0]["payload"]["source"] == "broker_inventory_seed"
    assert all(
        (f.get("payload") or {}).get("source") != "intent_chain_backfill" for f in prepared
    )
    rounds = iter_closed_rounds(prepared, default_multiplier=1000.0)
    # After seed BUY@895.7 + SELL@895.7 → flat 0; then BUY@895.5 still open → 1 closed round
    assert len(rounds) == 1
    assert rounds[0]["realized_pnl"] == 0.0
    assert account_realized_pnl(equity=999_860, init_balance=1_000_000, unrealized=0) == -140.0
    assert closed_rounds_summary(rounds)["realized_pnl_proxy"] == 0.0
