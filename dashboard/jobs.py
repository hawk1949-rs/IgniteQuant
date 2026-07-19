# -*- coding: utf-8 -*-
"""Async backtest job queue (大框架 §14.2) — local thread pool + SQLite."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
JOBS_DB = ROOT / "data" / "runtime" / "backtest_jobs.sqlite"

JobHandler = Callable[[dict[str, Any], Callable[[float, str], None]], dict[str, Any]]


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def idempotency_key(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


class BacktestJobQueue:
    """QUEUED → RUNNING → SUCCEEDED | FAILED | CANCELED."""

    def __init__(
        self,
        db_path: Path | str = JOBS_DB,
        *,
        max_workers: int = 1,
        handler: JobHandler | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="bt-job")
        self._futures: dict[str, Future[Any]] = {}
        self._handler = handler
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS backtest_job (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    progress_msg TEXT NOT NULL DEFAULT '',
                    result_run_ids_json TEXT NOT NULL DEFAULT '[]',
                    error_summary TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    config_hash TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_job_status ON backtest_job(status);
                """
            )

    def set_handler(self, handler: JobHandler) -> None:
        self._handler = handler

    def enqueue(self, request: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        key = idempotency_key(request)
        with self._lock:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT * FROM backtest_job WHERE idempotency_key = ?",
                    (key,),
                ).fetchone()
                if existing is not None and not force:
                    if existing["status"] in {"QUEUED", "RUNNING", "SUCCEEDED"}:
                        job = self._row_to_dict(existing)
                        if job["status"] == "QUEUED" and job["job_id"] not in self._futures:
                            self._futures[job["job_id"]] = self._executor.submit(
                                self._run_job, job["job_id"]
                            )
                        return job
                    # FAILED / CANCELED → requeue below

                job_id = uuid.uuid4().hex[:12]
                if existing is not None:
                    conn.execute("DELETE FROM backtest_job WHERE idempotency_key = ?", (key,))

                conn.execute(
                    """
                    INSERT INTO backtest_job(
                        job_id, idempotency_key, status, request_json,
                        created_at, config_hash
                    ) VALUES (?, ?, 'QUEUED', ?, ?, ?)
                    """,
                    (
                        job_id,
                        key,
                        json.dumps(request, ensure_ascii=False, default=str),
                        _utc(),
                        str(request.get("config_hash") or ""),
                    ),
                )
                job = {
                    "job_id": job_id,
                    "idempotency_key": key,
                    "status": "QUEUED",
                    "request": request,
                    "progress": 0.0,
                    "progress_msg": "",
                    "result_run_ids": [],
                    "error_summary": "",
                    "created_at": _utc(),
                    "started_at": None,
                    "finished_at": None,
                    "config_hash": str(request.get("config_hash") or ""),
                }
                self._futures[job_id] = self._executor.submit(self._run_job, job_id)
                return job

    def _run_job(self, job_id: str) -> None:
        if self._handler is None:
            self._fail(job_id, "no job handler registered")
            return
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM backtest_job WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] == "CANCELED":
                return
            request = json.loads(row["request_json"])
            conn.execute(
                """
                UPDATE backtest_job
                SET status='RUNNING', started_at=?, progress=0, progress_msg='starting'
                WHERE job_id=? AND status='QUEUED'
                """,
                (_utc(), job_id),
            )
            # Ensure we actually transitioned
            row2 = conn.execute(
                "SELECT status FROM backtest_job WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row2 is None or row2["status"] != "RUNNING":
                return

        def progress(pct: float, msg: str) -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE backtest_job
                    SET progress=?, progress_msg=?
                    WHERE job_id=? AND status='RUNNING'
                    """,
                    (float(pct), str(msg), job_id),
                )

        try:
            result = self._handler(request, progress)
            run_ids = result.get("run_ids") or []
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE backtest_job
                    SET status='SUCCEEDED', progress=1, progress_msg='done',
                        result_run_ids_json=?, finished_at=?, error_summary=''
                    WHERE job_id=? AND status='RUNNING'
                    """,
                    (json.dumps(run_ids), _utc(), job_id),
                )
        except Exception as exc:
            self._fail(job_id, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()[-800:]}")
        finally:
            self._futures.pop(job_id, None)

    def _fail(self, job_id: str, summary: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE backtest_job
                SET status='FAILED', error_summary=?, finished_at=?, progress_msg='failed'
                WHERE job_id=?
                """,
                (summary[:2000], _utc(), job_id),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM backtest_job WHERE job_id = ?", (job_id,)
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def list_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_job ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM backtest_job WHERE job_id = ?", (job_id,)
                ).fetchone()
                if row is None:
                    return None
                if row["status"] in {"SUCCEEDED", "FAILED", "CANCELED"}:
                    return self._row_to_dict(row)
                conn.execute(
                    """
                    UPDATE backtest_job
                    SET status='CANCELED', finished_at=?, progress_msg='canceled'
                    WHERE job_id=? AND status IN ('QUEUED', 'RUNNING')
                    """,
                    (_utc(), job_id),
                )
                fut = self._futures.pop(job_id, None)
                if fut is not None:
                    fut.cancel()
                row2 = conn.execute(
                    "SELECT * FROM backtest_job WHERE job_id = ?", (job_id,)
                ).fetchone()
                return self._row_to_dict(row2) if row2 else None

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "idempotency_key": row["idempotency_key"],
            "status": row["status"],
            "request": json.loads(row["request_json"]),
            "progress": float(row["progress"]),
            "progress_msg": row["progress_msg"],
            "result_run_ids": json.loads(row["result_run_ids_json"] or "[]"),
            "error_summary": row["error_summary"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "config_hash": row["config_hash"],
        }


_queue: BacktestJobQueue | None = None
_queue_lock = threading.Lock()


def get_job_queue() -> BacktestJobQueue:
    global _queue
    with _queue_lock:
        if _queue is None:
            _queue = BacktestJobQueue()
        return _queue
