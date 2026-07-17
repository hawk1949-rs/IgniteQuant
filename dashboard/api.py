# -*- coding: utf-8 -*-
"""策略看板 HTTP API（供 Magic UI / React 前端调用）。

启动：
    uvicorn dashboard.api:app --reload --port 8787
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.catalog import STRATEGIES, SYMBOLS
from dashboard.runners import run_falcon_v2, run_vwap_stub
from dashboard.scoring import score_metrics
from dashboard.store import delete_run, get_run, list_runs, save_run, update_run

RUNNERS = {
    "run_falcon_v2": run_falcon_v2,
    "run_vwap_stub": run_vwap_stub,
}

app = FastAPI(title="IgniteQuant Dashboard API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BacktestRequest(BaseModel):
    strategy_id: str = "falcon_v2"
    symbol_ids: list[str] = Field(default_factory=lambda: ["au"])
    start: dt.date = dt.date(2025, 1, 1)
    end: dt.date = dt.date(2025, 2, 28)
    init_balance: float = 1_000_000


class NotesRequest(BaseModel):
    notes: str = ""


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    return {
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "ready": s.runner != "run_vwap_stub",
            }
            for s in STRATEGIES.values()
        ],
        "symbols": [
            {
                "id": s.id,
                "name": s.name,
                "signal_symbol": s.signal_symbol,
                "exchange": s.exchange,
            }
            for s in SYMBOLS.values()
        ],
    }


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    return list_runs()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    rec = get_run(run_id)
    if not rec:
        raise HTTPException(404, "run not found")
    return rec


@app.post("/api/backtest")
def backtest(req: BacktestRequest) -> dict[str, Any]:
    if req.end <= req.start:
        raise HTTPException(400, "结束日期必须晚于开始日期")
    if req.strategy_id not in STRATEGIES:
        raise HTTPException(400, f"未知策略: {req.strategy_id}")
    if not req.symbol_ids:
        raise HTTPException(400, "请至少选择一个标的")

    strat = STRATEGIES[req.strategy_id]
    runner = RUNNERS[strat.runner]
    results: list[dict[str, Any]] = []

    for sid in req.symbol_ids:
        if sid not in SYMBOLS:
            raise HTTPException(400, f"未知标的: {sid}")
        sym = SYMBOLS[sid]
        try:
            out = runner(
                signal_symbol=sym.signal_symbol,
                start=req.start,
                end=req.end,
                init_balance=float(req.init_balance),
            )
        except NotImplementedError as e:
            raise HTTPException(501, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"{sym.name} 回测失败: {e}") from e

        scored = score_metrics(out.get("metrics") or {})
        record = {
            **out,
            "strategy_name": strat.name,
            "symbol_id": sid,
            "symbol_name": sym.name,
            "scorecard": scored,
            "notes": "",
        }
        save_run(record)
        results.append(record)

    return {"count": len(results), "runs": results}


@app.patch("/api/runs/{run_id}/notes")
def patch_notes(run_id: str, body: NotesRequest) -> dict[str, Any]:
    path = update_run(run_id, notes=body.notes)
    if path is None:
        raise HTTPException(404, "run not found")
    return get_run(run_id) or {}


@app.delete("/api/runs/{run_id}")
def remove_run(run_id: str) -> dict[str, bool]:
    if not delete_run(run_id):
        raise HTTPException(404, "run not found")
    return {"ok": True}
