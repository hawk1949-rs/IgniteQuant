"""Transaction cost / slippage / roll model (大框架 §9.2)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from typing import Any, Mapping

from ignitequant.analytics.tq_match import market_fill_price, quote_from_bar_close, tq_align_slip_ticks


COST_MODEL_VERSION = "falcon_cost_v1"
# research: optional wider roll slip; tq_kline: mirror TqSim (1 tick both ways)
ALIGN_MODE_RESEARCH = "research"
ALIGN_MODE_TQ_KLINE = "tq_kline"


@dataclass(frozen=True)
class CostModel:
    """Versioned cost assumptions for research / stress (not live broker fees)."""

    version: str = COST_MODEL_VERSION
    multiplier: float = 1000.0  # au contract size
    open_fee_per_lot: float = 10.0
    close_fee_per_lot: float = 10.0
    close_today_fee_per_lot: float = 10.0
    slippage_ticks: float = 1.0
    tick_size: float = 0.02
    roll_slippage_ticks: float = 2.0
    latency_bars: int = 0  # reserved: decision→fill lag in bars
    partial_fill_ratio: float = 1.0  # 1.0 = full fill assumption
    align_mode: str = ALIGN_MODE_TQ_KLINE

    def config_hash(self) -> str:
        blob = json.dumps(asdict(self), sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["config_hash"] = self.config_hash()
        return data

    def slip_price(self, side: str, price: float, *, roll: bool = False) -> float:
        """Fill price relative to signal/last.

        ``tq_kline`` mirrors TqSim market fills on kline-synthesized quotes
        (buy ask = last+tick, sell bid = last-tick). Roll does **not** add
        extra ticks — TqSim has no separate roll slippage.
        """
        if self.align_mode == ALIGN_MODE_TQ_KLINE:
            quote = quote_from_bar_close(price, self.tick_size)
            return market_fill_price(side, quote)
        ticks = self.roll_slippage_ticks if roll else self.slippage_ticks
        slip = ticks * self.tick_size
        if side.upper() in {"BUY", "LONG", "OPEN_LONG"}:
            return price + slip
        return price - slip

    def fee_for(self, *, qty: int, is_open: bool, close_today: bool = False) -> float:
        lots = abs(int(qty))
        if is_open:
            return lots * self.open_fee_per_lot
        if close_today:
            return lots * self.close_today_fee_per_lot
        return lots * self.close_fee_per_lot

    def tq_commission_per_lot(self) -> float:
        """Single per-lot fee for ``TqSim.set_commission`` (open≈close in align mode)."""
        return float(self.open_fee_per_lot)

    def notional(self, price: float, qty: int) -> float:
        return abs(float(price) * int(qty) * self.multiplier)

    def scaled(self, *, fee_mult: float = 1.0, slip_mult: float = 1.0) -> CostModel:
        return CostModel(
            version=f"{self.version}_stress",
            multiplier=self.multiplier,
            open_fee_per_lot=self.open_fee_per_lot * fee_mult,
            close_fee_per_lot=self.close_fee_per_lot * fee_mult,
            close_today_fee_per_lot=self.close_today_fee_per_lot * fee_mult,
            slippage_ticks=self.slippage_ticks * slip_mult,
            tick_size=self.tick_size,
            roll_slippage_ticks=self.roll_slippage_ticks * slip_mult,
            latency_bars=self.latency_bars,
            partial_fill_ratio=self.partial_fill_ratio,
            align_mode=self.align_mode,
        )

    def as_research(self) -> CostModel:
        return CostModel(
            **{
                **asdict(self),
                "align_mode": ALIGN_MODE_RESEARCH,
                "version": f"{self.version}_research",
            }
        )

    def as_tq_kline(self) -> CostModel:
        slip = tq_align_slip_ticks()
        return CostModel(
            **{
                **asdict(self),
                "align_mode": ALIGN_MODE_TQ_KLINE,
                "slippage_ticks": slip,
                "roll_slippage_ticks": slip,
                "version": f"{COST_MODEL_VERSION}_tq_kline",
            }
        )


def default_cost_model() -> CostModel:
    """Default is TqSim kline-aligned (1-tick book, same fee open/close)."""
    return CostModel().as_tq_kline()


def cost_from_mapping(data: Mapping[str, Any] | None) -> CostModel:
    if not data:
        return default_cost_model()
    base = asdict(default_cost_model())
    allowed = {f.name for f in fields(CostModel)}
    for key, value in data.items():
        if key in allowed:
            base[key] = value
    return CostModel(**base)
