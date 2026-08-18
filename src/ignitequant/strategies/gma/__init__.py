"""GMA strategy package."""

from ignitequant.strategies.gma.config import (
    GMA_CACHE_WARMUP_BARS,
    GMAIndicatorConfig,
    GMARuntimeConfig,
    default_gma_decision_config,
    load_gma_runtime,
)
from ignitequant.strategies.gma.pipeline import GMADecisionPipeline, annotate_gma_klines, gma_score_parts
from ignitequant.strategies.gma.regime import Alignment, classify_alignment

__all__ = [
    "Alignment",
    "GMA_CACHE_WARMUP_BARS",
    "GMADecisionPipeline",
    "GMAIndicatorConfig",
    "GMARuntimeConfig",
    "annotate_gma_klines",
    "classify_alignment",
    "default_gma_decision_config",
    "gma_score_parts",
    "load_gma_runtime",
]
