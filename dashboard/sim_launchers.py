# -*- coding: utf-8 -*-
"""Sim cockpit launcher matrix: one process per (strategy, symbol)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dashboard.catalog import STRATEGIES, SYMBOLS

ROOT = Path(__file__).resolve().parents[1]

READY_SIM_STRATEGIES: tuple[str, ...] = ("falcon_v2", "gma_v1", "gma_v2")

# Keep historical instance ids so existing sqlite / systemd / UI bookmarks still work.
COMPAT_INSTANCE_IDS: dict[tuple[str, str], str] = {
    ("falcon_v2", "au"): "falcon_au_sim",
    ("gma_v1", "au"): "gma_au_sim",
}


def sim_instance_id(strategy_id: str, symbol_id: str) -> str:
    sid = (strategy_id or "").strip()
    symbol = (symbol_id or "").strip().lower()
    compat = COMPAT_INSTANCE_IDS.get((sid, symbol))
    if compat:
        return compat
    return f"{sid}_{symbol}_sim"


def sim_script_for_strategy(strategy_id: str) -> Path:
    if strategy_id == "falcon_v2":
        return ROOT / "strategies" / "falcon_au_sim.py"
    if strategy_id == "gma_v1":
        return ROOT / "strategies" / "gma_au_sim.py"
    if strategy_id == "gma_v2":
        return ROOT / "strategies" / "gma_v2_sim.py"
    raise KeyError(f"no sim script for strategy {strategy_id}")


def build_sim_launchers() -> dict[str, dict[str, Any]]:
    launchers: dict[str, dict[str, Any]] = {}
    for strategy_id in READY_SIM_STRATEGIES:
        strat = STRATEGIES[strategy_id]
        script = sim_script_for_strategy(strategy_id)
        for symbol_id, spec in SYMBOLS.items():
            instance_id = sim_instance_id(strategy_id, symbol_id)
            launchers[instance_id] = {
                "label": f"{strat.name} {spec.name}模拟",
                "script": script,
                "symbol_id": symbol_id,
                "strategy_id": strategy_id,
                "framework": "tq",
            }
    return launchers


SIM_LAUNCHERS: dict[str, dict[str, Any]] = build_sim_launchers()
