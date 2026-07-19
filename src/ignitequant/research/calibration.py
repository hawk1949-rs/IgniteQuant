"""Offline Falcon calibration metrics on fixed bars (Phase 6).

Does not call tqsdk. Uses FalconDecisionPipeline + fixture CSVs / DataFrames.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd

from ignitequant.analytics.attribution import TradeFillRecord, attribute_fills
from ignitequant.analytics.cost_model import default_cost_model
from ignitequant.analytics.stress import run_cost_stress, stress_summary
from ignitequant.analytics.walk_forward import plan_walk_forward
from ignitequant.config.decision import DecisionConfig
from ignitequant.engine.decision_pipeline import FalconDecisionPipeline


@dataclass
class CalibrationMetrics:
    profile_id: str
    config_hash: str
    bars: int
    warm_bars: int
    target_changes: int
    stop_exits: int
    take_exits: int
    time_in_market_bars: int
    time_in_market_pct: float
    signal_nonzero_pct: float
    regime_counts: dict[str, int] = field(default_factory=dict)
    proxy_gross_pnl: float = 0.0
    proxy_net_pnl: float = 0.0
    stress_worst_net: float | None = None
    stress_all_survive: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "config_hash": self.config_hash,
            "bars": self.bars,
            "warm_bars": self.warm_bars,
            "target_changes": self.target_changes,
            "stop_exits": self.stop_exits,
            "take_exits": self.take_exits,
            "time_in_market_bars": self.time_in_market_bars,
            "time_in_market_pct": round(self.time_in_market_pct, 4),
            "signal_nonzero_pct": round(self.signal_nonzero_pct, 4),
            "regime_counts": self.regime_counts,
            "proxy_gross_pnl": round(self.proxy_gross_pnl, 2),
            "proxy_net_pnl": round(self.proxy_net_pnl, 2),
            "stress_worst_net": self.stress_worst_net,
            "stress_all_survive": self.stress_all_survive,
            "notes": self.notes,
        }


def _proxy_fills_from_replay(results: list, closes: Sequence[float]) -> list[TradeFillRecord]:
    """Synthesize OPEN/CLOSE fills when target changes (close as fill price)."""
    fills: list[TradeFillRecord] = []
    pos = 0
    seq = 0
    for i, result in enumerate(results):
        new_pos = int(result.target_after)
        if new_pos == pos:
            continue
        price = float(closes[i])
        # flatten old
        if pos != 0:
            seq += 1
            fills.append(
                TradeFillRecord(
                    trade_id=f"c{seq}",
                    symbol=result.target.symbol,
                    side="SELL" if pos > 0 else "BUY",
                    offset="CLOSE",
                    price=price,
                    qty=abs(pos),
                    regime=result.factors.regime.value,
                )
            )
        # open new
        if new_pos != 0:
            seq += 1
            fills.append(
                TradeFillRecord(
                    trade_id=f"o{seq}",
                    symbol=result.target.symbol,
                    side="BUY" if new_pos > 0 else "SELL",
                    offset="OPEN",
                    price=price,
                    qty=abs(new_pos),
                    regime=result.factors.regime.value,
                )
            )
        pos = new_pos
    if pos != 0 and results:
        seq += 1
        fills.append(
            TradeFillRecord(
                trade_id=f"c{seq}",
                symbol=results[-1].target.symbol,
                side="SELL" if pos > 0 else "BUY",
                offset="CLOSE",
                price=float(closes[-1]),
                qty=abs(pos),
                regime=results[-1].factors.regime.value,
            )
        )
    return fills


def evaluate_bars(
    bars: pd.DataFrame,
    config: DecisionConfig,
    *,
    profile_id: str = "",
) -> CalibrationMetrics:
    pipe = FalconDecisionPipeline(config)
    warmup = max(int(config.factor.warmup_bars), int(config.factor.ma_slow))
    if len(bars) < warmup:
        return CalibrationMetrics(
            profile_id=profile_id or config.config_version,
            config_hash=config.config_hash(),
            bars=len(bars),
            warm_bars=0,
            target_changes=0,
            stop_exits=0,
            take_exits=0,
            time_in_market_bars=0,
            time_in_market_pct=0.0,
            signal_nonzero_pct=0.0,
            notes=[f"insufficient bars: need>={warmup}"],
        )

    results = []
    closes: list[float] = []
    regimes: dict[str, int] = {}
    target_changes = 0
    stops = 0
    takes = 0
    tinm = 0
    sig_nz = 0
    warm = 0

    for bar_index in range(warmup - 1, len(bars)):
        window = bars.iloc[: bar_index + 1]
        result = pipe.on_bar_close(window, trade=True)
        results.append(result)
        warm += 1
        closes.append(float(window.iloc[-1]["close"]))
        regimes[result.factors.regime.value] = regimes.get(result.factors.regime.value, 0) + 1
        if result.signal.legacy_signal != 0:
            sig_nz += 1
        if result.applied_action == "TARGET":
            target_changes += 1
        elif result.applied_action == "STOP_LOSS":
            stops += 1
        elif result.applied_action == "TAKE_PROFIT":
            takes += 1
        if result.target_after != 0:
            tinm += 1

    fills = _proxy_fills_from_replay(results, closes)
    cost = default_cost_model()
    attr = attribute_fills(fills, cost=cost)
    stress_rows = run_cost_stress(fills, base=cost) if fills else []
    summary = stress_summary(stress_rows)

    return CalibrationMetrics(
        profile_id=profile_id or config.config_version,
        config_hash=config.config_hash(),
        bars=len(bars),
        warm_bars=warm,
        target_changes=target_changes,
        stop_exits=stops,
        take_exits=takes,
        time_in_market_bars=tinm,
        time_in_market_pct=tinm / warm if warm else 0.0,
        signal_nonzero_pct=sig_nz / warm if warm else 0.0,
        regime_counts=regimes,
        proxy_gross_pnl=attr.gross_pnl,
        proxy_net_pnl=attr.net_pnl,
        stress_worst_net=summary.get("worst_net"),
        stress_all_survive=bool(summary.get("all_survive")),
        notes=[
            "proxy fills use bar close; not broker fills",
            f"warmup={warmup}",
        ],
    )


@dataclass(frozen=True)
class GoLiveGate:
    """Pre-defined promotion criteria (大框架 Phase 6 exit)."""

    min_warm_bars: int = 200
    max_time_in_market_pct: float = 0.85
    min_target_changes: int = 3
    max_target_changes: int = 120
    require_stress_survive: bool = True
    require_positive_proxy_net: bool = True

    def evaluate(self, metrics: CalibrationMetrics) -> dict[str, Any]:
        checks = {
            "warm_bars_ok": metrics.warm_bars >= self.min_warm_bars,
            "tinm_ok": metrics.time_in_market_pct <= self.max_time_in_market_pct,
            "trades_ok": self.min_target_changes
            <= metrics.target_changes
            <= self.max_target_changes,
            "stress_ok": (not self.require_stress_survive) or metrics.stress_all_survive,
            "net_ok": (not self.require_positive_proxy_net) or metrics.proxy_net_pnl > 0,
        }
        passed = all(checks.values())
        return {
            "passed": passed,
            "checks": checks,
            "gate": {
                "min_warm_bars": self.min_warm_bars,
                "max_time_in_market_pct": self.max_time_in_market_pct,
                "min_target_changes": self.min_target_changes,
                "max_target_changes": self.max_target_changes,
                "require_stress_survive": self.require_stress_survive,
                "require_positive_proxy_net": self.require_positive_proxy_net,
            },
            "promote": False,  # never auto-promote; human approval required
            "message": (
                "PASS research gate — still requires human approval + sim shadow"
                if passed
                else "FAIL research gate — keep falcon_legacy_v1"
            ),
        }


def compare_profiles(
    bars: pd.DataFrame,
    configs: dict[str, DecisionConfig],
    *,
    gate: GoLiveGate | None = None,
) -> dict[str, Any]:
    gate = gate or GoLiveGate()
    rows = {}
    for name, cfg in configs.items():
        m = evaluate_bars(bars, cfg, profile_id=name)
        rows[name] = {
            "metrics": m.to_dict(),
            "gate": gate.evaluate(m),
        }
    return {"profiles": rows}


def walk_forward_plan_for_calibration(
    start: str,
    end: str,
    *,
    train_days: int = 40,
    test_days: int = 20,
) -> list[dict[str, Any]]:
    import datetime as dt

    windows = plan_walk_forward(
        dt.date.fromisoformat(start),
        dt.date.fromisoformat(end),
        train_days=train_days,
        test_days=test_days,
    )
    return [w.to_dict() for w in windows]
