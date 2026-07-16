#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Falcon v2 回测入口。

行情状态(ADX) + 格兰维尔/量能/KDJ 评分(-3~3) + 动态手数 + ATR 止盈止损。
- 信号：KQ.m@SHFE.au（沪金主力连续，覆盖 2025-01 ~ 2026-06）
- 交易：跟随 quote.underlying_symbol 的具体交割月（TqSim 不支持连续合约下单）
- Web UI：http://127.0.0.1:9876
- 可选：结束后用 common.backtest_archive 导出桌面对账单 Excel
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from pathlib import Path

from tqsdk import BacktestFinished, TargetPosTask, TqApi, TqAuth, TqBacktest, TqSim

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "strategies") not in sys.path:
    sys.path.insert(0, str(ROOT / "strategies"))

from common.backtest_archive import BacktestArchive
from falcon import (
    RiskAction,
    RiskManager,
    compute_indicators,
    detect_regime,
    lots_from_signal,
    score_signal,
)
from falcon.sizing import LOT_BY_SIGNAL


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
END_DT = datetime.date(2025, 6, 30)
KLINE_SECONDS = 60 * 60
WEB_GUI = ":9876"
# 设为 False 可关闭本次回测的 Excel 存档（模块本身仍可被其它策略接入）
ENABLE_ARCHIVE = True


def last_business_day_on_or_before(d: datetime.date) -> datetime.date:
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


FLAT_DATE = last_business_day_on_or_before(END_DT)


