"""TqSim kline-backtest match rules (offline mirror).

Source of truth: tqsdk ``tradeable.sim`` —
market orders fill at ask1 (BUY) / bid1 (SELL); under ``TqBacktest`` without ticks,
quote bid/ask are synthesized as ``last ± price_tick`` from the active kline.

LocalSim uses these helpers so offline fills stay within one tick of TqSim
when fees are also aligned via ``TqSim.set_commission``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class TqKlineQuote:
    """Minimal quote fields needed to mirror TqSim market fills."""

    last_price: float
    price_tick: float
    ask_price1: float | None = None
    bid_price1: float | None = None

    def ask(self) -> float:
        if self.ask_price1 is not None and _finite(self.ask_price1):
            return float(self.ask_price1)
        return float(self.last_price) + float(self.price_tick)

    def bid(self) -> float:
        if self.bid_price1 is not None and _finite(self.bid_price1):
            return float(self.bid_price1)
        return float(self.last_price) - float(self.price_tick)


def quote_from_bar_close(close: float, price_tick: float) -> TqKlineQuote:
    """Synthesize the kline-mode quote TqBacktest builds from a finished bar."""
    tick = float(price_tick)
    last = float(close)
    return TqKlineQuote(
        last_price=last,
        price_tick=tick,
        ask_price1=last + tick,
        bid_price1=last - tick,
    )


def market_fill_price(side: str, quote: TqKlineQuote) -> float:
    """TqSim market-order fill: BUY→ask, SELL→bid."""
    if side.upper() in {"BUY", "LONG", "OPEN_LONG"}:
        return quote.ask()
    return quote.bid()


def tq_align_slip_ticks() -> float:
    """Kline-mode synthetic book is exactly one tick wide; no extra research slip."""
    return 1.0


def metrics_delta(local: Mapping[str, Any], tq: Mapping[str, Any]) -> dict[str, Any]:
    """Numeric deltas for acceptance dashboards (None-safe)."""
    keys = (
        "ror",
        "annual_yield",
        "max_drawdown",
        "sharpe",
        "final_balance",
        "trade_count",
        "winning_rate",
        "profit_loss_ratio",
    )
    out: dict[str, Any] = {}
    for key in keys:
        lv = local.get(key)
        tv = tq.get(key)
        if isinstance(lv, (int, float)) and isinstance(tv, (int, float)):
            out[key] = {
                "local": lv,
                "tq": tv,
                "abs_diff": abs(float(lv) - float(tv)),
                "rel_diff": _rel(float(lv), float(tv)),
            }
        else:
            out[key] = {"local": lv, "tq": tv, "abs_diff": None, "rel_diff": None}
    return out


def within_tolerances(
    local: Mapping[str, Any],
    tq: Mapping[str, Any],
    *,
    ror_abs: float = 0.02,
    max_dd_abs: float = 0.02,
    trade_count_rel: float = 0.15,
    final_balance_rel: float = 0.03,
) -> tuple[bool, list[str]]:
    """Return (ok, failure reasons) for local↔tq alignment gates."""
    failures: list[str] = []
    lm = local if "ror" in local else (local.get("metrics") or {})
    tm = tq if "ror" in tq else (tq.get("metrics") or {})

    if _both_num(lm.get("ror"), tm.get("ror")):
        if abs(float(lm["ror"]) - float(tm["ror"])) > ror_abs:
            failures.append(
                f"ror abs_diff={abs(float(lm['ror']) - float(tm['ror'])):.4f} > {ror_abs}"
            )
    if _both_num(lm.get("max_drawdown"), tm.get("max_drawdown")):
        if abs(float(lm["max_drawdown"]) - float(tm["max_drawdown"])) > max_dd_abs:
            failures.append(
                "max_drawdown abs_diff="
                f"{abs(float(lm['max_drawdown']) - float(tm['max_drawdown'])):.4f} > {max_dd_abs}"
            )
    if _both_num(lm.get("final_balance"), tm.get("final_balance")):
        rel = _rel(float(lm["final_balance"]), float(tm["final_balance"]))
        if rel is not None and rel > final_balance_rel:
            failures.append(f"final_balance rel_diff={rel:.4f} > {final_balance_rel}")
    if _both_num(lm.get("trade_count"), tm.get("trade_count")):
        lt, tt = float(lm["trade_count"]), float(tm["trade_count"])
        base = max(tt, 1.0)
        if abs(lt - tt) / base > trade_count_rel:
            failures.append(
                f"trade_count rel_diff={abs(lt - tt) / base:.4f} > {trade_count_rel}"
            )
    return (not failures, failures)


def _finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def _both_num(a: Any, b: Any) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float))


def _rel(a: float, b: float) -> float | None:
    denom = max(abs(b), 1e-12)
    return abs(a - b) / denom
