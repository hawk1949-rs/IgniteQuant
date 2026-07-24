"""Offline Falcon backtest: local cache + RollStateMachine + LocalSimAccount."""

from __future__ import annotations

import datetime as dt
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
from ignitequant.market.trading_day import trading_day_from_timestamp_ns
import ignitequant as _iq

ProgressCb = Callable[[float, str], None]


def _last_business_day_on_or_before(d: dt.date) -> dt.date:
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def _window(bars: pd.DataFrame, end_idx: int, data_length: int) -> pd.DataFrame:
    start_idx = max(0, end_idx - data_length + 1)
    return bars.iloc[start_idx : end_idx + 1]


def _tq_datetime_change_window(bars: pd.DataFrame, end_idx: int, data_length: int) -> pd.DataFrame:
    """Build the kline window Falcon sees under TqBacktest ``is_changing(datetime)``.

    History bars keep completed OHLC; the decision bar is collapsed to an open stub
    (o=h=l=c=open, volume=0), matching Tq's newly opened last bar.
    """
    window = _window(bars, end_idx, data_length).copy()
    if window.empty:
        return window
    open_px = float(window.iloc[-1]["open"])
    window.iloc[-1, window.columns.get_loc("high")] = open_px
    window.iloc[-1, window.columns.get_loc("low")] = open_px
    window.iloc[-1, window.columns.get_loc("close")] = open_px
    if "volume" in window.columns:
        window.iloc[-1, window.columns.get_loc("volume")] = 0
    return window


