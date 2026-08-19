#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Falcon v2 快期模拟盘入口（TqKq）。

决策核：ignitequant.engine.FalconDecisionPipeline（与回测 / 看板共用）。
执行层：TargetPositionExecutor + RiskEngine（Phase 3）。
持久化：SQLite WAL + 启动对账（Phase 4，见 ENABLE_PERSISTENCE）。
云同步：心跳/收盘自动把 sync_outbox 推到 Supabase（ENABLE_CLOUD_SYNC，需 DATABASE_URL）。
- 账户：TqKq；无期末强制平仓
- Web UI：http://127.0.0.1:9876
- Ctrl+C 退出（可选先平仓，见 FLAT_ON_EXIT）
"""

from __future__ import annotations

import datetime
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

from tqsdk import TqApi, TqAuth, TqKq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "strategies") not in sys.path:
    sys.path.insert(0, str(ROOT / "strategies"))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from falcon.sizing import LOT_BY_SIGNAL
from ignitequant.config import load_active_decision_config
from ignitequant.domain.enums import ReasonCode, RiskAction
from ignitequant.domain.models import AccountSnapshot, FillEvent, PositionSnapshot
from ignitequant.engine import (
    BrokerFacts,
    FalconDecisionPipeline,
    LocalProjection,
    annotate_klines,
    apply_pretrade,
    atr_of,
    close_of,
    domestic_session_allows_orders,
    healthy_runtime,
    make_risk_engine,
    market_closed_reject_decision,
    may_submit_domestic_order,
    score_parts,
)
from ignitequant.execution import TargetPositionExecutor
from ignitequant.market.cache import resolve_instrument
from ignitequant.market.overseas_bars import (
    bars_dicts_to_dataframe,
    drop_forming_5m_bar,
    fetch_for_signal_source,
)
from ignitequant.market.session import shfe_precious_session_open
from ignitequant.market.symbols import resolve_signal_source
from ignitequant.persistence import PersistenceSession
from ignitequant.portfolio.stop_scale import scale_atr_to_entry


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


SIGNAL_SYMBOL = "KQ.m@SHFE.au"
KLINE_SECONDS = 60 * 5
DATA_LENGTH = 400
STRATEGY_ID = "falcon_v2"
STRATEGY_LABEL = "Falcon v2"
WEB_GUI = ":9876"
FLAT_ON_EXIT = True
HEARTBEAT_SECONDS = 60
ENABLE_PERSISTENCE = True
ENABLE_CLOUD_SYNC = os.environ.get("ENABLE_CLOUD_SYNC", "1").strip() not in {
    "0",
    "false",
    "False",
    "no",
}
INSTANCE_ID = "falcon_au_sim"
PERSIST_DB = ROOT / "data" / "runtime" / "falcon_au_sim.sqlite"
PID_FILE = PERSIST_DB.parent / f"{INSTANCE_ID}.pid"
RECON_EVERY_BARS = 12  # ~1 hour on 5m bars
MAX_CONSECUTIVE_ERRORS = 5
OVERSEAS_POLL_SECONDS = 20
OVERSEAS_BAR_SECONDS = 300


def _write_pid_file() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _cleanup_pid_file() -> None:
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def _cloud_sync_outbox(persist: PersistenceSession | None) -> None:
    """Best-effort push of local outbox → Supabase. Never raises."""
    if not ENABLE_CLOUD_SYNC or persist is None:
        return
    try:
        from ignitequant.persistence.cloud_sync import try_push_outbox

        conn = getattr(persist.repo, "_conn", None)
        result = try_push_outbox(
            conn,
            root=ROOT,
            db_hint=str(PERSIST_DB),
            limit=200,
            instance_key=INSTANCE_ID,
        )
        synced = int(result.get("synced") or 0)
        failed = int(result.get("failed") or 0)
        skipped = result.get("skipped")
        if skipped and skipped != "no_database_url":
            print(f"[云同步] 跳过: {skipped}", flush=True)
        elif skipped == "no_database_url":
            print("[云同步] 未配置 DATABASE_URL，跳过推送", flush=True)
        elif synced or failed:
            print(f"[云同步] synced={synced} failed={failed}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[云同步] 失败（忽略）: {exc}", flush=True)


def _with_fill_confirmed_entry(cfg):
    """Sim must arm stops only after broker fill — never on TARGET intent alone."""
    if getattr(cfg, "entry_mode", None) == "fill_confirmed":
        return cfg
    return replace(cfg, entry_mode="fill_confirmed")


def _arm_entry_after_fill(
    pipeline: FalconDecisionPipeline,
    *,
    side_lots: int,
    fill_price: float,
    signal_atr: float,
    signal: int,
    domestic_mark: float | None,
    overseas_close: float | None,
    sl_atr_mult: float = 1.3,
    tp_atr_mult: float = 2.3,
) -> dict[str, float]:
    """Lock SL/TP after confirmed fill.

    When signals are priced overseas, map the domestic fill into signal space so
    ``risk.check`` (overseas high/low) stays dimensionally consistent.

    Returns domestic display levels for the cockpit (same units as fill_price).
    """
    from ignitequant.portfolio.stop_scale import map_fill_to_signal_price

    entry_px = map_fill_to_signal_price(
        float(fill_price),
        domestic_mark=domestic_mark,
        overseas_close=overseas_close,
    )
    entry_atr = float(signal_atr)
    ratio = (float(entry_px) / float(fill_price)) if fill_price else 1.0
    pipeline.risk.on_entry(int(side_lots), entry_px, entry_atr, int(signal))

    domestic_atr = float(signal_atr) / ratio if ratio > 0 else float(signal_atr)
    fill = float(fill_price)
    if side_lots > 0:
        d_stop = fill - float(sl_atr_mult) * domestic_atr
        d_take = fill + float(tp_atr_mult) * domestic_atr
    else:
        d_stop = fill + float(sl_atr_mult) * domestic_atr
        d_take = fill - float(tp_atr_mult) * domestic_atr
    return {
        "display_entry_price": fill,
        "display_stop_price": d_stop,
        "display_take_price": d_take,
    }


def _domestic_mark(quote_px: float, *fallbacks: float) -> float | None:
    """Cockpit / fill mark must be domestic price — never overseas decision close."""
    if quote_px > 0:
        return float(quote_px)
    for raw in fallbacks:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _persist_state(
    session: PersistenceSession | None,
    pipeline: FalconDecisionPipeline,
    *,
    symbol: str,
    net: int,
    pending: int | None,
    last_bar_id: str,
    config_hash: str,
    last_price: float | None = None,
    signal_close: float | None = None,
    display_levels: dict[str, float] | None = None,
) -> None:
    if session is None:
        return
    rs = pipeline.risk.state
    extra: dict = {}
    if last_price is not None and float(last_price) > 0:
        extra["last_price"] = float(last_price)
        extra["quote_as_of"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if signal_close is not None and float(signal_close) > 0:
        # Overseas (or other) decision bar close — never use as cockpit tip paint.
        extra["signal_close"] = float(signal_close)
    if display_levels:
        for key in (
            "display_entry_price",
            "display_stop_price",
            "display_take_price",
        ):
            if key in display_levels and display_levels[key] is not None:
                extra[key] = float(display_levels[key])
    else:
        # Heartbeat / later persists must not wipe cockpit domestic stop levels.
        try:
            prev = session.repo.load_strategy_state(session.instance_id)
            prev_payload = dict(prev.payload or {}) if prev is not None else {}
            for key in (
                "display_entry_price",
                "display_stop_price",
                "display_take_price",
            ):
                if key in prev_payload and prev_payload[key] is not None:
                    extra[key] = float(prev_payload[key])
        except Exception:
            pass
    session.save_state(
        symbol=symbol,
        current_target=pipeline.current_target,
        confirmed_net=net,
        cooldown_left=int(rs.cooldown_left),
        entry_price=rs.entry_price,
        stop_price=rs.stop_price,
        take_price=rs.take_price,
        entry_signal=rs.entry_signal,
        pending_desired=pending,
        last_bar_id=last_bar_id,
        config_hash=config_hash,
        extra=extra or None,
    )


def _legs_net(position) -> int:
    """Net from long/short legs (more reliable than ``pos`` on some TqKq sync gaps)."""
    long_today = int(getattr(position, "pos_long_today", 0) or 0)
    long_his = int(getattr(position, "pos_long_his", 0) or 0)
    short_today = int(getattr(position, "pos_short_today", 0) or 0)
    short_his = int(getattr(position, "pos_short_his", 0) or 0)
    if long_today == 0 and long_his == 0:
        long_today = int(getattr(position, "volume_long_today", 0) or 0)
        long_his = int(getattr(position, "volume_long_his", 0) or 0)
    if short_today == 0 and short_his == 0:
        short_today = int(getattr(position, "volume_short_today", 0) or 0)
        short_his = int(getattr(position, "volume_short_his", 0) or 0)
    long_total = int(getattr(position, "pos_long", 0) or 0) or (long_today + long_his)
    short_total = int(getattr(position, "pos_short", 0) or 0) or (short_today + short_his)
    return int(long_total) - int(short_total)


def _broker_net(position) -> int:
    """Broker confirmed net lots for this contract."""
    try:
        pos = int(getattr(position, "pos", 0) or 0)
    except (TypeError, ValueError):
        pos = 0
    legs = _legs_net(position)
    if pos != legs:
        print(
            f"[仓位] pos={pos} 与多空腿净仓={legs} 不一致，采用腿净仓",
            flush=True,
        )
        return legs
    return pos


def _broker_avg_entry_price(position, net: int) -> float | None:
    """Average open price for the broker net side (domestic units)."""
    if net == 0 or position is None:
        return None
    raw = (
        getattr(position, "open_price_long", None)
        if net > 0
        else getattr(position, "open_price_short", None)
    )
    try:
        price = float(raw)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


# Occupied margin while net still reads flat → re-fetch. AU 1 lot is often ~40–50k;
# the previous 50_000 floor skipped real shorts (e.g. margin≈44596).
MARGIN_FLAT_REFRESH_HINT = 3_000.0


def refresh_broker_position(
    api: TqApi,
    trade_symbol: str,
    position,
    account,
    *,
    pending_desired: int | None = None,
):
    """Re-fetch position when margin/pending says we hold but ``pos`` still reads flat."""
    net = _broker_net(position)
    try:
        margin = float(getattr(account, "margin", 0) or 0)
    except (TypeError, ValueError):
        margin = 0.0
    pending_open = False
    if pending_desired is not None:
        try:
            pending_open = int(pending_desired) != 0
        except (TypeError, ValueError):
            pending_open = False
    should_refresh = net == 0 and (
        margin >= MARGIN_FLAT_REFRESH_HINT or pending_open
    )
    if not should_refresh:
        return position, net
    try:
        position = api.get_position(trade_symbol)
    except Exception as exc:  # noqa: BLE001
        print(f"[仓位] 重取失败: {exc}", flush=True)
        return position, net
    net2 = _broker_net(position)
    if net2 != 0:
        print(
            f"[仓位] 保证金={margin:.0f} pending={pending_desired} "
            f"但原净仓=0，重取后 net={net2}",
            flush=True,
        )
    return position, net2


def _fallback_signal_atr(
    *,
    fill_price: float,
    preferred: float | None = None,
    domestic_mark: float | None = None,
    overseas_close: float | None = None,
) -> float:
    """ATR for orphan re-arm when no recent signal ATR is available."""
    if preferred is not None and preferred > 0:
        return float(preferred)
    domestic_atr = max(0.8, float(fill_price) * 0.0012)
    if (
        overseas_close is not None
        and overseas_close > 0
        and domestic_mark is not None
        and domestic_mark > 0
        and abs(float(overseas_close) / float(domestic_mark) - 1.0) > 0.05
    ):
        return domestic_atr * (float(overseas_close) / float(domestic_mark))
    return domestic_atr


def _maybe_rearm_orphan_stops(
    pipeline: FalconDecisionPipeline,
    *,
    net: int,
    fill_price: float,
    signal_atr: float,
    signal: int,
    domestic_mark: float | None,
    overseas_close: float | None,
    sl_atr_mult: float = 1.3,
    tp_atr_mult: float = 2.3,
) -> dict[str, float] | None:
    """Arm SL/TP when broker already holds but runtime lost entry levels."""
    if net == 0 or pipeline.risk.state.stop_price is not None:
        return None
    if fill_price <= 0:
        return None
    atr = _fallback_signal_atr(
        fill_price=fill_price,
        preferred=signal_atr,
        domestic_mark=domestic_mark,
        overseas_close=overseas_close,
    )
    entry_signal = int(signal) if signal else (1 if net > 0 else -1)
    levels = _arm_entry_after_fill(
        pipeline,
        side_lots=net,
        fill_price=float(fill_price),
        signal_atr=atr,
        signal=entry_signal,
        domestic_mark=domestic_mark,
        overseas_close=overseas_close,
        sl_atr_mult=sl_atr_mult,
        tp_atr_mult=tp_atr_mult,
    )
    print(
        f"  孤儿仓补锁 entry={pipeline.risk.state.entry_price:.2f} "
        f"sl={pipeline.risk.state.stop_price:.2f} "
        f"tp={pipeline.risk.state.take_price:.2f} "
        f"(display_sl={levels['display_stop_price']:.2f} net={net})",
        flush=True,
    )
    return levels


def _tq_position_snapshot(
    symbol: str,
    position,
    *,
    last_price: float | None = None,
) -> PositionSnapshot:
    """Build PositionSnapshot from a tqsdk Position object."""
    from ignitequant.market.margin_rates import estimate_margin_for_symbol

    net = _broker_net(position)
    long_today = int(getattr(position, "pos_long_today", 0) or 0)
    long_his = int(getattr(position, "pos_long_his", 0) or 0)
    short_today = int(getattr(position, "pos_short_today", 0) or 0)
    short_his = int(getattr(position, "pos_short_his", 0) or 0)
    # Fallback volume_* names used by some SDK builds
    if long_today == 0 and long_his == 0:
        long_today = int(getattr(position, "volume_long_today", 0) or 0)
        long_his = int(getattr(position, "volume_long_his", 0) or 0)
    if short_today == 0 and short_his == 0:
        short_today = int(getattr(position, "volume_short_today", 0) or 0)
        short_his = int(getattr(position, "volume_short_his", 0) or 0)

    avg: float | None = None
    if net > 0:
        raw = getattr(position, "open_price_long", None)
        try:
            avg = float(raw) if raw not in (None, 0, 0.0) else None
        except (TypeError, ValueError):
            avg = None
    elif net < 0:
        raw = getattr(position, "open_price_short", None)
        try:
            avg = float(raw) if raw not in (None, 0, 0.0) else None
        except (TypeError, ValueError):
            avg = None

    try:
        upnl = float(getattr(position, "float_profit", 0) or 0)
        if upnl != upnl:  # NaN from tqsdk → SQLite NULL
            upnl = 0.0
    except (TypeError, ValueError):
        upnl = 0.0
    try:
        margin = float(getattr(position, "margin", 0) or 0)
        if margin != margin:
            margin = 0.0
    except (TypeError, ValueError):
        margin = 0.0

    px = last_price
    if px is None or px <= 0:
        px = avg
    if px is not None and float(px) > 0 and net != 0:
        est, _rate, _mult = estimate_margin_for_symbol(
            symbol, price=float(px), lots=net
        )
        if est is not None:
            margin = float(est)

    return PositionSnapshot(
        symbol=symbol,
        net_position=net,
        long_today=long_today,
        long_yesterday=long_his,
        short_today=short_today,
        short_yesterday=short_his,
        average_entry_price=avg,
        unrealized_pnl=upnl,
        margin=margin,
    )


def _tq_account_snapshot(
    account,
    *,
    symbol: str = "",
    net_position: int = 0,
    last_price: float | None = None,
) -> AccountSnapshot:
    from ignitequant.market.margin_rates import apply_ref_margin_to_account

    try:
        upnl = float(getattr(account, "float_profit", 0) or 0)
    except (TypeError, ValueError):
        upnl = 0.0
    try:
        rpnl = float(getattr(account, "close_profit", 0) or 0)
    except (TypeError, ValueError):
        rpnl = 0.0
    equity = float(account.balance)
    margin = float(account.margin)
    margin_ratio = float(getattr(account, "risk_ratio", 0) or 0)
    # Prefer ref_product_margin % × price × multiplier over TqSim risk_ratio.
    if symbol:
        ref = apply_ref_margin_to_account(
            equity=equity,
            symbol=symbol,
            net_position=int(net_position),
            last_price=last_price,
        )
        if ref.get("margin") is not None and ref.get("margin_ratio") is not None:
            margin = float(ref["margin"])
            margin_ratio = float(ref["margin_ratio"])
    return AccountSnapshot(
        account_id="tq_kq",
        equity=equity,
        available=float(account.available),
        margin=margin,
        margin_ratio=margin_ratio,
        realized_pnl_today=rpnl,
        unrealized_pnl=upnl,
    )


def _capture_live_klines(
    klines,
    *,
    trade_symbol: str,
    last_price: float | None = None,
    persist: PersistenceSession | None = None,
) -> None:
    """Dump Tq sim kline window for Sim Cockpit (JSON cache + SQLite market_bar)."""
    try:
        from ignitequant.market.sim_klines import dump_tq_klines_snapshot, load_klines_snapshot

        path = dump_tq_klines_snapshot(
            INSTANCE_ID,
            klines,
            signal_symbol=SIGNAL_SYMBOL,
            trade_symbol=trade_symbol,
            duration_seconds=KLINE_SECONDS,
            runtime_dir=PERSIST_DB.parent,
            last_price=last_price,
            include_forming=True,
        )
        if persist is not None and path is not None:
            snap = load_klines_snapshot(
                INSTANCE_ID, runtime_dir=PERSIST_DB.parent, limit=400
            )
            if snap and snap.get("bars"):
                persist.persist_market_bars(
                    list(snap["bars"]),
                    symbol=str(snap.get("signal_symbol") or SIGNAL_SYMBOL),
                    duration_sec=int(snap.get("duration_seconds") or KLINE_SECONDS),
                    source="tqsdk_sim_live",
                )
    except Exception as exc:  # noqa: BLE001 — must not stop trading
        print(f"[K线快照] 写入失败（忽略）: {exc}", flush=True)


def _try_confirm_fill(
    *,
    executor: TargetPositionExecutor | None,
    position,
    persist: PersistenceSession | None,
    last_price: float,
    atr: float,
    signal: int,
    pipeline: FalconDecisionPipeline | None = None,
    trade_symbol: str = "",
    config_hash: str = "",
    last_bar_id: str = "",
    domestic_mark: float | None = None,
    overseas_close: float | None = None,
    signal_atr: float | None = None,
    sl_atr_mult: float = 1.3,
    tp_atr_mult: float = 2.3,
) -> FillEvent | None:
    """Confirm pending TargetPosTask fill once broker net matches intent.

    On success: arm SL/TP (opens), clear entry (flats), and immediately write
    ``confirmed_net`` / ``pending_desired`` so cockpit Metrics match 当前持仓.
    """
    if executor is None or position is None:
        return None
    if executor.active_intent is None:
        return None
    try:
        net = _broker_net(position)
    except Exception:
        return None
    # Lock SL/TP / fill ledger on broker average open — not confirm-time last.
    avg_open = _broker_avg_entry_price(position, net)
    confirmed_px = float(avg_open) if avg_open is not None else float(last_price)
    fill = executor.poll_position(
        net,
        last_price=last_price,
        atr=atr,
        signal=signal,
        fill_price=confirmed_px,
    )
    if fill is None:
        return None
    if persist is not None:
        persist.record_fill(fill)
        try:
            persist.snapshot_position(
                _tq_position_snapshot(str(fill.symbol), position, last_price=last_price),
                source="broker_fill",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[持仓快照] 成交后写入失败（忽略）: {exc}", flush=True)
    avg_note = (
        f" avg={avg_open:.2f}"
        if avg_open is not None and abs(float(avg_open) - float(last_price)) > 1e-6
        else ""
    )
    print(
        f"  成交确认 {fill.side} {fill.qty}@{fill.price:.2f} "
        f"intent={fill.intent_id} net={net} last={float(last_price):.2f}{avg_note}",
        flush=True,
    )

    display_levels: dict[str, float] | None = None
    if pipeline is not None:
        desired = int(pipeline.current_target)
        mark = domestic_mark if domestic_mark is not None else float(last_price)
        atr_for_arm = float(signal_atr) if signal_atr is not None else float(atr)
        if net != 0 and pipeline.risk.state.stop_price is None:
            display_levels = _arm_entry_after_fill(
                pipeline,
                side_lots=net,
                fill_price=float(fill.price),
                signal_atr=atr_for_arm,
                signal=signal,
                domestic_mark=mark,
                overseas_close=overseas_close,
                sl_atr_mult=sl_atr_mult,
                tp_atr_mult=tp_atr_mult,
            )
            print(
                f"  风控锁定 entry={pipeline.risk.state.entry_price:.2f} "
                f"sl={pipeline.risk.state.stop_price:.2f} "
                f"tp={pipeline.risk.state.take_price:.2f} "
                f"(display_sl={display_levels['display_stop_price']:.2f})",
                flush=True,
            )
        elif net == 0 and (
            pipeline.risk.state.entry_price is not None
            or pipeline.risk.state.stop_price is not None
        ):
            pipeline.risk.on_flat()
            print("  风控清仓状态已复位（净仓=0）", flush=True)

        if trade_symbol:
            pending = None if net == desired else desired
            _persist_state(
                persist,
                pipeline,
                symbol=trade_symbol,
                net=net,
                pending=pending,
                last_bar_id=last_bar_id or "fill",
                config_hash=config_hash,
                last_price=float(last_price) if last_price else None,
                signal_close=overseas_close,
                display_levels=display_levels,
            )
    return fill


def _wait_fill_briefly(
    api: TqApi,
    *,
    executor: TargetPositionExecutor,
    position,
    persist: PersistenceSession | None,
    last_price: float,
    atr: float,
    signal: int,
    rounds: int = 8,
    timeout_s: float = 1.5,
    pipeline: FalconDecisionPipeline | None = None,
    trade_symbol: str = "",
    config_hash: str = "",
    last_bar_id: str = "",
    domestic_mark: float | None = None,
    overseas_close: float | None = None,
    signal_atr: float | None = None,
    sl_atr_mult: float = 1.3,
    tp_atr_mult: float = 2.3,
) -> FillEvent | None:
    """Poll a few quote updates after submit — TqKq rarely fills synchronously."""
    kwargs = dict(
        executor=executor,
        position=position,
        persist=persist,
        last_price=last_price,
        atr=atr,
        signal=signal,
        pipeline=pipeline,
        trade_symbol=trade_symbol,
        config_hash=config_hash,
        last_bar_id=last_bar_id,
        domestic_mark=domestic_mark,
        overseas_close=overseas_close,
        signal_atr=signal_atr,
        sl_atr_mult=sl_atr_mult,
        tp_atr_mult=tp_atr_mult,
    )
    fill = _try_confirm_fill(**kwargs)
    if fill is not None:
        return fill
    for _ in range(max(rounds, 0)):
        try:
            api.wait_update(deadline=time.time() + timeout_s)
        except Exception:
            break
        try:
            px = float(last_price)
        except (TypeError, ValueError):
            px = last_price
        kwargs["last_price"] = px
        fill = _try_confirm_fill(**kwargs)
        if fill is not None:
            return fill
    return None


def main() -> None:
    load_dotenv(ROOT / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise SystemExit("缺少 TQ_USER / TQ_PASS，请先配置项目根目录 .env")

    cfg = _with_fill_confirmed_entry(load_active_decision_config())
    risk_engine = make_risk_engine(cfg)
    persist: PersistenceSession | None = None
    if ENABLE_PERSISTENCE:
        persist = PersistenceSession.open(
            PERSIST_DB,
            instance_id=INSTANCE_ID,
            strategy_id=STRATEGY_ID,
        )
    _write_pid_file()

    print(f"启动 {STRATEGY_LABEL} 快期模拟盘: 信号={SIGNAL_SYMBOL}", flush=True)
    instrument = resolve_instrument(SIGNAL_SYMBOL)
    signal_source = resolve_signal_source(instrument)
    overseas_mode = signal_source.pricing_basis == "overseas"
    print(
        f"账户=TqKq | K线={KLINE_SECONDS // 60}分钟 | 仓位映射={LOT_BY_SIGNAL} | "
        f"pricing={signal_source.pricing_basis} "
        f"decision={signal_source.decision_symbol} exec={SIGNAL_SYMBOL} | "
        f"config={cfg.config_version} entry={cfg.entry_mode} | RiskEngine+Executor | "
        f"persist={'ON ' + str(PERSIST_DB) if persist else 'OFF'} | "
        f"Web UI: http://127.0.0.1{WEB_GUI}",
        flush=True,
    )

    api = TqApi(
        TqKq(),
        web_gui=WEB_GUI,
        auth=TqAuth(user, password),
    )

    pipeline = FalconDecisionPipeline(cfg)
    trade_symbol = ""
    last_saved_bar_id = ""
    last_seen_kline_ns = 0
    last_fill_atr = 1.0
    last_fill_signal = 0
    last_signal_atr = 1.0
    last_overseas_close: float | None = None
    orphan_rearmed_on_boot = False
    executor: TargetPositionExecutor | None = None
    position = None
    account = api.get_account()
    bars_since_recon = 0

    try:
        main_quote = api.get_quote(SIGNAL_SYMBOL)
        klines = api.get_kline_serial(SIGNAL_SYMBOL, KLINE_SECONDS, data_length=DATA_LENGTH)
        decision_klines = klines
        last_progress_day = None
        last_heartbeat = 0.0
        last_kline_dump = 0.0
        last_overseas_poll = 0.0
        last_seen_overseas_ts = 0
        try:
            last_seen_kline_ns = int(klines.iloc[-1]["datetime"])
        except Exception:
            last_seen_kline_ns = 0

        api.wait_update(deadline=time.time() + 30)
        print(
            f"登录成功 | 权益={account.balance:.2f} 可用={account.available:.2f} "
            f"保证金={account.margin:.2f} 风险度={getattr(account, 'risk_ratio', 0):.2%}",
            flush=True,
        )
        underlying0 = str(getattr(main_quote, "underlying_symbol", "") or "")
        print(
            f"行情就绪 | last={main_quote.last_price} underlying={underlying0 or '-'}",
            flush=True,
        )
        if underlying0:
            trade_symbol = underlying0
            executor = TargetPositionExecutor(api, trade_symbol)
            position = api.get_position(trade_symbol)
            print(f"交易合约切换为 {trade_symbol}", flush=True)
            _capture_live_klines(
                klines,
                trade_symbol=trade_symbol,
                last_price=float(getattr(main_quote, "last_price", 0) or 0) or None,
                persist=persist,
            )

            payload: dict = {}
            pending_boot_i: int | None = None
            if persist is not None:
                recovery = persist.recover(
                    BrokerFacts(
                        symbol=trade_symbol,
                        net_position=_broker_net(position),
                        equity=float(account.balance),
                        available=float(account.available),
                        margin=float(account.margin),
                    )
                )
                payload = recovery.restore_payload
                pipeline.restore_runtime(
                    current_target=int(payload.get("current_target", _broker_net(position))),
                    cooldown_left=int(payload.get("cooldown_left", 0)),
                    entry_price=payload.get("entry_price"),
                    stop_price=payload.get("stop_price"),
                    take_price=payload.get("take_price"),
                    entry_signal=payload.get("entry_signal"),
                )
                # Stale flat pos with occupied margin / pending target → re-fetch.
                pending_boot = payload.get("pending_desired")
                try:
                    pending_boot_i = (
                        int(pending_boot) if pending_boot is not None else None
                    )
                except (TypeError, ValueError):
                    pending_boot_i = None
                position, _ = refresh_broker_position(
                    api,
                    trade_symbol,
                    position,
                    account,
                    pending_desired=pending_boot_i,
                )
                # Never keep armed SL/TP when broker is flat — avoids ghost STOP.
                if _broker_net(position) == 0 and (
                    pipeline.risk.state.stop_price is not None
                    or pipeline.risk.state.entry_price is not None
                ):
                    print("启动清除幽灵止损 | broker_net=0 但恢复了 entry/stop", flush=True)
                    pipeline.risk.on_flat()
                executor.restore_idempotency_keys(recovery.idempotency_keys)
                print(
                    f"启动对账 | state={recovery.runtime_state} matched={recovery.report.matched} "
                    f"| {recovery.message}",
                    flush=True,
                )
                persist.snapshot_position(
                    _tq_position_snapshot(
                        trade_symbol,
                        position,
                        last_price=float(getattr(main_quote, "last_price", 0) or 0) or None,
                    ),
                    source="broker_startup",
                )
                persist.snapshot_account(
                    _tq_account_snapshot(
                        account,
                        symbol=trade_symbol,
                        net_position=_broker_net(position),
                        last_price=float(getattr(main_quote, "last_price", 0) or 0) or None,
                    )
                )
                _cloud_sync_outbox(persist)
                try:
                    from ignitequant.persistence.repair import repair_missing_fills

                    repaired = repair_missing_fills(PERSIST_DB, INSTANCE_ID)
                    if repaired:
                        print(f"[补录成交] repaired={repaired}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"[补录成交] 跳过: {exc}", flush=True)
                # Retry flatten if a prior STOP/pending-0 left broker lots open.
                pending0 = payload.get("pending_desired")
                net_boot = _broker_net(position)
                pending_flat = False
                if pending0 is not None:
                    try:
                        pending_flat = int(pending0) == 0
                    except (TypeError, ValueError):
                        pending_flat = False
                want_flat = pipeline.current_target == 0 or pending_flat
                if net_boot != 0 and want_flat:
                    print(
                        f"启动补平 | broker_net={net_boot} target={pipeline.current_target} "
                        f"pending={pending0}",
                        flush=True,
                    )
                    pipeline.force_flat()
                    decision_flat = f"boot-flat:{trade_symbol}:{net_boot}"
                    boot_session = shfe_precious_session_open()
                    boot_trade_status = str(boot_session["trade_status"])
                    allow_boot, boot_hits = may_submit_domestic_order(
                        trade_status=boot_trade_status
                    )
                    # Thinking-chain must show 1→0 启动补平 (NOT the later HOLD 0→0).
                    persist.record_ops_decision(
                        decision_id=decision_flat,
                        symbol=trade_symbol,
                        applied_action="BOOT_FLATTEN",
                        target_before=net_boot,
                        target_after=0,
                        legacy_signal=0,
                        payload={
                            "applied_action": "BOOT_FLATTEN",
                            "reason_codes": (
                                list(boot_hits)
                                if not allow_boot
                                else ["BOOT_FLATTEN_PENDING"]
                            ),
                            "note": (
                                "内盘休市：启动补平仅记决策，不登记委托/成交"
                                if not allow_boot
                                else "策略目标已为0但券商仍有仓，启动时对齐平仓（非止盈/止损）"
                            ),
                            "pending_desired": pending0,
                            "restored_target": 0,
                            "trade_status": boot_trade_status,
                            "session_label": boot_session.get("label"),
                        },
                    )
                    if not allow_boot:
                        persist.record_risk(
                            decision_flat,
                            market_closed_reject_decision(
                                decision_id=decision_flat,
                                net_position=net_boot,
                                requested_position=0,
                                config_version=cfg.config_version,
                            ),
                        )
                        print(
                            f"启动补平拒绝下单 | hits={boot_hits} "
                            f"session={boot_session.get('label')}",
                            flush=True,
                        )
                        _persist_state(
                            persist,
                            pipeline,
                            symbol=trade_symbol,
                            net=net_boot,
                            pending=0,
                            last_bar_id=decision_flat,
                            config_hash=cfg.config_hash(),
                            last_price=float(getattr(main_quote, "last_price", 0) or 0)
                            or None,
                        )
                    else:
                        intent_flat = executor.set_target(
                            0,
                            decision_id=decision_flat,
                            current_net=net_boot,
                            urgency="HIGH",
                            reason_codes=("BOOT_FLATTEN_PENDING",),
                            idempotency_key=f"boot-flat:{trade_symbol}:{net_boot}",
                        )
                        if intent_flat:
                            persist.record_intent(intent_flat)
                            boot_px = float(getattr(main_quote, "last_price", 0) or 0)
                            _wait_fill_briefly(
                                api,
                                executor=executor,
                                position=position,
                                persist=persist,
                                last_price=boot_px,
                                atr=0.0,
                                signal=0,
                                pipeline=pipeline,
                                trade_symbol=trade_symbol,
                                config_hash=cfg.config_hash(),
                                last_bar_id=decision_flat,
                                domestic_mark=boot_px if boot_px > 0 else None,
                                sl_atr_mult=float(cfg.risk.sl_atr_mult),
                                tp_atr_mult=float(cfg.risk.tp_atr_mult),
                            )
                        persist.snapshot_position(
                            _tq_position_snapshot(
                                trade_symbol,
                                position,
                                last_price=float(getattr(main_quote, "last_price", 0) or 0)
                                or None,
                            ),
                            source="broker_boot_flatten",
                        )

            # 启动补跑：把 last_bar_id 之后漏掉的已完成 5m K 写入决策链，并推进内存目标。
            if persist is not None and len(klines) >= 2:
                try:
                    from ignitequant.engine.catch_up import catch_up_missed_bars

                    completed = klines.iloc[:-1]
                    last_id = str(payload.get("last_bar_id") or "") if payload else ""
                    cu = catch_up_missed_bars(
                        session=persist,
                        pipeline=pipeline,
                        bars=completed,
                        last_bar_id=last_id or None,
                        confirmed_net=_broker_net(position),
                        source="tq_startup_klines",
                    )
                    if cu.missed:
                        print(
                            f"启动补跑K线 | {cu.message} source={cu.source}",
                            flush=True,
                        )
                        last_saved_bar_id = cu.last_bar_id_after or last_saved_bar_id
                        # 仅对最终目标做一次对齐下单（中间漏 K 只记决策）
                        want = int(pipeline.current_target)
                        net_cu = _broker_net(position)
                        if want != net_cu and executor is not None:
                            rt_cu = persist.runtime
                            increasing = abs(want) > abs(net_cu)
                            cu_session = shfe_precious_session_open()
                            cu_status = str(cu_session["trade_status"])
                            allow_cu, cu_hits = may_submit_domestic_order(
                                trade_status=cu_status
                            )
                            if not allow_cu:
                                print(
                                    f"启动补跑拒绝下单 | target={want} net={net_cu} "
                                    f"hits={cu_hits} session={cu_session.get('label')}",
                                    flush=True,
                                )
                            elif increasing and (
                                not rt_cu.reconciliation_matched
                                or rt_cu.kill_switch_active
                                or rt_cu.unknown_order_count > 0
                            ):
                                print(
                                    f"启动补跑跳过下单 | target={want} net={net_cu} "
                                    f"rt={rt_cu.runtime_state}",
                                    flush=True,
                                )
                            else:
                                intent_cu = executor.set_target(
                                    want,
                                    decision_id=f"catchup:{cu.final_bar_id or 'boot'}",
                                    current_net=net_cu,
                                    urgency="HIGH",
                                    reason_codes=("CATCH_UP_ALIGN",),
                                    idempotency_key=(
                                        f"catchup:{trade_symbol}:{want}:{net_cu}:"
                                        f"{cu.final_bar_id or ''}"
                                    ),
                                )
                                if intent_cu is not None:
                                    persist.record_intent(intent_cu)
                                    print(
                                        f"启动补跑对齐下单 | {net_cu}->{want}",
                                        flush=True,
                                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"启动补跑跳过: {exc}", flush=True)

            # Prefer overseas decision window on boot when pricing_basis=overseas.
            boot_klines = klines
            boot_overseas_close: float | None = None
            if overseas_mode:
                live_bars, live_src = fetch_for_signal_source(signal_source, limit=400)
                if live_bars:
                    if len(live_bars) > 1:
                        live_bars = drop_forming_5m_bar(live_bars, now=time.time())
                    boot_klines = bars_dicts_to_dataframe(
                        live_bars,
                        underlying_symbol=signal_source.overseas_signal_symbol or "",
                    )
                    decision_klines = boot_klines
                    last_seen_overseas_ts = int(live_bars[-1]["time"])
                    try:
                        boot_overseas_close = float(live_bars[-1]["close"])
                        last_overseas_close = boot_overseas_close
                    except (TypeError, ValueError, KeyError):
                        boot_overseas_close = None
                    print(
                        f"启动外盘窗口 | source={live_src} bars={len(live_bars)} "
                        f"symbol={signal_source.decision_symbol}",
                        flush=True,
                    )

            boot_net = _broker_net(position)
            need_orphan_rearm = (
                persist is not None
                and boot_net != 0
                and pipeline.risk.state.stop_price is None
            )
            if need_orphan_rearm:
                # Observe-only: get signal ATR without risk.check clearing a fresh arm.
                tip_obs = pipeline.on_bar_close(boot_klines, trade=False)
                tip_atr = float(atr_of(tip_obs) or last_signal_atr)
                tip_close = float(close_of(tip_obs) or 0)
                if overseas_mode and tip_close > 0:
                    boot_overseas_close = tip_close
                    last_overseas_close = tip_close
                last_signal_atr = tip_atr
                boot_px = float(getattr(main_quote, "last_price", 0) or 0)
                fill_px = _broker_avg_entry_price(position, boot_net) or boot_px
                boot_payload = payload if isinstance(payload, dict) else {}
                display_boot = _maybe_rearm_orphan_stops(
                    pipeline,
                    net=boot_net,
                    fill_price=float(fill_px or 0),
                    signal_atr=float(tip_atr),
                    signal=int(boot_payload.get("entry_signal") or 0),
                    domestic_mark=boot_px if boot_px > 0 else None,
                    overseas_close=boot_overseas_close if overseas_mode else None,
                    sl_atr_mult=float(cfg.risk.sl_atr_mult),
                    tp_atr_mult=float(cfg.risk.tp_atr_mult),
                )
                if display_boot is not None:
                    orphan_rearmed_on_boot = True
                    _persist_state(
                        persist,
                        pipeline,
                        symbol=trade_symbol,
                        net=boot_net,
                        pending=pending_boot_i,
                        last_bar_id=last_saved_bar_id,
                        config_hash=cfg.config_hash(),
                        last_price=boot_px if boot_px > 0 else None,
                        display_levels=display_boot,
                    )
                result0 = tip_obs
                annotate_klines(boot_klines, result0)
                if persist is not None:
                    persist.record_decision(result0)
                boot_session = shfe_precious_session_open()
                print(
                    f"启动评估(补锁后观察) | regime={result0.factors.regime.value} "
                    f"signal={result0.signal.legacy_signal} ({score_parts(result0)}) "
                    f"desired={result0.sizing_target} atr={atr_of(result0):.2f} "
                    f"close={close_of(result0):.2f} session={boot_session['label']} "
                    f"| 跳过立即止损/止盈，等下一根完成K",
                    flush=True,
                )
                if persist is not None:
                    _persist_state(
                        persist,
                        pipeline,
                        symbol=trade_symbol,
                        net=boot_net,
                        pending=pending_boot_i,
                        last_bar_id=result0.bar_id,
                        config_hash=cfg.config_hash(),
                        last_price=_domestic_mark(
                            float(getattr(main_quote, "last_price", 0) or 0)
                        ),
                    )
                    last_saved_bar_id = result0.bar_id
            else:
                result0 = pipeline.on_bar_close(boot_klines, trade=True)
                annotate_klines(boot_klines, result0)
                if persist is not None:
                    persist.record_decision(result0)
                boot_session = shfe_precious_session_open()
                print(
                    f"启动评估 | regime={result0.factors.regime.value} "
                    f"signal={result0.signal.legacy_signal} ({score_parts(result0)}) "
                    f"desired={result0.sizing_target} atr={atr_of(result0):.2f} "
                    f"close={close_of(result0):.2f} session={boot_session['label']}",
                    flush=True,
                )
                runtime0 = persist.runtime if persist is not None else healthy_runtime()
                # Boot path must execute flatten as well as opens. Previously only
                # TARGET(open) called set_target, so STOP_LOSS decisions were logged
                # without any order_intent — invisible in「委托与成交」.
                boot_actions = {"TARGET", "STOP_LOSS", "TAKE_PROFIT"}
                if result0.applied_action in boot_actions:
                    net0 = _broker_net(position)
                    pre0 = apply_pretrade(
                        result0,
                        net_position=net0,
                        last_price=float(getattr(main_quote, "last_price", 0) or 0)
                        or close_of(result0),
                        risk_engine=risk_engine,
                        runtime=runtime0,
                        symbol=trade_symbol,
                        trade_status=str(boot_session["trade_status"]),
                    )
                    if persist is not None:
                        persist.record_risk(result0.bar_id, pre0)
                    if pre0.action in {RiskAction.REJECT, RiskAction.HALT}:
                        print(
                            f"启动事前风控{pre0.action.value} | hits={pre0.rule_hits}",
                            flush=True,
                        )
                        _persist_state(
                            persist,
                            pipeline,
                            symbol=trade_symbol,
                            net=net0,
                            pending=(
                                0
                                if result0.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                                and net0 != 0
                                else None
                            ),
                            last_bar_id=result0.bar_id,
                            config_hash=cfg.config_hash(),
                            last_price=_domestic_mark(
                                float(getattr(main_quote, "last_price", 0) or 0)
                            ),
                        )
                        last_saved_bar_id = result0.bar_id
                    else:
                        desired0 = (
                            0
                            if result0.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                            else int(pre0.approved_position)
                        )
                        if desired0 != net0:
                            key0 = (
                                f"{result0.bar_id}:{desired0}:boot:"
                                f"{result0.applied_action}"
                            )
                            intent0 = executor.set_target(
                                desired0,
                                decision_id=result0.bar_id,
                                current_net=net0,
                                urgency=(
                                    "HIGH"
                                    if result0.applied_action != "TARGET"
                                    else "NORMAL"
                                ),
                                reason_codes=pre0.rule_hits,
                                idempotency_key=key0,
                                decision_price=_domestic_mark(
                                    float(getattr(main_quote, "last_price", 0) or 0)
                                ),
                            )
                            if intent0 is None:
                                print(
                                    f"启动意图被抑制 | action={result0.applied_action} "
                                    f"{net0}->{desired0} key={key0}",
                                    flush=True,
                                )
                            elif persist is not None:
                                persist.record_intent(intent0)
                                print(
                                    f"启动{result0.applied_action} 已登记意图 "
                                    f"{net0}->{desired0} | {trade_symbol}",
                                    flush=True,
                                )
                            last_fill_atr = atr_of(result0)
                            last_fill_signal = int(result0.signal.legacy_signal)
                            last_signal_atr = float(last_fill_atr)
                            if intent0 is not None:
                                _wait_fill_briefly(
                                    api,
                                    executor=executor,
                                    position=position,
                                    persist=persist,
                                    last_price=_domestic_mark(
                                        float(getattr(main_quote, "last_price", 0) or 0)
                                    ),
                                    atr=last_fill_atr,
                                    signal=last_fill_signal,
                                    pipeline=pipeline,
                                    trade_symbol=trade_symbol,
                                    config_hash=cfg.config_hash(),
                                    last_bar_id=result0.bar_id,
                                    domestic_mark=_domestic_mark(
                                        float(getattr(main_quote, "last_price", 0) or 0)
                                    ),
                                    signal_atr=last_signal_atr,
                                    sl_atr_mult=float(cfg.risk.sl_atr_mult),
                                    tp_atr_mult=float(cfg.risk.tp_atr_mult),
                                )
                            confirmed0 = _broker_net(position)
                            _persist_state(
                                persist,
                                pipeline,
                                symbol=trade_symbol,
                                net=confirmed0,
                                pending=None if confirmed0 == desired0 else desired0,
                                last_bar_id=result0.bar_id,
                                config_hash=cfg.config_hash(),
                                last_price=_domestic_mark(
                                    float(getattr(main_quote, "last_price", 0) or 0)
                                ),
                            )
                            last_saved_bar_id = result0.bar_id
                        else:
                            _persist_state(
                                persist,
                                pipeline,
                                symbol=trade_symbol,
                                net=net0,
                                pending=None,
                                last_bar_id=result0.bar_id,
                                config_hash=cfg.config_hash(),
                                last_price=_domestic_mark(
                                    float(getattr(main_quote, "last_price", 0) or 0)
                                ),
                            )
                            last_saved_bar_id = result0.bar_id

        consecutive_errors = 0
        while True:
            # Deadline keeps heartbeats / kline dumps alive during session breaks
            # when Tq may not push quote updates for a long time.
            try:
                api.wait_update(deadline=time.time() + 2.0)
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                consecutive_errors += 1
                print(
                    f"[行情等待异常] {exc} ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS})",
                    flush=True,
                )
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print("[行情等待异常] 连续失败过多，退出主循环", flush=True)
                    break
                time.sleep(min(30.0, 2.0 ** consecutive_errors))
                continue
            consecutive_errors = 0
            now = time.time()

            # Confirm async TargetPosTask fills between bars.
            try:
                q_px = float(main_quote.last_price)
            except (TypeError, ValueError):
                q_px = 0.0
            if trade_symbol and position is not None:
                pending_live = None
                if executor is not None and executor.active_intent is not None:
                    pending_live = int(executor.active_intent.desired_position)
                position, net_live = refresh_broker_position(
                    api,
                    trade_symbol,
                    position,
                    account,
                    pending_desired=pending_live,
                )
                if q_px > 0:
                    _try_confirm_fill(
                        executor=executor,
                        position=position,
                        persist=persist,
                        last_price=q_px,
                        atr=last_fill_atr,
                        signal=last_fill_signal,
                        pipeline=pipeline,
                        trade_symbol=trade_symbol,
                        config_hash=cfg.config_hash(),
                        last_bar_id=last_saved_bar_id,
                        domestic_mark=q_px,
                        overseas_close=last_overseas_close,
                        signal_atr=last_signal_atr,
                        sl_atr_mult=float(cfg.risk.sl_atr_mult),
                        tp_atr_mult=float(cfg.risk.tp_atr_mult),
                    )
                    net_live = _broker_net(position)
                if net_live != 0 and pipeline.risk.state.stop_price is None:
                    fill_px = _broker_avg_entry_price(position, net_live) or q_px
                    display_live = _maybe_rearm_orphan_stops(
                        pipeline,
                        net=net_live,
                        fill_price=float(fill_px or 0),
                        signal_atr=float(last_signal_atr),
                        signal=int(last_fill_signal or 0),
                        domestic_mark=q_px if q_px > 0 else None,
                        overseas_close=last_overseas_close,
                        sl_atr_mult=float(cfg.risk.sl_atr_mult),
                        tp_atr_mult=float(cfg.risk.tp_atr_mult),
                    )
                    if display_live is not None and persist is not None:
                        _persist_state(
                            persist,
                            pipeline,
                            symbol=trade_symbol,
                            net=net_live,
                            pending=pending_live,
                            last_bar_id=last_saved_bar_id,
                            config_hash=cfg.config_hash(),
                            last_price=q_px if q_px > 0 else None,
                            display_levels=display_live,
                        )

            try:
                cur_kline_ns = int(klines.iloc[-1]["datetime"])
            except Exception:
                cur_kline_ns = 0

            session = shfe_precious_session_open()
            trade_status = str(session["trade_status"])

            new_bar = False
            if overseas_mode:
                if now - last_overseas_poll >= OVERSEAS_POLL_SECONDS:
                    last_overseas_poll = now
                    live_bars, live_src = fetch_for_signal_source(signal_source, limit=400)
                    if live_bars:
                        # Decision clock uses completed 5m only (drop open bucket).
                        completed = drop_forming_5m_bar(live_bars, now=now)
                        if not completed:
                            completed = live_bars
                        last_ts = int(completed[-1]["time"])
                        decision_klines = bars_dicts_to_dataframe(
                            completed,
                            underlying_symbol=signal_source.overseas_signal_symbol or "",
                        )
                        if last_ts > last_seen_overseas_ts:
                            new_bar = True
                            last_seen_overseas_ts = last_ts
                            cur_kline_ns = last_ts * 1_000_000_000
                            tip_age = max(0.0, now - last_ts - OVERSEAS_BAR_SECONDS)
                            print(
                                f"[外盘K] source={live_src} bars={len(completed)} "
                                f"last={datetime.datetime.fromtimestamp(last_ts):%Y-%m-%d %H:%M} "
                                f"lag≈{tip_age:.0f}s session={session['label']}",
                                flush=True,
                            )
            else:
                # Require a *new* bar timestamp — deadline timeouts can leave stale
                # is_changing flags and would otherwise re-run the same close forever.
                new_bar = (
                    cur_kline_ns > 0
                    and cur_kline_ns != last_seen_kline_ns
                    and api.is_changing(klines.iloc[-1], "datetime")
                )

            if not new_bar:
                if now - last_heartbeat >= HEARTBEAT_SECONDS:
                    last_heartbeat = now
                    pending = None
                    if executor is not None and executor.active_intent is not None:
                        pending = int(executor.active_intent.desired_position)
                    position, net = refresh_broker_position(
                        api,
                        trade_symbol,
                        position,
                        account,
                        pending_desired=pending,
                    )
                    if (
                        q_px > 0
                        and executor is not None
                        and executor.active_intent is not None
                    ):
                        _try_confirm_fill(
                            executor=executor,
                            position=position,
                            persist=persist,
                            last_price=q_px,
                            atr=last_fill_atr,
                            signal=last_fill_signal,
                            pipeline=pipeline,
                            trade_symbol=trade_symbol,
                            config_hash=cfg.config_hash(),
                            last_bar_id=last_saved_bar_id,
                            domestic_mark=q_px,
                            overseas_close=last_overseas_close,
                            signal_atr=last_signal_atr,
                            sl_atr_mult=float(cfg.risk.sl_atr_mult),
                            tp_atr_mult=float(cfg.risk.tp_atr_mult),
                        )
                        net = _broker_net(position)
                        if executor.active_intent is None:
                            pending = None
                    if net != 0 and pipeline.risk.state.stop_price is None:
                        fill_px = _broker_avg_entry_price(position, net) or q_px
                        display_hb = _maybe_rearm_orphan_stops(
                            pipeline,
                            net=net,
                            fill_price=float(fill_px or 0),
                            signal_atr=float(last_signal_atr),
                            signal=int(last_fill_signal or 0),
                            domestic_mark=q_px if q_px > 0 else None,
                            overseas_close=last_overseas_close,
                            sl_atr_mult=float(cfg.risk.sl_atr_mult),
                            tp_atr_mult=float(cfg.risk.tp_atr_mult),
                        )
                        if display_hb is not None and persist is not None:
                            _persist_state(
                                persist,
                                pipeline,
                                symbol=trade_symbol,
                                net=net,
                                pending=pending,
                                last_bar_id=last_saved_bar_id,
                                config_hash=cfg.config_hash(),
                                last_price=q_px if q_px > 0 else None,
                                display_levels=display_hb,
                            )
                    print(
                        f"[心跳] {datetime.datetime.now():%H:%M:%S} "
                        f"{trade_symbol or '-'} target={pipeline.current_target} net={net} "
                        f"balance={account.balance:.2f} margin={float(getattr(account,'margin',0) or 0):.0f} "
                        f"last={main_quote.last_price} "
                        f"rt={(persist.runtime.runtime_state if persist else 'N/A')}"
                        f"{'' if pending is None else f' pending={pending}'}"
                        f"{'' if pipeline.risk.state.stop_price is None else f' sl={pipeline.risk.state.stop_price:.2f}'}",
                        flush=True,
                    )
                    # Retry aligning broker to strategy target between bars.
                    if (
                        executor is not None
                        and trade_symbol
                        and int(pipeline.current_target) != net
                        and (
                            executor.active_intent is None
                            or int(executor.active_intent.desired_position)
                            != int(pipeline.current_target)
                        )
                    ):
                        want = int(pipeline.current_target)
                        increasing = abs(want) > abs(net)
                        rt_hb = persist.runtime if persist is not None else healthy_runtime()
                        # 休市：开平仓都不走心跳旁路（与 MarketClosedRule / 座舱展示一致）。
                        allow_hb, hb_hits = may_submit_domestic_order(
                            trade_status=trade_status
                        )
                        if not allow_hb:
                            print(
                                f"[心跳] 跳过仓位补齐 target={want} net={net} "
                                f"(hits={hb_hits})",
                                flush=True,
                            )
                        elif increasing and (
                            not rt_hb.reconciliation_matched
                            or rt_hb.kill_switch_active
                            or rt_hb.unknown_order_count > 0
                        ):
                            print(
                                f"[心跳] 跳过加仓补齐 target={want} net={net} "
                                f"rt={rt_hb.runtime_state} matched={rt_hb.reconciliation_matched}",
                                flush=True,
                            )
                        else:
                            print(
                                f"[心跳] 仓位脱节补齐 target={want} net={net}",
                                flush=True,
                            )
                            intent_hb = executor.set_target(
                                want,
                                decision_id=f"hb-resync:{int(now)}",
                                current_net=net,
                                urgency="HIGH",
                                reason_codes=("TARGET_NET_RESYNC", "HEARTBEAT"),
                                idempotency_key=f"hb-resync:{trade_symbol}:{want}:{net}",
                                decision_price=q_px if q_px > 0 else None,
                            )
                            if intent_hb and persist is not None:
                                persist.record_intent(intent_hb)
                            pending = want
                    if persist is not None and trade_symbol:
                        _persist_state(
                            persist,
                            pipeline,
                            symbol=trade_symbol,
                            net=net,
                            pending=pending,
                            last_bar_id=last_saved_bar_id,
                            config_hash=cfg.config_hash(),
                            last_price=q_px if q_px > 0 else None,
                        )
                        # Keep cockpit equity / margin / net fresh outside bar closes.
                        persist.snapshot_position(
                            _tq_position_snapshot(
                                trade_symbol,
                                position,
                                last_price=q_px if q_px > 0 else None,
                            ),
                            source="broker_heartbeat",
                        )
                        persist.snapshot_account(
                            _tq_account_snapshot(
                                account,
                                symbol=trade_symbol,
                                net_position=net,
                                last_price=q_px if q_px > 0 else None,
                            )
                        )
                        persist.record_heartbeat(
                            last_price=q_px if q_px > 0 else None,
                            confirmed_net=net,
                            current_target=int(pipeline.current_target),
                            pending_desired=pending,
                            session_open=bool(session["open"]),
                            payload={
                                "trade_symbol": trade_symbol,
                                "pricing_basis": signal_source.pricing_basis,
                                "decision_symbol": signal_source.decision_symbol,
                                "trade_status": trade_status,
                                "session_label": session["label"],
                            },
                        )
                        _cloud_sync_outbox(persist)
                    if trade_symbol:
                        _capture_live_klines(
                            klines,
                            trade_symbol=trade_symbol,
                            last_price=q_px if q_px > 0 else None,
                            persist=persist,
                        )
                        last_kline_dump = now
                elif trade_symbol and q_px > 0 and now - last_kline_dump >= 5:
                    # Light quote tick for cockpit forming candle between heartbeats.
                    _capture_live_klines(
                        klines,
                        trade_symbol=trade_symbol,
                        last_price=q_px,
                        persist=persist,
                    )
                    last_kline_dump = now
                continue

            last_seen_kline_ns = cur_kline_ns
            last_heartbeat = now
            underlying = str(getattr(main_quote, "underlying_symbol", "") or "")
            if not underlying:
                continue

            _capture_live_klines(
                klines,
                trade_symbol=underlying,
                last_price=q_px if q_px > 0 else None,
                persist=persist,
            )
            last_kline_dump = now

            if underlying != trade_symbol:
                if executor is not None and (
                    pipeline.current_target != 0
                    or (position is not None and _broker_net(position) != 0)
                ):
                    print(
                        f"主力换月 {trade_symbol} -> {underlying}，先平旧仓",
                        flush=True,
                    )
                    net_old = _broker_net(position) if position is not None else 0
                    pipeline.force_flat()
                    allow_roll, roll_hits = may_submit_domestic_order(
                        trade_status=trade_status
                    )
                    if not allow_roll:
                        print(
                            f"换月平仓拒绝下单 | hits={roll_hits} "
                            f"session={session.get('label')}",
                            flush=True,
                        )
                        continue
                    intent = executor.set_target(
                        0,
                        decision_id=f"roll:{trade_symbol}",
                        current_net=net_old,
                        urgency="HIGH",
                        reason_codes=("ROLL_IN_PROGRESS",),
                    )
                    if intent and persist is not None:
                        persist.record_intent(intent)
                    _wait_fill_briefly(
                        api,
                        executor=executor,
                        position=position,
                        persist=persist,
                        last_price=q_px if q_px > 0 else float(getattr(main_quote, "last_price", 0) or 0),
                        atr=last_fill_atr,
                        signal=last_fill_signal,
                        rounds=12,
                        timeout_s=2.0,
                        pipeline=pipeline,
                        trade_symbol=trade_symbol,
                        config_hash=cfg.config_hash(),
                        last_bar_id=f"roll:{trade_symbol}",
                        domestic_mark=q_px if q_px > 0 else None,
                        overseas_close=last_overseas_close,
                        signal_atr=last_signal_atr,
                        sl_atr_mult=float(cfg.risk.sl_atr_mult),
                        tp_atr_mult=float(cfg.risk.tp_atr_mult),
                    )
                    if _broker_net(position) != 0:
                        continue
                    executor.destroy()
                trade_symbol = underlying
                executor = TargetPositionExecutor(api, trade_symbol)
                position = api.get_position(trade_symbol)
                print(f"交易合约切换为 {trade_symbol}", flush=True)

            assert executor is not None and position is not None

            result = pipeline.on_bar_close(decision_klines, trade=True)
            annotate_klines(decision_klines, result)
            if persist is not None:
                persist.record_decision(result)
                _cloud_sync_outbox(persist)
            dt = datetime.datetime.fromtimestamp(
                int(decision_klines.iloc[-1]["datetime"]) // 1_000_000_000
            )
            pending_bar = None
            if executor is not None and executor.active_intent is not None:
                pending_bar = int(executor.active_intent.desired_position)
            position, net_pos = refresh_broker_position(
                api,
                trade_symbol,
                position,
                account,
                pending_desired=pending_bar,
            )
            parts = score_parts(result)
            atr = atr_of(result)
            overseas_close = float(close_of(result)) if overseas_mode else None
            last_signal_atr = float(atr)
            last_overseas_close = overseas_close
            if overseas_mode and q_px > 0 and overseas_close and overseas_close > 0:
                # Scale overseas ATR onto domestic last for fill/stop locking.
                atr = scale_atr_to_entry(atr, overseas_close, q_px) or atr
            last_fill_atr = atr
            bars_since_recon += 1

            if last_progress_day != dt.date():
                last_progress_day = dt.date()
                print(
                    f"{dt.date()} 新交易日 | {trade_symbol} "
                    f"regime={result.factors.regime.value} "
                    f"signal={result.signal.legacy_signal} ({parts}) "
                    f"target={pipeline.current_target} net={net_pos} "
                    f"close={close_of(result):.2f} "
                    f"session={session['label']} decision={signal_source.decision_symbol}",
                    flush=True,
                )
            else:
                print(
                    f"{dt} K线收盘 | {trade_symbol} "
                    f"regime={result.factors.regime.value} "
                    f"signal={result.signal.legacy_signal} ({parts}) "
                    f"target={pipeline.current_target} net={net_pos} "
                    f"close={close_of(result):.2f} "
                    f"session={session['label']}",
                    flush=True,
                )

            if persist is not None and bars_since_recon >= RECON_EVERY_BARS:
                bars_since_recon = 0
                rt = persist.reconcile_now(
                    LocalProjection(
                        symbol=trade_symbol,
                        expected_net=net_pos,
                        current_target=pipeline.current_target,
                        pending_desired=(
                            executor.active_intent.desired_position
                            if executor.active_intent
                            else None
                        ),
                        cooldown_left=int(pipeline.risk.state.cooldown_left),
                        entry_price=pipeline.risk.state.entry_price,
                        runtime_state=persist.runtime.runtime_state,
                    ),
                    BrokerFacts(
                        symbol=trade_symbol,
                        net_position=net_pos,
                        equity=float(account.balance),
                        available=float(account.available),
                        margin=float(account.margin),
                    ),
                )
                if not rt.reconciliation_matched:
                    print(f"{dt} 周期对账不一致 → DEGRADED", flush=True)

            runtime = persist.runtime if persist is not None else healthy_runtime()
            # 换月后若仅因旧 DEGRADED 粘住，净仓已对齐则立即自愈（不必等整点周期对账）。
            if (
                persist is not None
                and trade_symbol
                and not runtime.reconciliation_matched
                and int(pipeline.current_target) == net_pos
                and runtime.unknown_order_count == 0
                and not runtime.kill_switch_active
            ):
                runtime = persist.reconcile_now(
                    LocalProjection(
                        symbol=trade_symbol,
                        expected_net=net_pos,
                        current_target=pipeline.current_target,
                        pending_desired=None,
                        cooldown_left=int(pipeline.risk.state.cooldown_left),
                        entry_price=pipeline.risk.state.entry_price,
                        runtime_state=persist.runtime.runtime_state,
                    ),
                    BrokerFacts(
                        symbol=trade_symbol,
                        net_position=net_pos,
                        equity=float(account.balance),
                        available=float(account.available),
                        margin=float(account.margin),
                    ),
                )
                if runtime.reconciliation_matched:
                    print(f"{dt} 对账自愈 → {runtime.runtime_state}", flush=True)

            # HOLD/COOLDOWN usually skip orders — but if strategy target ≠ broker net
            # (failed open, missed fill, etc.), keep retrying alignment each bar.
            hold_like = result.applied_action not in {
                "STOP_LOSS",
                "TAKE_PROFIT",
                "TARGET",
            }
            if hold_like and int(pipeline.current_target) == net_pos:
                _persist_state(
                    persist,
                    pipeline,
                    symbol=trade_symbol,
                    net=net_pos,
                    pending=None,
                    last_bar_id=result.bar_id,
                    config_hash=cfg.config_hash(),
                    last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                    signal_close=close_of(result),
                )
                last_saved_bar_id = result.bar_id
                continue
            # Already chasing the same desired volume — do NOT cancel/replace every bar
            # (that was leaving 成交通知 + net=0 permanently).
            if (
                hold_like
                and executor.active_intent is not None
                and int(executor.active_intent.desired_position)
                == int(pipeline.current_target)
                and int(pipeline.current_target) != net_pos
            ):
                if not domestic_session_allows_orders(trade_status):
                    print(
                        f"{dt} 等待成交暂停 | target={pipeline.current_target} net={net_pos} "
                        f"(内盘休市，不轮询成交)",
                        flush=True,
                    )
                    _persist_state(
                        persist,
                        pipeline,
                        symbol=trade_symbol,
                        net=net_pos,
                        pending=int(pipeline.current_target),
                        last_bar_id=result.bar_id,
                        config_hash=cfg.config_hash(),
                        last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                        signal_close=close_of(result),
                    )
                    last_saved_bar_id = result.bar_id
                    continue
                print(
                    f"{dt} 等待成交 | target={pipeline.current_target} net={net_pos} "
                    f"intent={executor.active_intent.intent_id}",
                    flush=True,
                )
                fill_wait = _wait_fill_briefly(
                    api,
                    executor=executor,
                    position=position,
                    persist=persist,
                    last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0))
                    or float(getattr(main_quote, "last_price", 0) or 0),
                    atr=atr,
                    signal=last_fill_signal,
                    rounds=12,
                    timeout_s=2.0,
                    pipeline=pipeline,
                    trade_symbol=trade_symbol,
                    config_hash=cfg.config_hash(),
                    last_bar_id=result.bar_id,
                    domestic_mark=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                    overseas_close=overseas_close,
                    signal_atr=float(atr_of(result)),
                    sl_atr_mult=float(cfg.risk.sl_atr_mult),
                    tp_atr_mult=float(cfg.risk.tp_atr_mult),
                )
                confirmed_w = _broker_net(position)
                # Arm+persist already done inside _try_confirm_fill when fill lands.
                if fill_wait is not None and confirmed_w != 0 and pipeline.risk.state.stop_price:
                    print(
                        f"  风控已锁定 entry={pipeline.risk.state.entry_price} "
                        f"sl={pipeline.risk.state.stop_price} tp={pipeline.risk.state.take_price}",
                        flush=True,
                    )
                _persist_state(
                    persist,
                    pipeline,
                    symbol=trade_symbol,
                    net=confirmed_w,
                    pending=(
                        None
                        if confirmed_w == int(pipeline.current_target)
                        else int(pipeline.current_target)
                    ),
                    last_bar_id=result.bar_id,
                    config_hash=cfg.config_hash(),
                    last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                    signal_close=close_of(result),
                )
                last_saved_bar_id = result.bar_id
                continue
            if hold_like:
                print(
                    f"{dt} 仓位脱节补齐 | target={pipeline.current_target} net={net_pos} "
                    f"action={result.applied_action}",
                    flush=True,
                )

            pretrade = apply_pretrade(
                result,
                net_position=net_pos,
                last_price=q_px if q_px > 0 else close_of(result),
                risk_engine=risk_engine,
                runtime=runtime,
                symbol=trade_symbol,
                trade_status=trade_status,
                override_desired=(
                    int(pipeline.current_target) if hold_like else None
                ),
            )
            if persist is not None:
                persist.record_risk(result.bar_id, pretrade)
            if pretrade.action in {RiskAction.REJECT, RiskAction.HALT}:
                print(
                    f"{dt} 事前风控{pretrade.action.value} | hits={pretrade.rule_hits}",
                    flush=True,
                )
                # TARGET 路径会先乐观改 current_target；被拒必须回滚，否则心跳会绕过风控成交。
                if result.applied_action == "TARGET":
                    before = int(result.target_before)
                    if before == 0:
                        pipeline.force_flat()
                    else:
                        pipeline.restore_runtime(
                            current_target=before,
                            cooldown_left=int(pipeline.risk.state.cooldown_left),
                            entry_price=pipeline.risk.state.entry_price,
                            stop_price=pipeline.risk.state.stop_price,
                            take_price=pipeline.risk.state.take_price,
                            entry_signal=pipeline.risk.state.entry_signal,
                        )
                    print(
                        f"{dt} 目标回滚 {result.target_after}->{before} "
                        f"(事前风控未批准下单)",
                        flush=True,
                    )
                _persist_state(
                    persist,
                    pipeline,
                    symbol=trade_symbol,
                    net=net_pos,
                    pending=(
                        0
                        if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                        and net_pos != 0
                        else (
                            int(pipeline.current_target)
                            if (
                                hold_like
                                or result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                            )
                            and int(pipeline.current_target) != net_pos
                            else None
                        )
                    ),
                    last_bar_id=result.bar_id,
                    config_hash=cfg.config_hash(),
                    last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                    signal_close=close_of(result),
                )
                last_saved_bar_id = result.bar_id
                continue

            desired = (
                0
                if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                else (
                    int(pipeline.current_target)
                    if hold_like
                    else int(pretrade.approved_position)
                )
            )
            allow_submit, submit_hits = may_submit_domestic_order(
                trade_status=trade_status,
                pretrade=pretrade,
            )
            if not allow_submit:
                print(
                    f"{dt} 拒绝下单 | hits={submit_hits} desired={desired} net={net_pos}",
                    flush=True,
                )
                if persist is not None and ReasonCode.MARKET_CLOSED.value in submit_hits:
                    persist.record_risk(
                        result.bar_id,
                        market_closed_reject_decision(
                            decision_id=result.bar_id,
                            net_position=net_pos,
                            requested_position=desired,
                            config_version=cfg.config_version,
                        ),
                    )
                _persist_state(
                    persist,
                    pipeline,
                    symbol=trade_symbol,
                    net=net_pos,
                    pending=desired if desired != net_pos else None,
                    last_bar_id=result.bar_id,
                    config_hash=cfg.config_hash(),
                    last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                    signal_close=close_of(result),
                )
                last_saved_bar_id = result.bar_id
                continue

            if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}:
                print(
                    f"{dt} 风控{result.applied_action} 清仓 | "
                    f"sl={pipeline.risk.state.stop_price} "
                    f"tp={pipeline.risk.state.take_price} atr={atr:.2f}",
                    flush=True,
                )
            elif result.applied_action == "TARGET":
                prev = result.target_before
                print(
                    f"{dt} 调仓 {prev}->{desired} | {trade_symbol} "
                    f"regime={result.factors.regime.value} "
                    f"signal={result.signal.legacy_signal} ({parts}) atr={atr:.2f}",
                    flush=True,
                )
            elif hold_like:
                print(
                    f"{dt} 仓位脱节补齐下单 | {net_pos}->{desired}",
                    flush=True,
                )

            key = (
                f"{result.bar_id}:{desired}:"
                f"{'RESYNC' if hold_like else result.applied_action}"
            )
            decision_px = _domestic_mark(
                q_px, float(getattr(main_quote, "last_price", 0) or 0)
            )
            intent = executor.set_target(
                desired,
                decision_id=result.bar_id,
                current_net=net_pos,
                urgency="HIGH" if result.applied_action != "TARGET" or hold_like else "NORMAL",
                reason_codes=(
                    (*pretrade.rule_hits, "TARGET_NET_RESYNC")
                    if hold_like
                    else pretrade.rule_hits
                ),
                idempotency_key=key,
                decision_price=decision_px,
            )
            if intent is None:
                print(f"{dt} 意图被抑制（换月/重复） key={key}", flush=True)
                # Still persist local target (e.g. STOP_LOSS→0) so restart won't
                # revive an old target while broker still holds the leftover lot.
                _persist_state(
                    persist,
                    pipeline,
                    symbol=trade_symbol,
                    net=net_pos,
                    pending=desired if desired != net_pos else None,
                    last_bar_id=result.bar_id,
                    config_hash=cfg.config_hash(),
                    last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                    signal_close=close_of(result),
                )
                last_saved_bar_id = result.bar_id
                continue
            if persist is not None and not persist.record_intent(intent):
                print(f"{dt} 持久化幂等命中，跳过重复意图 key={key}", flush=True)

            last_fill_atr = atr
            last_fill_signal = int(result.signal.legacy_signal)
            wait_rounds = 20 if result.applied_action == "TARGET" else 8
            fill = _wait_fill_briefly(
                api,
                executor=executor,
                position=position,
                persist=persist,
                last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)) or close_of(result),
                atr=atr,
                signal=last_fill_signal,
                rounds=wait_rounds,
                timeout_s=2.0,
                pipeline=pipeline,
                trade_symbol=trade_symbol,
                config_hash=cfg.config_hash(),
                last_bar_id=result.bar_id,
                domestic_mark=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                overseas_close=overseas_close,
                signal_atr=float(atr_of(result)),
                sl_atr_mult=float(cfg.risk.sl_atr_mult),
                tp_atr_mult=float(cfg.risk.tp_atr_mult),
            )
            confirmed = _broker_net(position)
            pending = None if fill or confirmed == desired else desired
            if fill and desired != 0 and pipeline.risk.state.stop_price is not None:
                print(
                    f"  风控已锁定 entry={pipeline.risk.state.entry_price:.2f} "
                    f"sl={pipeline.risk.state.stop_price:.2f} "
                    f"tp={pipeline.risk.state.take_price:.2f}",
                    flush=True,
                )
            elif (
                cfg.entry_mode == "fill_confirmed"
                and result.applied_action == "TARGET"
                and desired != 0
                and confirmed == 0
            ):
                print(
                    f"  未成交，不锁定止损 | target={desired} net={confirmed} "
                    f"(等待后续成交确认)",
                    flush=True,
                )
            display_orphan = None
            if confirmed != 0 and pipeline.risk.state.stop_price is None:
                mark = _domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0))
                fill_px = _broker_avg_entry_price(position, confirmed) or mark or 0.0
                display_orphan = _maybe_rearm_orphan_stops(
                    pipeline,
                    net=confirmed,
                    fill_price=float(fill_px),
                    signal_atr=float(atr_of(result)),
                    signal=int(result.signal.legacy_signal or last_fill_signal or 0),
                    domestic_mark=mark,
                    overseas_close=overseas_close,
                    sl_atr_mult=float(cfg.risk.sl_atr_mult),
                    tp_atr_mult=float(cfg.risk.tp_atr_mult),
                )
            if (
                result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                and confirmed != 0
            ):
                print(
                    f"{dt} 警告：{result.applied_action} 后账户仍持仓 net={confirmed}，"
                    "将在后续 K 线重试平仓",
                    flush=True,
                )
            _persist_state(
                persist,
                pipeline,
                symbol=trade_symbol,
                net=confirmed,
                pending=pending,
                last_bar_id=result.bar_id,
                config_hash=cfg.config_hash(),
                last_price=_domestic_mark(q_px, float(getattr(main_quote, "last_price", 0) or 0)),
                signal_close=close_of(result),
                display_levels=display_orphan,
            )
            last_saved_bar_id = result.bar_id

    except KeyboardInterrupt:
        print("收到退出信号。", flush=True)
        if FLAT_ON_EXIT and executor is not None and pipeline.current_target != 0:
            print(
                f"退出前平仓: {trade_symbol} target {pipeline.current_target} -> 0",
                flush=True,
            )
            net = _broker_net(position) if position is not None else 0
            pipeline.force_flat()
            intent = executor.set_target(
                0,
                decision_id="exit-flat",
                current_net=net,
                urgency="HIGH",
                reason_codes=("EXIT_FLAT",),
            )
            if intent and persist is not None:
                persist.record_intent(intent)
            try:
                api.wait_update(deadline=time.time() + 10)
            except Exception:
                pass
        if persist is not None and trade_symbol:
            net = _broker_net(position) if position is not None else 0
            _persist_state(
                persist,
                pipeline,
                symbol=trade_symbol,
                net=net,
                pending=None,
                last_bar_id="shutdown",
                config_hash=cfg.config_hash(),
            )
        print(
            f"退出模拟盘 | 合约={trade_symbol or '-'} "
            f"权益={account.balance:.2f} 可用={account.available:.2f}",
            flush=True,
        )
    finally:
        _cleanup_pid_file()
        if persist is not None:
            persist.close()
        api.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
