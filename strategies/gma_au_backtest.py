#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""GMA v1 回测入口。决策核：GMADecisionPipeline；执行层复用 Falcon 本地回放。"""

from __future__ import annotations

import datetime
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from ignitequant.engine.local_replay import run_local_falcon_backtest
from ignitequant.strategies.gma import GMA_CACHE_WARMUP_BARS, GMADecisionPipeline, load_gma_runtime
from ignitequant.strategies.gma.config import GMARuntimeConfig


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
KLINE_SECONDS = 60 * 5
INIT_BALANCE = 1_000_000
DATA_LENGTH = 8000


def main() -> None:
    load_dotenv(ROOT / ".env")
    runtime = load_gma_runtime()
    cfg = replace(runtime.decision, symbol=SIGNAL_SYMBOL, entry_mode="fill_confirmed")

    def factory(config):
        return GMADecisionPipeline(
            config,
            runtime=GMARuntimeConfig(indicators=runtime.indicators, decision=config),
        )

    print(
        f"启动 GMA v1 本地回测: 信号={SIGNAL_SYMBOL} 区间={START_DT}~{END_DT} "
        f"config={cfg.config_version} hash={cfg.config_hash()[:12]}",
        flush=True,
    )
    out = run_local_falcon_backtest(
        signal_symbol=SIGNAL_SYMBOL,
        start=START_DT,
        end=END_DT,
        init_balance=INIT_BALANCE,
        kline_seconds=KLINE_SECONDS,
        data_length=DATA_LENGTH,
        auto_download=True,
        record_decisions=True,
        config=cfg,
        pipeline_factory=factory,
        strategy_id="gma_v1",
        use_overseas=False,
        completed_bars=True,
        cache_warmup_bars=GMA_CACHE_WARMUP_BARS,
    )
    metrics = out.get("metrics") or {}
    print(
        f"完成 engine={out.get('engine')} net_pnl={metrics.get('net_pnl')} "
        f"trades={metrics.get('trade_count')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
