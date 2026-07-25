# -*- coding: utf-8 -*-
"""Live kline snapshot written by TqKq sim for Sim Cockpit (not market_cache)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUNTIME = ROOT / "data" / "runtime"


def klines_snapshot_path(instance_id: str, *, runtime_dir: Path | None = None) -> Path:
    base = runtime_dir or DEFAULT_RUNTIME
    return base / f"{instance_id}.klines.json"


def _row_to_bar(row: Any, underlying: str) -> dict[str, Any]:
    ns = int(row["datetime"])
    return {
        "time": ns // 1_000_000_000,
        "datetime_ns": ns,
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row.get("volume", 0) or 0),
        "open_oi": float(row.get("open_oi", 0) or 0),
        "close_oi": float(row.get("close_oi", 0) or 0),
        "underlying_symbol": str(underlying or row.get("underlying_symbol") or ""),
    }


def dump_tq_klines_snapshot(
    instance_id: str,
    klines: Any,
    *,
    signal_symbol: str,
    trade_symbol: str,
    duration_seconds: int = 300,
    runtime_dir: Path | None = None,
    limit: int = 400,
) -> Path | None:
    """Persist completed Tq kline serial bars for cockpit (excludes forming stub)."""
    if klines is None or len(klines) < 2:
        return None
    underlying = str(trade_symbol or "")
    # iloc[-1] is the in-progress bar; dump only completed bars.
    completed = klines.iloc[:-1].tail(limit)
    bars = [_row_to_bar(completed.iloc[i], underlying) for i in range(len(completed))]
    if not bars:
        return None
    payload = {
        "instance_id": instance_id,
        "signal_symbol": signal_symbol,
        "trade_symbol": trade_symbol,
        "duration_seconds": int(duration_seconds),
        "source": "tqsdk_sim_live",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_price": float(bars[-1]["close"]),
        "bars": bars,
    }
    path = klines_snapshot_path(instance_id, runtime_dir=runtime_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_klines_snapshot(
    instance_id: str,
    *,
    runtime_dir: Path | None = None,
    limit: int = 400,
) -> dict[str, Any] | None:
    path = klines_snapshot_path(instance_id, runtime_dir=runtime_dir)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    bars = list(raw.get("bars") or [])
    if limit and len(bars) > limit:
        bars = bars[-limit:]
    raw["bars"] = bars
    if bars and raw.get("last_price") is None:
        raw["last_price"] = float(bars[-1]["close"])
    return raw


def find_snapshot_for_symbol(
    symbol_id: str,
    launchers: dict[str, dict[str, Any]],
    *,
    runtime_dir: Path | None = None,
    limit: int = 400,
) -> dict[str, Any] | None:
    """Resolve live snapshot by catalog symbol via known sim launchers."""
    for iid, meta in launchers.items():
        if meta.get("symbol_id") == symbol_id:
            snap = load_klines_snapshot(iid, runtime_dir=runtime_dir, limit=limit)
            if snap is not None:
                return snap
    # Fallback: any snapshot whose signal matches instrument mapping is handled by caller.
    return None
