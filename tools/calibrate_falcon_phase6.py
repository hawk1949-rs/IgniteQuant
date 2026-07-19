#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Phase 6 offline calibration on Phase 0 fixtures.

Usage:
    python tools/calibrate_falcon_phase6.py
    python tools/calibrate_falcon_phase6.py --profiles falcon_legacy_v1,falcon_5m_sqrt_v1

Does not change production defaults. Writes report JSON under data/research/.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "strategies"))

import pandas as pd

from ignitequant.config import list_profiles, load_decision_config, load_profile_dict
from ignitequant.research import GoLiveGate, compare_profiles, walk_forward_plan_for_calibration


def main() -> None:
    parser = argparse.ArgumentParser(description="Falcon Phase 6 offline calibration")
    parser.add_argument(
        "--profiles",
        default="falcon_legacy_v1,falcon_5m_sqrt_v1,falcon_5m_lots_v1,falcon_5m_half_v1",
        help="comma-separated profile ids",
    )
    parser.add_argument(
        "--fixture",
        default="tests/fixtures/falcon_phase0/trend_up.csv",
        help="CSV fixture path",
    )
    args = parser.parse_args()

    fixture = ROOT / args.fixture
    bars = pd.read_csv(fixture)
    names = [p.strip() for p in args.profiles.split(",") if p.strip()]
    configs = {name: load_decision_config(name) for name in names}
    # Ensure JSON metadata available
    meta = {}
    for name in names:
        try:
            meta[name] = load_profile_dict(name)
        except FileNotFoundError:
            meta[name] = {"profile_id": name, "status": "inline"}

    gate = GoLiveGate()
    # Fixture has 400 bars — relax warm_bars for offline smoke
    if len(bars) < 500:
        gate = GoLiveGate(min_warm_bars=200)

    report = compare_profiles(bars, configs, gate=gate)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    report["fixture"] = str(fixture.relative_to(ROOT))
    report["fixture_bars"] = len(bars)
    report["profile_meta"] = {
        k: {
            "status": v.get("status"),
            "rollback_to": v.get("rollback_to"),
            "description": v.get("description"),
        }
        for k, v in meta.items()
    }
    report["walk_forward_example"] = walk_forward_plan_for_calibration(
        "2025-01-01", "2025-06-30", train_days=40, test_days=20
    )
    report["promotion_policy"] = {
        "auto_promote": False,
        "production_default": "falcon_legacy_v1",
        "activation": "set FALCON_PROFILE=<candidate> after human approval",
        "rollback": "unset FALCON_PROFILE or set FALCON_PROFILE=falcon_legacy_v1",
    }

    out_dir = ROOT / "data" / "research"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"phase6_calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"profiles available: {list_profiles()}")
    print(f"fixture: {fixture} bars={len(bars)}")
    for name, row in report["profiles"].items():
        m = row["metrics"]
        g = row["gate"]
        print(
            f"- {name}: targets={m['target_changes']} tinm={m['time_in_market_pct']:.1%} "
            f"net={m['proxy_net_pnl']:.0f} stress_ok={m['stress_all_survive']} "
            f"gate={'PASS' if g['passed'] else 'FAIL'}"
        )
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
