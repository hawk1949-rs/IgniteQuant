"""GMA local-replay HTF cache must match bar-by-bar resample (no future leak)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pandas as pd

from ignitequant.engine.local_replay import _asof_domestic_row, _window
from ignitequant.strategies.gma.config import GMAIndicatorConfig
from ignitequant.strategies.gma.pipeline import GMADecisionPipeline
from ignitequant.strategies.gma.resample import asof_bundle, resample_bundle
from ignitequant.strategies.gma.signal import generate_signal


def _bars(n: int, *, drift: float = 0.02) -> pd.DataFrame:
    start = datetime(2025, 1, 2, 9, 0, tzinfo=timezone.utc)
    rows = []
    price = 500.0
    for i in range(n):
        ts = start + timedelta(minutes=5 * i)
        price = price + drift + 0.15 * math.sin(i / 8.0)
        rows.append(
            {
                "datetime": int(ts.timestamp() * 1_000_000_000),
                "open": price - 0.1,
                "high": price + 0.4,
                "low": price - 0.4,
                "close": price,
                "volume": 100 + i % 7,
                "underlying_symbol": "SHFE.au2606",
            }
        )
    return pd.DataFrame(rows)


def test_asof_bundle_matches_window_resample() -> None:
    bars = _bars(2400, drift=0.03)
    full = resample_bundle(bars)
    cfg = GMAIndicatorConfig()
    for i in (900, 1200, 1800, 2200):
        window = _window(bars, i, 800)
        expected = generate_signal(window, indicators=cfg, current_target=0)
        bundle = asof_bundle(
            full,
            last_src_ns=int(window.iloc[-1]["datetime"]),
            first_src_ns=int(window.iloc[0]["datetime"]),
            max_5m=len(window),
        )
        got = generate_signal(window, indicators=cfg, current_target=0, bundle=bundle)
        assert got.signal == expected.signal
        assert got.desired == expected.desired
        assert got.reasons == expected.reasons
        assert got.alignment == expected.alignment
        assert abs(got.atr - expected.atr) < 1e-9


def test_prepare_replay_matches_stateless_pipeline() -> None:
    bars = _bars(1200, drift=0.04)
    data_length = 400
    cold = GMADecisionPipeline()
    cached = GMADecisionPipeline()
    cached.prepare_replay(bars)
    start = data_length - 1
    for i in range(start, len(bars)):
        window = _window(bars, i, data_length)
        a = cold.on_bar_close(window, trade=True)
        b = cached.on_bar_close(window, trade=True)
        assert a.applied_action == b.applied_action
        assert a.target_after == b.target_after
        assert a.signal.legacy_signal == b.signal.legacy_signal
        assert a.factors.reason_codes == b.factors.reason_codes


def test_domestic_asof_is_last_bar_at_or_before() -> None:
    domestic = _bars(20, drift=0.01)
    first_ns = int(domestic.iloc[0]["datetime"])
    mid_ns = int(domestic.iloc[10]["datetime"])
    step = mid_ns - int(domestic.iloc[9]["datetime"])
    open_px, close_px, under = _asof_domestic_row(domestic, mid_ns + step // 2)
    assert under == "SHFE.au2606"
    assert open_px == float(domestic.iloc[10]["open"])
    assert close_px == float(domestic.iloc[10]["close"])
    assert _asof_domestic_row(domestic, first_ns - 1) == (None, None, "")
