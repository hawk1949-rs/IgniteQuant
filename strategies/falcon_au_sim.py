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
from ignitequant.domain.enums import RiskAction
from ignitequant.domain.models import AccountSnapshot, FillEvent, PositionSnapshot
from ignitequant.engine import (
    BrokerFacts,
    FalconDecisionPipeline,
    LocalProjection,
    annotate_klines,
    apply_pretrade,
    atr_of,
    close_of,
    healthy_runtime,
    make_risk_engine,
    score_parts,
)
from ignitequant.execution import TargetPositionExecutor
from ignitequant.persistence import PersistenceSession


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
) -> None:
    if session is None:
        return
    rs = pipeline.risk.state
    extra: dict = {}
    if last_price is not None and float(last_price) > 0:
        extra["last_price"] = float(last_price)
        extra["quote_as_of"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
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
) -> FillEvent | None:
    """Confirm pending TargetPosTask fill once broker net matches intent."""
    if executor is None or position is None:
        return None
    if executor.active_intent is None:
        return None
    try:
        net = int(position.pos)
    except Exception:
        return None
    fill = executor.poll_position(net, last_price=last_price, atr=atr, signal=signal)
    if fill is None:
        return None
    if persist is not None:
        persist.record_fill(fill)
        try:
            persist.snapshot_position(
                PositionSnapshot(symbol=str(fill.symbol), net_position=net),
                source="broker_fill",
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[持仓快照] 成交后写入失败（忽略）: {exc}", flush=True)
    print(
        f"  成交确认 {fill.side} {fill.qty}@{fill.price:.2f} "
        f"intent={fill.intent_id} net={net}",
        flush=True,
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
) -> FillEvent | None:
    """Poll a few quote updates after submit — TqKq rarely fills synchronously."""
    fill = _try_confirm_fill(
        executor=executor,
        position=position,
        persist=persist,
        last_price=last_price,
        atr=atr,
        signal=signal,
    )
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
        fill = _try_confirm_fill(
            executor=executor,
            position=position,
            persist=persist,
            last_price=px,
            atr=atr,
            signal=signal,
        )
        if fill is not None:
            return fill
    return None


def main() -> None:
    load_dotenv(ROOT / ".env")
    user = os.environ.get("TQ_USER", "").strip()
    password = os.environ.get("TQ_PASS", "").strip()
    if not user or not password:
        raise SystemExit("缺少 TQ_USER / TQ_PASS，请先配置项目根目录 .env")

    cfg = load_active_decision_config()
    risk_engine = make_risk_engine(cfg)
    persist: PersistenceSession | None = None
    if ENABLE_PERSISTENCE:
        persist = PersistenceSession.open(
            PERSIST_DB,
            instance_id=INSTANCE_ID,
            strategy_id="falcon_v2",
        )
    _write_pid_file()

    print(f"启动 Falcon v2 快期模拟盘: 信号={SIGNAL_SYMBOL}", flush=True)
    print(
        f"账户=TqKq | K线={KLINE_SECONDS // 60}分钟 | 仓位映射={LOT_BY_SIGNAL} | "
        f"config={cfg.config_version} | RiskEngine+Executor | "
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
    executor: TargetPositionExecutor | None = None
    position = None
    account = api.get_account()
    bars_since_recon = 0

    try:
        main_quote = api.get_quote(SIGNAL_SYMBOL)
        klines = api.get_kline_serial(SIGNAL_SYMBOL, KLINE_SECONDS, data_length=400)
        last_progress_day = None
        last_heartbeat = 0.0
        last_kline_dump = 0.0
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

            if persist is not None:
                recovery = persist.recover(
                    BrokerFacts(
                        symbol=trade_symbol,
                        net_position=int(position.pos),
                        equity=float(account.balance),
                        available=float(account.available),
                        margin=float(account.margin),
                    )
                )
                payload = recovery.restore_payload
                pipeline.restore_runtime(
                    current_target=int(payload.get("current_target", int(position.pos))),
                    cooldown_left=int(payload.get("cooldown_left", 0)),
                    entry_price=payload.get("entry_price"),
                    stop_price=payload.get("stop_price"),
                    take_price=payload.get("take_price"),
                    entry_signal=payload.get("entry_signal"),
                )
                executor.restore_idempotency_keys(recovery.idempotency_keys)
                print(
                    f"启动对账 | state={recovery.runtime_state} matched={recovery.report.matched} "
                    f"| {recovery.message}",
                    flush=True,
                )
                persist.snapshot_position(
                    PositionSnapshot(symbol=trade_symbol, net_position=int(position.pos)),
                    source="broker_startup",
                )
                persist.snapshot_account(
                    AccountSnapshot(
                        account_id="tq_kq",
                        equity=float(account.balance),
                        available=float(account.available),
                        margin=float(account.margin),
                        margin_ratio=float(getattr(account, "risk_ratio", 0) or 0),
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
                net_boot = int(position.pos)
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
                            "reason_codes": ["BOOT_FLATTEN_PENDING"],
                            "note": "策略目标已为0但券商仍有仓，启动时对齐平仓（非止盈/止损）",
                            "pending_desired": pending0,
                            "restored_target": 0,
                        },
                    )
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
                        )
                    persist.snapshot_position(
                        PositionSnapshot(
                            symbol=trade_symbol, net_position=int(position.pos)
                        ),
                        source="broker_boot_flatten",
                    )

            result0 = pipeline.on_bar_close(klines, trade=True)
            annotate_klines(klines, result0)
            if persist is not None:
                persist.record_decision(result0)
            print(
                f"启动评估 | regime={result0.factors.regime.value} "
                f"signal={result0.signal.legacy_signal} ({score_parts(result0)}) "
                f"desired={result0.sizing_target} atr={atr_of(result0):.2f} "
                f"close={close_of(result0):.2f}",
                flush=True,
            )
            runtime0 = persist.runtime if persist is not None else healthy_runtime()
            # Boot path must execute flatten as well as opens. Previously only
            # TARGET(open) called set_target, so STOP_LOSS decisions were logged
            # without any order_intent — invisible in「委托与成交」.
            boot_actions = {"TARGET", "STOP_LOSS", "TAKE_PROFIT"}
            if result0.applied_action in boot_actions:
                net0 = int(position.pos)
                pre0 = apply_pretrade(
                    result0,
                    net_position=net0,
                    last_price=close_of(result0),
                    risk_engine=risk_engine,
                    runtime=runtime0,
                    symbol=trade_symbol,
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
                        last_price=close_of(result0),
                    )
                    last_saved_bar_id = result0.bar_id
                else:
                    desired0 = (
                        0
                        if result0.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                        else int(pre0.approved_position)
                    )
                    if desired0 != net0:
                        key0 = f"{result0.bar_id}:{desired0}:boot:{result0.applied_action}"
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
                        if intent0 is not None:
                            _wait_fill_briefly(
                                api,
                                executor=executor,
                                position=position,
                                persist=persist,
                                last_price=close_of(result0),
                                atr=last_fill_atr,
                                signal=last_fill_signal,
                            )
                        confirmed0 = int(position.pos)
                        _persist_state(
                            persist,
                            pipeline,
                            symbol=trade_symbol,
                            net=confirmed0,
                            pending=None if confirmed0 == desired0 else desired0,
                            last_bar_id=result0.bar_id,
                            config_hash=cfg.config_hash(),
                            last_price=close_of(result0),
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
                            last_price=close_of(result0),
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
            if q_px > 0:
                _try_confirm_fill(
                    executor=executor,
                    position=position,
                    persist=persist,
                    last_price=q_px,
                    atr=last_fill_atr,
                    signal=last_fill_signal,
                )

            try:
                cur_kline_ns = int(klines.iloc[-1]["datetime"])
            except Exception:
                cur_kline_ns = 0
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
                    net = int(position.pos) if position is not None else 0
                    pending = None
                    if executor is not None and executor.active_intent is not None:
                        pending = int(executor.active_intent.desired_position)
                    print(
                        f"[心跳] {datetime.datetime.now():%H:%M:%S} "
                        f"{trade_symbol or '-'} target={pipeline.current_target} net={net} "
                        f"balance={account.balance:.2f} last={main_quote.last_price} "
                        f"rt={(persist.runtime.runtime_state if persist else 'N/A')}"
                        f"{'' if pending is None else f' pending={pending}'}",
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
                            PositionSnapshot(symbol=trade_symbol, net_position=net),
                            source="broker_heartbeat",
                        )
                        persist.snapshot_account(
                            AccountSnapshot(
                                account_id="tq_kq",
                                equity=float(account.balance),
                                available=float(account.available),
                                margin=float(account.margin),
                                margin_ratio=float(
                                    getattr(account, "risk_ratio", 0) or 0
                                ),
                            )
                        )
                        persist.record_heartbeat(
                            last_price=q_px if q_px > 0 else None,
                            confirmed_net=net,
                            current_target=int(pipeline.current_target),
                            pending_desired=pending,
                            session_open=True,
                            payload={"trade_symbol": trade_symbol},
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
                    or (position is not None and int(position.pos) != 0)
                ):
                    print(
                        f"主力换月 {trade_symbol} -> {underlying}，先平旧仓",
                        flush=True,
                    )
                    net_old = int(position.pos) if position is not None else 0
                    pipeline.force_flat()
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
                    )
                    if int(position.pos) != 0:
                        continue
                    executor.destroy()
                trade_symbol = underlying
                executor = TargetPositionExecutor(api, trade_symbol)
                position = api.get_position(trade_symbol)
                print(f"交易合约切换为 {trade_symbol}", flush=True)

            assert executor is not None and position is not None

            result = pipeline.on_bar_close(klines, trade=True)
            annotate_klines(klines, result)
            if persist is not None:
                persist.record_decision(result)
                _cloud_sync_outbox(persist)
            dt = datetime.datetime.fromtimestamp(
                int(klines.iloc[-1]["datetime"]) // 1_000_000_000
            )
            net_pos = int(position.pos)
            parts = score_parts(result)
            atr = atr_of(result)
            bars_since_recon += 1

            if last_progress_day != dt.date():
                last_progress_day = dt.date()
                print(
                    f"{dt.date()} 新交易日 | {trade_symbol} "
                    f"regime={result.factors.regime.value} "
                    f"signal={result.signal.legacy_signal} ({parts}) "
                    f"target={pipeline.current_target} net={net_pos} "
                    f"close={close_of(result):.2f}",
                    flush=True,
                )
            else:
                print(
                    f"{dt} K线收盘 | {trade_symbol} "
                    f"regime={result.factors.regime.value} "
                    f"signal={result.signal.legacy_signal} ({parts}) "
                    f"target={pipeline.current_target} net={net_pos} "
                    f"close={close_of(result):.2f}",
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
                    last_price=close_of(result),
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
                last_price=close_of(result),
                risk_engine=risk_engine,
                runtime=runtime,
                symbol=trade_symbol,
            )
            if persist is not None:
                persist.record_risk(result.bar_id, pretrade)
            if pretrade.action in {RiskAction.REJECT, RiskAction.HALT}:
                print(
                    f"{dt} 事前风控{pretrade.action.value} | hits={pretrade.rule_hits}",
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
                            if hold_like and int(pipeline.current_target) != net_pos
                            else None
                        )
                    ),
                    last_bar_id=result.bar_id,
                    config_hash=cfg.config_hash(),
                    last_price=close_of(result),
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

            key = (
                f"{result.bar_id}:{desired}:"
                f"{'RESYNC' if hold_like else result.applied_action}"
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
                    last_price=close_of(result),
                )
                last_saved_bar_id = result.bar_id
                continue
            if persist is not None and not persist.record_intent(intent):
                print(f"{dt} 持久化幂等命中，跳过重复意图 key={key}", flush=True)

            last_fill_atr = atr
            last_fill_signal = int(result.signal.legacy_signal)
            fill = _wait_fill_briefly(
                api,
                executor=executor,
                position=position,
                persist=persist,
                last_price=close_of(result),
                atr=atr,
                signal=last_fill_signal,
            )
            confirmed = int(position.pos)
            pending = None if fill or confirmed == desired else desired
            if fill and desired != 0 and executor.state.entry is not None:
                print(
                    f"  风控锁定 entry={fill.price:.2f} "
                    f"sl={pipeline.risk.state.stop_price:.2f} "
                    f"tp={pipeline.risk.state.take_price:.2f}",
                    flush=True,
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
                last_price=close_of(result),
            )
            last_saved_bar_id = result.bar_id

    except KeyboardInterrupt:
        print("收到退出信号。", flush=True)
        if FLAT_ON_EXIT and executor is not None and pipeline.current_target != 0:
            print(
                f"退出前平仓: {trade_symbol} target {pipeline.current_target} -> 0",
                flush=True,
            )
            net = int(position.pos) if position is not None else 0
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
            net = int(position.pos) if position is not None else 0
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
