"""Engine package: unified decision pipeline (Phase 2) + runtime bridge (Phase 3)."""

from ignitequant.engine.decision_pipeline import (
    FalconDecisionPipeline,
    annotate_klines,
    atr_of,
    close_of,
    score_parts,
)
from ignitequant.strategies.gma import GMADecisionPipeline
from ignitequant.engine.runtime_bridge import (
    apply_pretrade,
    domestic_session_allows_orders,
    healthy_runtime,
    make_risk_engine,
    market_closed_reject_decision,
    may_submit_domestic_order,
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
    "GMADecisionPipeline",
    "LocalProjection",
    "LocalSimAccount",
    "PositionStateMachine",
    "ReconReport",
    "annotate_klines",
    "apply_pretrade",
    "atr_of",
    "close_of",
    "domestic_session_allows_orders",
    "healthy_runtime",
    "make_risk_engine",
    "market_closed_reject_decision",
    "may_submit_domestic_order",
    "reconcile",
    "run_local_falcon_backtest",
    "score_parts",
    "startup_recover",
    "submit_approved_target",
]
