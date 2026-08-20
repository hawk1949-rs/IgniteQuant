"""Unit tests for Sim Cockpit chart series enrichment."""

from __future__ import annotations

from ignitequant.market.chart_series import (
    assemble_visible_bars,
    build_chart_enrichment,
    merge_live_decisions,
    overlays_from_meta,
    price_lines_from_strategy_payload,
    replay_series,
)


def _synthetic_bars(n: int = 120, start_ns: int = 1_700_000_000_000_000_000) -> list[dict]:
    bars = []
    px = 500.0
    for i in range(n):
        ns = start_ns + i * 300_000_000_000
        px = px + (0.15 if i % 7 < 4 else -0.1)
        bars.append(
            {
                "time": ns // 1_000_000_000,
                "datetime_ns": ns,
                "open": px,
                "high": px + 0.3,
                "low": px - 0.3,
                "close": px + 0.05,
                "volume": 100 + i,
            }
        )
    return bars


def test_replay_series_fills_every_bar() -> None:
    bars = _synthetic_bars(90)
    meta = replay_series(bars)
    assert len(meta) == 90
    assert meta[0]["source"] == "replay"
    # After warmup, signal should be an int in [-3, 3]
    later = [m for m in meta[60:] if m["signal"] is not None]
    assert later
    assert all(-3 <= int(m["signal"]) <= 3 for m in later)
    assert any(m["ma52"] is not None for m in meta[60:])


def test_merge_live_overrides_replay() -> None:
    bars = _synthetic_bars(80)
    replay = replay_series(bars)
    target = replay[70]
    # Simulate overseas factor MAs (~4000) that must NOT replace chart MAs.
    decisions = [
        {
            "bar_id": f"KQ.m@SHFE.au:{bars[70]['datetime_ns']}",
            "legacy_signal": 3,
            "score_parts": [2, 1, 0, 0],
            "regime": "TREND_UP",
            "applied_action": "TARGET",
            "target_after": 2,
            "payload": {
                "factors": {
                    "regime": "TREND_UP",
                    "values": {
                        "ma7": 4036.0,
                        "ma14": 4035.0,
                        "ma52": 4049.0,
                        "atr": 12.0,
                        "adx": 35.0,
                    },
                }
            },
        }
    ]
    merged = merge_live_decisions(replay, decisions)
    hit = next(m for m in merged if m["time"] == target["time"])
    assert hit["source"] == "live"
    assert hit["signal"] == 3
    assert hit["score_parts"] == [2, 1, 0, 0]
    assert hit["regime"] == "TREND_UP"
    assert hit["adx"] == 35.0
    # Chart MAs stay on the visible bar scale (replay), not overseas factors.
    assert hit["ma7"] == target["ma7"]
    assert hit["ma52"] == target["ma52"]
    assert hit["atr"] == target["atr"]
    assert hit["ma7"] is None or hit["ma7"] < 1000


def test_overlays_align_to_meta() -> None:
    bars = _synthetic_bars(70)
    meta = replay_series(bars)
    overlays = overlays_from_meta(meta)
    assert overlays["ma7"]
    assert overlays["signal"]
    assert all("time" in p and "value" in p for p in overlays["ma7"])


def test_build_chart_enrichment_trims_to_visible() -> None:
    all_bars = _synthetic_bars(120)
    visible = all_bars[-40:]
    enrichment = build_chart_enrichment(visible, all_bars)
    assert len(enrichment["bar_meta"]) == 40
    assert enrichment["bar_meta"][0]["time"] == visible[0]["time"]
    assert enrichment["overlays"]["ma52"]
    assert enrichment.get("energy_profile") is None


def test_gma_v2_enrichment_includes_energy_histogram() -> None:
    """GMA 2.0 chart payload must carry right-side volume-profile bins."""
    all_bars = _synthetic_bars(80)
    visible = all_bars[-40:]
    enrichment = build_chart_enrichment(visible, all_bars, strategy_id="gma_v2")
    profile = enrichment.get("energy_profile")
    assert profile is not None
    assert profile["bins"]
    assert profile["poc"] is not None
    assert profile["vah"] is not None
    assert profile["val"] is not None
    assert any(b.get("in_va") for b in profile["bins"])
    assert enrichment["overlay_specs"]
    keys = {s["key"] for s in enrichment["overlay_specs"]}
    assert {"gma_poc", "gma_vah", "gma_val"} <= keys


def test_gma_v1_enrichment_skips_energy_histogram() -> None:
    all_bars = _synthetic_bars(80)
    visible = all_bars[-40:]
    enrichment = build_chart_enrichment(visible, all_bars, strategy_id="gma_v1")
    assert enrichment.get("energy_profile") is None


def test_assemble_visible_without_cache() -> None:
    hot = _synthetic_bars(50)
    visible, compute, source = assemble_visible_bars(
        hot, signal_symbol="KQ.m@SHFE.au", limit=30, use_cache=False
    )
    assert len(visible) == 30
    assert len(compute) >= 30
    assert source == "tqsdk_sim_live"
    assert visible[-1]["time"] == hot[-1]["time"]


def test_assemble_with_before_excludes_tip() -> None:
    hot = _synthetic_bars(50)
    tip = hot[-1]["time"]
    visible, _, _ = assemble_visible_bars(
        hot,
        signal_symbol="KQ.m@SHFE.au",
        limit=20,
        before_sec=tip,
        use_cache=False,
    )
    assert visible
    assert all(b["time"] < tip for b in visible)


def test_price_lines_from_payload() -> None:
    lines = price_lines_from_strategy_payload(
        {"entry_price": 880.5, "stop_price": 870.0, "take_price": 900.0}
    )
    assert len(lines) == 3
    assert {x["title"] for x in lines} == {"入场", "止损", "止盈"}
