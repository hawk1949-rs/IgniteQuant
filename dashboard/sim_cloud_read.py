"""Cloud (Supabase) read path for Sim Cockpit API."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import HTTPException

from dashboard.position_history import (
    closed_rounds_summary,
    iter_closed_rounds,
)
from ignitequant.persistence.cloud_sync import database_url as _database_url


STALE_AFTER = timedelta(minutes=8)
DEFAULT_INIT_BALANCE = 1_000_000.0
STATUS_LABELS = {
    "RUNNING": "运行中",
    "STALE": "数据滞后",
    "IDLE": "未运行",
}


def _ensure_dotenv(*, root=None) -> None:
    """Load project .env; override SIM_DATA_SOURCE/DATABASE_URL so reloads stick."""
    try:
        from pathlib import Path

        base = Path(root) if root is not None else Path(__file__).resolve().parents[1]
        path = base / ".env"
        if not path.is_file():
            return
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key in {"SIM_DATA_SOURCE", "DATABASE_URL", "SUPABASE_OWNER_ID"}:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)
    except Exception:
        pass


def data_source(*, root=None) -> str:
    _ensure_dotenv(root=root)
    raw = os.environ.get("SIM_DATA_SOURCE", "cloud").strip().lower()
    return "local" if raw == "local" else "cloud"


def is_cloud(*, root=None) -> bool:
    return data_source(root=root) == "cloud"


def require_pg_url(*, root=None) -> str:
    # Prefer loading .env through data_source path so SIM_DATA_SOURCE/DATABASE_URL stay in sync.
    _ensure_dotenv(root=root)
    url = _database_url(root=root)
    if not url:
        raise HTTPException(
            status_code=503,
            detail=(
                "SIM_DATA_SOURCE=cloud 需要 DATABASE_URL（Supabase Session pooler）。"
                "本机调试可设 SIM_DATA_SOURCE=local 读 data/runtime/*.sqlite。"
            ),
        )
    if "db." in url and ".supabase.co" in url and "pooler.supabase.com" not in url:
        # Soft warning via header-friendly detail only when connect fails; allow attempt.
        pass
    return url


def _connect(url: str):
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "云端读取需要 psycopg2（pip install psycopg2-binary）。"
                "本机调试可设 SIM_DATA_SOURCE=local。"
            ),
        ) from exc
    try:
        conn = psycopg2.connect(url, connect_timeout=10)
    except Exception as exc:  # noqa: BLE001 — surface as API 503
        raise HTTPException(
            status_code=503,
            detail=(
                f"无法连接 DATABASE_URL：{exc}。"
                "请使用 Supabase Session pooler（IPv4），或设 SIM_DATA_SOURCE=local。"
            ),
        ) from exc
    conn.autocommit = True
    return conn, RealDictCursor


def _loads(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, (bytes, memoryview)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _status_from_updated(updated_at: Any) -> str:
    dt = _parse_ts(updated_at)
    if dt is None:
        return "IDLE"
    now = datetime.now(timezone.utc)
    if now - dt <= STALE_AFTER:
        return "RUNNING"
    return "STALE"


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def list_sessions_cloud(
    *,
    root=None,
    process_status: Callable[[str], dict[str, Any]] | None = None,
    launchers: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    url = require_pg_url(root=root)
    conn, cur_factory = _connect(url)
    launchers = launchers or {}
    try:
        with conn.cursor(cursor_factory=cur_factory) as cur:
            cur.execute(
                """
                SELECT instance_key, strategy_id, symbol_id, status, runtime_state,
                       payload_json, updated_at, last_heartbeat_at, last_synced_at
                FROM sim_instance
                ORDER BY updated_at DESC NULLS LAST
                """
            )
            rows = cur.fetchall()
        sessions: list[dict[str, Any]] = []
        for row in rows:
            iid = str(row["instance_key"])
            payload = _loads(row["payload_json"])
            updated = row["updated_at"] or row["last_synced_at"] or row["last_heartbeat_at"]
            status = _status_from_updated(updated)
            # Cloud read: no local process → prefer STALE/IDLE over RUNNING for display
            proc = process_status(iid) if process_status else {
                "process_running": False,
                "pid": None,
                "can_start": iid in launchers,
                "label": launchers.get(iid, {}).get("label") or iid,
            }
            if not proc.get("process_running") and status == "RUNNING":
                # Heartbeat may still be fresh while viewing from another machine
                pass
            sessions.append(
                {
                    "instance_id": iid,
                    "strategy_id": row["strategy_id"] or "falcon_v2",
                    "account_id": (payload.get("account") or {}).get("account_id")
                    or payload.get("account_id")
                    or "cloud",
                    "symbol": payload.get("symbol")
                    or (payload.get("position") or {}).get("symbol")
                    or row["symbol_id"],
                    "runtime_state": row["runtime_state"] or payload.get("runtime_state") or "READY",
                    "status": status,
                    "status_label": _status_label(status),
                    "updated_at": _iso(updated),
                    "payload": payload,
                    "framework": "tq",
                    "label": launchers.get(iid, {}).get("label") or iid,
                    "data_source": "cloud",
                    "read_only": True,
                    **proc,
                }
            )
        return {
            "sessions": sessions,
            "count": len(sessions),
            "data_source": "cloud",
            "read_only_hint": "当前为云端只读座舱：数据来自 Supabase 投影；启动请在交易机运行。",
        }
    finally:
        conn.close()


def session_summary_cloud(
    instance_id: str,
    *,
    root=None,
    process_status: Callable[[str], dict[str, Any]] | None = None,
    launchers: dict[str, dict[str, Any]] | None = None,
    market_session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = require_pg_url(root=root)
    conn, cur_factory = _connect(url)
    launchers = launchers or {}
    try:
        with conn.cursor(cursor_factory=cur_factory) as cur:
            cur.execute(
                """
                SELECT instance_key, strategy_id, symbol_id, status, runtime_state,
                       payload_json, updated_at, last_heartbeat_at, last_synced_at
                FROM sim_instance WHERE instance_key = %s
                """,
                (instance_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise HTTPException(404, f"no cloud sim_instance for {instance_id}")
            cur.execute(
                """
                SELECT occurred_at FROM sim_decision_projection
                WHERE instance_key = %s
                ORDER BY occurred_at DESC LIMIT 1
                """,
                (instance_id,),
            )
            last_dec = cur.fetchone()
        payload = _loads(row["payload_json"])
        updated = row["updated_at"] or row["last_synced_at"] or row["last_heartbeat_at"]
        status = _status_from_updated(updated)
        proc = process_status(instance_id) if process_status else {
            "process_running": False,
            "pid": None,
            "can_start": instance_id in launchers,
            "label": launchers.get(instance_id, {}).get("label") or instance_id,
        }
        if not proc.get("process_running") and status == "RUNNING":
            status = "STALE"
        account = payload.get("account")
        if not isinstance(account, dict):
            account = None
            if payload.get("equity") is not None:
                account = {
                    "equity": payload.get("equity"),
                    "available": payload.get("available"),
                    "margin": payload.get("margin"),
                    "margin_ratio": payload.get("margin_ratio"),
                    "as_of": payload.get("as_of"),
                }
        position = payload.get("position")
        if not isinstance(position, dict):
            position = None
            if payload.get("confirmed_net") is not None or payload.get("net_position") is not None:
                position = {
                    "symbol": payload.get("symbol") or row["symbol_id"],
                    "net_position": int(payload.get("confirmed_net") or payload.get("net_position") or 0),
                    "source": "cloud",
                }
        net = int((position or {}).get("net_position") or 0)
        session = market_session or {"open": True}
        position_note = None
        if net != 0 and not session.get("open"):
            position_note = (
                f"非交易时段仍显示账户留存持仓 {net} 手（来源：云投影），"
                "不是前端误显示；周末休市不会自动平仓。"
            )
        last_price = payload.get("last_price")
        try:
            last_price_f = float(last_price) if last_price is not None else None
        except (TypeError, ValueError):
            last_price_f = None
        from dashboard.open_positions import open_positions_view

        open_positions = open_positions_view(
            position=position,
            account=account,
            state_payload=payload,
            last_price=last_price_f,
        )
        if account and (position or row["symbol_id"]):
            from ignitequant.market.margin_rates import apply_ref_margin_to_account

            sym = (position or {}).get("symbol") or payload.get("symbol") or row["symbol_id"]
            try:
                net_for_m = int(
                    payload.get("confirmed_net")
                    if payload.get("confirmed_net") is not None
                    else net
                )
            except (TypeError, ValueError):
                net_for_m = net
            ref_m = apply_ref_margin_to_account(
                equity=float(account.get("equity") or 0),
                symbol=str(sym),
                net_position=net_for_m,
                last_price=last_price_f,
            )
            if ref_m.get("margin") is not None and ref_m.get("margin_ratio") is not None:
                account = {
                    **account,
                    "margin": float(ref_m["margin"]),
                    "margin_ratio": float(ref_m["margin_ratio"]),
                    "margin_rate": ref_m.get("margin_rate"),
                    "margin_rate_pct": ref_m.get("margin_rate_pct"),
                    "margin_source": ref_m.get("margin_source"),
                }
        return {
            "instance_id": instance_id,
            "framework": "tq",
            "framework_label": "天勤模拟盘",
            "strategy_id": row["strategy_id"] or "falcon_v2",
            "account_id": (account or {}).get("account_id") or "cloud",
            "symbol": (position or {}).get("symbol")
            or payload.get("symbol")
            or row["symbol_id"],
            "runtime_state": row["runtime_state"] or payload.get("runtime_state") or "READY",
            "status": status,
            "status_label": _status_label(status),
            "label": launchers.get(instance_id, {}).get("label") or instance_id,
            "updated_at": _iso(updated),
            "payload": payload,
            "account": account,
            "position": position,
            "open_positions": open_positions,
            "position_note": position_note,
            "market_session": session,
            "last_decision_at": _iso(last_dec["occurred_at"]) if last_dec else None,
            "last_price": last_price_f,
            "last_price_source": "cloud_payload" if last_price_f is not None else None,
            "last_price_as_of": payload.get("quote_as_of") or _iso(updated),
            "cli_hint": "python strategies/falcon_au_sim.py（请在交易机运行）",
            "data_source": "cloud",
            "read_only": True,
            "read_only_hint": "当前为云端只读座舱：数据来自 Supabase 投影；启动请在交易机运行。",
            **proc,
        }
    finally:
        conn.close()


def _decision_item(row: dict[str, Any]) -> dict[str, Any]:
    factor_values = _loads(row.get("factor_values_json"))
    reason_codes = _loads(row.get("reason_codes_json"))
    if not isinstance(reason_codes, list):
        reason_codes = []
    score_parts = row.get("score_parts_json")
    if score_parts is not None:
        score_parts = _loads(score_parts)
    risk_out = None
    if row.get("risk_action") is not None:
        risk_out = {
            "action": row["risk_action"],
            "requested_position": row.get("requested_position"),
            "approved_position": row.get("approved_position"),
            "rule_hits": [],
            "payload": {},
            "created_at": _iso(row.get("occurred_at")),
        }
    return {
        "decision_id": row["decision_id"],
        "bar_id": row.get("bar_id") or row["decision_id"],
        "symbol": row.get("symbol"),
        "applied_action": row.get("applied_action"),
        "target_before": int(row["target_before"] or 0),
        "target_after": int(row["target_after"] or 0),
        "legacy_signal": int(row["legacy_signal"] or 0),
        "created_at": _iso(row.get("occurred_at") or row.get("created_at")),
        "regime": row.get("regime"),
        "factor_values": factor_values if isinstance(factor_values, dict) else {},
        "factor_quality": row.get("factor_quality"),
        "reason_codes": reason_codes,
        "score_parts": score_parts,
        "signal": {},
        "target": None,
        "risk": risk_out,
        "payload": _loads(row.get("payload_json")),
    }


def session_decisions_cloud(
    instance_id: str,
    *,
    limit: int = 50,
    before: str | None = None,
    root=None,
) -> dict[str, Any]:
    url = require_pg_url(root=root)
    conn, cur_factory = _connect(url)
    try:
        with conn.cursor(cursor_factory=cur_factory) as cur:
            if before:
                cur.execute(
                    """
                    SELECT * FROM sim_decision_projection
                    WHERE instance_key = %s AND occurred_at < %s
                    ORDER BY occurred_at DESC LIMIT %s
                    """,
                    (instance_id, before, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM sim_decision_projection
                    WHERE instance_key = %s
                    ORDER BY occurred_at DESC LIMIT %s
                    """,
                    (instance_id, limit),
                )
            rows = cur.fetchall()
        items = [_decision_item(dict(r)) for r in rows]
        return {
            "instance_id": instance_id,
            "count": len(items),
            "decisions": items,
            "data_source": "cloud",
        }
    finally:
        conn.close()


