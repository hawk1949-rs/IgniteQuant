# -*- coding: utf-8 -*-
"""家庭量化作坊：策略 / 品种目录。"""

from __future__ import annotations

from dataclasses import dataclass

from ignitequant.market.overseas import lab_overseas_pair_payload, lab_overseas_supported
from ignitequant.market.symbols import INSTRUMENTS


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
    overseas_supported: bool = False
    overseas_pair: dict[str, str] | None = None


STRATEGIES: dict[str, StrategyInfo] = {
    "falcon_v2": StrategyInfo(
        id="falcon_v2",
        name="Falcon v2",
        description="ADX 行情状态 + 格兰维尔/量能/KDJ 评分 + ATR 止盈止损（5 分钟）",
        runner="run_falcon_v2",
    ),
    "gma_v1": StrategyInfo(
        id="gma_v1",
        name="GMA v1",
        description="10W 多周期状态机 + 波动轨/加速轨 + 震荡/驱动/回踩（15m/1H/4H，5 分钟决策时钟）",
        runner="run_gma_v1",
    ),
    "vwap_au": StrategyInfo(
        id="vwap_au",
        name="VWAP（沪金）",
        description="VWAP 偏离回归（当前仅适配沪金示例脚本，看板内暂作占位）",
        runner="run_vwap_stub",
    ),
}

# Local-cache first instruments: 螺纹 / 沪金 / 沪银 / 玻璃
SYMBOLS: dict[str, SymbolInfo] = {
    sid: SymbolInfo(
        id=spec.id,
        name=spec.name,
        signal_symbol=spec.signal_symbol,
        exchange=spec.exchange,
        overseas_supported=lab_overseas_supported(sid),
        overseas_pair=lab_overseas_pair_payload(sid),
    )
    for sid, spec in INSTRUMENTS.items()
}

ENGINES = {
    "local": "本地缓存回放（默认，含换月 + LocalSim）",
    "tq": "天勤 TqBacktest 在线时光机",
}