def _record_settle_day(
    sim: LocalSimAccount,
    *,
    symbol: str,
    settle_day: dt.date,
    mark_price: float,
) -> None:
    """Write EOD equity using completed-bar close (TqSim settle last_price)."""
    if symbol:
        sim.mark(symbol, float(mark_price))
    sim.record_day(settle_day)


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
    record_decisions: bool = False,
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
    cost = cost_model_for(spec, tq_align=True)

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
    # Match TqSim trade_log: first settle day carries init pre_balance.
    sim.record_day(start)

    trade_symbol = ""
    last_progress_day: dt.date | None = None
    t0 = time.time()
    # Respect profile warmup; do not force ma_slow/60 floor (smoke/test may use warmup=5).
    warmup = max(int(cfg.factor.warmup_bars), 1)
    decisions: list[dict[str, Any]] = []

    for i in trade_indices:
        if i + 1 < warmup:
            continue

        row = bars.iloc[i]
        bar_ns = int(row["datetime"])
        # TQ decision gate uses wall-clock date (same as dashboard/runners).
        calendar_day = dt.datetime.fromtimestamp(bar_ns // 1_000_000_000).date()
        # TqSim trade_log / TqReport settle on exchange trading day.
        settle_day = trading_day_from_timestamp_ns(bar_ns)
        # TqBacktest(end_dt=end) stops at that trading day's settle — exclude later nights.
        if settle_day > end:
            continue
        underlying = str(row.get("underlying_symbol") or "").strip()
        if not underlying:
            underlying = signal_symbol.replace("KQ.m@", "LOCAL.")

        close_px = float(row["close"])
        # Tq decides on datetime-change using the new bar's open as last/close.
        decision_px = float(row["open"])

        if underlying != trade_symbol:
            if trade_symbol and not roll.in_progress:
                roll.detect(trade_symbol, underlying)
                roll.mark_flattening()

            if trade_symbol:
                net_old = sim.net_pos(trade_symbol)
                if pipeline.current_target != 0 or net_old != 0:
                    pipeline.force_flat()
                    mark_px = sim.marks.get(trade_symbol, decision_px)
                    sim.fill_to_target(
                        symbol=trade_symbol,
                        desired=0,
                        signal_price=mark_px,
                        regime="ROLL",
                        is_roll=True,
                        month=settle_day.strftime("%Y-%m"),
                    )
                    net_old = sim.net_pos(trade_symbol)
                roll.on_old_position(net_old)
                if net_old != 0:
                    _record_settle_day(
                        sim,
                        symbol=trade_symbol,
                        settle_day=settle_day,
                        mark_price=close_px,
                    )
                    continue
                try:
                    roll.complete_switch()
                except RuntimeError:
                    roll.abort_to_idle()

            trade_symbol = underlying
            if roll.in_progress:
                roll.abort_to_idle()

        sim.mark(trade_symbol, decision_px)
        window = _tq_datetime_change_window(bars, i, data_length)
        allow_trade = calendar_day < flat_date
        result = pipeline.on_bar_close(window, trade=allow_trade)

        if last_progress_day != calendar_day:
            last_progress_day = calendar_day
            if progress_cb is not None:
                span = max((end - start).days, 1)
                done = max((calendar_day - start).days, 0)
                progress_cb(
                    min(0.36 + 0.63 * (done / span), 0.99),
                    f"回测 {calendar_day} {trade_symbol}",
                )

        net_pos = sim.net_pos(trade_symbol)

        if not allow_trade:
            if net_pos != 0 or pipeline.current_target != 0:
                pipeline.force_flat()
                sim.fill_to_target(
                    symbol=trade_symbol,
                    desired=0,
                    signal_price=decision_px,
                    regime=result.factors.regime.value,
                    month=settle_day.strftime("%Y-%m"),
                )
            _record_settle_day(
                sim, symbol=trade_symbol, settle_day=settle_day, mark_price=close_px
            )
            continue

        if result.applied_action not in {"STOP_LOSS", "TAKE_PROFIT", "TARGET"}:
            _record_settle_day(
                sim, symbol=trade_symbol, settle_day=settle_day, mark_price=close_px
            )
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
            _record_settle_day(
                sim, symbol=trade_symbol, settle_day=settle_day, mark_price=close_px
            )
            continue

        desired = (
            0
            if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
            else int(pretrade.approved_position)
        )
        if roll.in_progress and abs(desired) > abs(net_pos):
            _record_settle_day(
                sim, symbol=trade_symbol, settle_day=settle_day, mark_price=close_px
            )
            continue

        before = sim.net_pos(trade_symbol)
        sim.fill_to_target(
            symbol=trade_symbol,
            desired=desired,
            signal_price=decision_px,
            regime=result.factors.regime.value,
            is_roll=False,
            month=settle_day.strftime("%Y-%m"),
        )
        if record_decisions and before != desired:
            decisions.append(
                {
                    "bar_id": result.bar_id,
                    "day": settle_day.isoformat(),
                    "calendar_day": calendar_day.isoformat(),
                    "symbol": trade_symbol,
                    "action": result.applied_action,
                    "desired": desired,
                    "net_before": before,
                    "close": decision_px,
                    "bar_close": close_px,
                }
            )
        _record_settle_day(
            sim, symbol=trade_symbol, settle_day=settle_day, mark_price=close_px
        )

    elapsed = time.time() - t0
    if progress_cb is not None:
        progress_cb(1.0, "完成")

    metrics = sim.metrics(start=start, end=end)

    attribution = attribute_fills(sim.fills, cost=cost)
    stress_rows = run_cost_stress(sim.fills, base=cost) if sim.fills else []
    metrics["gross_pnl_attr"] = attribution.gross_pnl
    metrics["fees_attr"] = attribution.fees
    metrics["net_pnl_attr"] = attribution.net_pnl
    metrics["slippage_attr"] = attribution.slippage_pnl

    out: dict[str, Any] = {
        "strategy_id": "falcon_v2",
        "engine": "local",
        "signal_symbol": signal_symbol,
        "trade_symbol": trade_symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "init_balance": init_balance,
        "elapsed_sec": round(elapsed, 2),
        "metrics": metrics,
        "equity_curve": [
            {"t": day, "equity": float(bal)}
            for day, bal in sorted(sim.daily_balances.items())
        ],
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
            "align_mode": cost.align_mode,
            "bars": len(bars),
        },
    }
    if record_decisions:
        out["decisions"] = decisions
        out["fills"] = [
            {
                "trade_id": f.trade_id,
                "symbol": f.symbol,
                "side": f.side,
                "offset": f.offset,
                "price": f.price,
                "qty": f.qty,
                "fee": f.fee,
                "signal_price": f.signal_price,
                "is_roll": f.is_roll,
            }
            for f in sim.fills
        ]
    return out
