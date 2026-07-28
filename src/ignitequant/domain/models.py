"""Frozen domain snapshots and decision events (Phase 1 contracts)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from ignitequant.domain.enums import (
    DecisionAction,
    FactorQuality,
    LegacyExitAction,
    Regime,
    RiskAction,
    SignalAction,
)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


@dataclass(frozen=True)
class SerializableMixin:
    def to_dict(self) -> dict[str, Any]:
        return {key: _jsonable(value) for key, value in asdict(self).items()}


@dataclass(frozen=True)
class BarSnapshot(SerializableMixin):
    bar_id: str
    symbol: str
    trading_day: date
    start_at: datetime
    end_at: datetime
    available_at: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    open_oi: int
    close_oi: int
    is_final: bool


@dataclass(frozen=True)
class FactorSnapshot(SerializableMixin):
    factor_snapshot_id: str
    symbol: str
    bar_id: str
    data_as_of: datetime
    values: Mapping[str, float | None]
    regime: Regime
    quality: FactorQuality
    factor_version: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SignalEvent(SerializableMixin):
    signal_id: str
    factor_snapshot_id: str
    action: SignalAction
    direction: int
    alpha: float
    strength: float
    confidence: float
    generated_at: datetime
    effective_from: datetime
    expires_at: datetime
    confirmation_bars: int
    reason_codes: tuple[str, ...]
    model_version: str
    legacy_signal: int


@dataclass(frozen=True)
class TargetPosition(SerializableMixin):
    target_id: str
    signal_id: str
    symbol: str
    decision_action: DecisionAction
    current_position: int
    desired_position: int
    delta: int
    planned_entry_price: float | None
    planned_stop_price: float | None
    stop_distance: float | None
    risk_per_lot: Decimal | None
    requested_risk: Decimal
    sizing_method: str
    reason_codes: tuple[str, ...]
    config_version: str


@dataclass(frozen=True)
class RiskDecision(SerializableMixin):
    risk_decision_id: str
    target_id: str
    action: RiskAction
    requested_position: int
    approved_position: int
    requested_risk: Decimal
    approved_risk: Decimal
    rule_hits: tuple[str, ...]
    warnings: tuple[str, ...]
    evaluated_at: datetime
    risk_config_version: str
    risk_snapshot_id: str
    legacy_exit_action: LegacyExitAction = LegacyExitAction.NONE
    cooldown_left: int = 0
    entry_price: float | None = None
    stop_price: float | None = None
    take_price: float | None = None


@dataclass(frozen=True)
class PipelineResult(SerializableMixin):
    """Phase 1 container; unified engine arrives in Phase 2."""

    bar_id: str
    factors: FactorSnapshot
    signal: SignalEvent
    target: TargetPosition
    risk_decision: RiskDecision
    applied_action: str
    target_before: int
    target_after: int
    sizing_target: int | None
    legacy_score_parts: tuple[int, int, int, int]


@dataclass(frozen=True)
class EntryContext(SerializableMixin):
    """Locked after fill confirmation (Phase 3). Intent-only fields may exist earlier."""

    symbol: str
    side_lots: int
    signal: int
    intent_price: float
    intent_atr: float
    fill_price: float | None
    stop_price: float | None
    take_price: float | None
    confirmed: bool
    opened_at: datetime | None = None


@dataclass(frozen=True)
class OrderIntent(SerializableMixin):
    intent_id: str
    decision_id: str
    symbol: str
    current_position: int
    desired_position: int
    urgency: str
    idempotency_key: str
    created_at: datetime
    reason_codes: tuple[str, ...] = ()
    side: str = ""
    offset: str = ""
    qty: int | None = None
    broker_order_id: str | None = None


@dataclass(frozen=True)
class FillEvent(SerializableMixin):
    fill_id: str
    intent_id: str
    symbol: str
    price: float
    qty: int
    fee: float
    side: str
    trade_time: datetime
    broker_order_id: str | None = None
    broker_trade_id: str | None = None
    multiplier: float | None = None
    realized_pnl: float | None = None


@dataclass(frozen=True)
class PositionSnapshot(SerializableMixin):
    symbol: str
    net_position: int
    long_today: int = 0
    long_yesterday: int = 0
    short_today: int = 0
    short_yesterday: int = 0
    average_entry_price: float | None = None
    unrealized_pnl: float = 0.0
    margin: float = 0.0
    as_of: datetime | None = None


@dataclass(frozen=True)
class AccountSnapshot(SerializableMixin):
    account_id: str
    equity: float
    available: float
    margin: float
    margin_ratio: float
    realized_pnl_today: float = 0.0
    unrealized_pnl: float = 0.0
    strategy_drawdown_pct: float = 0.0
    as_of: datetime | None = None


@dataclass(frozen=True)
class MarketSnapshot(SerializableMixin):
    symbol: str
    last_price: float
    bid_price_1: float | None = None
    ask_price_1: float | None = None
    bid_volume_1: int = 0
    ask_volume_1: int = 0
    spread_ticks: float | None = None
    latest_bar_volume: int = 0
    trade_status: str = "CONTINUOUS"
    is_upper_limit_locked: bool = False
    is_lower_limit_locked: bool = False
    data_age_seconds: float = 0.0
    as_of: datetime | None = None


@dataclass(frozen=True)
class ContractSnapshot(SerializableMixin):
    symbol: str
    exchange_id: str = "SHFE"
    product_id: str = "au"
    multiplier: float = 1000.0
    price_tick: float = 0.02
    margin_rate: float = 0.08
    open_fee: float = 0.0
    close_fee: float = 0.0
    close_today_fee: float = 0.0
    upper_limit: float | None = None
    lower_limit: float | None = None
    expire_at: datetime | None = None
    valid_at: datetime | None = None
    is_valid: bool = True


@dataclass(frozen=True)
class PortfolioSnapshot(SerializableMixin):
    total_open_risk: float = 0.0
    symbol_open_risk: float = 0.0
    gross_exposure: float = 0.0
    margin_after_pending_orders: float = 0.0
    pending_order_count: int = 0
    as_of: datetime | None = None


@dataclass(frozen=True)
class RuntimeSnapshot(SerializableMixin):
    runtime_state: str = "RUNNING"
    reconciliation_matched: bool = True
    unknown_order_count: int = 0
    persistence_healthy: bool = True
    market_gateway_healthy: bool = True
    trade_gateway_healthy: bool = True
    kill_switch_active: bool = False
    roll_in_progress: bool = False
    as_of: datetime | None = None
