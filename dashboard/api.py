# -*- coding: utf-8 -*-
"""策略看板 HTTP API（供 Magic UI / React 前端调用）。

Phase 5：异步 job 队列（默认），同步仅用于短冒烟（sync=true）。

启动：
    uvicorn dashboard.api:app --reload --port 8787
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from dashboard.auth import (
    CockpitAuthMiddleware,
    authenticate,
    extract_bearer,
    load_auth_config,
    verify_token,
)
from dashboard.catalog import ENGINES, STRATEGIES, SYMBOLS
from dashboard.jobs import get_job_queue
from dashboard.runners import run_falcon_local, run_falcon_v2, run_vwap_stub
from dashboard.scoring import score_metrics
from dashboard.sim_api import router as sim_router
from dashboard.store import delete_run, get_run, list_runs, save_run, update_run
from ignitequant.analytics import plan_walk_forward
from ignitequant.config import default_decision_config, list_profiles, load_profile_dict
from ignitequant.market.cache import cache_status

RUNNERS = {
    "run_falcon_v2": run_falcon_v2,
    "run_falcon_local": run_falcon_local,
    "run_vwap_stub": run_vwap_stub,
}

app = FastAPI(title="IgniteQuant Dashboard API", version="0.6.0")
# 先注册鉴权（内层），再注册 CORS（外层），保证 401 也带 CORS 头
app.add_middleware(CockpitAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(sim_router)


class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""


@app.get("/api/auth/status")
def auth_status() -> dict[str, object]:
    cfg = load_auth_config()
    return {"auth_required": cfg.enabled}


@app.post("/api/auth/login")
def auth_login(body: LoginRequest) -> dict[str, object]:
    cfg = load_auth_config()
    token, exp = authenticate(cfg, body.username, body.password)
    # authenticate 已校验；username 以签发主体为准（去掉首尾空格）
    username = body.username.strip()
    return {
        "token": token,
        "expires_at": exp,
        "username": username,
        "token_type": "Bearer",
    }


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict[str, object]:
    cfg = load_auth_config()
    if not cfg.enabled:
        return {"authenticated": True, "username": "dev", "auth_required": False}
    token = extract_bearer(request)
    user = verify_token(cfg, token or "")
    if not user:
        raise HTTPException(status_code=401, detail="未登录或会话已过期")
    return {"authenticated": True, "username": user, "auth_required": True}

WEB_DIST = ROOT / "web" / "dist"


class BacktestRequest(BaseModel):
    strategy_id: str = "falcon_v2"
    symbol_ids: list[str] = Field(default_factory=lambda: ["au"])
    start: dt.date = dt.date(2025, 1, 1)
    end: dt.date = dt.date(2025, 2, 28)
    init_balance: float = 1_000_000
    engine: Literal["local", "tq"] = "local"
    sync: bool = False
    force: bool = False
    auto_download: bool = True


class NotesRequest(BaseModel):
    notes: str = ""


class WalkForwardRequest(BaseModel):
    start: dt.date
    end: dt.date
    train_days: int = 40
    test_days: int = 20
    step_days: int | None = None


class ScorecardModel(BaseModel):
    score: float
    grade: str
    label: str
    parts: dict[str, float] = Field(default_factory=dict)
    review_tips: list[str] = Field(default_factory=list)
    perf_tips: list[str] = Field(default_factory=list)


class JobStatus(BaseModel):
    job_id: str
    status: Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED"]
    progress: float
    progress_msg: str = ""
    result_run_ids: list[str] = Field(default_factory=list)
    error_summary: str = ""
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    idempotency_key: str | None = None
    request: dict[str, Any] = Field(default_factory=dict)


def _execute_backtest_request(
    request: dict[str, Any],
    progress_cb,
) -> dict[str, Any]:
    strategy_id = request["strategy_id"]
    symbol_ids = request["symbol_ids"]
    start = dt.date.fromisoformat(request["start"])
    end = dt.date.fromisoformat(request["end"])
    init_balance = float(request.get("init_balance") or 1_000_000)
    engine = str(request.get("engine") or "local").lower()
    auto_download = bool(request.get("auto_download", True))

    if strategy_id not in STRATEGIES:
        raise ValueError(f"未知策略: {strategy_id}")
    if engine not in ENGINES:
        raise ValueError(f"未知引擎: {engine}（可选 local / tq）")
    strat = STRATEGIES[strategy_id]
    if engine == "local" and strat.runner == "run_falcon_v2":
        runner = RUNNERS["run_falcon_local"]
    else:
        runner = RUNNERS[strat.runner]
    run_ids: list[str] = []
    n = max(len(symbol_ids), 1)

    for i, sid in enumerate(symbol_ids):
        if sid not in SYMBOLS:
            raise ValueError(f"未知标的: {sid}")
        sym = SYMBOLS[sid]

        def _cb(pct: float, msg: str, _i=i, _n=n) -> None:
            overall = (_i + float(pct)) / _n
            progress_cb(min(overall, 0.99), f"{sym.name}: {msg}")

        kwargs: dict[str, Any] = {
            "signal_symbol": sym.signal_symbol,
            "start": start,
            "end": end,
            "init_balance": init_balance,
            "progress_cb": _cb,
        }
        if engine == "local" and strat.runner == "run_falcon_v2":
            kwargs["auto_download"] = auto_download

        out = runner(**kwargs)
        scored = score_metrics(out.get("metrics") or {})
        record = {
            **out,
            "engine": out.get("engine") or engine,
            "strategy_name": strat.name,
            "symbol_id": sid,
            "symbol_name": sym.name,
            "scorecard": scored,
            "notes": "",
            "schema_version": "backtest_run_v1",
        }
        path = save_run(record)
        run_ids.append(record["run_id"])
        _ = path

    progress_cb(1.0, "完成")
    return {"run_ids": run_ids}


@app.on_event("startup")
def _startup() -> None:
    queue = get_job_queue()
    queue.set_handler(_execute_backtest_request)
    queue.recover_queued()


@app.get("/api/health")
def health() -> dict[str, str]:
    from dashboard import sim_cloud_read

    return {
        "status": "ok",
        "phase": "6-local",
        "sim_data_source": sim_cloud_read.data_source(),
    }


@app.get("/api/catalog")
def catalog() -> dict[str, Any]:
    cfg = default_decision_config()
    profiles = []
    for pid in list_profiles():
        meta = load_profile_dict(pid)
        profiles.append(
            {
                "id": pid,
                "status": meta.get("status"),
                "description": meta.get("description", ""),
                "rollback_to": meta.get("rollback_to"),
            }
        )
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
        "engines": [
            {"id": eid, "name": label, "default": eid == "local"}
            for eid, label in ENGINES.items()
        ],
        "market_cache": cache_status(),
        "defaults": {
            "config_version": cfg.config_version,
            "config_hash": cfg.config_hash(),
            "profiles": profiles,
            "active_env_var": "FALCON_PROFILE",
            "production_default": "falcon_legacy_v1",
            "engine": "local",
        },
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
    """默认异步：立即返回 job；sync=true 时同步跑完（短区间冒烟）。"""
    if req.end <= req.start:
        raise HTTPException(400, "结束日期必须晚于开始日期")
    if req.strategy_id not in STRATEGIES:
        raise HTTPException(400, f"未知策略: {req.strategy_id}")
    if not req.symbol_ids:
        raise HTTPException(400, "请至少选择一个标的")
    for sid in req.symbol_ids:
        if sid not in SYMBOLS:
            raise HTTPException(400, f"未知标的: {sid}")

    if req.engine not in ENGINES:
        raise HTTPException(400, f"未知引擎: {req.engine}")

    payload = {
        "strategy_id": req.strategy_id,
        "symbol_ids": list(req.symbol_ids),
        "start": req.start.isoformat(),
        "end": req.end.isoformat(),
        "init_balance": float(req.init_balance),
        "engine": req.engine,
        "auto_download": bool(req.auto_download),
        "config_hash": default_decision_config().config_hash(),
    }

    if req.sync:
        try:
            result = _execute_backtest_request(payload, lambda _p, _m: None)
        except NotImplementedError as e:
            raise HTTPException(501, str(e)) from e
        except Exception as e:
            raise HTTPException(500, f"回测失败: {e}") from e
        runs_out = [get_run(rid) for rid in result["run_ids"]]
        return {
            "mode": "sync",
            "count": len(runs_out),
            "runs": [r for r in runs_out if r],
            "job": None,
        }

    job = get_job_queue().enqueue(payload, force=req.force)
    return {
        "mode": "async",
        "count": 0,
        "runs": [],
        "job": job,
    }


@app.get("/api/jobs")
def jobs(limit: int = 50) -> list[dict[str, Any]]:
    return get_job_queue().list_jobs(limit=limit)


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict[str, Any]:
    job = get_job_queue().get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    runs_out = [get_run(rid) for rid in job.get("result_run_ids") or []]
    return {**job, "runs": [r for r in runs_out if r]}


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict[str, Any]:
    job = get_job_queue().cancel(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


@app.post("/api/research/walk-forward")
def walk_forward(req: WalkForwardRequest) -> dict[str, Any]:
    try:
        windows = plan_walk_forward(
            req.start,
            req.end,
            train_days=req.train_days,
            test_days=req.test_days,
            step_days=req.step_days,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {
        "count": len(windows),
        "windows": [w.to_dict() for w in windows],
    }


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


def _mount_spa() -> None:
    if not WEB_DIST.is_dir():
        return
    assets_dir = WEB_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="web-assets")

    @app.get("/", include_in_schema=False)
    def spa_index() -> FileResponse:
        index = WEB_DIST / "index.html"
        if not index.is_file():
            raise HTTPException(
                404,
                "web/dist 未构建。本地开发请用 Vite；托管镜像请先 npm run build。",
            )
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        """Serve SPA shell for non-API routes (hash router still needs index.html)."""
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(404, "not found")
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        index = WEB_DIST / "index.html"
        if not index.is_file():
            raise HTTPException(404, "web/dist missing")
        return FileResponse(index)


_mount_spa()
