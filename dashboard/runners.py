# -*- coding: utf-8 -*-
"""Falcon v2 无界面回测引擎（供看板批量调用）。"""

from __future__ import annotations

import datetime as dt
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

from falcon import (  # noqa: E402
    RiskAction,
    RiskManager,
    compute_indicators,
    detect_regime,
    lots_from_signal,
    score_signal,
)


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


def _extract_metrics(sim: Any, trade_count: int, init_balance: float) -> dict[str, Any]:
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
    stat = getattr(sim, "tqsdk_stat", None)
    if isinstance(stat, dict):
        for k in (
            "ror",
            "annual_yield",
            "max_drawdown",
            "sharpe",
            "winning_rate",
            "profit_loss_ratio",
        ):
            if k in stat:
                try:
                    metrics[k] = float(stat[k])
                except Exception:
                    pass
        if "balance" in stat:
            try:
                metrics["final_balance"] = float(stat["balance"])
            except Exception:
                pass
    if metrics["final_balance"] is None:
        try:
            # 兜底：从 trade_log 末日权益
            trade_log = getattr(sim, "trade_log", None)
            if isinstance(trade_log, dict) and trade_log:
                last_day = sorted(trade_log.keys())[-1]
                acc = (trade_log[last_day] or {}).get("account") or {}
                if "balance" in acc:
                    metrics["final_balance"] = float(acc["balance"])
        except Exception:
            pass
    if metrics["ror"] is None and metrics["final_balance"] is not None and init_balance:
        metrics["ror"] = (metrics["final_balance"] - init_balance) / init_balance
    return metrics


def run_falcon_v2(
    *,
    signal_symbol: str,
    start: dt.date,
    end: dt.date,
    init_balance: float = 1_000_000,
    kline_seconds: int = 3600,
    data_length: int = 400,
    progress_cb=None,
) -> dict[str, Any]:
    """跑完一次 Falcon 回测并返回指标（无 web_gui，结束后立即关闭）。"""
    from tqsdk import BacktestFinished, TargetPosTask, TqApi, TqAuth, TqBacktest, TqSim

    load_dotenv(ROOT / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise RuntimeError("缺少 TQ_USER / TQ_PASS，请配置项目根目录 .env")

    flat_date = _last_business_day_on_or_before(end)
    sim = TqSim(init_balance=init_balance)
    api = TqApi(
        sim,
        backtest=TqBacktest(start_dt=start, end_dt=end),
        web_gui=False,
        auth=TqAuth(user, password),
    )

    risk = RiskManager(sl_atr_mult=1.3, tp_atr_mult=2.3, cooldown_bars=4)
    trade_symbol = ""
    target_pos: TargetPosTask | None = None
    position = None
    current_target = 0
    trade_events = 0
    t0 = time.time()

    try:
        main_quote = api.get_quote(signal_symbol)
        klines = api.get_kline_serial(signal_symbol, kline_seconds, data_length=data_length)
        last_progress_day = None

        while True:
            api.wait_update()
            if not api.is_changing(klines.iloc[-1], "datetime"):
                continue

            underlying = str(getattr(main_quote, "underlying_symbol", "") or "")
            if not underlying:
                continue

            if underlying != trade_symbol:
                if target_pos is not None and (
                    current_target != 0
                    or (position is not None and int(position.pos) != 0)
                ):
                    current_target = 0
                    target_pos.set_target_volume(0)
                    risk.on_flat()
                    trade_events += 1
                trade_symbol = underlying
                target_pos = TargetPosTask(api, trade_symbol)
                position = api.get_position(trade_symbol)

            assert target_pos is not None and position is not None

            ind = compute_indicators(klines)
            bar_dt = dt.datetime.fromtimestamp(int(klines.iloc[-1]["datetime"]) // 1_000_000_000)
            regime = detect_regime(ind)
            detail = score_signal(ind)
            atr = float(ind.atr[-1]) if ind.atr[-1] == ind.atr[-1] else 0.0
            net_pos = int(position.pos)
            risk.tick_cooldown()

            if last_progress_day != bar_dt.date():
                last_progress_day = bar_dt.date()
                if progress_cb is not None:
                    # 粗略进度：按日历跨度
                    span = max((end - start).days, 1)
                    done = max((bar_dt.date() - start).days, 0)
                    progress_cb(min(done / span, 0.99), f"{bar_dt.date()} {trade_symbol}")

            if bar_dt.date() >= flat_date:
                if net_pos != 0 or current_target != 0:
                    current_target = 0
                    target_pos.set_target_volume(0)
                    risk.on_flat()
                    trade_events += 1
                continue

            if current_target != 0:
                action = risk.check(
                    current_target,
                    float(ind.high[-1]),
                    float(ind.low[-1]),
                    float(ind.close[-1]),
                )
                if action != RiskAction.NONE:
                    risk.trigger(action)
                    current_target = 0
                    target_pos.set_target_volume(0)
                    trade_events += 1
                    continue

            if risk.in_cooldown:
                continue

            desired = lots_from_signal(detail.signal, regime)
            if desired is None or desired == current_target:
                continue

            current_target = desired
            target_pos.set_target_volume(current_target)
            trade_events += 1
            if current_target == 0:
                risk.on_flat()
            else:
                risk.on_entry(current_target, float(ind.close[-1]), atr, detail.signal)

    except BacktestFinished:
        pass
    finally:
        elapsed = time.time() - t0
        metrics = _extract_metrics(sim, trade_events, init_balance)
        # 成交笔数优先用 tqsdk 统计若可得
        try:
            # 粗算：trade_log 里成交条数
            n = 0
            trade_log = getattr(sim, "trade_log", None)
            if isinstance(trade_log, dict):
                for day, payload in trade_log.items():
                    trades = (payload or {}).get("trades") or {}
                    n += len(trades)
            if n:
                metrics["trade_count"] = n
        except Exception:
            pass
        api.close()

    if progress_cb is not None:
        progress_cb(1.0, "完成")

    return {
        "strategy_id": "falcon_v2",
        "signal_symbol": signal_symbol,
        "trade_symbol": trade_symbol,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "init_balance": init_balance,
        "elapsed_sec": round(elapsed, 2),
        "metrics": metrics,
    }


def run_vwap_stub(**kwargs) -> dict[str, Any]:
    raise NotImplementedError("VWAP 看板接入尚未完成，请先用 Falcon v2。")
