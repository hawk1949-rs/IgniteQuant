# -*- coding: utf-8 -*-
"""回测结果本地存储（JSON，适合家庭作坊）。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data" / "backtest_runs"


def _ensure_dir() -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return RUNS_DIR


def save_run(record: dict[str, Any]) -> Path:
    _ensure_dir()
    run_id = record.get("run_id") or uuid.uuid4().hex[:12]
    record["run_id"] = run_id
    record.setdefault("saved_at", datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"))
    path = RUNS_DIR / f"{run_id}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_runs() -> list[dict[str, Any]]:
    _ensure_dir()
    rows: list[dict[str, Any]] = []
    for path in sorted(RUNS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return rows


def get_run(run_id: str) -> dict[str, Any] | None:
    path = RUNS_DIR / f"{run_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_run(run_id: str, **fields: Any) -> Path | None:
    rec = get_run(run_id)
    if rec is None:
        return None
    rec.update(fields)
    return save_run(rec)


def delete_run(run_id: str) -> bool:
    path = RUNS_DIR / f"{run_id}.json"
    if path.is_file():
        path.unlink()
        return True
    return False
