# -*- coding: utf-8 -*-
"""Falcon v2 无界面回测引擎（供看板批量调用）。

决策核：FalconDecisionPipeline
执行层：TargetPositionExecutor + RiskEngine（小框架 SOP5 / Phase 3）
"""

from __future__ import annotations

import datetime as dt
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "strategies") not in sys.path:
    sys.path.insert(0, str(ROOT / "strategies"))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ignitequant.analytics import (
    attribute_fills,
    fills_from_tq_trade_log,
    run_cost_stress,
    stress_summary,
)
from ignitequant.analytics.tq_metrics import (
    annual_yield_from_ror,
    sharpe_from_daily_balances,
)
from ignitequant.config import DecisionConfig, default_decision_config
from ignitequant.domain.enums import RiskAction
from ignitequant.engine import (
    FalconDecisionPipeline,
    apply_pretrade,
    atr_of,
    close_of,
    healthy_runtime,
    make_risk_engine,
)
from ignitequant.execution import (
    RollStateMachine,
    TargetPositionExecutor,
    is_gfd_day_end_cancel,
)
from ignitequant.market.cache import resolve_instrument
from ignitequant.market.symbols import cost_model_for
import ignitequant as _iq


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _last_business_day_on_or_before(d: dt.date) -> dt.date:
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


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
    """Annualized Sharpe from end-of-day equity (aligned with tqsdk get_sharp)."""
    return sharpe_from_daily_balances(
        balances,
        init_balance=init_balance,
        risk_free_annual=risk_free_annual,
        trading_days_of_year=trading_days_of_year,
    )


def _balances_from_trade_log(trade_log: Any) -> list[float]:
    if not isinstance(trade_log, dict) or not trade_log:
        return []
    out: list[float] = []
    for day in sorted(trade_log.keys()):
        account = (trade_log.get(day) or {}).get("account") or {}
        bal = _finite_float(account.get("balance"))
        if bal is not None:
            out.append(bal)
    return out


def _sharpe_fallback_from_summary(
    *,
    ror: float | None,
    annual_yield: float | None,
    max_drawdown: float | None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    trading_days: int | None = None,
) -> float | None:
    """When daily equity is unavailable, approximate vol from max drawdown."""
    ay = annual_yield
    if ay is None and ror is not None:
        if trading_days and trading_days > 0:
            ay = annual_yield_from_ror(float(ror), int(trading_days))
        elif start and end and end > start:
            # last-resort calendar estimate only when settle-day count unknown
            years = max((end - start).days / 365.25, 1 / 365.25)
            ay = (1.0 + float(ror)) ** (1.0 / years) - 1.0
    dd = abs(float(max_drawdown)) if max_drawdown is not None else None
    if ay is None or dd is None or dd < 1e-8:
        return None
    # Conservative proxy: treat max drawdown as annualized vol scale.
    vol_ann = max(dd, 1e-4)
    approx = _finite_float((float(ay) - 0.025) / vol_ann)
    if approx is None:
        return None
    # Clamp absurd proxies from tiny-DD short samples.
    return max(-5.0, min(5.0, approx))


def _extract_metrics(
    sim: Any,
    trade_count: int,
    init_balance: float,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    trade_log: Any = None,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "init_balance": init_balance,
        "trade_count": trade_count,
        "ror": None,
        "annual_yield": None,
        "max_drawdown": None,
        "sharpe": None,
        "winning_rate": None,
        "profit_loss_ratio": None,
        "final_balance": None,
    }
    try:
        acc = sim.get_account()
        metrics["final_balance"] = float(getattr(acc, "balance", init_balance))
    except Exception:
        metrics["final_balance"] = init_balance

    stat = getattr(sim, "tqsdk_stat", None) or {}
    # tqsdk field is sharpe_ratio; may be NaN → treat as missing.
    alias = {"sharpe": ("sharpe", "sharpe_ratio")}
    for key in (
        "ror",
        "annual_yield",
        "max_drawdown",
        "sharpe",
        "winning_rate",
        "profit_loss_ratio",
    ):
        candidates = alias.get(key, (key,))
        for src in candidates:
            if src in stat and stat[src] is not None:
                parsed = _finite_float(stat[src])
                if parsed is not None:
                    metrics[key] = parsed
                    break

    if metrics["ror"] is None and metrics["final_balance"] is not None:
        metrics["ror"] = (metrics["final_balance"] - init_balance) / init_balance

    log = trade_log if trade_log is not None else getattr(sim, "trade_log", None)
    balances = _balances_from_trade_log(log)
    if balances:
        metrics["trading_days"] = len(balances)
    if metrics["sharpe"] is None:
        metrics["sharpe"] = _sharpe_from_daily_balances(
            balances,
            init_balance=init_balance,
        )
    if metrics["sharpe"] is None:
        metrics["sharpe"] = _sharpe_fallback_from_summary(
            ror=metrics.get("ror"),
            annual_yield=metrics.get("annual_yield"),
            max_drawdown=metrics.get("max_drawdown"),
            start=start,
            end=end,
            trading_days=metrics.get("trading_days"),
        )
    return metrics


