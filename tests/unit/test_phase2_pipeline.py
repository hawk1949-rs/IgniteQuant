"""Phase 2: unified FalconDecisionPipeline across characterization path."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ignitequant.engine import FalconDecisionPipeline
from tests.characterization.legacy_harness import run_legacy_characterization

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ("trend_up", "trend_down", "sideways_transition")


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_pipeline_matches_golden_and_harness(scenario: str) -> None:
    fixture = ROOT / "tests" / "fixtures" / "falcon_phase0" / f"{scenario}.csv"
    golden = json.loads(
        (ROOT / "tests" / "golden" / "falcon_phase0" / f"{scenario}.json").read_text(
            encoding="utf-8"
        )
    )["records"]
    bars = pd.read_csv(fixture)

    pipeline_rows = FalconDecisionPipeline().characterization_rows(bars)
    harness_rows = run_legacy_characterization(bars)

    assert pipeline_rows == golden
    assert harness_rows == golden


def test_pipeline_force_flat_and_observe_only() -> None:
    bars = pd.read_csv(ROOT / "tests" / "fixtures" / "falcon_phase0" / "trend_up.csv")
    pipeline = FalconDecisionPipeline()
    # Warm through enough bars to potentially open.
    for i in range(51, min(120, len(bars))):
        pipeline.on_bar_close(bars.iloc[: i + 1], trade=True)

    opened = pipeline.current_target
    observe = pipeline.on_bar_close(bars.iloc[:121], trade=False)
    assert observe.applied_action == "HOLD"
    # observe-only must not open/resize; force_flat clears explicitly.
    if opened != 0:
        pipeline.force_flat()
        assert pipeline.current_target == 0
        assert pipeline.risk.state.entry_price is None


def test_runners_import_unified_pipeline() -> None:
    import inspect

    import dashboard.runners as runners
    import strategies.falcon_au_backtest as backtest
    import strategies.falcon_au_sim as sim

    for mod in (runners, backtest, sim):
        src = inspect.getsource(mod)
        assert "FalconDecisionPipeline" in src
        # No second inlined decision chain.
        assert "lots_from_signal(" not in src
        assert "score_signal(" not in src
        assert "detect_regime(" not in src
