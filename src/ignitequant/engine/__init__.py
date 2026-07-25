"""Engine package: unified decision pipeline (Phase 2) + runtime bridge (Phase 3)."""

from ignitequant.engine.decision_pipeline import (
    FalconDecisionPipeline,
    annotate_klines,
    atr_of,
    close_of,
    score_parts,
)
from ignitequant.engine.runtime_bridge import (
    apply_pretrade,
    healthy_runtime,
    make_risk_engine,
    submit_approved_target,
)
from ignitequant.engine.reconciliation import (
    BrokerFacts,
    LocalProjection,
    ReconReport,
    reconcile,
    startup_recover,
)
from ignitequant.engine.state_machine import PositionStateMachine
from ignitequant.engine.local_replay import run_local_falcon_backtest
from ignitequant.engine.local_sim import LocalSimAccount

__all__ = [
    "BrokerFacts",
    "FalconDecisionPipeline",
    "LocalProjection",
    "LocalSimAccount",
    "PositionStateMachine",
    "ReconReport",
    "annotate_klines",
    "apply_pretrade",
    "atr_of",
    "close_of",
    "healthy_runtime",
    "make_risk_engine",
    "reconcile",
    "run_local_falcon_backtest",
    "score_parts",
    "startup_recover",
    "submit_approved_target",
]
