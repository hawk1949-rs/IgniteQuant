"""Adapt legacy Falcon modules into Phase 1 domain objects without changing formulas."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

from ignitequant.config.decision import DecisionConfig, default_decision_config
from ignitequant.domain.enums import (
    DecisionAction,
    FactorQuality,
    LegacyExitAction,
    Regime,
    RiskAction,
    SignalAction,
)
from ignitequant.domain.models import (
    FactorSnapshot,
    PipelineResult,
    RiskDecision,
    SignalEvent,
    TargetPosition,
)
from strategies.falcon import (
    RiskAction as LegacyRiskAction,
    RiskManager,
    compute_indicators,
    detect_regime,
    lots_from_signal,
    score_signal,
)
from strategies.falcon.regime import Regime as LegacyRegime

FACTOR_VERSION = "falcon_indicators_legacy_v1"


def _finite(value: Any) -> float | None:
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _bar_datetime(raw: Any) -> datetime:
    ts = int(raw)
    return datetime.fromtimestamp(ts / 1_000_000_000, tz=timezone.utc)


def _legacy_regime(regime: LegacyRegime) -> Regime:
    return Regime(regime.value)


def _signal_action(*, desired: int | None, current_target: int) -> SignalAction:
    if desired is None:
        return SignalAction.HOLD
    if desired == 0:
        return SignalAction.EXIT
    if desired > 0:
        if current_target <= 0:
            return SignalAction.ENTER_LONG
        if desired > current_target:
            return SignalAction.ENTER_LONG
        if desired < current_target:
            return SignalAction.REDUCE_LONG
        return SignalAction.HOLD
    if current_target >= 0:
        return SignalAction.ENTER_SHORT
    if desired < current_target:
        return SignalAction.ENTER_SHORT
    if desired > current_target:
        return SignalAction.REDUCE_SHORT
    return SignalAction.HOLD


def _decision_action(desired: int | None, current_target: int) -> DecisionAction:
    if desired is None:
        return DecisionAction.HOLD
    if desired == 0:
        return DecisionAction.FLAT
    if desired == current_target:
        return DecisionAction.HOLD
    return DecisionAction.TARGET


class LegacyDecisionAdapter:
    """Bar-by-bar wrapper around strategies.falcon with explicit domain objects."""

    def __init__(self, config: DecisionConfig | None = None) -> None:
        self.config = config or default_decision_config()
        if self.config.decision_mode not in {"legacy_compatible", "calibrated_5m"}:
            raise ValueError(
                "adapter supports decision_mode=legacy_compatible|calibrated_5m "
                f"(got {self.config.decision_mode!r})"
            )
        self.risk = RiskManager(**self.config.risk_kwargs())
        self.current_target = 0

    def reset(self) -> None:
        self.risk = RiskManager(**self.config.risk_kwargs())
        self.current_target = 0

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
        """Rebuild mutable risk/target after restart (Phase 4 recovery)."""
        self.current_target = int(current_target)
        self.risk.state.cooldown_left = max(0, int(cooldown_left))
        self.risk.state.entry_price = entry_price
        self.risk.state.stop_price = stop_price
        self.risk.state.take_price = take_price
        self.risk.state.entry_signal = int(entry_signal or 0)

    def on_bar_window(
        self,
        window: pd.DataFrame,
        *,
        bar_index: int,
        trade: bool = True,
    ) -> PipelineResult:
        del bar_index  # kept for call-site clarity / future tracing
        fc = self.config.factor
        ind = compute_indicators(
            window,
            ma_fast=fc.ma_fast,
            ma_mid=fc.ma_mid,
            ma_slow=fc.ma_slow,
            atr_period=fc.atr_period,
            adx_period=fc.adx_period,
            vol_ma_period=fc.vol_ma_period,
            kdj_n=fc.kdj_n,
        )
        legacy_regime = detect_regime(ind, adx_threshold=fc.adx_threshold)
        score = score_signal(ind)
        lot_map = {int(k): int(v) for k, v in self.config.sizing.lot_by_signal.items()}
        desired = lots_from_signal(score.signal, legacy_regime, lot_by_signal=lot_map)

        target_before = self.current_target
        self.risk.tick_cooldown()
        risk_action = LegacyRiskAction.NONE
        applied_action = "HOLD"

        if trade:
            if self.current_target != 0:
                risk_action = self.risk.check(
                    self.current_target,
                    float(ind.high[-1]),
                    float(ind.low[-1]),
                    float(ind.close[-1]),
                )
                if risk_action != LegacyRiskAction.NONE:
                    self.risk.trigger(risk_action)
                    self.current_target = 0
                    applied_action = risk_action.value

            if risk_action == LegacyRiskAction.NONE:
                if self.risk.in_cooldown:
                    applied_action = "COOLDOWN_HOLD"
                elif desired is not None and desired != self.current_target:
                    self.current_target = desired
                    applied_action = "TARGET"
                    if self.current_target == 0:
                        self.risk.on_flat()
                    else:
                        self.risk.on_entry(
                            self.current_target,
                            float(ind.close[-1]),
                            float(ind.atr[-1]),
                            score.signal,
                        )

        end_at = _bar_datetime(window.iloc[-1]["datetime"])
        bar_id = f"{self.config.symbol}:{int(window.iloc[-1]['datetime'])}"
        factor_id = f"factor:{bar_id}"
        signal_id = f"signal:{bar_id}"
        target_id = f"target:{bar_id}"
        risk_id = f"risk:{bar_id}"

        quality = FactorQuality.READY
        if any(
            _finite(x) is None
            for x in (ind.ma52[-1], ind.atr[-1], ind.adx[-1], ind.close[-1])
        ):
            quality = FactorQuality.WARMING_UP

        factors = FactorSnapshot(
            factor_snapshot_id=factor_id,
            symbol=self.config.symbol,
            bar_id=bar_id,
            data_as_of=end_at,
            values={
                "close": _finite(ind.close[-1]),
                "ma7": _finite(ind.ma7[-1]),
                "ma14": _finite(ind.ma14[-1]),
                "ma52": _finite(ind.ma52[-1]),
                "atr": _finite(ind.atr[-1]),
                "adx": _finite(ind.adx[-1]),
                "kdj_k": _finite(ind.k[-1]),
                "kdj_d": _finite(ind.d[-1]),
                "kdj_j": _finite(ind.j[-1]),
                "vol_ma": _finite(ind.vol_ma[-1]),
            },
            regime=_legacy_regime(legacy_regime),
            quality=quality,
            factor_version=FACTOR_VERSION,
            reason_codes=("LEGACY_INDICATORS",),
        )

        direction = 0 if score.signal == 0 else (1 if score.signal > 0 else -1)
        signal = SignalEvent(
            signal_id=signal_id,
            factor_snapshot_id=factor_id,
            action=_signal_action(desired=desired, current_target=target_before),
            direction=direction,
            alpha=float(score.signal) / 3.0,
            strength=abs(int(score.signal)) / 3.0,
            confidence=1.0 if quality is FactorQuality.READY else 0.0,
            generated_at=end_at,
            effective_from=end_at,
            expires_at=end_at,
            confirmation_bars=self.config.signal.confirmation_bars,
            reason_codes=(
                f"gv={score.granville}",
                f"vol={score.volume}",
                f"kdj={score.kdj}",
                f"pen={score.conflict_penalty}",
            ),
            model_version=self.config.signal.model_version,
            legacy_signal=int(score.signal),
        )

        desired_position = target_before if desired is None else int(desired)
        target = TargetPosition(
            target_id=target_id,
            signal_id=signal_id,
            symbol=self.config.symbol,
            decision_action=_decision_action(desired, target_before),
            current_position=target_before,
            desired_position=desired_position,
            delta=desired_position - target_before,
            planned_entry_price=_finite(ind.close[-1]),
            planned_stop_price=None,
            stop_distance=None,
            risk_per_lot=None,
            requested_risk=Decimal("0"),
            sizing_method=self.config.sizing.mode,
            reason_codes=("LEGACY_FIXED_LOT",),
            config_version=self.config.config_version,
        )

        if risk_action != LegacyRiskAction.NONE:
            risk_enum = RiskAction.PASS
            approved = 0
            rule_hits = (risk_action.value,)
        elif applied_action == "COOLDOWN_HOLD":
            risk_enum = RiskAction.REJECT
            approved = target_before
            rule_hits = ("COOLDOWN",)
        else:
            risk_enum = RiskAction.PASS
            approved = self.current_target
            rule_hits = ()

        risk_decision = RiskDecision(
            risk_decision_id=risk_id,
            target_id=target_id,
            action=risk_enum,
            requested_position=desired_position,
            approved_position=approved,
            requested_risk=Decimal("0"),
            approved_risk=Decimal("0"),
            rule_hits=rule_hits,
            warnings=(),
            evaluated_at=end_at,
            risk_config_version=self.config.config_version,
            risk_snapshot_id=f"risksnap:{bar_id}",
            legacy_exit_action=LegacyExitAction(risk_action.value),
            cooldown_left=int(self.risk.state.cooldown_left),
            entry_price=_finite(self.risk.state.entry_price)
            if self.risk.state.entry_price is not None
            else None,
            stop_price=_finite(self.risk.state.stop_price)
            if self.risk.state.stop_price is not None
            else None,
            take_price=_finite(self.risk.state.take_price)
            if self.risk.state.take_price is not None
            else None,
        )

        return PipelineResult(
            bar_id=bar_id,
            factors=factors,
            signal=signal,
            target=target,
            risk_decision=risk_decision,
            applied_action=applied_action,
            target_before=target_before,
            target_after=self.current_target,
            sizing_target=desired,
            legacy_score_parts=(
                score.granville,
                score.volume,
                score.kdj,
                score.conflict_penalty,
            ),
        )

    def replay(self, bars: pd.DataFrame) -> list[PipelineResult]:
        self.reset()
        warmup = self.config.factor.warmup_bars
        if len(bars) < warmup:
            raise ValueError(f"need at least {warmup} bars")
        return [
            self.on_bar_window(bars.iloc[: bar_index + 1], bar_index=bar_index)
            for bar_index in range(warmup - 1, len(bars))
        ]

    def characterization_rows(self, bars: pd.DataFrame) -> list[dict[str, Any]]:
        """Project adapter output into Phase 0 golden record shape."""
        from tests.characterization.legacy_harness import _number

        rows: list[dict[str, Any]] = []
        warmup = self.config.factor.warmup_bars
        for offset, result in enumerate(self.replay(bars)):
            bar_index = warmup - 1 + offset
            values = result.factors.values
            gv, vol, kdj, pen = result.legacy_score_parts
            rows.append(
                {
                    "bar_index": bar_index,
                    "datetime": int(bars.iloc[bar_index]["datetime"]),
                    "close": _number(values["close"]),
                    "ma7": _number(values["ma7"]),
                    "ma14": _number(values["ma14"]),
                    "ma52": _number(values["ma52"]),
                    "atr": _number(values["atr"]),
                    "adx": _number(values["adx"]),
                    "kdj_k": _number(values["kdj_k"]),
                    "kdj_d": _number(values["kdj_d"]),
                    "kdj_j": _number(values["kdj_j"]),
                    "vol_ma": _number(values["vol_ma"]),
                    "regime": result.factors.regime.value,
                    "signal": result.signal.legacy_signal,
                    "granville": gv,
                    "volume_score": vol,
                    "kdj_score": kdj,
                    "conflict_penalty": pen,
                    "sizing_target": result.sizing_target,
                    "target_before": result.target_before,
                    "target_after": result.target_after,
                    "applied_action": result.applied_action,
                    "risk_action": result.risk_decision.legacy_exit_action.value,
                    "entry_price": _number(result.risk_decision.entry_price)
                    if result.risk_decision.entry_price is not None
                    else None,
                    "stop_price": _number(result.risk_decision.stop_price)
                    if result.risk_decision.stop_price is not None
                    else None,
                    "take_price": _number(result.risk_decision.take_price)
                    if result.risk_decision.take_price is not None
                    else None,
                    "cooldown_left": result.risk_decision.cooldown_left,
                }
            )
        return rows
