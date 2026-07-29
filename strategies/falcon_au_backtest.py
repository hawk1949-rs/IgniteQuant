#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Falcon v2 回测入口。

决策核：ignitequant.engine.FalconDecisionPipeline（与模拟盘 / 看板共用）。
执行层：TargetPositionExecutor + RiskEngine（小框架 SOP5 / Phase 3）。
- 信号：KQ.m@SHFE.au
- 交易：跟随 quote.underlying_symbol
- Web UI：http://127.0.0.1:9876
- 可选：结束后用 common.backtest_archive 导出桌面对账单 Excel
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from pathlib import Path

from tqsdk import BacktestFinished, TqApi, TqAuth, TqBacktest, TqSim

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "strategies") not in sys.path:
    sys.path.insert(0, str(ROOT / "strategies"))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from common.backtest_archive import BacktestArchive
from falcon.sizing import LOT_BY_SIGNAL
from ignitequant.config import load_active_decision_config
from ignitequant.engine import (
    FalconDecisionPipeline,
    annotate_klines,
    apply_pretrade,
    atr_of,
    close_of,
    healthy_runtime,
    make_risk_engine,
    score_parts,
)
from ignitequant.execution import TargetPositionExecutor, is_gfd_day_end_cancel
from ignitequant.domain.enums import RiskAction
from ignitequant.market.cache import resolve_instrument
from ignitequant.market.symbols import cost_model_for, resolve_signal_source
from ignitequant.engine.local_replay import run_local_falcon_backtest


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


SIGNAL_SYMBOL = "KQ.m@SHFE.au"
START_DT = datetime.date(2025, 1, 1)
END_DT = datetime.date(2026, 2, 28)
KLINE_SECONDS = 60 * 5  # 5 分钟 K 线
WEB_GUI = ":9876"
INIT_BALANCE = 1_000_000
ENABLE_ARCHIVE = True


def last_business_day_on_or_before(d: datetime.date) -> datetime.date:
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


FLAT_DATE = last_business_day_on_or_before(END_DT)


