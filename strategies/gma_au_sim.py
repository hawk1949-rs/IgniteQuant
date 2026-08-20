#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GMA v1 快期模拟盘：复用 Falcon 执行/持久化壳，替换决策核。"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "strategies") not in sys.path:
    sys.path.insert(0, str(ROOT / "strategies"))

import strategies.falcon_au_sim as sim
from ignitequant.strategies.gma import (
    GMADecisionPipeline,
    annotate_gma_klines,
    gma_score_parts,
    load_gma_runtime,
)
from ignitequant.strategies.gma.config import GMARuntimeConfig

sim.INSTANCE_ID = "gma_au_sim"
sim.STRATEGY_ID = "gma_v1"
sim.STRATEGY_LABEL = "GMA v1"
sim.PERSIST_DB = ROOT / "data" / "runtime" / "gma_au_sim.sqlite"
sim.PID_FILE = sim.PERSIST_DB.parent / f"{sim.INSTANCE_ID}.pid"
sim.DATA_LENGTH = 8000
sim.annotate_klines = annotate_gma_klines
sim.score_parts = gma_score_parts


def _load_gma_decision_config():
    runtime = load_gma_runtime("gma_v1")
    return replace(runtime.decision, entry_mode="fill_confirmed")


def _gma_v1_pipeline(config=None, runtime=None):  # type: ignore[no-untyped-def]
    base = load_gma_runtime("gma_v1")
    if runtime is not None:
        return GMADecisionPipeline(config, runtime=runtime)
    if config is not None:
        return GMADecisionPipeline(
            config,
            runtime=GMARuntimeConfig(indicators=base.indicators, decision=config),
        )
    return GMADecisionPipeline(runtime=base)


sim.load_active_decision_config = _load_gma_decision_config
sim.FalconDecisionPipeline = _gma_v1_pipeline  # type: ignore[assignment]


if __name__ == "__main__":
    sim.main()
