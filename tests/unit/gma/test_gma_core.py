"""GMA core unit tests: indicators, resample, alignment, sizing, pipeline."""

from __future__ import annotations

import inspect
import math
from datetime import datetime, timedelta, timezone

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ignitequant.domain.enums import Regime
from ignitequant.strategies.gma.config import default_gma_decision_config, load_gma_runtime
from ignitequant.strategies.gma.indicators import TenWState, hull_ma, line_color, rkk_fisher
from ignitequant.strategies.gma.pipeline import GMADecisionPipeline
from ignitequant.strategies.gma.regime import Alignment, classify_alignment
from ignitequant.strategies.gma.resample import resample_closed
from ignitequant.strategies.gma.sizing import apply_hold_flat_and_no_flip, lots_from_gma_signal

ROOT = Path(__file__).resolve().parents[3]


def _bars(
    n: int,
    *,
    start: datetime | None = None,
    step_minutes: int = 5,
    start_price: float = 500.0,
    drift: float = 0.0,
    wave: float = 0.0,
) -> pd.DataFrame:
    start = start or datetime(2025, 1, 2, 9, 0, tzinfo=timezone.utc)
    rows = []
    price = start_price
    for i in range(n):
        ts = start + timedelta(minutes=step_minutes * i)
        price = price + drift + wave * math.sin(i / 8.0)
        high = price + 0.4
        low = price - 0.4
        rows.append(
            {
                "datetime": int(ts.timestamp() * 1_000_000_000),
                "open": price - drift / 2.0,
                "high": high,
                "low": low,
                "close": price,
                "volume": 100 + i % 7,
                "underlying_symbol": "SHFE.au2606",
            }
        )
    return pd.DataFrame(rows)


def test_hull_ma_is_deterministic_and_finite() -> None:
    close = np.linspace(400.0, 460.0, 120)
    a = hull_ma(close, 20)
    b = hull_ma(close, 20)
    assert np.allclose(a[30:], b[30:], equal_nan=True)
    assert np.isfinite(a[-1])
    up = line_color(a)
    assert up[-1] > 0


def test_rkk_zero_cross_matches_trend_flip() -> None:
    down = np.linspace(520.0, 480.0, 80)
    up = np.linspace(480.0, 530.0, 80)
    high = np.concatenate([down + 1, up + 1])
    low = np.concatenate([down - 1, up - 1])
    fish = rkk_fisher(high, low, 21)
    assert fish[-1] > fish[70]


def test_resample_drops_incomplete_15m_bucket() -> None:
    bars = _bars(8)  # 40 minutes -> two full 15m + leftover 10m
    out = resample_closed(bars, 15)
    assert len(out) == 2
    assert float(out.iloc[0]["open"]) == pytest.approx(float(bars.iloc[0]["open"]))


def _state(*, fc: int, sc: int, above: bool, golden: bool = False, death: bool = False) -> TenWState:
    return TenWState(
        fast=10.0,
        slow=9.0 if above else 11.0,
        fast_color=fc,
        slow_color=sc,
        fast_above_slow=above,
        golden_cross=golden,
        death_cross=death,
        single_drive=fc == sc != 0 and ((fc > 0 and above) or (fc < 0 and not above)),
        single_direction=fc == sc != 0,
        single_conflict=fc != 0 and sc != 0 and fc != sc,
    )


def test_alignment_drive_direction_range() -> None:
    bull = _state(fc=1, sc=1, above=True)
    snap = classify_alignment(bull, bull, bull)
    assert snap.alignment is Alignment.DRIVE
    assert snap.regime is Regime.TREND_UP

    h1 = _state(fc=1, sc=1, above=True)
    h4 = _state(fc=1, sc=1, above=True)
    m15 = _state(fc=-1, sc=1, above=False)
    snap = classify_alignment(m15, h1, h4)
    assert snap.alignment is Alignment.DIRECTION

    bear_h1 = _state(fc=-1, sc=-1, above=False)
    snap = classify_alignment(bull, bear_h1, h4)
    assert snap.alignment is Alignment.RANGE
    assert snap.regime is Regime.RANGE


def test_sizing_hold_vs_flat_and_no_flip() -> None:
    assert lots_from_gma_signal(0, lot_by_signal={1: 1, 2: 1, 3: 2}) is None
    assert lots_from_gma_signal(2, lot_by_signal={1: 1, 2: 1, 3: 2}) == 1
    assert lots_from_gma_signal(-3, lot_by_signal={1: 1, 2: 1, 3: 2}) == -2
    assert apply_hold_flat_and_no_flip(sizing_lots=None, explicit_flat=False, current_target=1) is None
    assert apply_hold_flat_and_no_flip(sizing_lots=-1, explicit_flat=False, current_target=1) == 0
    assert apply_hold_flat_and_no_flip(sizing_lots=1, explicit_flat=False, current_target=2) is None
    assert apply_hold_flat_and_no_flip(sizing_lots=0, explicit_flat=True, current_target=1) == 0


