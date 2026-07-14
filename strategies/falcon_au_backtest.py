#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Falcon：格兰维尔均线战法回测（MA7 / MA14 / MA52）。

标的与区间与 VWAP 回测一致：
- 合约：SHFE.au2606
- 区间：2026-01-01 ~ 2026-05-31
- Web UI：http://127.0.0.1:9876

K 线周期：1 小时（便于回测时钟完整走完区间，并在 web_gui 上观察均线）

规则说明（以 MA52 为主均线，MA7/MA14 作短中期确认）：
买点
1. MA52 由平/降转升，且收盘价上穿 MA52，同时 MA7 > MA14
2. 收盘价在 MA52 上方，回踩接近 MA52（未有效跌破）后再次抬头，且 MA7 > MA14
3. 均线多头排列 MA7 > MA14 > MA52，收盘价重新站上 MA7
卖点（对称）
1. MA52 由平/升转降，且收盘价下穿 MA52，同时 MA7 < MA14
2. 收盘价在 MA52 下方，反抽接近 MA52（未有效突破）后再次回落，且 MA7 < MA14
3. 均线空头排列 MA7 < MA14 < MA52，收盘价重新跌破 MA7
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from pathlib import Path

import numpy as np
from tqsdk import BacktestFinished, TargetPosTask, TqApi, TqAuth, TqBacktest, TqSim


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


SYMBOL = "SHFE.au2606"
START_DT = datetime.date(2026, 1, 1)
END_DT = datetime.date(2026, 5, 31)
POSITION_SIZE = 5
MA_FAST = 7
MA_MID = 14
MA_SLOW = 52
KLINE_SECONDS = 60 * 60  # 1 小时
NEAR_MA_PCT = 0.002
# 项目约定：回测 Web UI 固定本机 9876 端口（见 Ruler.md）
WEB_GUI = ":9876"


def last_business_day_on_or_before(d: datetime.date) -> datetime.date:
    """结束日落在周末时，回退到最后一个交易日再清仓（否则 BacktestFinished 前可能来不及平仓）。"""
    while d.weekday() >= 5:
        d -= datetime.timedelta(days=1)
    return d


# 回测结束前强制清仓的起始交易日
FLAT_DATE = last_business_day_on_or_before(END_DT)


def near(a: float, b: float, pct: float = NEAR_MA_PCT) -> bool:
    if b == 0 or np.isnan(a) or np.isnan(b):
        return False
    return abs(a - b) / abs(b) <= pct


def decide_target(close, ma7, ma14, ma52) -> int | None:
    """返回目标净持仓；None 表示本根 K 不改仓。"""
    if np.isnan(ma52[-1]) or np.isnan(ma52[-2]) or np.isnan(ma52[-3]):
        return None
    if any(np.isnan(x[-1]) or np.isnan(x[-2]) for x in (close, ma7, ma14)):
        return None

    c0, c1 = close[-1], close[-2]
    f0, f1 = ma7[-1], ma7[-2]
    m0 = ma14[-1]
    s0, s1, s2 = ma52[-1], ma52[-2], ma52[-3]

    ma52_turn_up = s1 <= s2 and s0 > s1
    ma52_turn_down = s1 >= s2 and s0 < s1
    cross_up_ma52 = c1 <= s1 and c0 > s0
    cross_down_ma52 = c1 >= s1 and c0 < s0
    pullback_hold = c0 > s0 and near(min(c0, c1), s0) and c0 > c1
    bounce_fail = c0 < s0 and near(max(c0, c1), s0) and c0 < c1
    bull_align = f0 > m0 > s0
    bear_align = f0 < m0 < s0
    reclaim_ma7 = c1 <= f1 and c0 > f0
    lose_ma7 = c1 >= f1 and c0 < f0

    if ma52_turn_up and cross_up_ma52 and f0 > m0:
        return POSITION_SIZE
    if pullback_hold and f0 > m0:
        return POSITION_SIZE
    if bull_align and reclaim_ma7:
        return POSITION_SIZE

    if ma52_turn_down and cross_down_ma52 and f0 < m0:
        return -POSITION_SIZE
    if bounce_fail and f0 < m0:
        return -POSITION_SIZE
    if bear_align and lose_ma7:
        return -POSITION_SIZE

    return None


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise SystemExit("缺少 TQ_USER / TQ_PASS，请先配置项目根目录 .env")

    print(f"启动 Falcon（格兰维尔 MA{MA_FAST}/{MA_MID}/{MA_SLOW}）回测: {SYMBOL}", flush=True)
    print(f"区间: {START_DT} ~ {END_DT}（{FLAT_DATE} 起强制清仓）", flush=True)
    print(f"Web UI: http://127.0.0.1{WEB_GUI}", flush=True)

    api = TqApi(
        TqSim(init_balance=20_000_000),
        backtest=TqBacktest(start_dt=START_DT, end_dt=END_DT),
        web_gui=WEB_GUI,
        auth=TqAuth(user, password),
    )

    try:
        api.get_quote(SYMBOL)
        klines = api.get_kline_serial(SYMBOL, KLINE_SECONDS, data_length=200)
        target_pos = TargetPosTask(api, SYMBOL)
        current_target = 0
        last_progress_day = None

        while True:
            api.wait_update()
            if not api.is_changing(klines.iloc[-1], "datetime"):
                continue

            close = klines.close.to_numpy(dtype=float)
            ma7 = klines.close.rolling(MA_FAST).mean().to_numpy(dtype=float)
            ma14 = klines.close.rolling(MA_MID).mean().to_numpy(dtype=float)
            ma52 = klines.close.rolling(MA_SLOW).mean().to_numpy(dtype=float)

            klines["ma7"] = ma7
            klines["ma14"] = ma14
            klines["ma52"] = ma52

            dt = datetime.datetime.fromtimestamp(int(klines.iloc[-1]["datetime"]) // 1_000_000_000)
            # 无新开平仓时也按日打印进度，避免 web_gui 停在最后一笔成交时误以为卡死
            if last_progress_day != dt.date():
                last_progress_day = dt.date()
                print(
                    f"{dt.date()} 推进中 | 持仓目标={current_target} close={close[-1]:.2f}",
                    flush=True,
                )

            # 回测结束前清仓，并不再接受新信号
            if dt.date() >= FLAT_DATE:
                if current_target != 0:
                    print(f"{dt} 回测结束前清仓 -> 0", flush=True)
                    current_target = 0
                    target_pos.set_target_volume(0)
                continue

            new_target = decide_target(close, ma7, ma14, ma52)
            if new_target is None or new_target == current_target:
                continue

            current_target = new_target
            print(
                f"{dt} 信号目标持仓={current_target} "
                f"close={close[-1]:.2f} ma7={ma7[-1]:.2f} ma14={ma14[-1]:.2f} ma52={ma52[-1]:.2f}",
                flush=True,
            )
            target_pos.set_target_volume(current_target)

    except BacktestFinished:
        print(
            "回测结束（结束前已按约定清仓）。可刷新 http://127.0.0.1:9876 查看报表。",
            flush=True,
        )
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("退出回测进程。", flush=True)
    finally:
        api.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
