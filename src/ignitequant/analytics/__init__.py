"""Analytics: cost model, attribution, walk-forward, stress (Phase 5)."""

from ignitequant.analytics.attribution import (
    AttributionReport,
    TradeFillRecord,
    attribute_fills,
    fill_record_to_dict,
    fills_from_tq_trade_log,
    stamp_fills_with_intent_log,
)
from ignitequant.analytics.cost_model import COST_MODEL_VERSION, CostModel, default_cost_model
from ignitequant.analytics.stress import DEFAULT_STRESS, run_cost_stress, stress_summary
from ignitequant.analytics.tq_match import (
    TqKlineQuote,
    market_fill_price,
    metrics_delta,
    quote_from_bar_close,
    within_tolerances,
)
from ignitequant.analytics.tq_metrics import (
    annual_yield_from_ror,
    equity_curve_metrics,
    sharpe_from_daily_balances,
)
from ignitequant.analytics.walk_forward import WalkForwardWindow, plan_walk_forward

__all__ = [
    "COST_MODEL_VERSION",
    "AttributionReport",
    "CostModel",
    "DEFAULT_STRESS",
    "TradeFillRecord",
    "TqKlineQuote",
    "WalkForwardWindow",
    "annual_yield_from_ror",
    "attribute_fills",
    "default_cost_model",
    "equity_curve_metrics",
    "fill_record_to_dict",
    "fills_from_tq_trade_log",
    "stamp_fills_with_intent_log",
    "market_fill_price",
    "metrics_delta",
    "plan_walk_forward",
    "quote_from_bar_close",
    "run_cost_stress",
    "sharpe_from_daily_balances",
    "stress_summary",
    "within_tolerances",
]
