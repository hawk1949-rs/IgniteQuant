#!/usr/bin/env python
"""Compare local (cache + LocalSim) vs tq (TqBacktest + TqSim) on the same window.

Usage:
  python tools/compare_local_tq.py --symbol KQ.m@SHFE.au --start 2025-01-02 --end 2025-01-15

Requires TQ_USER / TQ_PASS in .env for the tq leg. Local leg uses data/market_cache.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def _parse_date(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def main() -> int:
    parser = argparse.ArgumentParser(description="Align gate: local vs tq Falcon backtest")
    parser.add_argument("--symbol", default="KQ.m@SHFE.au")
    parser.add_argument("--start", type=_parse_date, required=True)
    parser.add_argument("--end", type=_parse_date, required=True)
    parser.add_argument("--init-balance", type=float, default=1_000_000)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--record-decisions", action="store_true")
    args = parser.parse_args()

    from dashboard.runners import run_falcon_local, run_falcon_v2
    from ignitequant.analytics.tq_match import metrics_delta, within_tolerances
    from ignitequant.engine.local_replay import run_local_falcon_backtest

    print(f"[local] {args.symbol} {args.start}..{args.end}")
    if args.record_decisions:
        local = run_local_falcon_backtest(
            signal_symbol=args.symbol,
            start=args.start,
            end=args.end,
            init_balance=args.init_balance,
            auto_download=True,
            record_decisions=True,
        )
    else:
        local = run_falcon_local(
            signal_symbol=args.symbol,
            start=args.start,
            end=args.end,
            init_balance=args.init_balance,
            auto_download=True,
        )
    print(
        f"  ror={local['metrics'].get('ror')} "
        f"trades={local['metrics'].get('trade_count')} "
        f"final={local['metrics'].get('final_balance')} "
        f"align={local.get('reproducibility', {}).get('align_mode')}"
    )

    print(f"[tq]    {args.symbol} {args.start}..{args.end}")
    tq = run_falcon_v2(
        signal_symbol=args.symbol,
        start=args.start,
        end=args.end,
        init_balance=args.init_balance,
    )
    print(
        f"  ror={tq['metrics'].get('ror')} "
        f"trades={tq['metrics'].get('trade_count')} "
        f"final={tq['metrics'].get('final_balance')} "
        f"align={tq.get('reproducibility', {}).get('align_mode')}"
    )

    delta = metrics_delta(local["metrics"], tq["metrics"])
    ok, fails = within_tolerances(local, tq)
    report = {
        "symbol": args.symbol,
        "start": args.start.isoformat(),
        "end": args.end.isoformat(),
        "local_metrics": local["metrics"],
        "tq_metrics": tq["metrics"],
        "delta": delta,
        "within_tolerances": ok,
        "failures": fails,
        "local_cost": local.get("cost_model"),
        "tq_cost": tq.get("cost_model"),
    }
    print(json.dumps({"within_tolerances": ok, "failures": fails, "delta": delta}, indent=2, ensure_ascii=False))
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {args.json_out}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
