"""Cost / delay stress helpers (大框架 §9.3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ignitequant.analytics.attribution import AttributionReport, TradeFillRecord, attribute_fills
from ignitequant.analytics.cost_model import CostModel, default_cost_model


@dataclass(frozen=True)
class StressScenario:
    name: str
    fee_mult: float = 1.0
    slip_mult: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fee_mult": self.fee_mult,
            "slip_mult": self.slip_mult,
        }


DEFAULT_STRESS: tuple[StressScenario, ...] = (
    StressScenario("base", 1.0, 1.0),
    StressScenario("fee_x2", 2.0, 1.0),
    StressScenario("slip_x2", 1.0, 2.0),
    StressScenario("fee_slip_x2", 2.0, 2.0),
    StressScenario("fee_x3_slip_x3", 3.0, 3.0),
)


def run_cost_stress(
    fills: Sequence[TradeFillRecord],
    *,
    base: CostModel | None = None,
    scenarios: Sequence[StressScenario] = DEFAULT_STRESS,
) -> list[dict[str, Any]]:
    model = base or default_cost_model()
    rows: list[dict[str, Any]] = []
    for sc in scenarios:
        stressed = model.scaled(fee_mult=sc.fee_mult, slip_mult=sc.slip_mult)
        report = attribute_fills(fills, cost=stressed)
        rows.append(
            {
                "scenario": sc.to_dict(),
                "cost_model": stressed.to_dict(),
                "attribution": report.to_dict(),
                "net_pnl": report.net_pnl,
                "survives": report.net_pnl > 0,
            }
        )
    return rows


def stress_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"scenarios": 0, "all_survive": False, "worst_net": None}
    nets = [float(r["net_pnl"]) for r in rows]
    return {
        "scenarios": len(rows),
        "all_survive": all(bool(r["survives"]) for r in rows),
        "worst_net": min(nets),
        "best_net": max(nets),
        "base_net": nets[0],
    }