def test_long_short_alignment_is_symmetric() -> None:
    long = classify_alignment(
        _state(fc=1, sc=1, above=True),
        _state(fc=1, sc=1, above=True),
        _state(fc=1, sc=1, above=True),
    )
    short = classify_alignment(
        _state(fc=-1, sc=-1, above=False),
        _state(fc=-1, sc=-1, above=False),
        _state(fc=-1, sc=-1, above=False),
    )
    assert long.direction == -short.direction
    assert long.alignment is short.alignment is Alignment.DRIVE


def test_pipeline_warming_up_does_not_open() -> None:
    bars = _bars(40)
    cfg = default_gma_decision_config()
    from dataclasses import replace as dc_replace

    cfg = dc_replace(cfg, factor=dc_replace(cfg.factor, warmup_bars=5))
    pipe = GMADecisionPipeline(cfg)
    result = pipe.on_bar_close(bars, trade=True)
    assert result.target_after == 0
    assert result.applied_action in {"HOLD", "COOLDOWN_HOLD"}
    assert "FACTOR_NOT_READY" in result.factors.reason_codes or result.factors.quality.value == "WARMING_UP"


def test_pipeline_observe_only_does_not_trade() -> None:
    bars = _bars(80, drift=0.15)
    pipe = GMADecisionPipeline()
    before = pipe.current_target
    result = pipe.on_bar_close(bars, trade=False)
    assert result.applied_action == "HOLD"
    assert pipe.current_target == before == 0


def test_consecutive_loss_pause_resets_next_day() -> None:
    from datetime import date

    pipe = GMADecisionPipeline()
    pipe._consecutive_losses = 2
    pipe._loss_pause_day = date(2025, 1, 2)
    same_day = _bars(80, start=datetime(2025, 1, 2, 10, 0, tzinfo=timezone.utc))
    paused = pipe.on_bar_close(same_day, trade=True)
    assert pipe._consecutive_losses == 2
    assert paused.applied_action == "COOLDOWN_HOLD"
    next_day = _bars(80, start=datetime(2025, 1, 3, 1, 0, tzinfo=timezone.utc))
    pipe.on_bar_close(next_day, trade=True)
    assert pipe._consecutive_losses == 0


def test_confirm_local_fill_arms_stop() -> None:
    pipe = GMADecisionPipeline()
    pipe.current_target = 1
    pipe.confirm_local_fill(price=500.0, atr=2.0, signal=2)
    assert pipe.risk.state.stop_price is not None
    assert pipe.risk.state.take_price is not None
    assert pipe.risk.state.stop_price < 500.0


def test_gma_modules_do_not_import_tqsdk() -> None:
    import ignitequant.strategies.gma.energy as energy
    import ignitequant.strategies.gma.indicators as indicators
    import ignitequant.strategies.gma.pipeline as pipeline
    import ignitequant.strategies.gma.signal as signal

    for mod in (energy, indicators, pipeline, signal):
        src = inspect.getsource(mod)
        assert "import tqsdk" not in src
        assert "from tqsdk" not in src
        assert "insert_order" not in src


def test_htf_warmup_requires_more_than_falcon_400_bars() -> None:
    """4H HMA90 cannot become ready on Falcon's 400-bar cache slice."""
    cold = GMADecisionPipeline().on_bar_close(_bars(400, drift=0.02), trade=True)
    assert "HTF_WARMING_UP" in cold.factors.reason_codes
    assert cold.target_after == 0
    assert cold.applied_action in {"HOLD", "COOLDOWN_HOLD"}

    warm = GMADecisionPipeline().on_bar_close(_bars(8000, drift=0.02), trade=True)
    assert "HTF_WARMING_UP" not in warm.factors.reason_codes


def test_load_gma_profile() -> None:
    runtime = load_gma_runtime("gma_v1")
    assert runtime.decision.config_version == "gma_v1"
    assert runtime.indicators.fast_period == 20
    assert runtime.indicators.slow_period == 90
    assert runtime.indicators.keltner_inner_atr == 1.5
    assert runtime.indicators.accel_atr == 2.4


def test_catalog_and_sim_launcher_register_gma() -> None:
    from dashboard.catalog import STRATEGIES

    assert "gma_v1" in STRATEGIES
    assert STRATEGIES["gma_v1"].runner == "run_gma_v1"
    assert "gma_v2" in STRATEGIES
    assert STRATEGIES["gma_v2"].runner == "run_gma_v2"
    sim_src = (ROOT / "dashboard" / "sim_api.py").read_text(encoding="utf-8")
    assert '"gma_au_sim"' in sim_src
    assert "gma_au_sim.py" in sim_src
    assert (ROOT / "strategies" / "gma_au_sim.py").is_file()
    assert (ROOT / "strategies" / "gma_au_backtest.py").is_file()