def run_falcon_v2(
    *,
    signal_symbol: str,
    start: dt.date,
    end: dt.date,
    init_balance: float = 1_000_000,
    kline_seconds: int = 300,
    data_length: int = 400,
    progress_cb=None,
) -> dict[str, Any]:
    """跑完一次 Falcon 回测并返回指标（无 web_gui，结束后立即关闭）。"""
    from tqsdk import BacktestFinished, TqApi, TqAuth, TqBacktest, TqSim

    load_dotenv(ROOT / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise RuntimeError("缺少 TQ_USER / TQ_PASS，请配置项目根目录 .env")

    flat_date = _last_business_day_on_or_before(end)
    cfg = DecisionConfig(entry_mode="fill_confirmed")
    # Keep legacy risk/sizing numbers; only entry_mode changes for Phase 3 runners.
    base = default_decision_config()
    cfg = DecisionConfig(
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
    commission_per_lot = cost.tq_commission_per_lot()

    sim = TqSim(init_balance=init_balance)
    api = TqApi(
        sim,
        backtest=TqBacktest(start_dt=start, end_dt=end),
        web_gui=False,
        auth=TqAuth(user, password),
    )

    pipeline = FalconDecisionPipeline(cfg)
    risk_engine = make_risk_engine(cfg)
    roll = RollStateMachine()
    executor: TargetPositionExecutor | None = None
    trade_symbol = ""
    position = None
    trade_events = 0
    t0 = time.time()
    trade_log = None

    try:
        main_quote = api.get_quote(signal_symbol)
        klines = api.get_kline_serial(signal_symbol, kline_seconds, data_length=data_length)
        last_progress_day = None

        while True:
            try:
                api.wait_update()
            except BacktestFinished:
                raise
            except Exception as exc:
                # Hard-pinned limits that never cross the book get GFD-cancelled at
                # settle; TargetPosTask raises 错单 and dies. Rebuild and retry.
                if not is_gfd_day_end_cancel(exc):
                    raise
                if executor is not None and position is not None:
                    try:
                        decision_px = float(klines.iloc[-1]["open"])
                    except Exception:
                        decision_px = None
                    executor.recover_after_gfd_cancel(
                        current_net=int(position.pos),
                        decision_price=decision_px,
                        desired=int(pipeline.current_target),
                    )
                    trade_events += 1
                continue

            if not api.is_changing(klines.iloc[-1], "datetime"):
                continue

            underlying = str(getattr(main_quote, "underlying_symbol", "") or "")
            if not underlying:
                continue

            if underlying != trade_symbol:
                if trade_symbol and not roll.in_progress:
                    roll.detect(trade_symbol, underlying)
                    roll.mark_flattening()

                if executor is not None and trade_symbol:
                    net_old = int(position.pos) if position is not None else 0
                    if pipeline.current_target != 0 or net_old != 0:
                        executor.set_target(
                            0,
                            decision_id=f"roll-flat:{trade_symbol}",
                            current_net=net_old,
                            urgency="HIGH",
                            reason_codes=("ROLL_IN_PROGRESS",),
                            decision_price=float(klines.iloc[-1]["open"]),
                        )
                        pipeline.force_flat()
                        trade_events += 1
                        net_old = int(position.pos)
                    roll.on_old_position(net_old)
                    if net_old != 0:
                        continue
                    try:
                        roll.complete_switch()
                    except RuntimeError:
                        roll.abort_to_idle()
                    executor.destroy()

                trade_symbol = underlying
                # Force TqSim fees onto the same CostModel as LocalSim (align gate).
                try:
                    sim.set_commission(trade_symbol, commission_per_lot)
                except Exception:
                    pass
                executor = TargetPositionExecutor(
                    api,
                    trade_symbol,
                    align_tq_kline=True,
                    price_tick=float(cost.tick_size),
                )
                position = api.get_position(trade_symbol)
                if roll.in_progress:
                    roll.abort_to_idle()

            assert executor is not None and position is not None

            bar_dt = dt.datetime.fromtimestamp(
                int(klines.iloc[-1]["datetime"]) // 1_000_000_000
            )
            # Decision / align fill reference: newly opened bar's open (stub close).
            decision_px = float(klines.iloc[-1]["open"])
            net_pos = int(position.pos)
            allow_trade = bar_dt.date() < flat_date
            result = pipeline.on_bar_close(klines, trade=allow_trade)

            if last_progress_day != bar_dt.date():
                last_progress_day = bar_dt.date()
                if progress_cb is not None:
                    span = max((end - start).days, 1)
                    done = max((bar_dt.date() - start).days, 0)
                    progress_cb(min(done / span, 0.99), f"回测 {bar_dt.date()} {trade_symbol}")

            if not allow_trade:
                if net_pos != 0 or pipeline.current_target != 0:
                    pipeline.force_flat()
                    executor.set_target(
                        0,
                        decision_id=f"flat-date:{result.bar_id}",
                        current_net=net_pos,
                        urgency="HIGH",
                        reason_codes=("END_FLAT",),
                        decision_price=decision_px,
                    )
                    trade_events += 1
                continue

            if result.applied_action not in {"STOP_LOSS", "TAKE_PROFIT", "TARGET"}:
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
                continue

            desired = 0 if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"} else int(
                pretrade.approved_position
            )
            intent = executor.set_target(
                desired,
                decision_id=result.bar_id,
                current_net=net_pos,
                urgency="HIGH" if result.applied_action != "TARGET" else "NORMAL",
                reason_codes=pretrade.rule_hits,
                idempotency_key=f"{result.bar_id}:{desired}:{result.applied_action}",
                decision_price=decision_px,
            )
            if intent is None:
                continue
            trade_events += 1
            # After TargetPosTask, re-read net; confirm fill when matched.
            net_after = int(position.pos)
            executor.poll_position(
                net_after,
                last_price=close_of(result),
                atr=atr_of(result),
                signal=result.signal.legacy_signal,
            )

    except BacktestFinished:
        pass
    finally:
        elapsed = time.time() - t0
        trade_log = getattr(sim, "trade_log", None)
        metrics = _extract_metrics(
            sim,
            trade_events,
            init_balance,
            start=start,
            end=end,
            trade_log=trade_log,
        )
        try:
            n = 0
            if isinstance(trade_log, dict):
                for _day, payload in trade_log.items():
                    trades = (payload or {}).get("trades") or {}
                    n += len(trades)
            if n:
                metrics["trade_count"] = n
        except Exception:
            pass
        api.close()

    if progress_cb is not None:
        progress_cb(1.0, "完成")

    fills = fills_from_tq_trade_log(trade_log, default_symbol=trade_symbol)
    attribution = attribute_fills(fills, cost=cost)
    stress_rows = run_cost_stress(fills, base=cost) if fills else []
    metrics["gross_pnl_attr"] = attribution.gross_pnl
    metrics["fees_attr"] = attribution.fees
    metrics["net_pnl_attr"] = attribution.net_pnl
    metrics["slippage_attr"] = attribution.slippage_pnl

    equity_curve: list[dict[str, Any]] = []
    if isinstance(trade_log, dict):
        for day in sorted(trade_log.keys()):
            account = (trade_log.get(day) or {}).get("account") or {}
            bal = account.get("balance")
            if isinstance(bal, (int, float)):
                equity_curve.append({"t": str(day), "equity": float(bal)})

    return {
        "strategy_id": "falcon_v2",
        "engine": "tq",
        "signal_symbol": signal_symbol,
        "trade_symbol": trade_symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "init_balance": init_balance,
        "elapsed_sec": round(elapsed, 2),
        "metrics": metrics,
        "equity_curve": equity_curve,
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
            "engine": "tq",
            "align_mode": cost.align_mode,
            "tq_commission_per_lot": commission_per_lot,
        },
    }


def run_falcon_local(
    *,
    signal_symbol: str,
    start: dt.date,
    end: dt.date,
    init_balance: float = 1_000_000,
    kline_seconds: int = 300,
    data_length: int = 400,
    progress_cb=None,
    auto_download: bool = True,
) -> dict[str, Any]:
    """本地行情缓存 + 离线回放（含换月 / LocalSim 撮合）。"""
    from ignitequant.engine.local_replay import run_local_falcon_backtest

    return run_local_falcon_backtest(
        signal_symbol=signal_symbol,
        start=start,
        end=end,
        init_balance=init_balance,
        kline_seconds=kline_seconds,
        data_length=data_length,
        progress_cb=progress_cb,
        auto_download=auto_download,
    )


def run_vwap_stub(**kwargs) -> dict[str, Any]:
    raise NotImplementedError("VWAP 看板接入尚未完成，请先用 Falcon v2。")
