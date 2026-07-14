#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""沪金 VWAP 回测（带 web_gui）。

基于天勤官方 VWAP 示例改造：
- 品种：沪金 SHFE.au2606（覆盖 2026-01 ~ 2026-05 交易时段）
- 周期：2026-01-01 ~ 2026-05-31
- 每个交易日在预设时段按历史量能分布调仓，时段结束后平仓，便于多日观察
"""

from __future__ import annotations

import datetime
import os
import time
from pathlib import Path

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


TIME_CELL = 5 * 60
TARGET_VOLUME = 5  # 沪金单手保证金较高，回测先用较小目标手数
SYMBOL = "SHFE.au2606"
HISTORY_DAY_LENGTH = 20
# 沪金日盘第一节约 09:00-10:15，窗口避开休息时段
START_HOUR, START_MINUTE = 9, 0
END_HOUR, END_MINUTE = 10, 15
START_DT = datetime.date(2026, 1, 1)
END_DT = datetime.date(2026, 5, 31)
# 项目约定：回测 Web UI 固定本机 9876 端口（见 Ruler.md）
WEB_GUI = ":9876"


def get_kline_time(kline_datetime: int) -> datetime.time:
    return datetime.datetime.fromtimestamp(kline_datetime // 1000000000).time()


def get_market_day(kline_datetime: int) -> datetime.date:
    kline_dt = datetime.datetime.fromtimestamp(kline_datetime // 1000000000)
    if kline_dt.hour >= 18:
        kline_dt = kline_dt + datetime.timedelta(days=1)
    while kline_dt.weekday() >= 5:
        kline_dt = kline_dt + datetime.timedelta(days=1)
    return kline_dt.date()


def build_predicted_volume(klines) -> dict:
    time_slot_start = datetime.time(START_HOUR, START_MINUTE)
    time_slot_end = datetime.time(END_HOUR, END_MINUTE)

    hist = klines.copy()
    hist["time"] = hist.datetime.apply(get_kline_time)
    hist["date"] = hist.datetime.apply(get_market_day)

    if time_slot_end > time_slot_start:
        hist = hist[(hist["time"] >= time_slot_start) & (hist["time"] <= time_slot_end)]
    else:
        hist = hist[(hist["time"] >= time_slot_start) | (hist["time"] <= time_slot_end)]

    date_cnt = hist["date"].value_counts()
    if date_cnt.empty:
        raise RuntimeError("预设时段内没有可用历史 K 线，请调整交易时段或合约。")

    max_num = date_cnt.max()
    need_date = date_cnt[date_cnt == max_num].sort_index().index[-HISTORY_DAY_LENGTH - 1 : -1]
    df = hist[hist["date"].isin(need_date)]
    if df.empty:
        raise RuntimeError("历史样本交易日不足，无法估算成交量占比。")

    datetime_grouped = df.groupby(["date", "time"])["volume"].sum()
    volume_percent = datetime_grouped / datetime_grouped.groupby(level=0).sum()
    predicted_percent = volume_percent.groupby(level=1).mean()
    print("各时间单元成交量占比:")
    print(predicted_percent)

    predicted_volume = {}
    percentage_left = 1.0
    volume_left = TARGET_VOLUME
    for index, value in predicted_percent.items():
        if percentage_left <= 0:
            predicted_volume[index] = 0
            continue
        volume = round(volume_left * (value / percentage_left))
        predicted_volume[index] = volume
        percentage_left -= value
        volume_left -= volume
    print("各时间单元应下单手数:")
    print(predicted_volume)
    return predicted_volume


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise SystemExit("缺少 TQ_USER / TQ_PASS，请先配置项目根目录 .env")

    print(f"启动沪金 VWAP 回测: {SYMBOL}")
    print(f"区间: {START_DT} ~ {END_DT}")
    print(f"Web UI: http://127.0.0.1{WEB_GUI}")

    api = TqApi(
        TqSim(init_balance=20_000_000),
        backtest=TqBacktest(start_dt=START_DT, end_dt=END_DT),
        web_gui=WEB_GUI,
        auth=TqAuth(user, password),
    )

    try:
        data_length = int(10 * 60 * 60 / TIME_CELL * (HISTORY_DAY_LENGTH + 5))
        klines = api.get_kline_serial(SYMBOL, TIME_CELL, data_length=data_length)
        target_pos = TargetPosTask(api, SYMBOL)
        predicted_volume = build_predicted_volume(klines)

        day_volume = 0
        last_trade_date = None
        flattened_dates = set()

        while True:
            api.wait_update()
            if not api.is_changing(klines.iloc[-1], "datetime"):
                continue

            dt_ns = int(klines.iloc[-1]["datetime"])
            t = get_kline_time(dt_ns)
            d = get_market_day(dt_ns)

            if last_trade_date != d:
                day_volume = 0
                last_trade_date = d

            if t in predicted_volume:
                day_volume += predicted_volume[t]
                print(f"{d} {t} 调整目标持仓 -> {day_volume}")
                target_pos.set_target_volume(day_volume)

            # 时段结束后平仓，方便跨日观察下一轮 VWAP
            if (
                d not in flattened_dates
                and t > datetime.time(END_HOUR, END_MINUTE)
                and day_volume != 0
            ):
                print(f"{d} {t} 时段结束，平仓")
                target_pos.set_target_volume(0)
                day_volume = 0
                flattened_dates.add(d)

    except BacktestFinished:
        print("回测结束。浏览器可继续查看报表，窗口将保持打开。")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            print("退出回测进程。")
    finally:
        api.close()


if __name__ == "__main__":
    main()
