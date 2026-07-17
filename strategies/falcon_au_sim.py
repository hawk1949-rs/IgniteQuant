#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Falcon v2 快期模拟盘入口（TqKq）。

与回测共用同一套信号/风控/手数逻辑，差异：
- 账户：TqKq（快期模拟盘，实时行情 + 模拟撮合）
- 无 TqBacktest / 无期末强制平仓
- 信号：KQ.m@SHFE.au；交易：跟随 quote.underlying_symbol
- Web UI：http://127.0.0.1:9876
- Ctrl+C 退出（可选先平仓，见 FLAT_ON_EXIT）
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from pathlib import Path

from tqsdk import TargetPosTask, TqApi, TqAuth, TqKq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "strategies") not in sys.path:
    sys.path.insert(0, str(ROOT / "strategies"))

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
KLINE_SECONDS = 60 * 60
WEB_GUI = ":9876"
# 退出时是否把目标仓位打到 0（模拟盘建议 True，避免残留挂单目标）
FLAT_ON_EXIT = True
# 无新 K 线时，每隔多久打印一次心跳（秒）
HEARTBEAT_SECONDS = 60


def main() -> None:
    load_dotenv(ROOT / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise SystemExit("缺少 TQ_USER / TQ_PASS，请先配置项目根目录 .env")

    print(f"启动 Falcon v2 快期模拟盘: 信号={SIGNAL_SYMBOL}", flush=True)
    print(
        f"账户=TqKq | 仓位映射={LOT_BY_SIGNAL} | "
        f"交易跟主力 underlying | Web UI: http://127.0.0.1{WEB_GUI}",
        flush=True,
    )

    api = TqApi(
        TqKq(),
        web_gui=WEB_GUI,
        auth=TqAuth(user, password),
    )

    risk = RiskManager(sl_atr_mult=1.3, tp_atr_mult=2.3, cooldown_bars=4)

    trade_symbol = ""
    target_pos: TargetPosTask | None = None
    position = None
    current_target = 0
    account = api.get_account()

    try:
        main_quote = api.get_quote(SIGNAL_SYMBOL)
        klines = api.get_kline_serial(SIGNAL_SYMBOL, KLINE_SECONDS, data_length=400)
        last_progress_day = None
        last_heartbeat = 0.0

        # 等首包行情 / 账户
        api.wait_update(deadline=time.time() + 30)
        print(
            f"登录成功 | 权益={account.balance:.2f} 可用={account.available:.2f} "
            f"保证金={account.margin:.2f} 风险度={getattr(account, 'risk_ratio', 0):.2%}",
            flush=True,
        )
        underlying0 = str(getattr(main_quote, "underlying_symbol", "") or "")
        print(
            f"行情就绪 | last={main_quote.last_price} underlying={underlying0 or '-'}",
            flush=True,
        )
        if underlying0:
            trade_symbol = underlying0
            target_pos = TargetPosTask(api, trade_symbol)
            position = api.get_position(trade_symbol)
            print(f"交易合约切换为 {trade_symbol}", flush=True)

            # 启动时对最新已收盘 K 线评估一次，避免干等到下一根 1H 收盘
            ind0 = compute_indicators(klines)
            regime0 = detect_regime(ind0)
            detail0 = score_signal(ind0)
            atr0 = float(ind0.atr[-1]) if ind0.atr[-1] == ind0.atr[-1] else 0.0
            desired0 = lots_from_signal(detail0.signal, regime0)
            print(
                f"启动评估 | regime={regime0.value} signal={detail0.signal} "
                f"({detail0.parts}) desired={desired0} atr={atr0:.2f} "
                f"close={float(ind0.close[-1]):.2f}",
                flush=True,
            )
            if desired0 is not None and desired0 != 0:
                current_target = desired0
                target_pos.set_target_volume(current_target)
                risk.on_entry(current_target, float(ind0.close[-1]), atr0, detail0.signal)
                print(
                    f"启动调仓 0->{current_target} | {trade_symbol} "
                    f"sl={risk.state.stop_price:.2f} tp={risk.state.take_price:.2f}",
                    flush=True,
                )

        while True:
            api.wait_update()
            now = time.time()

            if not api.is_changing(klines.iloc[-1], "datetime"):
                if now - last_heartbeat >= HEARTBEAT_SECONDS:
                    last_heartbeat = now
                    net = int(position.pos) if position is not None else 0
                    print(
                        f"[心跳] {datetime.datetime.now():%H:%M:%S} "
                        f"{trade_symbol or '-'} target={current_target} net={net} "
                        f"balance={account.balance:.2f} last={main_quote.last_price}",
                        flush=True,
                    )
                continue

            last_heartbeat = now
            underlying = str(getattr(main_quote, "underlying_symbol", "") or "")
            if not underlying:
                continue

            # 主力换月：先平旧合约，再切换 TargetPosTask
            if underlying != trade_symbol:
                if target_pos is not None and (
                    current_target != 0
                    or (position is not None and int(position.pos) != 0)
                ):
                    print(
                        f"主力换月 {trade_symbol} -> {underlying}，先平旧仓",
                        flush=True,
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

            dt = datetime.datetime.fromtimestamp(
                int(klines.iloc[-1]["datetime"]) // 1_000_000_000
            )
            regime = detect_regime(ind)
            detail = score_signal(ind)
            atr = float(ind.atr[-1]) if ind.atr[-1] == ind.atr[-1] else 0.0
            net_pos = int(position.pos)

            risk.tick_cooldown()

            if last_progress_day != dt.date():
                last_progress_day = dt.date()
                print(
                    f"{dt.date()} 新交易日 | {trade_symbol} regime={regime.value} "
                    f"signal={detail.signal} ({detail.parts}) target={current_target} "
                    f"net={net_pos} close={ind.close[-1]:.2f}",
                    flush=True,
                )
            else:
                print(
                    f"{dt} K线收盘 | {trade_symbol} regime={regime.value} "
                    f"signal={detail.signal} ({detail.parts}) target={current_target} "
                    f"net={net_pos} close={ind.close[-1]:.2f}",
                    flush=True,
                )

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

    except KeyboardInterrupt:
        print("收到退出信号。", flush=True)
        if FLAT_ON_EXIT and target_pos is not None and current_target != 0:
            print(f"退出前平仓: {trade_symbol} target {current_target} -> 0", flush=True)
            target_pos.set_target_volume(0)
            try:
                api.wait_update(deadline=time.time() + 10)
            except Exception:
                pass
        print(
            f"退出模拟盘 | 合约={trade_symbol or '-'} "
            f"权益={account.balance:.2f} 可用={account.available:.2f}",
            flush=True,
        )
    finally:
        api.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
