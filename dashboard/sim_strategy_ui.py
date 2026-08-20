# -*- coding: utf-8 -*-
"""Sim cockpit strategy presentation registry.

Each sim strategy registers how to replay chart meta, format score parts, and
summarize factors. The cockpit API and web UI consume this metadata instead of
hardcoding Falcon-specific fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ignitequant.domain.enums import FactorQuality, Regime
from ignitequant.market.chart_series import bar_datetime_ns, bar_time_sec


@dataclass(frozen=True)
class OverlayLineSpec:
    key: str
    label: str
    color: str
    pane: str = "main"  # main | signal


@dataclass(frozen=True)
class StrategyUIProfile:
    family: str
    score_parts_schema: str
    score_part_labels: tuple[str, ...]
    overlay_specs: tuple[OverlayLineSpec, ...]
    warmup_bars: int
    regime_note: str

    def overlay_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.overlay_specs)

    def empty_overlays(self) -> dict[str, list[dict[str, Any]]]:
        return {spec.key: [] for spec in self.overlay_specs}

    def overlay_specs_public(self) -> list[dict[str, str]]:
        return [
            {"key": s.key, "label": s.label, "color": s.color, "pane": s.pane}
            for s in self.overlay_specs
        ]

    def presentation_public(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "score_parts_schema": self.score_parts_schema,
            "score_part_labels": list(self.score_part_labels),
            "overlay_specs": self.overlay_specs_public(),
            "warmup_bars": self.warmup_bars,
            "regime_note": self.regime_note,
        }

    def format_score_parts(self, parts: Sequence[int] | None) -> str:
        if not parts:
            return "—"
        labels = self.score_part_labels
        chunks: list[str] = []
        for i, raw in enumerate(parts):
            label = labels[i] if i < len(labels) else f"p{i}"
            chunks.append(f"{label}={int(raw)}")
        return " · ".join(chunks)

    def format_factor_summary(
        self,
        *,
        regime: str | None,
        quality: str | None,
        values: Mapping[str, Any] | None,
    ) -> str:
        raise NotImplementedError

    def replay_bar_meta(self, bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def overlays_from_meta(
        self, bar_meta: Sequence[Mapping[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        out = self.empty_overlays()
        keys = set(self.overlay_keys())
        for row in bar_meta:
            t = int(row.get("time") or 0)
            for key in keys:
                val = row.get(key)
                if val is None:
                    continue
                try:
                    f = float(val)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(f):
                    continue
                out[key].append({"time": t, "value": f})
        return out

    def enrich_live_meta(
        self,
        item: dict[str, Any],
        live: Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> None:
        """Attach strategy-specific overlay fields from a persisted decision."""
        del live, values, item  # default: no extra fields


def _finite(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def _nan_to_none(value: float) -> float | None:
    if value != value or not math.isfinite(value):
        return None
    return float(value)


def _bars_to_rows(bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for b in bars:
        ns = bar_datetime_ns(b)
        if ns is None:
            continue
        rows.append(
            {
                "datetime": int(ns),
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume") or 0),
            }
        )
    return rows


def _regime_label(regime: str | None) -> str:
    mapping = {
        "TREND_UP": "上升趋势",
        "TREND_DOWN": "下降趋势",
        "RANGE": "震荡",
        "TRANSITION": "切换中",
    }
    if not regime:
        return "—"
    return mapping.get(str(regime), str(regime))


def _quality_label(quality: str | None) -> str:
    mapping = {
        "READY": "就绪",
        "WARMING_UP": "预热中",
        "STALE": "过期",
        "MISSING_DATA": "缺数据",
        "INVALID_VALUE": "无效",
    }
    if not quality:
        return "—"
    return mapping.get(str(quality), str(quality))


@dataclass(frozen=True)
class FalconUIProfile(StrategyUIProfile):
    def format_factor_summary(
        self,
        *,
        regime: str | None,
        quality: str | None,
        values: Mapping[str, Any] | None,
    ) -> str:
        vals = values or {}
        parts = [
            f"策略{_regime_label(regime)}",
            _quality_label(quality),
        ]
        adx = _finite(vals.get("adx"))
        if adx is not None:
            parts.append(f"ADX {adx:.1f}")
        close = _finite(vals.get("close"))
        ma52 = _finite(vals.get("ma52"))
        if close is not None and ma52 is not None:
            parts.append(f"Close/MA52 {close - ma52:+.2f}")
        return " · ".join(p for p in parts if p and p != "—")

    def replay_bar_meta(self, bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        from strategies.falcon import compute_indicators, detect_regime
        from strategies.falcon.score import score_signal

        rows = _bars_to_rows(bars)
        if not rows:
            return []

        df = pd.DataFrame(rows)
        ind = compute_indicators(df)

        def slice_bundle(end_idx: int):
            sl = slice(0, end_idx + 1)
            return type(ind)(
                close=ind.close[sl],
                high=ind.high[sl],
                low=ind.low[sl],
                volume=ind.volume[sl],
                ma7=ind.ma7[sl],
                ma14=ind.ma14[sl],
                ma52=ind.ma52[sl],
                atr=ind.atr[sl],
                adx=ind.adx[sl],
                k=ind.k[sl],
                d=ind.d[sl],
                j=ind.j[sl],
                vol_ma=ind.vol_ma[sl],
            )

        out: list[dict[str, Any]] = []
        for i in range(len(rows)):
            t = int(rows[i]["datetime"] // 1_000_000_000)
            meta: dict[str, Any] = {
                "time": t,
                "signal": None,
                "score_parts": None,
                "regime": None,
                "close": _finite(rows[i].get("close")),
                "ma7": _nan_to_none(float(ind.ma7[i])),
                "ma14": _nan_to_none(float(ind.ma14[i])),
                "ma52": _nan_to_none(float(ind.ma52[i])),
                "atr": _nan_to_none(float(ind.atr[i])),
                "adx": _nan_to_none(float(ind.adx[i])),
                "source": "replay",
            }
            if i < 2:
                out.append(meta)
                continue
            try:
                sliced = slice_bundle(i)
                detail = score_signal(sliced)
                regime = detect_regime(sliced)
                meta["signal"] = int(detail.signal)
                meta["score_parts"] = [
                    int(detail.granville),
                    int(detail.volume),
                    int(detail.kdj),
                    int(detail.conflict_penalty),
                ]
                meta["regime"] = regime.value
            except Exception:
                pass
            out.append(meta)
        return out


def _same_price_scale(a: float, b: float) -> bool:
    """True when a/b is near 1 (same market scale)."""
    if a == 0 or b == 0:
        return False
    ratio = abs(a / b)
    return 0.75 <= ratio <= 1.35


def _overlay_scale(chart_close: float | None, signal_close: float | None) -> float | None:
    """Map decision-clock prices onto the chart candle scale.

    GMA decisions are often priced on XAUUSD (~4500) while the domestic cockpit
    chart is SHFE.au (~970). Without scaling, live overlays paint off-chart.
    """
    if chart_close is None or signal_close is None or signal_close == 0:
        return None
    ratio = float(chart_close) / float(signal_close)
    if _same_price_scale(chart_close, signal_close):
        return 1.0
    # Typical au domestic/XAUUSD ratio is ~0.2; reject absurd jumps.
    if 0.12 <= ratio <= 0.45 or 2.2 <= ratio <= 8.5:
        return ratio
    return None


@dataclass(frozen=True)
class GmaUIProfile(StrategyUIProfile):
    runtime_profile: str = "gma_v1"

    def format_factor_summary(
        self,
        *,
        regime: str | None,
        quality: str | None,
        values: Mapping[str, Any] | None,
    ) -> str:
        vals = values or {}
        align = vals.get("alignment")
        if align is None:
            parts_raw = vals.get("score_parts")
            if isinstance(parts_raw, (list, tuple)) and parts_raw:
                align = parts_raw[0]
        align_txt = "—"
        if align is not None:
            code = int(float(align))
            align_txt = {3: "驱动", 2: "方向", 0: "震荡"}.get(code, str(code))
        parts = [
            f"策略{_regime_label(regime)}",
            f"对齐{align_txt}",
            _quality_label(quality),
        ]
        poc = _finite(vals.get("poc")) or _finite(vals.get("gma_poc"))
        if poc is not None:
            parts.append(f"POC {poc:.2f}")
        return " · ".join(p for p in parts if p and p != "—")

    def replay_bar_meta(self, bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Chart-local GMA overlays (fast/slow/mid/POC) on the candle price scale.

        Uses one HTF resample + as-of lookup instead of per-bar ``generate_signal``
        so cockpit charts stay responsive. Signal/regime still come from live
        decisions when available.
        """
        from ignitequant.strategies.gma import load_gma_runtime
        from ignitequant.strategies.gma.indicators import (
            keltner_channel,
            tenw_series,
            volume_profile,
        )
        from ignitequant.strategies.gma.resample import resample_bundle

        rows = _bars_to_rows(bars)
        if not rows:
            return []

        df = pd.DataFrame(rows)
        runtime = load_gma_runtime(self.runtime_profile)
        ind = runtime.indicators
        bundle = resample_bundle(df)
        m15 = bundle.get("15m")
        h1 = bundle.get("1h")

        t15 = (
            (m15["datetime"].to_numpy(dtype="int64") // 1_000_000_000).astype(int)
            if m15 is not None and not m15.empty
            else np.array([], dtype=int)
        )
        t1 = (
            (h1["datetime"].to_numpy(dtype="int64") // 1_000_000_000).astype(int)
            if h1 is not None and not h1.empty
            else np.array([], dtype=int)
        )
        f15 = s15 = np.array([])
        mid1 = atr1 = np.array([])
        if len(t15):
            f15, s15, _fc, _sc = tenw_series(
                m15.close.to_numpy(dtype=float),
                fast_period=ind.fast_period,
                slow_period=ind.slow_period,
            )
        if len(t1):
            high = h1.high.to_numpy(dtype=float)
            low = h1.low.to_numpy(dtype=float)
            close = h1.close.to_numpy(dtype=float)
            mid1, _up, _lo, atr1 = keltner_channel(
                high, low, close, length=ind.keltner_length, times_atr=ind.keltner_inner_atr
            )

        out: list[dict[str, Any]] = []
        lookback = max(8, int(ind.vp_lookback_15m))
        # VP is relatively expensive; only fill POC for the tip window used by the chart.
        poc_from = max(0, len(rows) - 160)
        poc_by_j: dict[int, float] = {}
        for i, row in enumerate(rows):
            t = int(row["datetime"] // 1_000_000_000)
            meta: dict[str, Any] = {
                "time": t,
                "signal": None,
                "score_parts": None,
                "regime": None,
                "gma_fast": None,
                "gma_slow": None,
                "gma_mid": None,
                "gma_poc": None,
                "atr": None,
                "close": _finite(row.get("close")),
                "source": "replay",
            }
            j = -1
            if len(t15):
                j = int(np.searchsorted(t15, t, side="right") - 1)
                if j >= 0:
                    meta["gma_fast"] = _nan_to_none(float(f15[j])) if j < len(f15) else None
                    meta["gma_slow"] = _nan_to_none(float(s15[j])) if j < len(s15) else None
                    if i >= poc_from and j + 1 >= lookback and m15 is not None:
                        if j not in poc_by_j:
                            sl = m15.iloc[max(0, j + 1 - lookback) : j + 1]
                            try:
                                vp = volume_profile(
                                    sl.high.to_numpy(dtype=float),
                                    sl.low.to_numpy(dtype=float),
                                    sl.close.to_numpy(dtype=float),
                                    sl.volume.to_numpy(dtype=float),
                                    bins=ind.vp_bins,
                                    value_pct=ind.vp_value_pct,
                                )
                                poc = _finite(vp.poc)
                                if poc is not None:
                                    poc_by_j[j] = poc
                            except Exception:
                                pass
                        if j in poc_by_j:
                            meta["gma_poc"] = poc_by_j[j]
                            meta["poc"] = meta["gma_poc"]
            if len(t1):
                k = int(np.searchsorted(t1, t, side="right") - 1)
                if k >= 0:
                    meta["gma_mid"] = _nan_to_none(float(mid1[k])) if k < len(mid1) else None
                    meta["atr"] = _nan_to_none(float(atr1[k])) if k < len(atr1) else None
            out.append(meta)
        return out

    def enrich_live_meta(
        self,
        item: dict[str, Any],
        live: Mapping[str, Any],
        values: Mapping[str, Any],
    ) -> None:
        del live
        chart_close = _finite(item.get("_candle_close")) or _finite(item.get("close"))
        signal_close = _finite(values.get("close"))
        scale = _overlay_scale(chart_close, signal_close)
        if scale is None:
            # Keep chart-local replay overlays; never paint a foreign price scale.
            return
        mapping = {
            "m15_fast": "gma_fast",
            "m15_slow": "gma_slow",
            "h1_mid": "gma_mid",
            "poc": "gma_poc",
            "atr": "atr",
        }
        for src, dst in mapping.items():
            val = _finite(values.get(src))
            if val is None:
                continue
            item[dst] = float(val) * scale
        if scale != 1.0 and signal_close is not None and chart_close is not None:
            item["close"] = chart_close


@dataclass(frozen=True)
class GenericUIProfile(StrategyUIProfile):
    """Fallback for strategies without dedicated chart replay yet."""

    def format_factor_summary(
        self,
        *,
        regime: str | None,
        quality: str | None,
        values: Mapping[str, Any] | None,
    ) -> str:
        parts = [_regime_label(regime), _quality_label(quality)]
        vals = values or {}
        close = _finite(vals.get("close"))
        if close is not None:
            parts.append(f"Close {close:.2f}")
        return " · ".join(p for p in parts if p and p != "—")

    def replay_bar_meta(self, bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [
            {"time": bar_time_sec(b), "source": "replay", "signal": None}
            for b in bars
            if bar_time_sec(b) > 0
        ]


FALCON_UI = FalconUIProfile(
    family="falcon",
    score_parts_schema="falcon_v2",
    score_part_labels=("Granville", "量能", "KDJ", "冲突"),
    overlay_specs=(
        OverlayLineSpec("ma7", "MA7", "#64d2ff"),
        OverlayLineSpec("ma14", "MA14", "#ffd60a"),
        OverlayLineSpec("ma52", "MA52", "#bf5af2"),
        OverlayLineSpec("signal", "信号", "#30d158", pane="signal"),
    ),
    warmup_bars=80,
    regime_note="ADX/MA 趋势状态机",
)

GMA_V1_UI = GmaUIProfile(
    family="gma",
    score_parts_schema="gma_v1",
    score_part_labels=("对齐", "方向", "信号", "连亏"),
    overlay_specs=(
        OverlayLineSpec("gma_fast", "15m快", "#64d2ff"),
        OverlayLineSpec("gma_slow", "15m慢", "#ffd60a"),
        OverlayLineSpec("gma_mid", "1H中", "#bf5af2"),
        OverlayLineSpec("gma_poc", "POC", "#ff9f0a"),
        OverlayLineSpec("signal", "信号", "#30d158", pane="signal"),
    ),
    warmup_bars=200,
    regime_note="多周期对齐映射的趋势/震荡",
    runtime_profile="gma_v1",
)

GMA_V2_UI = GmaUIProfile(
    family="gma",
    score_parts_schema="gma_v2",
    score_part_labels=("对齐", "方向", "信号", "连亏"),
    overlay_specs=(
        OverlayLineSpec("gma_fast", "15m快", "#64d2ff"),
        OverlayLineSpec("gma_slow", "15m慢", "#ffd60a"),
        OverlayLineSpec("gma_mid", "1H中", "#bf5af2"),
        OverlayLineSpec("gma_poc", "POC", "#ff9f0a"),
        OverlayLineSpec("signal", "信号", "#30d158", pane="signal"),
    ),
    warmup_bars=200,
    regime_note="多周期对齐 + 能量分布",
    runtime_profile="gma_v2",
)

GENERIC_UI = GenericUIProfile(
    family="generic",
    score_parts_schema="generic",
    score_part_labels=("p0", "p1", "p2", "p3"),
    overlay_specs=(OverlayLineSpec("signal", "信号", "#30d158", pane="signal"),),
    warmup_bars=50,
    regime_note="通用策略展示",
)

_PROFILES: dict[str, StrategyUIProfile] = {
    "falcon_v2": FALCON_UI,
    "gma_v1": GMA_V1_UI,
    "gma_v2": GMA_V2_UI,
}


def resolve_strategy_ui(strategy_id: str) -> StrategyUIProfile:
    sid = (strategy_id or "").strip()
    if sid in _PROFILES:
        return _PROFILES[sid]
    if sid.startswith("gma"):
        return GMA_V1_UI
    if sid.startswith("falcon"):
        return FALCON_UI
    return GENERIC_UI


def presentation_catalog() -> dict[str, dict[str, Any]]:
    return {sid: profile.presentation_public() for sid, profile in _PROFILES.items()}


def format_pipeline_risk(payload: Mapping[str, Any] | None) -> str | None:
    if not payload:
        return None
    risk = payload.get("risk_decision")
    if not isinstance(risk, dict):
        return None
    chunks: list[str] = []
    stop = _finite(risk.get("stop_price"))
    take = _finite(risk.get("take_price"))
    exit_action = risk.get("legacy_exit_action")
    cooldown = risk.get("cooldown_left")
    if stop is not None:
        chunks.append(f"止损 {stop:.2f}")
    if take is not None:
        chunks.append(f"止盈 {take:.2f}")
    if exit_action and str(exit_action) not in {"NONE", "none", ""}:
        chunks.append(f"退出 {exit_action}")
    if cooldown is not None and int(cooldown) > 0:
        chunks.append(f"冷却 {int(cooldown)}")
    return " · ".join(chunks) if chunks else None


def build_chart_context(
    strategy_id: str,
    bars: Sequence[Mapping[str, Any]],
    *,
    latest_decision: Mapping[str, Any] | None = None,
    short_bias: str | None = None,
) -> dict[str, Any] | None:
    """Strategy-aware chart context; prefers persisted decision over replay."""
    profile = resolve_strategy_ui(strategy_id)
    if latest_decision:
        factors = latest_decision.get("factor_values") or {}
        if not isinstance(factors, dict):
            payload = latest_decision.get("payload") or {}
            inner = (payload.get("factors") or {}) if isinstance(payload, dict) else {}
            factors = inner.get("values") if isinstance(inner, dict) else {}
            if not isinstance(factors, dict):
                factors = {}
        regime = latest_decision.get("regime")
        quality = None
        payload = latest_decision.get("payload") or {}
        if isinstance(payload, dict):
            inner = payload.get("factors") or {}
            if isinstance(inner, dict):
                quality = inner.get("quality")
                regime = regime or inner.get("regime")
        return {
            "strategy_id": strategy_id,
            "regime": regime,
            "short_bias": short_bias,
            "factor_summary": profile.format_factor_summary(
                regime=str(regime) if regime else None,
                quality=str(quality) if quality else None,
                values=factors,
            ),
            "score_parts_schema": profile.score_parts_schema,
            "source": "live_decision",
        }

    if len(bars) < 30:
        return None
    replay = profile.replay_bar_meta(bars)
    if not replay:
        return None
    last = replay[-1]
    return {
        "strategy_id": strategy_id,
        "regime": last.get("regime"),
        "short_bias": short_bias,
        "factor_summary": profile.format_factor_summary(
            regime=str(last.get("regime")) if last.get("regime") else None,
            quality=FactorQuality.READY.value,
            values={k: last.get(k) for k in last if k not in {"time", "source", "signal", "score_parts", "regime"}},
        ),
        "score_parts_schema": profile.score_parts_schema,
        "source": "replay",
    }
