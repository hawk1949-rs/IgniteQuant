"""Offline Falcon backtest: local cache + RollStateMachine + LocalSimAccount."""

from __future__ import annotations

import datetime as dt
import math
import time
from typing import Any, Callable

import pandas as pd

from ignitequant.analytics import attribute_fills, run_cost_stress, stress_summary
from ignitequant.config import DecisionConfig, default_decision_config
from ignitequant.domain.enums import RiskAction
from ignitequant.engine.decision_pipeline import FalconDecisionPipeline, close_of
from ignitequant.engine.local_sim import LocalSimAccount
from ignitequant.engine.runtime_bridge import (
    apply_pretrade,
    healthy_runtime,
    make_risk_engine,
)
from ignitequant.execution.roll import RollStateMachine
from ignitequant.market.cache import ensure_cache, resolve_instrument
from ignitequant.market.symbols import cost_model_for
import ignitequant as _iq

ProgressCb = Callable[[float, str], None]


def _last_business_day_on_or_before(d: dt.date) -> dt.date:
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _bar_date(ns: int) -> dt.date:
    return dt.datetime.fromtimestamp(int(ns) / 1_000_000_000).date()


def _window(bars: pd.DataFrame, end_idx: int, data_length: int) -> pd.DataFrame:
    start_idx = max(0, end_idx - data_length + 1)
    return bars.iloc[start_idx : end_idx + 1]


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sharpe_from_daily_balances(
    balances: list[float],
    *,
    init_balance: float,
    risk_free_annual: float = 0.025,
    trading_days_of_year: int = 250,
) -> float | None:
    if len(balances) < 2:
        return None
    prev = float(init_balance) if init_balance > 0 else balances[0]
    if prev <= 0:
        return None
    yields: list[float] = []
    for bal in balances:
        if prev <= 0:
            return None
        yields.append(bal / prev - 1.0)
        prev = bal
    if len(yields) < 2:
        return None
    mean = sum(yields) / len(yields)
    var = sum((y - mean) ** 2 for y in yields) / len(yields)
    std = math.sqrt(var)
    if std <= 1e-12:
        return None
    rf_daily = (1.0 + risk_free_annual) ** (1.0 / trading_days_of_year) - 1.0
    return _finite_float(math.sqrt(trading_days_of_year) * (mean - rf_daily) / std)


def _sharpe_fallback(
    *,
    ror: float | None,
    annual_yield: float | None,
    max_drawdown: float | None,
    start: dt.date | None,
    end: dt.date | None,
) -> float | None:
    ay = annual_yield
    if ay is None and ror is not None and start and end and end > start:
        years = max((end - start).days / 365.25, 1 / 365.25)
        ay = (1.0 + float(ror)) ** (1.0 / years) - 1.0
    dd = abs(float(max_drawdown)) if max_drawdown is not None else None
    if ay is None or dd is None or dd < 1e-8:
        return None
    approx = _finite_float((float(ay) - 0.025) / max(dd, 1e-4))
    if approx is None:
        return None
    return max(-5.0, min(5.0, approx))


