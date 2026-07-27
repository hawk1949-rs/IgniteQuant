# -*- coding: utf-8 -*-
"""Safe path/id validation for dashboard APIs."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_safe_id(value: str, *, field: str = "id") -> str:
    text = (value or "").strip()
    if not text or not _SAFE_ID_RE.match(text):
        raise HTTPException(400, f"invalid {field}")
    return text


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_runtime_db(runtime_dir: Path, instance_id: str) -> Path:
    """Resolve a sim session SQLite file under runtime_dir."""
    safe_id = validate_safe_id(instance_id, field="instance_id")
    root = runtime_dir.resolve()
    path = (root / f"{safe_id}.sqlite").resolve()
    if not _is_under_root(path, root):
        raise HTTPException(400, "invalid instance_id")
    if not path.is_file():
        raise HTTPException(404, f"session not found: {safe_id}")
    return path


def resolve_run_json(runs_dir: Path, run_id: str) -> Path:
    """Resolve a backtest run JSON file under runs_dir."""
    safe_id = validate_safe_id(run_id, field="run_id")
    root = runs_dir.resolve()
    path = (root / f"{safe_id}.json").resolve()
    if not _is_under_root(path, root):
        raise HTTPException(400, "invalid run_id")
    if not path.is_file():
        raise HTTPException(404, f"run not found: {safe_id}")
    return path
