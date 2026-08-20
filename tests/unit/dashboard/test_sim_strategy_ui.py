# -*- coding: utf-8 -*-
from dashboard.sim_strategy_ui import (
    FALCON_UI,
    GMA_V1_UI,
    _overlay_scale,
    _same_price_scale,
    build_chart_context,
    resolve_strategy_ui,
)
from ignitequant.market.chart_series import merge_live_decisions


def test_resolve_strategy_ui_falcon_and_gma() -> None:
    assert resolve_strategy_ui("falcon_v2").family == "falcon"
    assert resolve_strategy_ui("gma_v1").family == "gma"
    assert resolve_strategy_ui("gma_v2").score_parts_schema == "gma_v2"
    assert resolve_strategy_ui("unknown_strategy").family == "generic"


def test_format_score_parts_labels() -> None:
    assert "Granville=1" in FALCON_UI.format_score_parts([1, 0, 2, 0])
    assert "对齐=3" in GMA_V1_UI.format_score_parts([3, 1, 2, 0])


def test_gma_format_factor_summary_reads_replay_meta_fields() -> None:
    summary = GMA_V1_UI.format_factor_summary(
        regime="TREND_UP",
        quality="READY",
        values={"score_parts": [3, 1, 2, 0], "gma_poc": 881.5},
    )
    assert "对齐驱动" in summary
    assert "POC 881.50" in summary


def test_build_chart_context_prefers_live_decision() -> None:
    decision = {
        "regime": "RANGE",
        "factor_values": {"alignment": 0.0, "close": 880.0},
        "payload": {"factors": {"quality": "READY", "regime": "RANGE", "values": {"alignment": 0.0}}},
    }
    ctx = build_chart_context("gma_v1", [], latest_decision=decision)
    assert ctx is not None
    assert ctx["regime"] == "RANGE"
    assert ctx["source"] == "live_decision"
    assert "对齐" in str(ctx["factor_summary"])


def test_overlay_scale_rejects_absurd_and_accepts_au_xau() -> None:
    assert _same_price_scale(973.0, 972.5)
    assert not _same_price_scale(973.0, 4498.0)
    assert _overlay_scale(973.0, 4498.0) is not None
    assert abs((_overlay_scale(973.0, 4498.0) or 0) - 973.0 / 4498.0) < 1e-9
    assert _overlay_scale(973.0, 973.0) == 1.0
    assert _overlay_scale(973.0, 50.0) is None


def test_gma_live_enrich_scales_xau_onto_domestic_chart() -> None:
    """Domestic candles (~970) must not keep raw XAUUSD (~4500) overlay tips."""
    t = 1_700_000_000
    replay = [
        {
            "time": t,
            "signal": None,
            "gma_fast": 970.0,
            "gma_slow": 968.0,
            "gma_mid": 969.0,
            "gma_poc": 971.0,
            "close": 973.0,
            "source": "replay",
        }
    ]
    decisions = [
        {
            "bar_id": f"XAUUSD:{t * 1_000_000_000}",
            "legacy_signal": 2,
            "regime": "TREND_UP",
            "payload": {
                "factors": {
                    "regime": "TREND_UP",
                    "values": {
                        "close": 4498.0,
                        "m15_fast": 4490.0,
                        "m15_slow": 4480.0,
                        "h1_mid": 4485.0,
                        "poc": 4492.0,
                        "atr": 12.0,
                    },
                }
            },
        }
    ]
    merged = merge_live_decisions(
        replay,
        decisions,
        strategy_id="gma_v1",
        candle_closes={t: 973.0},
    )
    hit = merged[0]
    assert hit["source"] == "live"
    assert hit["signal"] == 2
    assert hit["gma_fast"] is not None
    assert hit["gma_fast"] < 1200
    assert abs(hit["gma_fast"] - 4490.0 * (973.0 / 4498.0)) < 0.05
    assert "_candle_close" not in hit


def test_gma_live_enrich_same_scale_keeps_absolute() -> None:
    t = 1_700_000_300
    replay = [
        {
            "time": t,
            "signal": None,
            "gma_fast": 4488.0,
            "close": 4495.0,
            "source": "replay",
        }
    ]
    decisions = [
        {
            "bar_id": f"XAUUSD:{t * 1_000_000_000}",
            "legacy_signal": 1,
            "regime": "TREND_UP",
            "payload": {
                "factors": {
                    "values": {
                        "close": 4498.0,
                        "m15_fast": 4491.0,
                        "m15_slow": 4482.0,
                    },
                }
            },
        }
    ]
    merged = merge_live_decisions(
        replay,
        decisions,
        strategy_id="gma_v2",
        candle_closes={t: 4495.0},
    )
    hit = merged[0]
    assert hit["gma_fast"] == 4491.0
    assert hit["gma_slow"] == 4482.0


def test_gma_live_enrich_skips_when_scale_unknown() -> None:
    t = 1_700_000_600
    replay = [
        {
            "time": t,
            "signal": None,
            "gma_fast": 970.0,
            "close": 973.0,
            "source": "replay",
        }
    ]
    decisions = [
        {
            "bar_id": f"XAUUSD:{t * 1_000_000_000}",
            "legacy_signal": 0,
            "payload": {
                "factors": {
                    "values": {
                        "close": 50.0,
                        "m15_fast": 49.0,
                    },
                }
            },
        }
    ]
    merged = merge_live_decisions(
        replay,
        decisions,
        strategy_id="gma_v1",
        candle_closes={t: 973.0},
    )
    assert merged[0]["gma_fast"] == 970.0
