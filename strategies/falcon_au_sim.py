#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Falcon v2 快期模拟盘入口（TqKq）。

决策核：ignitequant.engine.FalconDecisionPipeline（与回测 / 看板共用）。
执行层：TargetPositionExecutor + RiskEngine（Phase 3）。
持久化：SQLite WAL + 启动对账（Phase 4，见 ENABLE_PERSISTENCE）。
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
INSTANCE_ID = "falcon_au_sim"
PERSIST_DB = ROOT / "data" / "runtime" / "falcon_au_sim.sqlite"
RECON_EVERY_BARS = 12  # ~1 hour on 5m bars


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


def _capture_live_klines(klines, *, trade_symbol: str) -> None:
    """Dump Tq sim kline window for Sim Cockpit (not market_cache)."""
    try:
        from ignitequant.market.sim_klines import dump_tq_klines_snapshot

        dump_tq_klines_snapshot(
            INSTANCE_ID,
            klines,
            signal_symbol=SIGNAL_SYMBOL,
            trade_symbol=trade_symbol,
            duration_seconds=KLINE_SECONDS,
            runtime_dir=PERSIST_DB.parent,
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
            _capture_live_klines(klines, trade_symbol=trade_symbol)

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
            if result0.applied_action == "TARGET" and result0.target_after != 0:
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
                if pre0.action not in {RiskAction.REJECT, RiskAction.HALT}:
                    desired0 = int(pre0.approved_position)
                    key0 = f"{result0.bar_id}:{desired0}:boot"
                    intent0 = executor.set_target(
                        desired0,
                        decision_id=result0.bar_id,
                        current_net=net0,
                        urgency="NORMAL",
                        reason_codes=pre0.rule_hits,
                        idempotency_key=key0,
                    )
                    if intent0 and persist is not None:
                        persist.record_intent(intent0)
                    last_fill_atr = atr_of(result0)
                    last_fill_signal = int(result0.signal.legacy_signal)
                    _wait_fill_briefly(
                        api,
                        executor=executor,
                        position=position,
                        persist=persist,
                        last_price=close_of(result0),
                        atr=last_fill_atr,
                        signal=last_fill_signal,
                    )
                    print(
                        f"启动调仓 0->{desired0} | {trade_symbol} "
                        f"sl={pipeline.risk.state.stop_price:.2f} "
                        f"tp={pipeline.risk.state.take_price:.2f}",
                        flush=True,
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

        while True:
            api.wait_update()
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

            if not api.is_changing(klines.iloc[-1], "datetime"):
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
                    if trade_symbol:
                        _capture_live_klines(klines, trade_symbol=trade_symbol)
                continue

            last_heartbeat = now
            underlying = str(getattr(main_quote, "underlying_symbol", "") or "")
            if not underlying:
                continue

            _capture_live_klines(klines, trade_symbol=underlying)

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

            if result.applied_action not in {"STOP_LOSS", "TAKE_PROFIT", "TARGET"}:
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
                continue

            desired = (
                0
                if result.applied_action in {"STOP_LOSS", "TAKE_PROFIT"}
                else int(pretrade.approved_position)
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

            key = f"{result.bar_id}:{desired}:{result.applied_action}"
            intent = executor.set_target(
                desired,
                decision_id=result.bar_id,
                current_net=net_pos,
                urgency="HIGH" if result.applied_action != "TARGET" else "NORMAL",
                reason_codes=pretrade.rule_hits,
                idempotency_key=key,
            )
            if intent is None:
                print(f"{dt} 意图被抑制（换月/重复） key={key}", flush=True)
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
        if persist is not None:
            persist.close()
        api.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
