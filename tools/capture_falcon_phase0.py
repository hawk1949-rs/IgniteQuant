#!/usr/bin/env python
"""Capture fixed Falcon 5-minute fixtures and their Phase 0 Golden Master.

Market access is used only with ``--capture``.  Normal test runs are offline and
never rewrite the approved baseline.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.characterization.legacy_harness import (  # noqa: E402
    FLOAT_DIGITS,
    RISK_PARAMETERS,
    run_legacy_characterization,
)

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "falcon_phase0"
GOLDEN_DIR = ROOT / "tests" / "golden" / "falcon_phase0"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
SYMBOL = "KQ.m@SHFE.au"
DURATION_SECONDS = 300
WINDOW_BARS = 400
CAPTURE_START = dt.date(2025, 1, 1)
CAPTURE_END = dt.date(2025, 3, 31)
CSV_COLUMNS = [
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_oi",
    "close_oi",
]


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _capture_market_bars() -> pd.DataFrame:
    from tqsdk import BacktestFinished, TqApi, TqAuth, TqBacktest, TqSim

    _load_dotenv(ROOT / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise RuntimeError("TQ_USER / TQ_PASS are required for --capture")

    api = TqApi(
        TqSim(init_balance=1_000_000),
        backtest=TqBacktest(start_dt=CAPTURE_START, end_dt=CAPTURE_END),
        web_gui=False,
        auth=TqAuth(user, password),
    )
    serial = api.get_kline_serial(SYMBOL, DURATION_SECONDS, data_length=10_000)
    try:
        while True:
            api.wait_update()
    except BacktestFinished:
        frame = serial.copy(deep=True)
    finally:
        api.close()

    frame = frame.loc[:, [column for column in CSV_COLUMNS if column in frame.columns]]
    frame = frame.dropna(subset=["datetime", "open", "high", "low", "close", "volume"])
    frame["datetime"] = frame["datetime"].astype("int64")
    frame = frame.sort_values("datetime").drop_duplicates("datetime", keep="last")

    local_time = pd.to_datetime(frame["datetime"], unit="ns")
    start = pd.Timestamp(CAPTURE_START)
    end = pd.Timestamp(CAPTURE_END + dt.timedelta(days=1))
    frame = frame.loc[(local_time >= start) & (local_time < end)].reset_index(drop=True)

    for column in ("open_oi", "close_oi"):
        if column not in frame.columns:
            frame[column] = 0
    if len(frame) < WINDOW_BARS * 3:
        raise RuntimeError(f"captured only {len(frame)} bars; need at least {WINDOW_BARS * 3}")
    return frame.loc[:, CSV_COLUMNS]


def _overlaps(left: int, right: int) -> bool:
    return not (left + WINDOW_BARS <= right or right + WINDOW_BARS <= left)


def _select_windows(frame: pd.DataFrame) -> dict[str, tuple[int, dict[str, float]]]:
    closes = frame["close"].to_numpy(dtype=float)
    candidates: list[tuple[int, float, float]] = []
    for start in range(0, len(frame) - WINDOW_BARS + 1, 5):
        window = closes[start : start + WINDOW_BARS]
        net_return = float(window[-1] / window[0] - 1.0)
        path = float(np.abs(np.diff(window)).sum())
        efficiency = abs(float(window[-1] - window[0])) / path if path > 0 else 0.0
        candidates.append((start, net_return, efficiency))

    up = max(candidates, key=lambda item: item[1])
    down_pool = [item for item in candidates if not _overlaps(item[0], up[0])]
    down = min(down_pool, key=lambda item: item[1])
    range_pool = [
        item
        for item in candidates
        if not _overlaps(item[0], up[0]) and not _overlaps(item[0], down[0])
    ]
    sideways = min(range_pool, key=lambda item: (item[2], abs(item[1])))

    return {
        "trend_up": (up[0], {"net_return": up[1], "path_efficiency": up[2]}),
        "trend_down": (
            down[0],
            {"net_return": down[1], "path_efficiency": down[2]},
        ),
        "sideways_transition": (
            sideways[0],
            {"net_return": sideways[1], "path_efficiency": sideways[2]},
        ),
    }


def _save_fixtures(frame: pd.DataFrame) -> dict[str, Any]:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    selected = _select_windows(frame)
    scenarios: dict[str, Any] = {}

    for name, (start, selection_metrics) in selected.items():
        window = frame.iloc[start : start + WINDOW_BARS].copy()
        path = FIXTURE_DIR / f"{name}.csv"
        window.to_csv(
            path,
            index=False,
            columns=CSV_COLUMNS,
            float_format=f"%.{FLOAT_DIGITS}f",
            lineterminator="\n",
        )
        timestamps = pd.to_datetime(window["datetime"], unit="ns")
        scenarios[name] = {
            "file": path.relative_to(ROOT).as_posix(),
            "bars": len(window),
            "first_bar": timestamps.iloc[0].isoformat(),
            "last_bar": timestamps.iloc[-1].isoformat(),
            "input_sha256": _sha256(path),
            "selection_metrics": {
                key: round(value, FLOAT_DIGITS)
                for key, value in selection_metrics.items()
            },
        }

    manifest = {
        "schema_version": 1,
        "purpose": "Phase 0 characterization only; not strategy validation",
        "source": "tqsdk historical KQ.m@SHFE.au",
        "symbol": SYMBOL,
        "duration_seconds": DURATION_SECONDS,
        "capture_period": {
            "start": CAPTURE_START.isoformat(),
            "end": CAPTURE_END.isoformat(),
        },
        "selection": (
            "non-overlapping 400-bar windows: maximum net return, minimum net "
            "return, then minimum path efficiency"
        ),
        "scenarios": scenarios,
    }
    _write_json(MANIFEST_PATH, manifest)
    return manifest


def _generate_golden(manifest: dict[str, Any]) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    for name, metadata in manifest["scenarios"].items():
        fixture_path = ROOT / metadata["file"]
        bars = pd.read_csv(fixture_path)
        records = run_legacy_characterization(bars)
        payload = {
            "schema_version": 1,
            "scenario": name,
            "input_sha256": metadata["input_sha256"],
            "float_digits": FLOAT_DIGITS,
            "risk_parameters": RISK_PARAMETERS,
            "records": records,
        }
        golden_path = GOLDEN_DIR / f"{name}.json"
        _write_json(golden_path, payload)
        metadata["golden_file"] = golden_path.relative_to(ROOT).as_posix()
        metadata["golden_sha256"] = _sha256(golden_path)
        metadata["golden_records"] = len(records)
    _write_json(MANIFEST_PATH, manifest)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--capture",
        action="store_true",
        help="fetch and overwrite fixed market fixtures before generating golden files",
    )
    args = parser.parse_args()

    if args.capture:
        manifest = _save_fixtures(_capture_market_bars())
    elif MANIFEST_PATH.is_file():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    else:
        raise SystemExit("No fixtures exist. Run once with --capture.")

    _generate_golden(manifest)
    print(f"Phase 0 fixtures: {FIXTURE_DIR}")
    print(f"Phase 0 golden files: {GOLDEN_DIR}")


if __name__ == "__main__":
    main()
