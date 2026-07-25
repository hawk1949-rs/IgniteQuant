"""Typed decision configuration — single source for legacy-compatible parameters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


CONFIG_VERSION = "falcon_legacy_v1"


@dataclass(frozen=True)
class FactorConfig:
    warmup_bars: int = 5
    subscription_bars: int = 400
    ma_fast: int = 7
    ma_mid: int = 14
    ma_slow: int = 52
    atr_period: int = 14
    adx_period: int = 14
    adx_threshold: float = 25.0
    vol_ma_period: int = 20
    kdj_n: int = 9
    kline_seconds: int = 300


@dataclass(frozen=True)
class SignalConfig:
    """Legacy score stays in strategies.falcon.score; thresholds reserved for Phase 6."""

    model_version: str = "falcon_score_legacy_v1"
    confirmation_bars: int = 1
    signal_ttl_bars: int = 1


@dataclass(frozen=True)
class SizingConfig:
    mode: str = "legacy_fixed_lot"
    lot_scale: int = 1
    lot_by_signal: Mapping[int, int] = field(
        default_factory=lambda: {1: 1, 2: 1, 3: 1}
    )


@dataclass(frozen=True)
class RiskConfig:
    """Production entry kwargs used by backtest/sim/runner (not RiskManager class defaults)."""

    sl_atr_mult: float = 1.3
    tp_atr_mult: float = 2.3
    cooldown_bars: int = 4
    max_bar_delay_seconds: float = 30.0
    max_symbol_lots: int = 3


@dataclass(frozen=True)
class DecisionConfig:
    decision_mode: str = "legacy_compatible"
    # intent_legacy: on_entry at target intent (Golden Master)
    # fill_confirmed: EntryContext locked after executor fill poll (Phase 3 runners)
    entry_mode: str = "intent_legacy"
    config_version: str = CONFIG_VERSION
    symbol: str = "KQ.m@SHFE.au"
    factor: FactorConfig = field(default_factory=FactorConfig)
    signal: SignalConfig = field(default_factory=SignalConfig)
    sizing: SizingConfig = field(default_factory=SizingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        # Mapping may not survive asdict cleanly for nested defaults; normalize.
        payload["sizing"]["lot_by_signal"] = {
            str(k): int(v) for k, v in self.sizing.lot_by_signal.items()
        }
        return payload

    def config_hash(self) -> str:
        blob = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def sanitized_snapshot(self) -> dict[str, Any]:
        """Printable runtime snapshot (no credentials; Phase 1 has none here)."""
        data = self.to_dict()
        data["config_hash"] = self.config_hash()
        return data

    def risk_kwargs(self) -> dict[str, float | int]:
        return {
            "sl_atr_mult": self.risk.sl_atr_mult,
            "tp_atr_mult": self.risk.tp_atr_mult,
            "cooldown_bars": self.risk.cooldown_bars,
        }


def default_decision_config() -> DecisionConfig:
    return DecisionConfig()
