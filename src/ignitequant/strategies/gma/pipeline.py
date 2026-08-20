"""GMA decision pipeline — Falcon-compatible ``on_bar_close`` contract."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pandas as pd

from ignitequant.config.decision import DecisionConfig
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
from ignitequant.strategies.gma.config import (
    GMA_FACTOR_VERSION,
    GMARuntimeConfig,
    load_gma_runtime,
)
from ignitequant.strategies.gma.regime import Alignment
from ignitequant.strategies.gma.resample import asof_bundle, resample_bundle
from ignitequant.strategies.gma.signal import generate_signal
from ignitequant.strategies.gma.sizing import apply_hold_flat_and_no_flip, lots_from_gma_signal
from strategies.falcon.risk import RiskAction as LegacyRiskAction
from strategies.falcon.risk import RiskManager

from ignitequant.strategies.falcon.legacy_adapter import (
    _decision_action,
    _finite,
    _signal_action,
)


def _bar_datetime(raw: Any) -> datetime:
    ts = int(raw)
    return datetime.fromtimestamp(ts / 1_000_000_000, tz=timezone.utc)


def _alignment_regime(alignment: Alignment, direction: int) -> Regime:
    if alignment is Alignment.RANGE or direction == 0:
        return Regime.RANGE
    if direction > 0:
        return Regime.TREND_UP
    return Regime.TREND_DOWN


class GMADecisionPipeline:
    """Bar-by-bar GMA core. Same runner-facing surface as FalconDecisionPipeline."""

    def __init__(
        self,
        config: DecisionConfig | None = None,
        runtime: GMARuntimeConfig | None = None,
    ) -> None:
        self.runtime = runtime or load_gma_runtime()
        if config is not None:
            self.runtime = GMARuntimeConfig(
                indicators=self.runtime.indicators,
                decision=config,
            )
        self.config = self.runtime.decision
        self.risk = RiskManager(**self.config.risk_kwargs())
        self.current_target = 0
        self._consecutive_losses = 0
        self._loss_pause_day = None
        self._replay_bundle: dict[str, pd.DataFrame] | None = None

    def reset(self) -> None:
        self.risk = RiskManager(**self.config.risk_kwargs())
        self.current_target = 0
        self._consecutive_losses = 0
        self._loss_pause_day = None
        self._replay_bundle = None

    def clear_replay(self) -> None:
        self._replay_bundle = None

    def prepare_replay(self, bars: pd.DataFrame) -> None:
        """Precompute HTF series once for local cache replay.

        Per-bar ``on_bar_close`` still as-of slices so later 5m bars cannot leak
        into earlier decisions.
        """
        if bars is None or bars.empty:
            self._replay_bundle = None
            return
        self._replay_bundle = resample_bundle(bars)

    @property
    def gma(self) -> GMARuntimeConfig:
        return self.runtime

    def force_flat(self) -> None:
        self.current_target = 0
        self.risk.on_flat()

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
        self.current_target = int(current_target)
        self.risk.state.cooldown_left = max(0, int(cooldown_left))
        self.risk.state.entry_price = entry_price
        self.risk.state.stop_price = stop_price
        self.risk.state.take_price = take_price
        self.risk.state.entry_signal = int(entry_signal or 0)

    def confirm_local_fill(self, price: float, atr: float, signal: int) -> None:
        """Arm SL/TP after LocalSim instant fill (fill_confirmed backtest path)."""
        if self.current_target == 0 or atr <= 0 or not math.isfinite(price):
            return
        self.risk.on_entry(self.current_target, float(price), float(atr), int(signal))

    def on_bar_close(self, klines: pd.DataFrame, *, trade: bool = True) -> PipelineResult:
        return self.on_bar_window(klines, bar_index=len(klines) - 1, trade=trade)

    def on_bar_window(
        self,
        window: pd.DataFrame,
        *,
        bar_index: int,
        trade: bool = True,
    ) -> PipelineResult:
        del bar_index
        bundle = None
        if self._replay_bundle is not None and window is not None and not window.empty:
            bundle = asof_bundle(
                self._replay_bundle,
                last_src_ns=int(window.iloc[-1]["datetime"]),
                first_src_ns=int(window.iloc[0]["datetime"]),
                max_5m=len(window),
            )
        gma_sig = generate_signal(
            window,
            indicators=self.runtime.indicators,
            current_target=self.current_target,
            bundle=bundle,
        )
        lot_map = {int(k): int(v) for k, v in self.config.sizing.lot_by_signal.items()}
        max_lots = int(self.config.risk.max_symbol_lots)
        if gma_sig.desired is None:
            sized = lots_from_gma_signal(
                gma_sig.signal,
                lot_by_signal=lot_map,
                max_lots=max_lots,
            )
            explicit_flat = False
        elif gma_sig.desired == 0:
            sized = 0
            explicit_flat = True
        else:
            sign = 1 if gma_sig.desired > 0 else -1
            sized = sign * min(abs(int(gma_sig.desired)), max_lots)
            explicit_flat = False
        desired = apply_hold_flat_and_no_flip(
            sizing_lots=sized,
            explicit_flat=explicit_flat,
            current_target=self.current_target,
        )

        target_before = self.current_target
        self.risk.tick_cooldown()
        risk_action = LegacyRiskAction.NONE
        applied_action = "HOLD"
        exit_entry = self.risk.state.entry_price
        exit_stop = self.risk.state.stop_price
        exit_take = self.risk.state.take_price

        last_high = float(window.iloc[-1]["high"])
        last_low = float(window.iloc[-1]["low"])
        last_close = float(gma_sig.close if math.isfinite(gma_sig.close) else window.iloc[-1]["close"])
        last_atr = float(gma_sig.atr) if math.isfinite(gma_sig.atr) else 0.0
        bar_day = _bar_datetime(window.iloc[-1]["datetime"]).date()
        if self._loss_pause_day is not None and bar_day != self._loss_pause_day:
            self._consecutive_losses = 0
            self._loss_pause_day = None
        paused = self._consecutive_losses >= self.runtime.indicators.max_consecutive_losses

        if trade:
            if self.current_target != 0:
                risk_action = self.risk.check(
                    self.current_target,
                    last_high,
                    last_low,
                    last_close,
                )
                if risk_action != LegacyRiskAction.NONE:
                    exit_entry = self.risk.state.entry_price
                    exit_stop = self.risk.state.stop_price
                    exit_take = self.risk.state.take_price
                    self.risk.trigger(risk_action)
                    self.current_target = 0
                    applied_action = risk_action.value
                    if risk_action == LegacyRiskAction.STOP_LOSS:
                        self._consecutive_losses += 1
                        self._loss_pause_day = bar_day
                    elif risk_action == LegacyRiskAction.TAKE_PROFIT:
                        self._consecutive_losses = 0

            if risk_action == LegacyRiskAction.NONE:
                if self.risk.in_cooldown or paused:
                    applied_action = "COOLDOWN_HOLD"
                elif desired is not None and desired != self.current_target:
                    self.current_target = desired
                    applied_action = "TARGET"
                    if self.current_target == 0:
                        self.risk.on_flat()
                    elif self.config.entry_mode == "fill_confirmed":
                        pass
                    else:
                        self.risk.on_entry(
                            self.current_target,
                            last_close,
                            last_atr,
                            gma_sig.signal,
                        )

        end_at = _bar_datetime(window.iloc[-1]["datetime"])
        bar_id = f"{self.config.symbol}:{int(window.iloc[-1]['datetime'])}"
        quality = FactorQuality.READY
        if "FACTOR_NOT_READY" in gma_sig.reasons:
            quality = FactorQuality.WARMING_UP

        regime = _alignment_regime(gma_sig.alignment, gma_sig.regime_direction)
        factors = FactorSnapshot(
            factor_snapshot_id=f"factor:{bar_id}",
            symbol=self.config.symbol,
            bar_id=bar_id,
            data_as_of=end_at,
            values={
                "close": _finite(last_close),
                "atr": _finite(last_atr),
                "m15_fast": _finite(gma_sig.m15_fast),
                "m15_slow": _finite(gma_sig.m15_slow),
                "h1_mid": _finite(gma_sig.h1_mid),
                "poc": _finite(gma_sig.poc),
                "vah": _finite(gma_sig.vah),
                "val": _finite(gma_sig.val),
                "alignment": float(
                    {"DRIVE": 3, "DIRECTION": 2, "RANGE": 0}.get(gma_sig.alignment.value, 0)
                ),
            },
            regime=regime,
            quality=quality,
            factor_version=GMA_FACTOR_VERSION,
            reason_codes=gma_sig.reasons,
        )

        direction = 0 if gma_sig.signal == 0 else (1 if gma_sig.signal > 0 else -1)
        signal = SignalEvent(
            signal_id=f"signal:{bar_id}",
            factor_snapshot_id=factors.factor_snapshot_id,
            action=_signal_action(desired=desired, current_target=target_before),
            direction=direction,
            alpha=max(-1.0, min(1.0, float(gma_sig.signal) / 3.0)),
            strength=abs(int(gma_sig.signal)) / 3.0,
            confidence=1.0 if quality is FactorQuality.READY else 0.0,
            generated_at=end_at,
            effective_from=end_at,
            expires_at=end_at,
            confirmation_bars=self.config.signal.confirmation_bars,
            reason_codes=gma_sig.reasons,
            model_version=self.config.signal.model_version,
            legacy_signal=int(gma_sig.signal),
        )

        desired_position = target_before if desired is None else int(desired)
        target = TargetPosition(
            target_id=f"target:{bar_id}",
            signal_id=signal.signal_id,
            symbol=self.config.symbol,
            decision_action=_decision_action(desired, target_before),
            current_position=target_before,
            desired_position=desired_position,
            delta=desired_position - target_before,
            planned_entry_price=_finite(last_close),
            planned_stop_price=None,
            stop_distance=None,
            risk_per_lot=None,
            requested_risk=Decimal("0"),
            sizing_method=self.config.sizing.mode,
            reason_codes=("GMA_FIXED_LOT",),
            config_version=self.config.config_version,
        )

        if risk_action != LegacyRiskAction.NONE:
            risk_enum = RiskAction.PASS
            approved = 0
            rule_hits = (risk_action.value,)
        elif applied_action == "COOLDOWN_HOLD":
            risk_enum = RiskAction.REJECT
            approved = target_before
            rule_hits = ("COOLDOWN",) if self.risk.in_cooldown else ("DAILY_LOSS_LIMIT",)
        else:
            risk_enum = RiskAction.PASS
            approved = self.current_target
            rule_hits = ()

        risk_decision = RiskDecision(
            risk_decision_id=f"risk:{bar_id}",
            target_id=target.target_id,
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
            entry_price=_finite(
                self.risk.state.entry_price
                if self.risk.state.entry_price is not None
                else exit_entry
            ),
            stop_price=_finite(
                self.risk.state.stop_price
                if self.risk.state.stop_price is not None
                else exit_stop
            ),
            take_price=_finite(
                self.risk.state.take_price
                if self.risk.state.take_price is not None
                else exit_take
            ),
        )

        align_code = {"DRIVE": 3, "DIRECTION": 2, "RANGE": 0}.get(gma_sig.alignment.value, 0)
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
                int(align_code),
                int(gma_sig.regime_direction),
                int(gma_sig.signal),
                int(self._consecutive_losses),
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


def annotate_gma_klines(klines: pd.DataFrame, result: PipelineResult) -> None:
    """Attach last-bar GMA levels for web GUI / cockpit overlays."""
    values = result.factors.values
    n = len(klines)
    for key, alias in (
        ("m15_fast", "gma_fast"),
        ("m15_slow", "gma_slow"),
        ("h1_mid", "gma_mid"),
        ("atr", "atr"),
        ("poc", "gma_poc"),
    ):
        col = [float("nan")] * n
        raw = values.get(key)
        if raw is not None:
            col[-1] = float(raw)
        klines[alias] = col


def gma_score_parts(result: PipelineResult) -> str:
    align, direction, signal, losses = result.legacy_score_parts
    return (
        f"align={align} dir={direction} sig={signal} losses={losses} "
        f"=> {result.signal.legacy_signal}"
    )
