"""Catch up missed completed bars into Falcon decisions (trading-machine SoT).

Design:
- Replay each missed completed 5m bar through FalconDecisionPipeline.
- Persist decision rows + advance last_bar_id.
- Do **not** submit broker orders for intermediate bars.
- Caller may execute only the **final** bar's approved target (sim startup).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ignitequant.config import default_decision_config, load_active_decision_config
from ignitequant.domain.models import PipelineResult
from ignitequant.engine.decision_pipeline import FalconDecisionPipeline
from ignitequant.persistence.session import PersistenceSession

_CST = timezone(timedelta(hours=8))


def parse_bar_id_ns(bar_id: str | None) -> int | None:
    if not bar_id:
        return None
    text = str(bar_id).strip()
    if not text or text in {"shutdown", "boot"}:
        return None
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    try:
        return int(text)
    except ValueError:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def cst_day_start_ns(now: datetime | None = None) -> int:
    """Asia/Shanghai calendar-day start (00:00) as bar datetime ns."""
    cst = datetime.now(_CST) if now is None else now.astimezone(_CST)
    day_start = cst.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(day_start.timestamp() * 1_000_000_000)


def build_catch_up_pipeline(
    strategy_id: str,
    signal_symbol: str,
) -> tuple[Any, int, str]:
    """Return (pipeline, data_length, persistence strategy_id)."""
    sid = (strategy_id or "falcon_v2").strip()
    if sid.startswith("gma"):
        from ignitequant.strategies.gma import GMADecisionPipeline, load_gma_runtime

        profile = "gma_v2" if sid == "gma_v2" else "gma_v1"
        runtime = load_gma_runtime(profile)
        cfg = replace(runtime.decision, entry_mode="fill_confirmed", symbol=signal_symbol)
        return GMADecisionPipeline(cfg, runtime=runtime), 8000, sid
    try:
        cfg = load_active_decision_config()
    except Exception:
        cfg = default_decision_config()
    try:
        cfg = replace(cfg, entry_mode="fill_confirmed", symbol=signal_symbol)
    except TypeError:
        cfg = replace(cfg, symbol=signal_symbol)
    return FalconDecisionPipeline(cfg), 400, sid


@dataclass
class CatchUpResult:
    missed: int = 0
    recorded: int = 0
    skipped_existing: int = 0
    last_bar_id_before: str | None = None
    last_bar_id_after: str | None = None
    final_target: int = 0
    confirmed_net: int = 0
    final_bar_id: str | None = None
    final_applied_action: str | None = None
    source: str = ""
    message: str = ""
    bar_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "missed": self.missed,
            "recorded": self.recorded,
            "skipped_existing": self.skipped_existing,
            "last_bar_id_before": self.last_bar_id_before,
            "last_bar_id_after": self.last_bar_id_after,
            "final_target": self.final_target,
            "confirmed_net": self.confirmed_net,
            "final_bar_id": self.final_bar_id,
            "final_applied_action": self.final_applied_action,
            "source": self.source,
            "message": self.message,
            "bar_ids": self.bar_ids,
        }


def _existing_decision_ids(conn: sqlite3.Connection, instance_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT decision_id FROM decision_event WHERE instance_id = ?",
        (instance_id,),
    ).fetchall()
    return {str(r[0]) for r in rows}


def _window(bars: pd.DataFrame, end_idx: int, data_length: int) -> pd.DataFrame:
    start_idx = max(0, end_idx - data_length + 1)
    return bars.iloc[start_idx : end_idx + 1].copy()


def klines_snapshot_to_frame(snapshot: dict[str, Any] | None) -> pd.DataFrame:
    """Convert sim_klines JSON snapshot to Tq-like OHLCV frame."""
    if not snapshot:
        return pd.DataFrame()
    rows = snapshot.get("bars") or []
    if not rows:
        return pd.DataFrame()
    records: list[dict[str, Any]] = []
    for b in rows:
        ns = b.get("datetime_ns")
        if ns is None and b.get("time") is not None:
            ns = int(b["time"]) * 1_000_000_000
        if ns is None:
            continue
        records.append(
            {
                "datetime": int(ns),
                "open": float(b["open"]),
                "high": float(b["high"]),
                "low": float(b["low"]),
                "close": float(b["close"]),
                "volume": float(b.get("volume") or 0),
                "open_oi": float(b.get("open_oi") or 0),
                "close_oi": float(b.get("close_oi") or 0),
            }
        )
    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).sort_values("datetime").reset_index(drop=True)


def load_catch_up_bars(
    *,
    instance_id: str,
    signal_symbol: str = "KQ.m@SHFE.au",
    runtime_dir: Path | None = None,
    root: Path | None = None,
    drop_forming: bool = True,
) -> tuple[pd.DataFrame, str]:
    """Prefer live sim snapshot, else market_cache."""
    from ignitequant.market.sim_klines import load_klines_snapshot

    snap = load_klines_snapshot(instance_id, runtime_dir=runtime_dir)
    frame = klines_snapshot_to_frame(snap)
    if not frame.empty:
        if drop_forming and len(frame) >= 2:
            # Snapshot usually includes forming tip; catch-up uses completed only.
            # Drop last if younger than ~4.5 minutes vs previous (heuristic: always
            # drop last when include_forming default — safer for offline API).
            frame = frame.iloc[:-1].reset_index(drop=True)
        if not frame.empty:
            return frame, "klines_snapshot"

    try:
        from ignitequant.market.cache import load_bars

        bars = load_bars(signal_symbol, duration_seconds=300, root=root)
        if bars is not None and not bars.empty:
            return bars.reset_index(drop=True), "market_cache"
    except FileNotFoundError:
        pass
    return pd.DataFrame(), "none"


def catch_up_missed_bars(
    *,
    session: PersistenceSession,
    pipeline: Any,
    bars: pd.DataFrame,
    last_bar_id: str | None,
    confirmed_net: int,
    data_length: int = 400,
    source: str = "",
    max_bars: int = 500,
    bootstrap_today: bool = False,
    bootstrap_from_ns: int | None = None,
) -> CatchUpResult:
    """Replay completed bars after last_bar_id; persist decisions; advance state.

    Orders are never submitted here. ``final_target`` reflects pipeline after replay
    so the caller (sim) can align broker once.
    """
    result = CatchUpResult(
        last_bar_id_before=last_bar_id,
        confirmed_net=int(confirmed_net),
        final_target=int(pipeline.current_target),
        source=source,
    )
    if bars is None or bars.empty or "datetime" not in bars.columns:
        result.message = "无可用 K 线，无法补跑"
        return result

    after_ns = parse_bar_id_ns(last_bar_id)
    if after_ns is None and bootstrap_today and bootstrap_from_ns is None:
        bootstrap_from_ns = cst_day_start_ns()
    if after_ns is None and bootstrap_from_ns is not None:
        idxs = [
            i
            for i, ns in enumerate(bars["datetime"].astype("int64").tolist())
            if int(ns) >= int(bootstrap_from_ns)
        ]
        if not idxs:
            result.message = "当日尚无已完成 K 线可补信号"
            result.last_bar_id_after = last_bar_id
            return result
    elif after_ns is None:
        result.message = "无 last_bar_id，跳过补跑（避免全历史重放；GMA 可用 bootstrap_today）"
        return result
    else:
        idxs = [
            i
            for i, ns in enumerate(bars["datetime"].astype("int64").tolist())
            if int(ns) > after_ns
        ]
        if not idxs:
            result.message = "没有漏掉的已完成 K 线"
            result.last_bar_id_after = last_bar_id
            return result

    if hasattr(pipeline, "prepare_replay"):
        pipeline.prepare_replay(bars)

    if len(idxs) > max_bars:
        idxs = idxs[-max_bars:]
        result.message = f"漏 K 过多，仅补最近 {max_bars} 根"

    existing = _existing_decision_ids(session.repo._conn, session.instance_id)  # noqa: SLF001
    result.missed = len(idxs)
    final: PipelineResult | None = None

    for i in idxs:
        window = _window(bars, i, data_length)
        if len(window) < 50:
            continue
        pr = pipeline.on_bar_close(window, trade=True)
        final = pr
        result.bar_ids.append(pr.bar_id)
        if pr.bar_id in existing:
            result.skipped_existing += 1
        else:
            session.record_decision(pr)
            existing.add(pr.bar_id)
            result.recorded += 1
        session.save_state(
            symbol=session.symbol or pr.target.symbol,
            current_target=int(pipeline.current_target),
            confirmed_net=int(confirmed_net),
            cooldown_left=int(pipeline.risk.state.cooldown_left),
            entry_price=pipeline.risk.state.entry_price,
            stop_price=pipeline.risk.state.stop_price,
            take_price=pipeline.risk.state.take_price,
            entry_signal=pipeline.risk.state.entry_signal,
            last_bar_id=pr.bar_id,
            config_hash=pipeline.config.config_hash(),
            pending_desired=(
                int(pipeline.current_target)
                if int(pipeline.current_target) != int(confirmed_net)
                else None
            ),
        )

    if final is not None:
        result.final_target = int(pipeline.current_target)
        result.final_bar_id = final.bar_id
        result.final_applied_action = final.applied_action
        result.last_bar_id_after = final.bar_id
        if not result.message:
            if bootstrap_from_ns is not None and after_ns is None:
                result.message = (
                    f"当日补信号完成：共 {result.missed} 根，新记决策 {result.recorded}，"
                    f"已有跳过 {result.skipped_existing}；目标={result.final_target}"
                )
            else:
                result.message = (
                    f"补跑完成：漏 {result.missed} 根，新记决策 {result.recorded}，"
                    f"已有跳过 {result.skipped_existing}；目标={result.final_target}"
                )
    return result


def catch_up_session_db(
    db_path: Path | str,
    instance_id: str,
    *,
    strategy_id: str = "falcon_v2",
    runtime_dir: Path | None = None,
    root: Path | None = None,
    signal_symbol: str = "KQ.m@SHFE.au",
    max_bars: int = 500,
    bootstrap_today: bool = False,
) -> CatchUpResult:
    """Open local sqlite, load bars, restore pipeline, catch up (no live orders)."""
    path = Path(db_path)
    if not path.is_file():
        return CatchUpResult(message=f"sqlite 不存在: {path}")

    bars, source = load_catch_up_bars(
        instance_id=instance_id,
        signal_symbol=signal_symbol,
        runtime_dir=runtime_dir,
        root=root,
        drop_forming=True,
    )
    if bars.empty:
        return CatchUpResult(
            source=source,
            message="无 K 线来源（需要 *.klines.json 或 market_cache）",
        )

    pipeline, data_length, persist_strategy_id = build_catch_up_pipeline(
        strategy_id,
        signal_symbol,
    )

    session = PersistenceSession.open(
        path,
        instance_id=instance_id,
        strategy_id=persist_strategy_id,
    )
    try:
        state = session.repo.load_strategy_state(instance_id)
        payload = dict(state.payload) if state else {}
        confirmed = int(payload.get("confirmed_net", 0))
        pipeline.restore_runtime(
            current_target=int(payload.get("current_target", confirmed)),
            cooldown_left=int(payload.get("cooldown_left", 0)),
            entry_price=payload.get("entry_price"),
            stop_price=payload.get("stop_price"),
            take_price=payload.get("take_price"),
            entry_signal=payload.get("entry_signal"),
        )
        if state and state.symbol:
            session.symbol = state.symbol
        out = catch_up_missed_bars(
            session=session,
            pipeline=pipeline,
            bars=bars,
            last_bar_id=payload.get("last_bar_id"),
            confirmed_net=confirmed,
            data_length=data_length,
            source=source,
            max_bars=max_bars,
            bootstrap_today=bootstrap_today,
        )
        try:
            from ignitequant.persistence.cloud_sync import try_push_outbox

            conn = getattr(session.repo, "_conn", None)
            try_push_outbox(conn, root=root or path.parents[1], db_hint=str(path))
        except Exception:
            pass
        return out
    finally:
        session.close()
