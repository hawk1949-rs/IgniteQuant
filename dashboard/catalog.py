# -*- coding: utf-8 -*-
"""家庭量化作坊：策略 / 品种目录。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyInfo:
    id: str
    name: str
    description: str
    runner: str  # dashboard.runners 中的函数名


@dataclass(frozen=True)
class SymbolInfo:
    id: str
    name: str
    signal_symbol: str  # 连续合约，用于信号
    exchange: str


STRATEGIES: dict[str, StrategyInfo] = {
    "falcon_v2": StrategyInfo(
        id="falcon_v2",
        name="Falcon v2",
        description="ADX 行情状态 + 格兰维尔/量能/KDJ 评分 + ATR 止盈止损（1H）",
        runner="run_falcon_v2",
    ),
    "vwap_au": StrategyInfo(
        id="vwap_au",
        name="VWAP（沪金）",
        description="VWAP 偏离回归（当前仅适配沪金示例脚本，看板内暂作占位）",
        runner="run_vwap_stub",
    ),
}

SYMBOLS: dict[str, SymbolInfo] = {
    "au": SymbolInfo("au", "沪金", "KQ.m@SHFE.au", "SHFE"),
    "ag": SymbolInfo("ag", "沪银", "KQ.m@SHFE.ag", "SHFE"),
    "cu": SymbolInfo("cu", "沪铜", "KQ.m@SHFE.cu", "SHFE"),
}