def session_intents_cloud(
    instance_id: str, *, limit: int = 100, root=None
) -> dict[str, Any]:
    url = require_pg_url(root=root)
    conn, cur_factory = _connect(url)
    try:
        with conn.cursor(cursor_factory=cur_factory) as cur:
            cur.execute(
                """
                SELECT * FROM sim_intent_projection
                WHERE instance_key = %s
                ORDER BY occurred_at DESC LIMIT %s
                """,
                (instance_id, limit),
            )
            rows = cur.fetchall()
        items = []
        for r in rows:
            reason = _loads(r.get("reason_codes_json"))
            items.append(
                {
                    "intent_id": r["intent_id"],
                    "decision_id": r.get("decision_id"),
                    "symbol": r.get("symbol"),
                    "current_position": int(r["current_position"] or 0),
                    "desired_position": int(r["desired_position"] or 0),
                    "urgency": r.get("urgency"),
                    "idempotency_key": r.get("idempotency_key"),
                    "status": r.get("status"),
                    "reason_codes": reason if isinstance(reason, list) else [],
                    "payload": _loads(r.get("payload_json")),
                    "created_at": _iso(r.get("occurred_at") or r.get("created_at")),
                }
            )
        return {
            "instance_id": instance_id,
            "count": len(items),
            "intents": items,
            "data_source": "cloud",
        }
    finally:
        conn.close()


