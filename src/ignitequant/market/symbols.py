"""Supported instruments for local cache + cost defaults (research approximations)."""

from __future__ import annotations

from dataclasses import dataclass

from ignitequant.analytics.cost_model import CostModel


@dataclass(frozen=True)
class InstrumentSpec:
    id: str
    name: str
    signal_symbol: str  # KQ.m@ continuous
    exchange: str
    multiplier: float
    tick_size: float
    open_fee_per_lot: float = 10.0
    close_fee_per_lot: float = 10.0
    close_today_fee_per_lot: float = 10.0
    slippage_ticks: float = 1.0
    roll_slippage_ticks: float = 2.0


# Four products for the local engine (螺纹 / 沪金 / 沪银 / 玻璃).
INSTRUMENTS: dict[str, InstrumentSpec] = {
    "au": InstrumentSpec(
        id="au",
        name="沪金",
        signal_symbol="KQ.m@SHFE.au",
        exchange="SHFE",
        multiplier=1000.0,
        tick_size=0.02,
        open_fee_per_lot=10.0,
        close_fee_per_lot=10.0,
        close_today_fee_per_lot=10.0,
    ),
    "ag": InstrumentSpec(
        id="ag",
        name="沪银",
        signal_symbol="KQ.m@SHFE.ag",
        exchange="SHFE",
        multiplier=15.0,
        tick_size=1.0,
        open_fee_per_lot=3.0,
        close_fee_per_lot=3.0,
        close_today_fee_per_lot=3.0,
    ),
    "rb": InstrumentSpec(
        id="rb",
        name="螺纹钢",
        signal_symbol="KQ.m@SHFE.rb",
        exchange="SHFE",
        multiplier=10.0,
        tick_size=1.0,
        open_fee_per_lot=3.0,
        close_fee_per_lot=3.0,
        close_today_fee_per_lot=3.0,
    ),
    "fg": InstrumentSpec(
        id="fg",
        name="玻璃",
        signal_symbol="KQ.m@CZCE.FG",
        exchange="CZCE",
        multiplier=20.0,
        tick_size=1.0,
        open_fee_per_lot=3.0,
        close_fee_per_lot=3.0,
        close_today_fee_per_lot=3.0,
    ),
}


def instrument_by_id(symbol_id: str) -> InstrumentSpec:
    key = symbol_id.strip().lower()
    if key not in INSTRUMENTS:
        raise KeyError(f"unsupported instrument id: {symbol_id}")
    return INSTRUMENTS[key]


def instrument_by_signal(signal_symbol: str) -> InstrumentSpec | None:
    for spec in INSTRUMENTS.values():
        if spec.signal_symbol == signal_symbol:
            return spec
    return None


def cost_model_for(spec: InstrumentSpec, *, tq_align: bool = True) -> CostModel:
    """Build cost model for an instrument.

    ``tq_align=True`` (default): mirror TqSim kline backtest — 1-tick synthetic
    book and no extra roll slip. Pass ``tq_align=False`` for research stress
    (wider ``roll_slippage_ticks`` from the instrument table).
    """
    base = CostModel(
        version=f"falcon_cost_v1_{spec.id}",
        multiplier=spec.multiplier,
        open_fee_per_lot=spec.open_fee_per_lot,
        close_fee_per_lot=spec.close_fee_per_lot,
        close_today_fee_per_lot=spec.close_today_fee_per_lot,
        slippage_ticks=spec.slippage_ticks,
        tick_size=spec.tick_size,
        roll_slippage_ticks=spec.roll_slippage_ticks,
    )
    return base.as_tq_kline() if tq_align else base.as_research()
