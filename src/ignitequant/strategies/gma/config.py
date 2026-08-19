"""GMA strategy configuration — independent of Falcon profiles."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from ignitequant.config.decision import (
    DecisionConfig,
    FactorConfig,
    RiskConfig,
    SignalConfig,
    SizingConfig,
)

ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = ROOT / "configs" / "gma"
DEFAULT_PROFILE = "gma_v1"
GMA_CONFIG_VERSION = "gma_v1"
GMA_MODEL_VERSION = "gma_signal_v1"
GMA_FACTOR_VERSION = "gma_factors_v1"
# 4H HMA(90) needs ~90 completed 4H bars ≈ 4320 5m bars; keep extra for session gaps.
GMA_CACHE_WARMUP_BARS = 8000


@dataclass(frozen=True)
class GMAIndicatorConfig:
    """Documented GMA / MT4 parameters (10W reconstruction uses HMA 20/90)."""

    fast_period: int = 20
    slow_period: int = 90
    keltner_length: int = 14
    keltner_inner_atr: float = 1.5
    keltner_outer_atr: float = 2.5
    accel_length: int = 20
    accel_atr: float = 2.4
    stoch_k: int = 5
    stoch_d: int = 3
    stoch_slowing: int = 2
    stoch_overbought: float = 80.0
    stoch_oversold: float = 20.0
    rkk_period: int = 21
    donchian_mid: int = 444
    donchian_long: int = 1600
    vp_lookback_15m: int = 96
    vp_bins: int = 48
    vp_value_pct: float = 0.70
    pullback_near_pct: float = 0.002
    breakout_lookback: int = 20
    bias_atr_mult: float = 4.0
    max_consecutive_losses: int = 2
    energy_enabled: bool = False


@dataclass(frozen=True)
class GMARuntimeConfig:
    indicators: GMAIndicatorConfig
    decision: DecisionConfig

    def to_dict(self) -> dict[str, Any]:
        return {
            "indicators": asdict(self.indicators),
            "decision": self.decision.to_dict(),
        }


def default_gma_decision_config() -> DecisionConfig:
    return DecisionConfig(
        decision_mode="gma_v1",
        entry_mode="intent_legacy",
        config_version=GMA_CONFIG_VERSION,
        symbol="KQ.m@SHFE.au",
        factor=FactorConfig(
            warmup_bars=200,
            subscription_bars=8000,
            ma_fast=20,
            ma_mid=14,
            ma_slow=90,
            atr_period=14,
            adx_period=14,
            adx_threshold=25.0,
            vol_ma_period=20,
            kdj_n=9,
            kline_seconds=300,
        ),
        signal=SignalConfig(
            model_version=GMA_MODEL_VERSION,
            confirmation_bars=1,
            signal_ttl_bars=1,
        ),
        sizing=SizingConfig(
            mode="gma_fixed_lot",
            lot_scale=1,
            lot_by_signal={1: 1, 2: 1, 3: 2},
        ),
        risk=RiskConfig(
            sl_atr_mult=1.3,
            tp_atr_mult=2.3,
            cooldown_bars=4,
            max_bar_delay_seconds=30.0,
            max_symbol_lots=2,
        ),
    )


def default_gma_runtime() -> GMARuntimeConfig:
    return GMARuntimeConfig(
        indicators=GMAIndicatorConfig(),
        decision=default_gma_decision_config(),
    )


def _decision_from_dict(data: Mapping[str, Any]) -> DecisionConfig:
    base = default_gma_decision_config()
    factor = FactorConfig(**{**asdict(base.factor), **(data.get("factor") or {})})
    signal = SignalConfig(**{**asdict(base.signal), **(data.get("signal") or {})})
    sizing_raw = {**asdict(base.sizing), **(data.get("sizing") or {})}
    lots = sizing_raw.get("lot_by_signal") or dict(base.sizing.lot_by_signal)
    sizing_raw["lot_by_signal"] = {int(k): int(v) for k, v in dict(lots).items()}
    sizing = SizingConfig(**sizing_raw)
    risk = RiskConfig(**{**asdict(base.risk), **(data.get("risk") or {})})
    return DecisionConfig(
        decision_mode=str(data.get("decision_mode") or "gma_v1"),
        entry_mode=str(data.get("entry_mode") or base.entry_mode),
        config_version=str(data.get("config_version") or GMA_CONFIG_VERSION),
        symbol=str(data.get("symbol") or base.symbol),
        factor=factor,
        signal=signal,
        sizing=sizing,
        risk=risk,
    )


def load_gma_runtime(profile_id: str | None = None) -> GMARuntimeConfig:
    pid = (profile_id or DEFAULT_PROFILE).strip() or DEFAULT_PROFILE
    path = PROFILES_DIR / f"{pid}.json"
    if not path.is_file():
        return default_gma_runtime()
    data = json.loads(path.read_text(encoding="utf-8"))
    indicators = GMAIndicatorConfig(
        **{**asdict(GMAIndicatorConfig()), **(data.get("indicators") or {})}
    )
    return GMARuntimeConfig(
        indicators=indicators,
        decision=_decision_from_dict(data),
    )