def main() -> None:
    load_dotenv(ROOT / ".env")

    instrument = resolve_instrument(SIGNAL_SYMBOL)
    source = resolve_signal_source(instrument)
    if source.pricing_basis == "overseas":
        print(
            f"启动 Falcon v2 外盘驱动本地回测: decision={source.decision_symbol} "
            f"exec={SIGNAL_SYMBOL}",
            flush=True,
        )
        print(f"区间: {START_DT} ~ {END_DT}", flush=True)
        out = run_local_falcon_backtest(
            signal_symbol=SIGNAL_SYMBOL,
            start=START_DT,
            end=END_DT,
            init_balance=INIT_BALANCE,
            kline_seconds=KLINE_SECONDS,
            auto_download=True,
            record_decisions=True,
        )
        metrics = out.get("metrics") or {}
        print(
            f"完成 engine={out.get('engine')} decision={out.get('decision_symbol')} "
            f"pricing={out.get('pricing_basis')} "
            f"net_pnl={metrics.get('net_pnl')} trades={metrics.get('trade_count')}",
            flush=True,
        )
        return

    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise SystemExit("缺少 TQ_USER / TQ_PASS，请先配置项目根目录 .env")

    cfg = load_active_decision_config()
    risk_engine = make_risk_engine(cfg)
    cost = cost_model_for(instrument, tq_align=True)
    commission_per_lot = cost.tq_commission_per_lot()
    print(f"启动 Falcon v2 回测: 信号={SIGNAL_SYMBOL}", flush=True)
    print(f"区间: {START_DT} ~ {END_DT}（{FLAT_DATE} 起强制清仓）", flush=True)
    print(
        f"账户初始资金: {INIT_BALANCE:,.0f} | 仓位映射: {LOT_BY_SIGNAL} | "
        f"config={cfg.config_version} hash={cfg.config_hash()[:12]} | "
        f"align={cost.align_mode} fee/lot={commission_per_lot} | "
        f"RiskEngine+Executor | Web UI: http://127.0.0.1{WEB_GUI}",
        flush=True,
    )

    sim = TqSim(init_balance=INIT_BALANCE)
    archive: BacktestArchive | None = None
    if ENABLE_ARCHIVE:
        archive = BacktestArchive(
            strategy_name="Falcon v2",
            symbol=SIGNAL_SYMBOL,
            backtest_start=START_DT,
            backtest_end=END_DT,
            init_balance=INIT_BALANCE,
            sim_account=sim,
        )
        print(f"回测存档已启用，结束后写入: {archive.default_path()}", flush=True)

    api = TqApi(
        sim,
        backtest=TqBacktest(start_dt=START_DT, end_dt=END_DT),
        web_gui=WEB_GUI,
        auth=TqAuth(user, password),
    )

    pipeline = FalconDecisionPipeline(cfg)
    trade_symbol = ""
    executor: TargetPositionExecutor | None = None
    position = None

    try:
        main_quote = api.get_quote(SIGNAL_SYMBOL)
        klines = api.get_kline_serial(SIGNAL_SYMBOL, KLINE_SECONDS, data_length=400)
        last_progress_day = None
        end_flat_announced = False

        while True:
            try:
                api.wait_update()
            except BacktestFinished:
                raise
            except Exception as exc:
                if not is_gfd_day_end_cancel(exc):
                    raise
                if executor is not None and position is not None:
                    try:
                        decision_px = float(klines.iloc[-1]["open"])
                    except Exception:
                        decision_px = None
                    print(
                        f"GFD日终撤单，重建 TargetPosTask | {trade_symbol} "
                        f"net={int(position.pos)} target={pipeline.current_target}",
                        flush=True,
                    )
                    executor.recover_after_gfd_cancel(
                        current_net=int(position.pos),
                        decision_price=decision_px,
                        desired=int(pipeline.current_target),
                    )
                continue

            if archive is not None:
                archive.poll(api)

            if not api.is_changing(klines.iloc[-1], "datetime"):
                continue

            underlying = str(getattr(main_quote, "underlying_symbol", "") or "")
            if not underlying:
                continue

            if underlying != trade_symbol:
                if executor is not None and (
                    pipeline.current_target != 0
                    or (position is not None and int(position.pos) != 0)
                ):
                    print(
                        f"主力换月 {trade_symbol} -> {underlying}，先平旧仓",
                        flush=True,
                    )
                    if archive is not None:
                        archive.tag_next(
                            pipeline.risk.state.entry_signal or 0,
                            note=f"主力换月平仓 {trade_symbol}->{underlying}",
                        )
                    net_old = int(position.pos) if position is not None else 0
                    pipeline.force_flat()
                    executor.set_target(
                        0,
                        decision_id=f"roll:{trade_symbol}",
                        current_net=net_old,
                        urgency="HIGH",
                        reason_codes=("ROLL_IN_PROGRESS",),
                        decision_price=float(klines.iloc[-1]["open"]),
                    )
                    if int(position.pos) != 0:
                        continue
                    executor.destroy()
                trade_symbol = underlying
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
                print(f"交易合约切换为 {trade_symbol}", flush=True)

            assert executor is not None and position is not None

            dt = datetime.datetime.fromtimestamp(
                int(klines.iloc[-1]["datetime"]) // 1_000_000_000
            )
            net_pos = int(position.pos)
            allow_trade = dt.date() < FLAT_DATE
            result = pipeline.on_bar_close(klines, trade=allow_trade)
            annotate_klines(klines, result)
            atr = atr_of(result)
            parts = score_parts(result)

            if last_progress_day != dt.date():
                last_progress_day = dt.date()
                print(
                    f"{dt.date()} 推进 | {trade_symbol} regime={result.factors.regime.value} "
                    f"signal={result.signal.legacy_signal} ({parts}) "
                    f"target={pipeline.current_target} net={net_pos} "
                    f"close={close_of(result):.2f}",
                    flush=True,
                )

            if not allow_trade:
                if net_pos != 0 or pipeline.current_target != 0:
                    print(
                        f"{dt} 期末强制平仓 | {trade_symbol} net={net_pos} "
                        f"target={pipeline.current_target} -> 0",
                        flush=True,
                    )
                    if archive is not None:
                        archive.tag_next(
                            pipeline.risk.state.entry_signal or result.signal.legacy_signal,
                            regime=result.factors.regime.value,
                            parts=parts,
                            note="期末强制平仓",
                        )
                    pipeline.force_flat()
                    executor.set_target(
                        0,
                        decision_id=f"endflat:{result.bar_id}",
                        current_net=net_pos,
                        urgency="HIGH",
                        reason_codes=("END_FLAT",),
                        decision_price=float(klines.iloc[-1]["open"]),
                    )
                elif not end_flat_announced:
                    print(
                        f"{dt.date()} 已到回测期末且净仓为 0（强制平仓完成）",
                        flush=True,
                    )
                    end_flat_announced = True
                continue

            if result.applied_action not in {"STOP_LOSS", "TAKE_PROFIT", "TARGET"}:
                continue

            pretrade = apply_pretrade(
                result,
                net_position=net_pos,
                last_price=close_of(result),
                risk_engine=risk_engine,
                runtime=healthy_runtime(),
                symbol=trade_symbol,
            )
            if pretrade.action in {RiskAction.REJECT, RiskAction.HALT}:
                print(
                    f"{dt} 事前风控{pretrade.action.value} | hits={pretrade.rule_hits}",
                    flush=True,
                )
                continue

            desired = (
                0
                if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                else int(pretrade.approved_position)
            )
            if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}:
                print(
                    f"{dt} 风控{result.applied_action} 清仓 | "
                    f"sl={pipeline.risk.state.stop_price} "
                    f"tp={pipeline.risk.state.take_price} atr={atr:.2f}",
                    flush=True,
                )
                if archive is not None:
                    archive.tag_next(
                        pipeline.risk.state.entry_signal or result.signal.legacy_signal,
                        regime=result.factors.regime.value,
                        parts=parts,
                        note=f"风控{result.applied_action}",
                    )
            elif result.applied_action == "TARGET":
                prev = result.target_before
                if archive is not None:
                    archive.tag_next(
                        result.signal.legacy_signal,
                        regime=result.factors.regime.value,
                        parts=parts,
                        note=f"调仓 {prev}->{desired}",
                    )
                print(
                    f"{dt} 调仓 {prev}->{desired} | {trade_symbol} "
                    f"regime={result.factors.regime.value} "
                    f"signal={result.signal.legacy_signal} ({parts}) atr={atr:.2f}",
                    flush=True,
                )

            executor.set_target(
                desired,
                decision_id=result.bar_id,
                current_net=net_pos,
                urgency="HIGH" if result.applied_action != "TARGET" else "NORMAL",
                reason_codes=pretrade.rule_hits,
                idempotency_key=f"{result.bar_id}:{desired}:{result.applied_action}",
                decision_price=float(klines.iloc[-1]["open"]),
            )
            fill = executor.poll_position(
                int(position.pos),
                last_price=close_of(result),
                atr=atr,
                signal=result.signal.legacy_signal,
            )
            if fill and desired != 0 and executor.state.entry is not None:
                print(
                    f"  成交确认 entry={fill.price:.2f} "
                    f"sl={pipeline.risk.state.stop_price:.2f} "
                    f"tp={pipeline.risk.state.take_price:.2f}",
                    flush=True,
                )

    except BacktestFinished:
        try:
            final_net = int(api.get_position(trade_symbol).pos) if trade_symbol else 0
        except Exception:
            final_net = pipeline.current_target
        print(
            f"回测结束 | 交易合约={trade_symbol or '-'} 最终净仓={final_net}"
            f"（期末强制平仓日={FLAT_DATE}）。",
            flush=True,
        )
        if archive is not None:
            try:
                xlsx = archive.save(api)
                print(
                    f"回测存档已生成（{archive.trade_count} 笔成交）: {xlsx}",
                    flush=True,
                )
            except Exception as exc:
                print(f"回测存档失败: {exc}", flush=True)
        print(
            "Web GUI 保活中（Ctrl+C 退出）。页面: "
            f"http://127.0.0.1{WEB_GUI}",
            flush=True,
        )
        try:
            while True:
                api.wait_update()
        except KeyboardInterrupt:
            print("已退出保活。", flush=True)
    finally:
        api.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
