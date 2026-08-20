# -*- coding: utf-8 -*-
from dashboard.sim_launchers import (
    SIM_LAUNCHERS,
    sim_instance_id,
    sim_script_for_strategy,
)


def test_compat_instance_ids_keep_legacy_sqlite_names() -> None:
    assert sim_instance_id("falcon_v2", "au") == "falcon_au_sim"
    assert sim_instance_id("gma_v1", "au") == "gma_au_sim"
    assert sim_instance_id("gma_v2", "au") == "gma_v2_au_sim"
    assert sim_instance_id("falcon_v2", "ag") == "falcon_v2_ag_sim"


def test_launcher_matrix_covers_ready_strategies_and_symbols() -> None:
    assert "falcon_au_sim" in SIM_LAUNCHERS
    assert "gma_au_sim" in SIM_LAUNCHERS
    assert "gma_v2_au_sim" in SIM_LAUNCHERS
    assert "falcon_v2_ag_sim" in SIM_LAUNCHERS
    assert "gma_v1_rb_sim" in SIM_LAUNCHERS
    assert SIM_LAUNCHERS["falcon_au_sim"]["symbol_id"] == "au"
    assert SIM_LAUNCHERS["falcon_au_sim"]["strategy_id"] == "falcon_v2"
    assert SIM_LAUNCHERS["gma_v2_au_sim"]["strategy_id"] == "gma_v2"
    assert SIM_LAUNCHERS["falcon_v2_ag_sim"]["symbol_id"] == "ag"
    assert sim_script_for_strategy("gma_v2").name == "gma_v2_sim.py"
    # Distinct strategies must be able to run the same product without sharing instance id.
    assert sim_instance_id("falcon_v2", "au") != sim_instance_id("gma_v1", "au")
    assert sim_instance_id("gma_v1", "au") != sim_instance_id("gma_v2", "au")