def run_local_falcon_backtest(
    *,
    signal_symbol: str,
    start: dt.date,
    end: dt.date,
    init_balance: float = 1_000_000,
    kline_seconds: int = 300,
    data_length: int = 400,
    progress_cb: ProgressCb | None = None,
    auto_download: bool = True,
    bars: pd.DataFrame | None = None,
    config: DecisionConfig | None = None,
) -> dict[str, Any]:
    """Mirror dashboard/runners.run_falcon_v2 semantics without tqsdk event loop."""
    flat_date = _last_business_day_on_or_before(end)
    base = default_decision_config()
    cfg = config or DecisionConfig(
        decision_mode=base.decision_mode,
        entry_mode="fill_confirmed",
        config_version=base.config_version,
        symbol=signal_symbol,
        factor=base.factor,
        signal=base.signal,
        sizing=base.sizing,
        risk=base.risk,
    )

    spec = resolve_instrument(signal_symbol)
    cost = cost_model_for(spec)

    if bars is None:
        bars = ensure_cache(
            signal_symbol,
            start=start,
            end=end,
            duration_seconds=kline_seconds,
            auto_download=auto_download,
            progress_cb=progress_cb,
        )
    if bars.empty:
        raise RuntimeError(f"no bars for {signal_symbol}")

    start_ns = int(dt.datetime.combine(start, dt.time.min).timestamp() * 1_000_000_000)
    end_ns = int(
        dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min).timestamp() * 1_000_000_000
    )
    trade_indices = [
        i
        for i in range(len(bars))
        if start_ns <= int(bars.iloc[i]["datetime"]) < end_ns
    ]
    if not trade_indices:
        raise RuntimeError(f"no bars in range {start}..{end} for {signal_symbol}")

    pipeline = FalconDecisionPipeline(cfg)
    risk_engine = make_risk_engine(cfg)
    roll = RollStateMachine()
    sim = LocalSimAccount(init_balance=init_balance, cost=cost)

    trade_symbol = ""
    last_progress_day: dt.date | None = None
    t0 = time.time()
    warmup = max(int(cfg.factor.warmup_bars), int(cfg.factor.ma_slow), 60)

    for i in trade_indices:
        if i + 1 < warmup:
            continue

        row = bars.iloc[i]
        bar_dt = _bar_date(int(row["datetime"]))
        underlying = str(row.get("underlying_symbol") or "").strip()
        if not underlying:
            underlying = signal_symbol.replace("KQ.m@", "LOCAL.")

        close_px = float(row["close"])

        if underlying != trade_symbol:
            if trade_symbol and not roll.in_progress:
                roll.detect(trade_symbol, underlying)
                roll.mark_flattening()

            if trade_symbol:
                net_old = sim.net_pos(trade_symbol)
                if pipeline.current_target != 0 or net_old != 0:
                    pipeline.force_flat()
                    mark_px = sim.marks.get(trade_symbol, close_px)
                    sim.fill_to_target(
                        symbol=trade_symbol,
                        desired=0,
                        signal_price=mark_px,
                        regime="ROLL",
                        is_roll=True,
                        month=bar_dt.strftime("%Y-%m"),
                    )
                    net_old = sim.net_pos(trade_symbol)
                roll.on_old_position(net_old)
                if net_old != 0:
                    sim.mark(trade_symbol, sim.marks.get(trade_symbol, close_px))
                    sim.record_day(bar_dt)
                    continue
                try:
                    roll.complete_switch()
                except RuntimeError:
                    roll.abort_to_idle()

            trade_symbol = underlying
            if roll.in_progress:
                roll.abort_to_idle()

        sim.mark(trade_symbol, close_px)
        window = _window(bars, i, data_length)
        allow_trade = bar_dt < flat_date
        result = pipeline.on_bar_close(window, trade=allow_trade)

        if last_progress_day != bar_dt:
            last_progress_day = bar_dt
            if progress_cb is not None:
                span = max((end - start).days, 1)
                done = max((bar_dt - start).days, 0)
                progress_cb(min(done / span, 0.99), f"{bar_dt} {trade_symbol}")

        net_pos = sim.net_pos(trade_symbol)

        if not allow_trade:
            if net_pos != 0 or pipeline.current_target != 0:
                pipeline.force_flat()
                sim.fill_to_target(
                    symbol=trade_symbol,
                    desired=0,
                    signal_price=close_px,
                    regime=result.factors.regime.value,
                    month=bar_dt.strftime("%Y-%m"),
                )
            sim.record_day(bar_dt)
            continue

        if result.applied_action not in {"STOP_LOSS", "TAKE_PROFIT", "TARGET"}:
            sim.record_day(bar_dt)
            continue

        pretrade = apply_pretrade(
            result,
            net_position=net_pos,
            last_price=close_of(result),
            risk_engine=risk_engine,
            runtime=healthy_runtime(roll_in_progress=roll.in_progress),
            symbol=trade_symbol,
        )
        if pretrade.action in {RiskAction.REJECT, RiskAction.HALT}:
            sim.record_day(bar_dt)
            continue

        desired = (
            0
            if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
            else int(pretrade.approved_position)
        )
        if roll.in_progress and abs(desired) > abs(net_pos):
            sim.record_day(bar_dt)
            continue

        sim.fill_to_target(
            symbol=trade_symbol,
            desired=desired,
            signal_price=close_px,
            regime=result.factors.regime.value,
            is_roll=False,
            month=bar_dt.strftime("%Y-%m"),
        )
        sim.record_day(bar_dt)

    elapsed = time.time() - t0
    if progress_cb is not None:
        progress_cb(1.0, "完成")

    metrics = sim.metrics(start=start, end=end)
    daily = [sim.daily_balances[k] for k in sorted(sim.daily_balances.keys())]
    metrics["sharpe"] = _sharpe_from_daily_balances(daily, init_balance=init_balance)
    if metrics["sharpe"] is None:
        metrics["sharpe"] = _sharpe_fallback(
            ror=metrics.get("ror"),
            annual_yield=metrics.get("annual_yield"),
            max_drawdown=metrics.get("max_drawdown"),
            start=start,
            end=end,
        )

    attribution = attribute_fills(sim.fills, cost=cost)
    stress_rows = run_cost_stress(sim.fills, base=cost) if sim.fills else []
    metrics["gross_pnl_attr"] = attribution.gross_pnl
    metrics["fees_attr"] = attribution.fees
    metrics["net_pnl_attr"] = attribution.net_pnl
    metrics["slippage_attr"] = attribution.slippage_pnl

    return {
        "strategy_id": "falcon_v2",
        "engine": "local",
        "signal_symbol": signal_symbol,
        "trade_symbol": trade_symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "init_balance": init_balance,
        "elapsed_sec": round(elapsed, 2),
        "metrics": metrics,
        "config_version": cfg.config_version,
        "config_hash": cfg.config_hash(),
        "entry_mode": cfg.entry_mode,
        "code_version": getattr(_iq, "__version__", "0.1.0"),
        "cost_model": cost.to_dict(),
        "attribution": attribution.to_dict(),
        "stress": {
            "rows": stress_rows,
            "summary": stress_summary(stress_rows),
        },
        "reproducibility": {
            "config_hash": cfg.config_hash(),
            "cost_model_hash": cost.config_hash(),
            "kline_seconds": kline_seconds,
            "data_length": data_length,
            "entry_mode": cfg.entry_mode,
            "engine": "local",
            "bars": len(bars),
        },
    }
