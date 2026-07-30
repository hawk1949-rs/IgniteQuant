"""Sim Cockpit chart series: overlays + per-bar meta (live decision preferred, else replay)."""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import pandas as pd

from ignitequant.engine.catch_up import parse_bar_id_ns

DEFAULT_VISIBLE_BARS = 100
WARMUP_BARS = 80
MAX_VISIBLE_BARS = 1500
HISTORY_CHUNK = 100


def _finite(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def bar_time_sec(bar: Mapping[str, Any]) -> int:
    if bar.get("time") is not None:
        return int(bar["time"])
    ns = bar.get("datetime_ns")
    if ns is not None:
        return int(ns) // 1_000_000_000
    dt = bar.get("datetime")
    if dt is not None:
        return int(dt) // 1_000_000_000
    return 0


def bar_datetime_ns(bar: Mapping[str, Any]) -> int | None:
    if bar.get("datetime_ns") is not None:
        return int(bar["datetime_ns"])
    dt = bar.get("datetime")
    if dt is not None:
        return int(dt)
    if bar.get("time") is not None:
        return int(bar["time"]) * 1_000_000_000
    return None


def _slice_bundle(ind: Any, end_idx: int) -> Any:
    """Return IndicatorBundle truncated to ``[:end_idx+1]`` (same dataclass type)."""
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


def _nan_to_none(value: float) -> float | None:
    if value != value or not math.isfinite(value):
        return None
    return float(value)


def replay_series(bars: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Compute MA / regime / legacy signal for every bar (chart-only replay)."""
    if not bars:
        return []

    from strategies.falcon import compute_indicators, detect_regime
    from strategies.falcon.score import score_signal

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
    if not rows:
        return []

    df = pd.DataFrame(rows)
    ind = compute_indicators(df)
    out: list[dict[str, Any]] = []
    for i in range(len(rows)):
        t = int(rows[i]["datetime"] // 1_000_000_000)
        meta: dict[str, Any] = {
            "time": t,
            "signal": None,
            "score_parts": None,
            "regime": None,
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
        sliced = _slice_bundle(ind, i)
        try:
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


def _decision_time_sec(decision: Mapping[str, Any]) -> int | None:
    ns = parse_bar_id_ns(str(decision.get("bar_id") or ""))
    if ns is not None:
        # bar_id may store ns or already-seconds; normalize.
        if ns > 10_000_000_000:
            return int(ns // 1_000_000_000)
        return int(ns)
    created = decision.get("created_at")
    if created:
        try:
            from datetime import datetime

            text = str(created).replace("Z", "+00:00")
            return int(datetime.fromisoformat(text).timestamp())
        except ValueError:
            return None
    return None


def _score_parts_from_decision(decision: Mapping[str, Any]) -> list[int] | None:
    payload = decision.get("payload") if isinstance(decision.get("payload"), dict) else {}
    raw = (
        decision.get("score_parts")
        or decision.get("legacy_score_parts")
        or (payload.get("legacy_score_parts") if isinstance(payload, dict) else None)
        or (payload.get("score_parts") if isinstance(payload, dict) else None)
    )
    if raw is None:
        return None
    try:
        parts = [int(x) for x in list(raw)]
    except (TypeError, ValueError):
        return None
    return parts if parts else None


def merge_live_decisions(
    replay_meta: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Prefer persisted decision signal/regime when bar times align.

    Do **not** overwrite MA/ATR from live factor_values onto chart meta: Falcon may
    decide on overseas prices (XAU ~4000) while the cockpit candle pane shows
    domestic SHFE.au (~880). Mixing those onto one price scale collapses the K-lines.
    Keep MA/ATR from replay computed on the visible bars.
    """
    by_time: dict[int, Mapping[str, Any]] = {}
    for d in decisions:
        t = _decision_time_sec(d)
        if t is None:
            continue
        by_time[t] = d

    merged: list[dict[str, Any]] = []
    for row in replay_meta:
        item = dict(row)
        live = by_time.get(int(item["time"]))
        if live is None:
            merged.append(item)
            continue
        payload = live.get("payload") if isinstance(live.get("payload"), dict) else {}
        factors = (payload.get("factors") or {}) if isinstance(payload, dict) else {}
        values = factors.get("values") if isinstance(factors, dict) else None
        if not isinstance(values, dict):
            values = live.get("factor_values") if isinstance(live.get("factor_values"), dict) else {}

        item["source"] = "live"
        item["signal"] = int(live.get("legacy_signal") or 0)
        parts = _score_parts_from_decision(live)
        if parts is not None:
            item["score_parts"] = parts
        regime = live.get("regime") or (factors.get("regime") if isinstance(factors, dict) else None)
        if regime:
            item["regime"] = str(regime)
        # ADX is scale-free; safe to show strategy's ADX even when pricing_basis=overseas.
        if values:
            adx = _finite(values.get("adx"))
            if adx is not None:
                item["adx"] = adx
        item["applied_action"] = live.get("applied_action")
        item["target_after"] = live.get("target_after")
        merged.append(item)
    return merged


def overlays_from_meta(bar_meta: Sequence[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    def series(key: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for row in bar_meta:
            val = row.get(key)
            if val is None:
                continue
            try:
                f = float(val)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(f):
                continue
            out.append({"time": int(row["time"]), "value": f})
        return out

    return {
        "ma7": series("ma7"),
        "ma14": series("ma14"),
        "ma52": series("ma52"),
        "signal": series("signal"),
    }


def cache_bars_as_cockpit(
    signal_symbol: str,
    *,
    before_sec: int | None = None,
    limit: int,
    duration_seconds: int = 300,
    root: Any = None,
) -> list[dict[str, Any]]:
    """Load completed bars from market_cache as cockpit bar dicts."""
    try:
        from ignitequant.market.cache import load_bars
    except Exception:
        return []
    try:
        frame = load_bars(signal_symbol, duration_seconds=duration_seconds, root=root)
    except FileNotFoundError:
        return []
    except Exception:
        return []
    if frame is None or frame.empty:
        return []

    rows = frame.to_dict(orient="records")
    out: list[dict[str, Any]] = []
    for r in rows:
        ns = int(r["datetime"])
        t = ns // 1_000_000_000
        if before_sec is not None and t >= int(before_sec):
            continue
        # Skip flat stub bars (open==high==low==close and volume≈0) when richer sibling exists —
        # cache merge already prefers richer; still drop obvious stubs at tip.
        o, h, l, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        vol = float(r.get("volume") or 0)
        if vol <= 0 and h == l == o == c:
            continue
        out.append(
            {
                "time": t,
                "datetime_ns": ns,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
                "open_oi": float(r.get("open_oi") or 0),
                "close_oi": float(r.get("close_oi") or 0),
                "underlying_symbol": str(r.get("underlying_symbol") or ""),
            }
        )
    if limit > 0:
        out = out[-limit:]
    return out


def merge_bar_windows(
    primary: Sequence[Mapping[str, Any]],
    older: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Merge older+primary by time; primary wins on duplicates."""
    by_time: dict[int, dict[str, Any]] = {}
    for b in older:
        by_time[bar_time_sec(b)] = dict(b)
    for b in primary:
        by_time[bar_time_sec(b)] = dict(b)
    return [by_time[t] for t in sorted(by_time)]


def assemble_visible_bars(
    hot_bars: Sequence[Mapping[str, Any]],
    *,
    signal_symbol: str,
    limit: int = DEFAULT_VISIBLE_BARS,
    before_sec: int | None = None,
    warmup: int = WARMUP_BARS,
    use_cache: bool = True,
    cache_root: Any = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """Return ``(visible_bars, compute_bars, source_note)``.

    ``compute_bars`` includes warmup prefix for indicator stability.
    ``visible_bars`` is the last ``limit`` bars ending at ``before_sec`` (exclusive) or tip.
    """
    limit = max(10, min(int(limit), MAX_VISIBLE_BARS))
    warmup = max(0, int(warmup))

    hot = [dict(b) for b in hot_bars]
    if before_sec is not None:
        hot = [b for b in hot if bar_time_sec(b) < int(before_sec)]

    source = "tqsdk_sim_live"
    need = limit + warmup
    merged = list(hot)

    if use_cache and len(merged) < need:
        earliest = bar_time_sec(merged[0]) if merged else before_sec
        cache_limit = need - len(merged) + 5
        older = cache_bars_as_cockpit(
            signal_symbol,
            before_sec=earliest,
            limit=cache_limit,
            root=cache_root,
        )
        if older:
            merged = merge_bar_windows(merged, older)
            source = "tqsdk_sim_live+market_cache" if hot else "market_cache"

    if before_sec is not None:
        merged = [b for b in merged if bar_time_sec(b) < int(before_sec)]

    if not merged:
        return [], [], source

    visible = merged[-limit:]
    compute_start = max(0, len(merged) - (limit + warmup))
    compute = merged[compute_start:]
    return visible, compute, source


def build_chart_enrichment(
    visible_bars: Sequence[Mapping[str, Any]],
    compute_bars: Sequence[Mapping[str, Any]],
    *,
    decisions: Sequence[Mapping[str, Any]] | None = None,
    price_lines: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build overlays + bar_meta aligned to ``visible_bars``."""
    if not visible_bars:
        return {
            "overlays": {"ma7": [], "ma14": [], "ma52": [], "signal": []},
            "bar_meta": [],
            "price_lines": list(price_lines or []),
        }

    replay = replay_series(compute_bars or visible_bars)
    if decisions:
        replay = merge_live_decisions(replay, decisions)

    visible_times = {bar_time_sec(b) for b in visible_bars}
    bar_meta = [dict(m) for m in replay if int(m["time"]) in visible_times]
    # Keep order of visible bars
    by_t = {int(m["time"]): m for m in bar_meta}
    ordered = []
    for b in visible_bars:
        t = bar_time_sec(b)
        ordered.append(by_t.get(t) or {"time": t, "source": "replay", "signal": None})

    return {
        "overlays": overlays_from_meta(ordered),
        "bar_meta": ordered,
        "price_lines": list(price_lines or []),
    }


def price_lines_from_strategy_payload(payload: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    lines: list[dict[str, Any]] = []
    mapping = (
        ("entry_price", "入场", "#0a84ff"),
        ("stop_price", "止损", "#ff453a"),
        ("take_price", "止盈", "#30d158"),
    )
    for key, title, color in mapping:
        val = _finite(payload.get(key))
        if val is None:
            continue
        lines.append({"price": val, "title": title, "color": color})
    return lines
