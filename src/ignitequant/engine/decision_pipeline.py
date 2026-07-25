"""Unified Falcon decision pipeline (Phase 2).

Backtest / sim / dashboard runners must call this instead of inlined
indicator → regime → score → sizing → risk loops.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ignitequant.config.decision import DecisionConfig, default_decision_config
from ignitequant.domain.models import PipelineResult
from ignitequant.strategies.falcon.legacy_adapter import LegacyDecisionAdapter


class FalconDecisionPipeline:
    """Single decision entry for completed bars."""

    def __init__(self, config: DecisionConfig | None = None) -> None:
        self.config = config or default_decision_config()
        self._adapter = LegacyDecisionAdapter(self.config)

    def reset(self) -> None:
        self._adapter.reset()

    @property
    def current_target(self) -> int:
        return self._adapter.current_target

    @property
    def risk(self) -> Any:
        return self._adapter.risk

    def force_flat(self) -> None:
        """Environment-driven flat (roll / end-date / shutdown). Clears entry state."""
        self._adapter.current_target = 0
        self._adapter.risk.on_flat()

    def restore_runtime(
        self,
        *,
        current_target: int,
        cooldown_left: int = 0,
        entry_price: float | None = None,
        stop_price: float | None = None,
        take_price: float | None = None,
        entry_signal: int | None = None,
    ) -> None:
        """Apply persisted strategy payload after startup reconciliation."""
        self._adapter.restore_runtime(
            current_target=current_target,
            cooldown_left=cooldown_left,
            entry_price=entry_price,
            stop_price=stop_price,
            take_price=take_price,
            entry_signal=entry_signal,
        )

    def on_bar_close(
        self,
        klines: pd.DataFrame,
        *,
        trade: bool = True,
    ) -> PipelineResult:
        """Evaluate one completed bar.

        Parameters
        ----------
        klines:
            Growing kline serial (or fixture window) ending at the decision bar.
        trade:
            When False, only observe (indicators/score + cooldown tick). Used for
            backtest end-flat days to preserve legacy semantics.
        """
        return self._adapter.on_bar_window(
            klines,
            bar_index=len(klines) - 1,
            trade=trade,
        )

    def replay(self, bars: pd.DataFrame) -> list[PipelineResult]:
        return self._adapter.replay(bars)

    def characterization_rows(self, bars: pd.DataFrame) -> list[dict[str, Any]]:
        return self._adapter.characterization_rows(bars)


def annotate_klines(klines: pd.DataFrame, result: PipelineResult) -> None:
    """Attach last-bar factor series for tqsdk web_gui charts (in-place)."""
    # Recompute full series for chart columns — same as legacy runners.
    from strategies.falcon import compute_indicators

    ind = compute_indicators(klines)
    klines["ma7"] = ind.ma7
    klines["ma14"] = ind.ma14
    klines["ma52"] = ind.ma52
    klines["adx"] = ind.adx
    klines["atr"] = ind.atr
    klines["kdj_k"] = ind.k
    klines["kdj_d"] = ind.d


def score_parts(result: PipelineResult) -> str:
    gv, vol, kdj, pen = result.legacy_score_parts
    return f"gv={gv} vol={vol} kdj={kdj} pen={pen} => {result.signal.legacy_signal}"


def atr_of(result: PipelineResult) -> float:
    value = result.factors.values.get("atr")
    return float(value) if value is not None else 0.0


def close_of(result: PipelineResult) -> float:
    value = result.factors.values.get("close")
    return float(value) if value is not None else float("nan")