def session_fills_cloud(
    instance_id: str, *, limit: int = 100, root=None
) -> dict[str, Any]:
    url = require_pg_url(root=root)
    conn, cur_factory = _connect(url)
    try:
        with conn.cursor(cursor_factory=cur_factory) as cur:
            cur.execute(
                """
                SELECT * FROM sim_fill_projection
                WHERE instance_key = %s
                ORDER BY occurred_at DESC LIMIT %s
                """,
                (instance_id, limit),
            )
            rows = cur.fetchall()
        items = [
            {
                "fill_id": r["fill_id"],
                "intent_id": r.get("intent_id"),
                "symbol": r.get("symbol"),
                "price": float(r["price"] or 0),
                "qty": int(r["qty"] or 0),
                "fee": float(r["fee"] or 0),
                "side": r.get("side"),
                "trade_time": _iso(r.get("trade_time")),
                "payload": _loads(r.get("payload_json")),
                "created_at": _iso(r.get("occurred_at") or r.get("created_at")),
            }
            for r in rows
        ]
        return {
            "instance_id": instance_id,
            "count": len(items),
            "fills": items,
            "data_source": "cloud",
        }
    finally:
        conn.close()


def _metrics_from_fills(fills: list[dict[str, Any]], equity: float | None) -> dict[str, Any]:
    """Approximate local _compute_metrics from cloud fill rows (ASC order)."""
    rounds = iter_closed_rounds(fills)
    summary = closed_rounds_summary(rounds)
    realized = float(summary["realized_pnl_proxy"])
    current_equity = float(equity) if equity is not None else DEFAULT_INIT_BALANCE + realized
    return {
        "trade_count": summary["trade_count"],
        "win_count": summary["wins"],
        "loss_count": summary["losses"],
        "wins": summary["wins"],
        "losses": summary["losses"],
        "win_rate": summary["win_rate"] if summary["trade_count"] else None,
        "realized_pnl": realized,
        "current_equity": current_equity,
        "max_drawdown": None,
        "max_drawdown_pct": None,
        "equity_curve": [
            {"t": None, "equity": current_equity},
        ],
        "approx": True,
        "data_source": "cloud",
    }


def session_position_history_cloud(
    instance_id: str, *, limit: int = 100, root=None
) -> dict[str, Any]:
    fills_body = session_fills_cloud(instance_id, limit=2000, root=root)
    fills_asc = list(reversed(fills_body.get("fills") or []))
    rounds = iter_closed_rounds(fills_asc)
    rounds_desc = list(reversed(rounds))[:limit]
    return {
        "instance_id": instance_id,
        "count": len(rounds),
        "positions": rounds_desc,
        "data_source": "cloud",
    }


def session_metrics_cloud(instance_id: str, *, root=None) -> dict[str, Any]:
    fills_body = session_fills_cloud(instance_id, limit=500, root=root)
    fills_asc = list(reversed(fills_body["fills"]))
    summary = session_summary_cloud(instance_id, root=root)
    equity = None
    if isinstance(summary.get("account"), dict):
        equity = summary["account"].get("equity")
    metrics = _metrics_from_fills(fills_asc, equity)
    return {"instance_id": instance_id, **metrics}
