# -*- coding: utf-8 -*-
"""Identity audit: strategy_id / config / script / UI / runner must not drift apart."""

from __future__ import annotations

from dashboard import runners
from dashboard.catalog import STRATEGIES
from dashboard.sim_launchers import (
    READY_SIM_STRATEGIES,
    SIM_LAUNCHERS,
    sim_script_for_strategy,
)
from dashboard.sim_strategy_ui import _PROFILES, resolve_strategy_ui
from ignitequant.config.profiles import DEFAULT_PROFILE, load_active_decision_config
from ignitequant.strategies.gma.config import load_gma_runtime
from ignitequant.strategies.gma.pipeline import GMADecisionPipeline


def test_ready_sim_strategies_have_script_runner_and_ui() -> None:
    for sid in READY_SIM_STRATEGIES:
        assert sid in STRATEGIES, sid
        info = STRATEGIES[sid]
        script = sim_script_for_strategy(sid)
        assert script.is_file(), script
        assert callable(getattr(runners, info.runner, None)), info.runner
        assert sid in _PROFILES, f"UI profile missing for {sid}"
        ui = resolve_strategy_ui(sid)
        if sid.startswith("gma"):
            assert ui.family == "gma"
        if sid.startswith("falcon"):
            assert ui.family == "falcon"


def test_launcher_script_matches_strategy() -> None:
    for iid, meta in SIM_LAUNCHERS.items():
        expected = sim_script_for_strategy(str(meta["strategy_id"])).name
        assert meta["script"].name == expected, iid


def test_gma_sim_shell_style_pipeline_keeps_profile_indicators() -> None:
    """Regression for the gma_v2 energy_enabled=false wiring bug."""
    for pid, expect_energy in (("gma_v1", False), ("gma_v2", True)):
        runtime = load_gma_runtime(pid)
        pipe = GMADecisionPipeline(runtime.decision)
        assert pipe.config.config_version == pid
        assert pipe.runtime.indicators.energy_enabled is expect_energy


def test_falcon_v2_catalog_uses_legacy_profile_by_default() -> None:
    """Documented naming: product id falcon_v2, active archive falcon_legacy_v1."""
    assert DEFAULT_PROFILE == "falcon_legacy_v1"
    cfg = load_active_decision_config()
    assert cfg.config_version == "falcon_legacy_v1"
    assert cfg.decision_mode == "legacy_compatible"
    assert "falcon_v2" in STRATEGIES


def test_vwap_is_catalog_stub_not_ready_sim() -> None:
    assert "vwap_au" in STRATEGIES
    assert "vwap_au" not in READY_SIM_STRATEGIES
    assert STRATEGIES["vwap_au"].runner == "run_vwap_stub"


def test_catch_up_builder_matches_strategy_family() -> None:
    from ignitequant.engine.catch_up import build_catch_up_pipeline
    from ignitequant.strategies.gma.pipeline import GMADecisionPipeline as GmaPipe
    from ignitequant.engine import FalconDecisionPipeline

    gma2, n2, sid2 = build_catch_up_pipeline("gma_v2", "KQ.m@SHFE.au")
    assert sid2 == "gma_v2"
    assert isinstance(gma2, GmaPipe)
    assert gma2.runtime.indicators.energy_enabled is True
    assert n2 >= 8000

    gma1, _, sid1 = build_catch_up_pipeline("gma_v1", "KQ.m@SHFE.au")
    assert sid1 == "gma_v1"
    assert isinstance(gma1, GmaPipe)
    assert gma1.runtime.indicators.energy_enabled is False

    falcon, n_f, sid_f = build_catch_up_pipeline("falcon_v2", "KQ.m@SHFE.au")
    assert sid_f == "falcon_v2"
    assert isinstance(falcon, FalconDecisionPipeline)
    assert n_f == 400
