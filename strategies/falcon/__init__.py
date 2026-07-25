"""Falcon v2：行情状态 + 多指标评分 + 动态仓位 + ATR 风控。"""

from .indicators import compute_indicators
from .regime import Regime, detect_regime
from .risk import RiskManager, RiskAction
from .score import ScoreDetail, score_signal
from .sizing import lots_from_signal

__all__ = [
    "compute_indicators",
    "Regime",
    "detect_regime",
    "RiskManager",
    "RiskAction",
    "ScoreDetail",
    "score_signal",
    "lots_from_signal",
]
