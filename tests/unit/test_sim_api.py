# -*- coding: utf-8 -*-
"""Sim Cockpit read-only API tests (temporary SQLite fixture)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ignitequant.persistence.schema import DDL


@pytest.fixture()
def runtime_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    db_path = runtime / "falcon_au_sim.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(DDL)
    monkeypatch.setenv("SIM_DATA_SOURCE", "local")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO strategy_state(
            instance_id, strategy_id, account_id, symbol, runtime_state,
            payload_json, state_version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "falcon_au_sim",
            "falcon_v2",
            "local",
            "SHFE.au2608",
            "READY",
            json.dumps(
                {
                    "current_target": 1,
                    "confirmed_net": 1,
                    "cooldown_left": 0,
                    "config_hash": "abc",
                    "entry_price": 870.0,
                    "stop_price": 860.0,
                    "take_price": 900.0,
                }
            ),
            1,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO account_snapshot_event(
            instance_id, account_id, equity, available, margin, margin_ratio,
            as_of, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("falcon_au_sim", "local", 1_001_200.0, 960_000.0, 40_000.0, 0.04, now, "{}", now),
    )
    conn.execute(
        """
        INSERT INTO position_snapshot_event(
            instance_id, symbol, net_position, source, as_of, payload_json, created_at,
            avg_entry_price, unrealized_pnl, margin
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("falcon_au_sim", "SHFE.au2608", 1, "broker", now, "{}", now, 870.0, 10_000.0, 40_000.0),
    )
    payload = {
        "factors": {
            "regime": "TREND_UP",
            "quality": "READY",
            "values": {"atr": 0.5, "adx": 28.0, "close": 880.0},
            "reason_codes": [],
        },
        "signal": {"legacy_signal": 1, "reason_codes": ["SCORE"]},
        "target": {"desired_position": 1},
        "legacy_score_parts": [0, 0, 1, 0],
    }
    conn.execute(
        """
        INSERT INTO decision_event(
            instance_id, decision_id, bar_id, symbol, applied_action,
            target_before, target_after, legacy_signal, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "falcon_au_sim",
            "bar-1",
            "bar-1",
            "SHFE.au2608",
            "TARGET",
            0,
            1,
            1,
            json.dumps(payload),
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO risk_decision_event(
            instance_id, risk_decision_id, decision_id, action,
            requested_position, approved_position, rule_hits_json, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "falcon_au_sim",
            "risk-1",
            "bar-1",
            "PASS",
            1,
            1,
            "[]",
            "{}",
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO order_intent_event(
            instance_id, intent_id, decision_id, symbol, current_position,
            desired_position, urgency, idempotency_key, status,
            reason_codes_json, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "falcon_au_sim",
            "intent-1",
            "bar-1",
            "SHFE.au2608",
            0,
            1,
            "NORMAL",
            "key-1",
            "FILLED",
            "[]",
            "{}",
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO trade_fill_event(
            instance_id, fill_id, intent_id, symbol, price, qty, fee, side,
            trade_time, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "falcon_au_sim",
            "fill-1",
            "intent-1",
            "SHFE.au2608",
            880.0,
            1,
            10.0,
            "BUY",
            now,
            "{}",
            now,
        ),
    )
    conn.commit()
    conn.close()

    import dashboard.sim_api as sim_api

    monkeypatch.setattr(sim_api, "RUNTIME_DIR", runtime)
    return db_path


@pytest.fixture()
def client(runtime_db: Path) -> TestClient:
    from dashboard.api import app

    return TestClient(app)


def test_sim_catalog(client: TestClient) -> None:
    res = client.get("/api/sim/catalog")
    assert res.status_code == 200
    body = res.json()
    assert any(f["id"] == "tq" and f["enabled"] for f in body["frameworks"])
    assert any(f["id"] == "mt5" and not f["enabled"] for f in body["frameworks"])
    assert any(s["id"] == "falcon_v2" for s in body["strategies"])
    au = next(s for s in body["symbols"] if s["id"] == "au")
    assert au["overseas_pair"]["display_symbol"] == "XAUUSD"
    assert any(l["instance_id"] == "falcon_au_sim" for l in body["launchers"])


def test_catch_up_bars_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from ignitequant.engine.catch_up import CatchUpResult

    def _fake(*args, **kwargs):
        return CatchUpResult(
            missed=2,
            recorded=2,
            message="补跑完成：漏 2 根",
            source="test",
            final_target=0,
            confirmed_net=0,
        )

    monkeypatch.setattr(
        "ignitequant.engine.catch_up.catch_up_session_db",
        _fake,
    )
    res = client.post("/api/sim/sessions/falcon_au_sim/catch-up-bars")
    assert res.status_code == 200
    body = res.json()
    assert body["missed"] == 2
    assert body["recorded"] == 2
    assert "instance_id" in body


def test_sim_sessions_and_summary(client: TestClient) -> None:
    res = client.get("/api/sim/sessions")
    assert res.status_code == 200
    sessions = res.json()["sessions"]
    assert any(s["instance_id"] == "falcon_au_sim" for s in sessions)

    summary = client.get("/api/sim/sessions/falcon_au_sim/summary")
    assert summary.status_code == 200
    body = summary.json()
    assert body["symbol"] == "SHFE.au2608"
    assert body["account"]["equity"] == 1_001_200.0
    assert body["position"]["net_position"] == 1
    assert body["status"] in {"RUNNING", "STALE", "IDLE"}
    assert body["status_label"] in {"运行中", "数据滞后", "未运行"}
    assert body["framework_label"] == "天勤模拟盘"
    assert body["last_price"] == pytest.approx(880.0)
    assert body["last_price_source"] == "decision_close"
    assert len(body["open_positions"]) == 1
    op = body["open_positions"][0]
    assert op["symbol"] == "SHFE.au2608"
    assert op["side"] == "LONG"
    assert op["lots"] == 1
    assert op["average_entry_price"] == pytest.approx(870.0)
    assert op["unrealized_pnl"] == pytest.approx(10_000.0)
    # ref margin: 880 * 1000 * 1 * 16% (not the seeded broker margin 40k)
    assert op["margin"] == pytest.approx(140_800.0)
    assert op["margin_rate_pct"] == pytest.approx(16.0)
    assert op["stop_price"] == pytest.approx(860.0)
    assert body["account"]["margin"] == pytest.approx(140_800.0)
    assert body["account"]["margin_ratio"] == pytest.approx(140_800.0 / 1_001_200.0)
    assert body["account"]["margin_source"] == "ref_product_margin"


def test_open_positions_view_unit() -> None:
    from dashboard.open_positions import open_positions_view

    assert open_positions_view(position=None, account=None, state_payload={}, last_price=1) == []
    flat = open_positions_view(
        position={"symbol": "SHFE.au2608", "net_position": 0},
        account=None,
        state_payload={},
        last_price=880,
    )
    assert flat == []
    rows = open_positions_view(
        position={
            "symbol": "SHFE.au2610",
            "net_position": -2,
            "average_entry_price": 900.0,
            "unrealized_pnl": 0,
            "margin": 0,
        },
        account={"margin": 80_000.0},
        state_payload={"entry_price": 901.0},
        last_price=890.0,
    )
    assert len(rows) == 1
    assert rows[0]["side"] == "SHORT"
    assert rows[0]["lots"] == 2
    # (890-900)*2*1000*(-1 for short? wait direction=-1 for short)
    # direction = -1 when net < 0
    # upnl = (890-900)*2*1000*(-1) = (-10)*2*1000*(-1) = 20000
    assert rows[0]["unrealized_pnl"] == pytest.approx(20_000.0)
    # SHFE.au → 16%: 890 * 1000 * 2 * 0.16
    assert rows[0]["margin"] == pytest.approx(284_800.0)
    assert rows[0]["margin_rate_pct"] == pytest.approx(16.0)


def test_sim_metrics_and_decisions(client: TestClient) -> None:
    metrics = client.get("/api/sim/sessions/falcon_au_sim/metrics").json()
    assert metrics["equity"] == 1_001_200.0
    assert metrics["pnl"] == pytest.approx(1_200.0)
    assert metrics["fill_count"] == 1

    decisions = client.get("/api/sim/sessions/falcon_au_sim/decisions?limit=10").json()
    assert decisions["count"] == 1
    d0 = decisions["decisions"][0]
    assert d0["applied_action"] == "TARGET"
    assert d0["regime"] == "TREND_UP"
    assert d0["risk"]["action"] == "PASS"

    intents = client.get("/api/sim/sessions/falcon_au_sim/intents").json()
    assert intents["count"] == 1
    fills = client.get("/api/sim/sessions/falcon_au_sim/fills").json()
    assert fills["count"] == 1
    assert fills["fills"][0]["side"] == "BUY"


def test_sim_replay(client: TestClient) -> None:
    now = datetime.now(timezone.utc).isoformat()
    res = client.get("/api/sim/sessions/falcon_au_sim/replay", params={"at": now})
    assert res.status_code == 200
    body = res.json()
    assert body["mode"] == "replay"
    assert body["decision"]["legacy_signal"] == 1
    assert body["metrics_snapshot"]["fill_count"] == 1


def test_sim_missing_session(client: TestClient) -> None:
    res = client.get("/api/sim/sessions/does_not_exist/summary")
    assert res.status_code == 404


def test_sim_sessions_skips_job_db(
    runtime_db: Path, client: TestClient, tmp_path: Path
) -> None:
    """backtest_jobs.sqlite must not 500 /api/sim/sessions."""
    import dashboard.sim_api as sim_api

    jobs = sim_api.RUNTIME_DIR / "backtest_jobs.sqlite"
    conn = sqlite3.connect(str(jobs))
    conn.execute("CREATE TABLE backtest_job (id TEXT PRIMARY KEY)")
    conn.commit()
    conn.close()

    res = client.get("/api/sim/sessions")
    assert res.status_code == 200
    ids = [s["instance_id"] for s in res.json()["sessions"]]
    assert "falcon_au_sim" in ids
    assert "backtest_jobs" not in ids


def test_signal_symbol_for_trade_maps_contracts() -> None:
    from dashboard.sim_api import _signal_symbol_for_trade

    assert _signal_symbol_for_trade("SHFE.au2608") == "KQ.m@SHFE.au"
    assert _signal_symbol_for_trade("KQ.m@SHFE.au") == "KQ.m@SHFE.au"
    assert _signal_symbol_for_trade("au") == "KQ.m@SHFE.au"
    assert _signal_symbol_for_trade("CZCE.FG509") == "KQ.m@CZCE.FG"


def test_sim_market_and_overseas_endpoints(client: TestClient) -> None:
    market = client.get("/api/sim/market/bars", params={"symbol_id": "au", "limit": 50})
    assert market.status_code == 200
    body = market.json()
    assert body["symbol_id"] == "au"
    assert body["signal_symbol"] == "KQ.m@SHFE.au"
    assert "bars" in body
    # Cockpit no longer serves market_cache; empty until sim writes live snapshot.
    assert body.get("source") == "tqsdk_sim_live"

    overseas = client.get("/api/sim/overseas/bars", params={"symbol_id": "rb"})
    assert overseas.status_code == 200
    assert overseas.json()["supported"] is False

    au_pair = client.get("/api/sim/overseas/bars", params={"symbol_id": "au"})
    assert au_pair.status_code == 200
    assert au_pair.json()["supported"] is True
    assert au_pair.json()["pair"]["display_symbol"] == "XAUUSD"


def test_sim_live_klines_snapshot(client: TestClient, runtime_db: Path) -> None:
    import dashboard.sim_api as sim_api
    from ignitequant.market.sim_klines import dump_tq_klines_snapshot
    import pandas as pd

    # Fake Tq kline serial: 3 completed + 1 forming stub
    ns0 = 1_784_875_500_000_000_000
    rows = []
    for i in range(4):
        px = 880.0 + i * 0.1
        rows.append(
            {
                "datetime": ns0 + i * 300_000_000_000,
                "open": px,
                "high": px + 0.2,
                "low": px - 0.2,
                "close": px + 0.05,
                "volume": 100 + i,
                "open_oi": 1,
                "close_oi": 1,
            }
        )
    klines = pd.DataFrame(rows)
    dump_tq_klines_snapshot(
        "falcon_au_sim",
        klines,
        signal_symbol="KQ.m@SHFE.au",
        trade_symbol="SHFE.au2608",
        runtime_dir=sim_api.RUNTIME_DIR,
    )

    market = client.get("/api/sim/market/bars", params={"symbol_id": "au"}).json()
    assert len(market["bars"]) == 4  # includes forming stub for cockpit
    assert market["last_price"] == pytest.approx(880.35)
    assert market["source"] == "tqsdk_sim_live"
    assert market["trade_symbol"] == "SHFE.au2608"

    session = client.get("/api/sim/sessions/falcon_au_sim/bars").json()
    assert len(session["bars"]) == 4
    assert session["source"] == "tqsdk_sim_live"
    # Prefer decision/sim live quote (fixture close=880) over snapshot tip.
    assert session["last_price"] == pytest.approx(880.0)


def test_sim_start_unknown_session(client: TestClient) -> None:
    res = client.post("/api/sim/sessions/unknown_sim/start")
    assert res.status_code == 400


def test_sim_backfills_fills_from_submitted_intents(
    client: TestClient, runtime_db: Path
) -> None:
    """Submitted intents that clearly reached target should show as fills."""
    conn = sqlite3.connect(str(runtime_db))
    now = datetime.now(timezone.utc).isoformat()
    # Wipe fixture fill; leave a SUBMITTED open→flat chain.
    conn.execute("DELETE FROM trade_fill_event")
    conn.execute("DELETE FROM order_intent_event")
    for bar_id, close in (("bar-a", 880.0), ("bar-b", 881.0)):
        conn.execute(
            """
            INSERT INTO decision_event(
                instance_id, decision_id, bar_id, symbol, applied_action,
                target_before, target_after, legacy_signal, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "falcon_au_sim",
                bar_id,
                bar_id,
                "SHFE.au2608",
                "HOLD",
                0,
                0,
                0,
                json.dumps({"factors": {"values": {"close": close}}}),
                now,
            ),
        )
    conn.execute(
        """
        INSERT INTO order_intent_event(
            instance_id, intent_id, decision_id, symbol, current_position,
            desired_position, urgency, idempotency_key, status,
            reason_codes_json, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "falcon_au_sim",
            "intent-a",
            "bar-a",
            "SHFE.au2608",
            0,
            -1,
            "NORMAL",
            "key-a",
            "SUBMITTED",
            "[]",
            "{}",
            now,
        ),
    )
    later = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """
        INSERT INTO order_intent_event(
            instance_id, intent_id, decision_id, symbol, current_position,
            desired_position, urgency, idempotency_key, status,
            reason_codes_json, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "falcon_au_sim",
            "intent-b",
            "bar-b",
            "SHFE.au2608",
            -1,
            0,
            "HIGH",
            "key-b",
            "SUBMITTED",
            "[]",
            "{}",
            later,
        ),
    )
    conn.commit()
    # Latest position is flat → last intent (-1→0) is also filled.
    conn.execute("DELETE FROM position_snapshot_event")
    conn.execute(
        """
        INSERT INTO position_snapshot_event(
            instance_id, symbol, net_position, source, as_of, payload_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("falcon_au_sim", "SHFE.au2608", 0, "broker", later, "{}", later),
    )
    conn.commit()
    conn.close()

    repair = client.post("/api/sim/sessions/falcon_au_sim/repair-fills")
    assert repair.status_code == 200
    assert repair.json()["repaired"] >= 2

    fills = client.get("/api/sim/sessions/falcon_au_sim/fills").json()
    assert fills["count"] >= 2
    intents = client.get("/api/sim/sessions/falcon_au_sim/intents").json()
    statuses = {i["intent_id"]: i["status"] for i in intents["intents"]}
    assert statuses["intent-a"] == "FILLED"
    assert statuses["intent-b"] == "FILLED"
    from ignitequant.persistence.repair import repair_missing_fills

    assert repair_missing_fills(runtime_db, "falcon_au_sim") == 0


def test_sim_rejects_path_traversal_instance_id(client: TestClient) -> None:
    res = client.get("/api/sim/sessions/../../tmp/evil/summary")
    assert res.status_code in {400, 404}