def main() -> None:
    load_dotenv(ROOT / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise SystemExit("缺少 TQ_USER / TQ_PASS，请先配置项目根目录 .env")

    print(f"启动 Falcon v2 回测: 信号={SIGNAL_SYMBOL}", flush=True)
    print(f"区间: {START_DT} ~ {END_DT}（{FLAT_DATE} 起强制清仓）", flush=True)
    print(
        f"仓位映射: {LOT_BY_SIGNAL} | 交易跟主力 underlying | Web UI: http://127.0.0.1{WEB_GUI}",
        flush=True,
    )

    init_balance = 20_000_000
    sim = TqSim(init_balance=init_balance)

    archive: BacktestArchive | None = None
    if ENABLE_ARCHIVE:
        archive = BacktestArchive(
            strategy_name="Falcon v2",
            symbol=SIGNAL_SYMBOL,
            backtest_start=START_DT,
            backtest_end=END_DT,
            init_balance=init_balance,
            sim_account=sim,
        )
        print(f"回测存档已启用，结束后写入: {archive.default_path()}", flush=True)

    api = TqApi(
        sim,
        backtest=TqBacktest(start_dt=START_DT, end_dt=END_DT),
        web_gui=WEB_GUI,
        auth=TqAuth(user, password),
    )

    # 手数放大后略收紧止损、加长冷却，避免单笔回撤与连续亏损叠加
    risk = RiskManager(sl_atr_mult=1.3, tp_atr_mult=2.3, cooldown_bars=4)

    trade_symbol = ""
    target_pos: TargetPosTask | None = None
    position = None
    current_target = 0

    try:
        main_quote = api.get_quote(SIGNAL_SYMBOL)
        klines = api.get_kline_serial(SIGNAL_SYMBOL, KLINE_SECONDS, data_length=400)
        last_progress_day = None
        end_flat_announced = False

        while True:
            api.wait_update()
            if archive is not None:
                archive.poll(api)

            if not api.is_changing(klines.iloc[-1], "datetime"):
                continue

            underlying = str(getattr(main_quote, "underlying_symbol", "") or "")
            if not underlying:
                continue

            # 主力换月：先平旧合约，再切换 TargetPosTask
            if underlying != trade_symbol:
                if target_pos is not None and (current_target != 0 or (position is not None and int(position.pos) != 0)):
                    print(
                        f"主力换月 {trade_symbol} -> {underlying}，先平旧仓",
                        flush=True,
                    )
                    if archive is not None:
                        archive.tag_next(
                            risk.state.entry_signal or 0,
                            note=f"主力换月平仓 {trade_symbol}->{underlying}",
                        )
                    current_target = 0
                    target_pos.set_target_volume(0)
                    risk.on_flat()
                trade_symbol = underlying
                target_pos = TargetPosTask(api, trade_symbol)
                position = api.get_position(trade_symbol)
                print(f"交易合约切换为 {trade_symbol}", flush=True)

            assert target_pos is not None and position is not None

            ind = compute_indicators(klines)
            klines["ma7"] = ind.ma7
            klines["ma14"] = ind.ma14
            klines["ma52"] = ind.ma52
            klines["adx"] = ind.adx
            klines["atr"] = ind.atr
            klines["kdj_k"] = ind.k
            klines["kdj_d"] = ind.d

            dt = datetime.datetime.fromtimestamp(int(klines.iloc[-1]["datetime"]) // 1_000_000_000)
            regime = detect_regime(ind)
            detail = score_signal(ind)
            atr = float(ind.atr[-1]) if ind.atr[-1] == ind.atr[-1] else 0.0
            net_pos = int(position.pos)

            risk.tick_cooldown()

            if last_progress_day != dt.date():
                last_progress_day = dt.date()
                print(
                    f"{dt.date()} 推进 | {trade_symbol} regime={regime.value} "
                    f"signal={detail.signal} ({detail.parts}) target={current_target} "
                    f"net={net_pos} close={ind.close[-1]:.2f}",
                    flush=True,
                )

            # 回测周期最后交易日起：按真实持仓强制平仓，直到净仓为 0
            if dt.date() >= FLAT_DATE:
                if net_pos != 0 or current_target != 0:
                    print(
                        f"{dt} 期末强制平仓 | {trade_symbol} net={net_pos} "
                        f"target={current_target} -> 0",
                        flush=True,
                    )
                    if archive is not None:
                        archive.tag_next(
                            risk.state.entry_signal or detail.signal,
                            regime=regime.value,
                            parts=detail.parts,
                            note="期末强制平仓",
                        )
                    current_target = 0
                    target_pos.set_target_volume(0)
                    risk.on_flat()
                elif not end_flat_announced:
                    print(
                        f"{dt.date()} 已到回测期末且净仓为 0（强制平仓完成）",
                        flush=True,
                    )
                    end_flat_announced = True
                continue

            # 持仓风控优先
            if current_target != 0:
                action = risk.check(
                    current_target,
                    float(ind.high[-1]),
                    float(ind.low[-1]),
                    float(ind.close[-1]),
                )
                if action != RiskAction.NONE:
                    print(
                        f"{dt} 风控{action.value} 清仓 | "
                        f"sl={risk.state.stop_price} tp={risk.state.take_price} atr={atr:.2f}",
                        flush=True,
                    )
                    if archive is not None:
                        archive.tag_next(
                            risk.state.entry_signal,
                            regime=regime.value,
                            parts=detail.parts,
                            note=f"风控{action.value}",
                        )
                    risk.trigger(action)
                    current_target = 0
                    target_pos.set_target_volume(0)
                    continue

            if risk.in_cooldown:
                continue

            desired = lots_from_signal(detail.signal, regime)
            if desired is None or desired == current_target:
                continue

            prev = current_target
            current_target = desired
            if archive is not None:
                archive.tag_next(
                    detail.signal,
                    regime=regime.value,
                    parts=detail.parts,
                    note=f"调仓 {prev}->{current_target}",
                )
            target_pos.set_target_volume(current_target)
            print(
                f"{dt} 调仓 {prev}->{current_target} | {trade_symbol} "
                f"regime={regime.value} signal={detail.signal} ({detail.parts}) atr={atr:.2f}",
                flush=True,
            )

            if current_target == 0:
                risk.on_flat()
            else:
                risk.on_entry(current_target, float(ind.close[-1]), atr, detail.signal)
                print(
                    f"  入场风险 sl={risk.state.stop_price:.2f} tp={risk.state.take_price:.2f}",
                    flush=True,
                )

    except BacktestFinished:
        try:
            final_net = int(api.get_position(trade_symbol).pos) if trade_symbol else 0
        except Exception:
            final_net = current_target
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
                print(f"回测存档写入失败: {exc}", flush=True)
        # web_gui 跑在同一事件循环上：结束后必须继续 wait_update 保活，
        # 不能 time.sleep，否则页面会僵死（Listen 但 HTTP 超时僵死）。
        print(
            "UI 保活中，请刷新 http://127.0.0.1:9876 查看报表；按 Ctrl+C 退出。",
            flush=True,
        )
        try:
            while True:
                try:
                    api.wait_update()
                except BacktestFinished:
                    try:
                        api._loop.run_until_complete(__import__("asyncio").sleep(0.25))
                    except Exception:
                        time.sleep(0.25)
        except KeyboardInterrupt:
            print("退出回测进程。", flush=True)
    finally:
        api.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
