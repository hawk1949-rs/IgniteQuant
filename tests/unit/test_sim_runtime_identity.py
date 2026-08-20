# -*- coding: utf-8 -*-
from pathlib import Path


def test_apply_runtime_identity_switches_symbol_and_db(
    monkeypatch,
) -> None:
    import strategies.falcon_au_sim as sim

    monkeypatch.setenv("IQ_SIM_INSTANCE_ID", "falcon_v2_ag_sim")
    monkeypatch.setenv("IQ_SIM_STRATEGY_ID", "falcon_v2")
    monkeypatch.setenv("IQ_SIM_SYMBOL_ID", "ag")
    try:
        sim.apply_runtime_identity()
        assert sim.INSTANCE_ID == "falcon_v2_ag_sim"
        assert sim.STRATEGY_ID == "falcon_v2"
        assert sim.SIGNAL_SYMBOL == "KQ.m@SHFE.ag"
        assert sim.PERSIST_DB.name == "falcon_v2_ag_sim.sqlite"
        assert sim.PID_FILE.name == "falcon_v2_ag_sim.pid"
        assert Path(sim.PERSIST_DB).parent == Path(sim.PID_FILE).parent
    finally:
        monkeypatch.delenv("IQ_SIM_INSTANCE_ID", raising=False)
        monkeypatch.delenv("IQ_SIM_STRATEGY_ID", raising=False)
        monkeypatch.delenv("IQ_SIM_SYMBOL_ID", raising=False)
        sim.INSTANCE_ID = "falcon_au_sim"
        sim.STRATEGY_ID = "falcon_v2"
        sim.STRATEGY_LABEL = "Falcon v2"
        sim.SIGNAL_SYMBOL = "KQ.m@SHFE.au"
        sim.PERSIST_DB = sim.ROOT / "data" / "runtime" / "falcon_au_sim.sqlite"
        sim.PID_FILE = sim.PERSIST_DB.parent / "falcon_au_sim.pid"


def test_gma_au_sim_patches_decision_pipeline() -> None:
    import importlib

    import strategies.falcon_au_sim as falcon_sim
    import strategies.gma_au_sim as gma_sim
    from ignitequant.engine import annotate_klines as engine_annotate
    from ignitequant.engine.decision_pipeline import FalconDecisionPipeline as EngineFalcon
    from ignitequant.strategies.gma import GMADecisionPipeline, annotate_gma_klines

    falcon_sim = importlib.reload(falcon_sim)
    assert falcon_sim.FalconDecisionPipeline is EngineFalcon
    assert falcon_sim.annotate_klines is engine_annotate

    gma_sim = importlib.reload(gma_sim)
    assert gma_sim.sim.FalconDecisionPipeline is GMADecisionPipeline
    assert gma_sim.sim.annotate_klines is annotate_gma_klines
    assert gma_sim.sim.load_active_decision_config.__name__ == "_load_gma_decision_config"
