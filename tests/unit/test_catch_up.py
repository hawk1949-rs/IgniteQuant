"""Catch-up missed completed bars into decision chain."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ignitequant.config import default_decision_config
from ignitequant.engine.catch_up import (
    catch_up_missed_bars,
    catch_up_session_db,
    klines_snapshot_to_frame,
    parse_bar_id_ns,
)
from ignitequant.engine.decision_pipeline import FalconDecisionPipeline
from ignitequant.persistence.schema import DDL
from ignitequant.persistence.session import PersistenceSession


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bars(n: int = 220, start_ns: int = 1_700_000_000_000_000_000) -> pd.DataFrame:
    rows = []
    px = 800.0
    for i in range(n):
        ns = start_ns + i * 300 * 1_000_000_000
        o = px
        c = px + (0.2 if i % 7 else -0.1)
        h = max(o, c) + 0.3
        l = min(o, c) - 0.3
        rows.append(
            {
                "datetime": ns,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": 100 + i,
                "open_oi": 1000,
                "close_oi": 1000,
            }
        )
        px = c
    return pd.DataFrame(rows)


def test_parse_bar_id_ns() -> None:
    assert parse_bar_id_ns("KQ.m@SHFE.au:1700000000000000000") == 1_700_000_000_000_000_000
    assert parse_bar_id_ns("shutdown") is None
    assert parse_bar_id_ns(None) is None


def test_catch_up_records_missed_decisions(tmp_path: Path) -> None:
    db = tmp_path / "falcon_au_sim.sqlite"
    conn_setup = __import__("sqlite3").connect(str(db))
    conn_setup.executescript(DDL)
    now = _now()
    bars = _bars(220)
    # Pretend last decided bar is index 200
    last_ns = int(bars.iloc[200]["datetime"])
    last_bar_id = f"KQ.m@SHFE.au:{last_ns}"
    conn_setup.execute(
        """
        INSERT INTO strategy_state(
            instance_id, strategy_id, account_id, symbol, runtime_state,
            payload_json, state_version, updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "falcon_au_sim",
            "falcon_v2",
            "local",
            "SHFE.au2610",
            "READY",
            json.dumps(
                {
                    "current_target": 0,
                    "confirmed_net": 0,
                    "last_bar_id": last_bar_id,
                    "cooldown_left": 0,
                }
            ),
            1,
            now,
        ),
    )
    conn_setup.commit()
    conn_setup.close()

    session = PersistenceSession.open(db, instance_id="falcon_au_sim")
    pipeline = FalconDecisionPipeline(default_decision_config())
    pipeline.restore_runtime(current_target=0)
    out = catch_up_missed_bars(
        session=session,
        pipeline=pipeline,
        bars=bars,
        last_bar_id=last_bar_id,
        confirmed_net=0,
        source="test",
    )
    session.close()
    assert out.missed == 19  # 201..219
    assert out.recorded == out.missed
    assert out.last_bar_id_after is not None
    assert parse_bar_id_ns(out.last_bar_id_after) == int(bars.iloc[-1]["datetime"])

    # Second run is idempotent
    session2 = PersistenceSession.open(db, instance_id="falcon_au_sim")
    state = session2.repo.load_strategy_state("falcon_au_sim")
    assert state is not None
    pipeline2 = FalconDecisionPipeline(default_decision_config())
    pipeline2.restore_runtime(current_target=int(state.payload.get("current_target", 0)))
    out2 = catch_up_missed_bars(
        session=session2,
        pipeline=pipeline2,
        bars=bars,
        last_bar_id=state.payload.get("last_bar_id"),
        confirmed_net=0,
        source="test",
    )
    session2.close()
    assert out2.missed == 0
    assert out2.recorded == 0


def test_klines_snapshot_to_frame() -> None:
    snap = {
        "bars": [
            {
                "time": 1700000000,
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 10,
            }
        ]
    }
    df = klines_snapshot_to_frame(snap)
    assert len(df) == 1
    assert int(df.iloc[0]["datetime"]) == 1_700_000_000_000_000_000


def test_catch_up_session_db_no_bars(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "falcon_au_sim.sqlite"
    conn = __import__("sqlite3").connect(str(db))
    conn.executescript(DDL)
    conn.execute(
        """
        INSERT INTO strategy_state(
            instance_id, strategy_id, account_id, symbol, runtime_state,
            payload_json, state_version, updated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            "falcon_au_sim",
            "falcon_v2",
            "local",
            "SHFE.au2610",
            "READY",
            json.dumps({"last_bar_id": "KQ.m@SHFE.au:1", "current_target": 0, "confirmed_net": 0}),
            1,
            _now(),
        ),
    )
    conn.commit()
    conn.close()

    import ignitequant.engine.catch_up as cu

    monkeypatch.setattr(
        cu,
        "load_catch_up_bars",
        lambda **kwargs: (pd.DataFrame(), "none"),
    )
    out = catch_up_session_db(db, "falcon_au_sim", root=tmp_path, runtime_dir=tmp_path)
    assert "无 K 线" in out.message
