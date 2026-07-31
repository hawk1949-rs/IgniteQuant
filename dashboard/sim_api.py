# -*- coding: utf-8 -*-
"""Read-only Sim Cockpit API (TqKq persistence + market cache)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from dashboard.safe_path import resolve_runtime_db
from dashboard.catalog import STRATEGIES, SYMBOLS
from dashboard import sim_cloud_read
from dashboard.open_positions import open_positions_view as _open_positions_view
from dashboard.position_history import (
    account_realized_pnl as _account_realized_pnl,
    closed_rounds_summary as _closed_rounds_summary,
    iter_closed_rounds as _iter_closed_rounds,
    iter_closed_rounds_from_broker as _iter_closed_rounds_from_broker,
    make_unattributed_close_leg as _make_unattributed_close_leg,
    prepare_fills_for_rounds as _prepare_fills_for_rounds,
    rounds_to_open_close_legs as _rounds_to_open_close_legs,
)
from ignitequant.market.chart_series import (
    DEFAULT_VISIBLE_BARS,
    assemble_visible_bars,
    build_chart_enrichment,
    price_lines_from_strategy_payload,
)
from ignitequant.market.sim_klines import (
    find_snapshot_for_symbol,
    load_klines_snapshot,
)
from ignitequant.market.symbols import INSTRUMENTS
from ignitequant.market.overseas import cockpit_overseas_pair as _cockpit_overseas_pair
from ignitequant.market.overseas_bars import fetch_live_overseas_5m_bars as _fetch_overseas_5m_bars_impl
from ignitequant.market.session import shfe_precious_session_open as _shfe_precious_session_open

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = ROOT / "data" / "runtime"

STALE_AFTER = timedelta(minutes=8)  # ~1.5× 5m bar; heartbeat alone does not touch DB
DEFAULT_INIT_BALANCE = 1_000_000.0

STATUS_LABELS = {
    "RUNNING": "运行中",
    "STALE": "数据滞后",
    "IDLE": "未运行",
}

# IgniteQuant 本地品种目录（非天勤「自带列表」）；交易走天勤连续合约，K 线默认读本地 market_cache。
# 外盘对照优先走东方财富 COMEX 连续（国内可达）；Yahoo 作备用 / 历史归档源。
_CST = timezone(timedelta(hours=8))

OVERSEAS_PAIRS: dict[str, dict[str, str]] = {
    "au": _cockpit_overseas_pair("au") or {},
    "ag": _cockpit_overseas_pair("ag") or {},
}

# instance_id → launcher
SIM_LAUNCHERS: dict[str, dict[str, Any]] = {
    "falcon_au_sim": {
        "label": "Falcon 沪金天勤模拟",
        "script": ROOT / "strategies" / "falcon_au_sim.py",
        "symbol_id": "au",
        "strategy_id": "falcon_v2",
        "framework": "tq",
    },
}

router = APIRouter(prefix="/api/sim", tags=["sim"])

_start_locks: dict[str, threading.Lock] = {}
_start_locks_guard = threading.Lock()


def _start_lock(instance_id: str) -> threading.Lock:
    with _start_locks_guard:
        if instance_id not in _start_locks:
            _start_locks[instance_id] = threading.Lock()
        return _start_locks[instance_id]


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def _live_quote(conn: sqlite3.Connection, instance_id: str) -> dict[str, Any]:
    """Prefer sim-persisted quote / latest decision close over stale market_cache."""
    state = conn.execute(
        """
        SELECT symbol, payload_json, updated_at
        FROM strategy_state WHERE instance_id = ?
        """,
        (instance_id,),
    ).fetchone()
    payload = _loads(state["payload_json"]) if state else {}
    trade_symbol = str(state["symbol"] if state else "") or None

    raw_price = payload.get("last_price")
    if raw_price is not None:
        try:
            price = float(raw_price)
            if price > 0:
                return {
                    "last_price": price,
                    "last_price_source": "sim_quote",
                    "last_price_as_of": payload.get("quote_as_of") or (state["updated_at"] if state else None),
                    "trade_symbol": trade_symbol,
                }
        except (TypeError, ValueError):
            pass

    row = conn.execute(
        """
        SELECT created_at, payload_json FROM decision_event
        WHERE instance_id = ?
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_id,),
    ).fetchone()
    if row is not None:
        dec = _loads(row["payload_json"])
        factors = dec.get("factors") if isinstance(dec, dict) else None
        values = (factors or {}).get("values") if isinstance(factors, dict) else None
        close = (values or {}).get("close") if isinstance(values, dict) else None
        if close is not None:
            try:
                price = float(close)
                if price > 0:
                    return {
                        "last_price": price,
                        "last_price_source": "decision_close",
                        "last_price_as_of": row["created_at"],
                        "trade_symbol": trade_symbol,
                    }
            except (TypeError, ValueError):
                pass

    return {
        "last_price": None,
        "last_price_source": None,
        "last_price_as_of": None,
        "trade_symbol": trade_symbol,
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _open_ro(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(str(db_path))
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _open_rw(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise FileNotFoundError(str(db_path))
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _decision_close_price(
    conn: sqlite3.Connection, instance_id: str, decision_id: str
) -> float | None:
    row = conn.execute(
        """
        SELECT payload_json FROM decision_event
        WHERE instance_id = ? AND (decision_id = ? OR bar_id = ?)
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_id, decision_id, decision_id),
    ).fetchone()
    if row is None:
        return None
    payload = _loads(row["payload_json"])
    factors = payload.get("factors") if isinstance(payload, dict) else None
    values = (factors or {}).get("values") if isinstance(factors, dict) else None
    close = (values or {}).get("close") if isinstance(values, dict) else None
    try:
        price = float(close)
        return price if price > 0 else None
    except (TypeError, ValueError):
        return None


def _repair_missing_fills(db_path: Path, instance_id: str) -> int:
    """Persist fills for SUBMITTED intents that clearly reached desired net.

    Happens when TargetPosTask filled asynchronously but runner only polled once.
    """
    try:
        conn = _open_rw(db_path)
    except FileNotFoundError:
        return 0
    repaired = 0
    try:
        intents = conn.execute(
            """
            SELECT intent_id, decision_id, symbol, current_position, desired_position,
                   status, created_at
            FROM order_intent_event
            WHERE instance_id = ?
            ORDER BY seq ASC
            """,
            (instance_id,),
        ).fetchall()
        filled_ids = {
            str(r["intent_id"])
            for r in conn.execute(
                "SELECT intent_id FROM trade_fill_event WHERE instance_id = ?",
                (instance_id,),
            ).fetchall()
        }
        latest_pos = conn.execute(
            """
            SELECT net_position FROM position_snapshot_event
            WHERE instance_id = ?
            ORDER BY seq DESC LIMIT 1
            """,
            (instance_id,),
        ).fetchone()
        latest_net = int(latest_pos["net_position"]) if latest_pos is not None else None
        if latest_net is None:
            state = conn.execute(
                "SELECT payload_json FROM strategy_state WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
            if state is not None:
                payload = _loads(state["payload_json"])
                try:
                    latest_net = int(payload.get("confirmed_net"))
                except (TypeError, ValueError):
                    latest_net = None

        for i, intent in enumerate(intents):
            intent_id = str(intent["intent_id"])
            if intent_id in filled_ids:
                continue
            status = str(intent["status"] or "")
            if status == "FILLED":
                continue
            cur = int(intent["current_position"])
            desired = int(intent["desired_position"])
            if cur == desired:
                continue
            reached = False
            trade_time = str(intent["created_at"] or "")
            if i + 1 < len(intents):
                nxt = intents[i + 1]
                if int(nxt["current_position"]) == desired:
                    reached = True
                    trade_time = str(nxt["created_at"] or trade_time)
            elif latest_net is not None and latest_net == desired:
                reached = True
            if not reached:
                continue

            price = _decision_close_price(conn, instance_id, str(intent["decision_id"] or ""))
            if price is None:
                continue
            qty = abs(desired - cur)
            side = "BUY" if desired > cur else "SELL"
            fill_id = f"fill-backfill-{intent_id}"
            now = _utc_now().isoformat()
            conn.execute(
                """
                INSERT OR IGNORE INTO trade_fill_event(
                    instance_id, fill_id, intent_id, symbol, price, qty, fee,
                    side, trade_time, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instance_id,
                    fill_id,
                    intent_id,
                    str(intent["symbol"] or ""),
                    float(price),
                    int(qty),
                    0.0,
                    side,
                    trade_time or now,
                    json.dumps(
                        {
                            "source": "intent_chain_backfill",
                            "intent_id": intent_id,
                            "note": "异步成交补记：意图后持仓已到达目标",
                        },
                        ensure_ascii=False,
                    ),
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE order_intent_event
                SET status = ?
                WHERE instance_id = ? AND intent_id = ?
                """,
                ("FILLED", instance_id, intent_id),
            )
            repaired += 1
        if repaired:
            conn.commit()
    finally:
        conn.close()
    return repaired


def _loads(raw: str | None) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


# Job / non-persistence DBs that live under data/runtime but are not sim sessions.
_SKIP_DB_NAMES = frozenset({"backtest_jobs.sqlite"})


def _has_persistence_schema(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'strategy_state'
        LIMIT 1
        """
    ).fetchone()
    return row is not None


def _discover_dbs() -> list[Path]:
    if not RUNTIME_DIR.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(RUNTIME_DIR.glob("*.sqlite")):
        if path.name in _SKIP_DB_NAMES:
            continue
        try:
            conn = _open_ro(path)
        except Exception:
            continue
        try:
            if _has_persistence_schema(conn):
                out.append(path)
        finally:
            conn.close()
    return out


def _instance_id_from_path(path: Path) -> str:
    return path.stem


def _pid_path(instance_id: str) -> Path:
    return RUNTIME_DIR / f"{instance_id}.pid"


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _find_sim_pids(script_name: str = "falcon_au_sim.py") -> list[int]:
    """Best-effort scan for running sim script (Windows-friendly)."""
    pids: list[int] = []
    if os.name == "nt":
        try:
            out = subprocess.check_output(
                [
                    "wmic",
                    "process",
                    "where",
                    f"CommandLine like '%{script_name}%'",
                    "get",
                    "ProcessId",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=8,
            )
            for line in out.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.append(int(line))
        except Exception:
            pass
    else:
        try:
            out = subprocess.check_output(["pgrep", "-f", script_name], text=True, timeout=5)
            pids = [int(x) for x in out.split() if x.isdigit()]
        except Exception:
            pass
    return [p for p in pids if _process_alive(p)]


def _process_status(instance_id: str) -> dict[str, Any]:
    launcher = SIM_LAUNCHERS.get(instance_id)
    pid_file = _pid_path(instance_id)
    pid: int | None = None
    if pid_file.is_file():
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except ValueError:
            pid = None
    alive = bool(pid and _process_alive(pid))
    if not alive:
        scanned = _find_sim_pids(Path(launcher["script"]).name if launcher else "falcon_au_sim.py")
        if scanned:
            pid = scanned[0]
            alive = True
            try:
                RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
                pid_file.write_text(str(pid), encoding="utf-8")
            except OSError:
                pass
    return {
        "process_running": alive,
        "pid": pid if alive else None,
        "label": (launcher or {}).get("label") or instance_id,
        "can_start": instance_id in SIM_LAUNCHERS,
    }


_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


def _http_get_text(url: str, *, headers: dict[str, str], timeout: float = 12) -> str | None:
    """GET text body; prefer requests, then curl.exe (more stable vs some CN hosts)."""
    try:
        import requests

        resp = requests.get(url, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.text
    except Exception:
        pass
    try:
        cmd = [
            "curl.exe",
            "-sL",
            "--fail",
            "--max-time",
            str(int(timeout)),
            "-A",
            headers.get("User-Agent") or _BROWSER_UA,
        ]
        referer = headers.get("Referer")
        if referer:
            cmd.extend(["-e", referer])
        accept = headers.get("Accept")
        if accept:
            cmd.extend(["-H", f"Accept: {accept}"])
        cmd.append(url)
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout + 3)
        text = out.decode("utf-8", errors="replace").strip()
        return text or None
    except Exception:
        return None


_EASTMONEY_HOSTS = (
    "push2delay.eastmoney.com",
    "push2his.eastmoney.com",
    "82.push2his.eastmoney.com",
    "79.push2his.eastmoney.com",
)


def _aggregate_1m_to_5m(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    """Aggregate 1m OHLC rows (already sorted) into 5m bars."""
    bars: list[dict[str, Any]] = []
    bucket_ts: int | None = None
    cur: dict[str, Any] | None = None
    for row in rows:
        ts = int(row["time"])
        # Floor to 5-minute boundary in local epoch seconds.
        floored = ts - (ts % 300)
        if bucket_ts != floored:
            if cur is not None:
                bars.append(cur)
            bucket_ts = floored
            cur = {
                "time": floored,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            continue
        assert cur is not None
        cur["high"] = max(cur["high"], float(row["high"]))
        cur["low"] = min(cur["low"], float(row["low"]))
        cur["close"] = float(row["close"])
        cur["volume"] = float(cur["volume"]) + float(row["volume"])
    if cur is not None:
        bars.append(cur)
    return bars[-limit:]


def _fetch_eastmoney_trends_5m_bars(secid: str, *, limit: int = 400) -> list[dict[str, Any]]:
    """Eastmoney trends2 (1m) → aggregate to 5m. Often works when kline/get returns empty."""
    if not secid:
        return []
    # ndays max ~5 on this endpoint; enough for a few hundred 5m bars.
    qs = urllib.parse.urlencode(
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "ndays": "5",
            "iscr": "0",
            "iscca": "0",
        }
    )
    headers = {
        "User-Agent": _BROWSER_UA,
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    trends: list[str] = []
    for host in _EASTMONEY_HOSTS:
        url = f"https://{host}/api/qt/stock/trends2/get?{qs}"
        text = _http_get_text(url, headers=headers, timeout=12)
        if not text:
            continue
        try:
            candidate = json.loads(text)
        except json.JSONDecodeError:
            continue
        rows = ((candidate.get("data") or {}).get("trends")) or []
        if rows:
            trends = [str(x) for x in rows]
            break
    if not trends:
        return []
    minutes: list[dict[str, Any]] = []
    for row in trends:
        # time, open, close, high, low, volume, amount, avg
        parts = row.split(",")
        if len(parts) < 6:
            continue
        try:
            dt = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=_CST)
            o, c, h, l = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
            vol = float(parts[5] or 0)
        except ValueError:
            continue
        minutes.append(
            {
                "time": int(dt.timestamp()),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": vol,
            }
        )
    return _aggregate_1m_to_5m(minutes, limit=limit)


def _fetch_eastmoney_5m_bars(secid: str, *, limit: int = 400) -> list[dict[str, Any]]:
    """Fetch recent 5m bars from Eastmoney COMEX continuous. Fail soft → []."""
    if not secid:
        return []
    qs = urllib.parse.urlencode(
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "5",
            "fqt": "1",
            "end": "20500101",
            "lmt": str(max(limit, 10)),
        }
    )
    headers = {
        "User-Agent": _BROWSER_UA,
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
    }
    payload: dict[str, Any] | None = None
    for host in _EASTMONEY_HOSTS:
        url = f"https://{host}/api/qt/stock/kline/get?{qs}"
        for _ in range(2):
            text = _http_get_text(url, headers=headers, timeout=12)
            if not text:
                continue
            try:
                candidate = json.loads(text)
            except json.JSONDecodeError:
                continue
            klines = ((candidate.get("data") or {}).get("klines")) or []
            if klines:
                payload = candidate
                break
        if payload is not None:
            break
    if payload is not None:
        klines = ((payload.get("data") or {}).get("klines")) or []
        bars: list[dict[str, Any]] = []
        for row in klines:
            # date, open, close, high, low, volume, ...
            parts = str(row).split(",")
            if len(parts) < 6:
                continue
            try:
                dt = datetime.strptime(parts[0].strip(), "%Y-%m-%d %H:%M").replace(tzinfo=_CST)
                o, c, h, l = (float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4]))
                vol = float(parts[5] or 0)
            except ValueError:
                continue
            bars.append(
                {
                    "time": int(dt.timestamp()),
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": vol,
                }
            )
        if bars:
            return bars[-limit:]
    # kline/get often returns empty klines for global futures in CN; trends2 is reliable.
    return _fetch_eastmoney_trends_5m_bars(secid, limit=limit)


def _fetch_yahoo_5m_bars(yahoo_symbol: str, *, limit: int = 400) -> list[dict[str, Any]]:
    """Fetch recent 5m bars from Yahoo chart API (no key). Fail soft → []."""
    qs = urllib.parse.urlencode(
        {
            "interval": "5m",
            "range": "5d",
            "includePrePost": "false",
        }
    )
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(yahoo_symbol)}?{qs}"
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "application/json",
    }
    text = _http_get_text(url, headers=headers, timeout=10)
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    try:
        result = payload["chart"]["result"][0]
        ts_list = result["timestamp"]
        quote = result["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        return []
    bars: list[dict[str, Any]] = []
    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    for i, ts in enumerate(ts_list):
        o, h, l, c = (
            opens[i] if i < len(opens) else None,
            highs[i] if i < len(highs) else None,
            lows[i] if i < len(lows) else None,
            closes[i] if i < len(closes) else None,
        )
        if None in (o, h, l, c):
            continue
        bars.append(
            {
                "time": int(ts),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(volumes[i] or 0) if i < len(volumes) else 0.0,
            }
        )
    return bars[-limit:]


# Cockpit polls overseas often; upstream HTTP is ~1–3s. Short TTL avoids blocking every refresh.
# Always pull a deep window so /overseas/bars can paginate with ``before`` without re-hitting
# Eastmoney/Yahoo for every scroll chunk.
_OVERSEAS_BARS_TTL_S = 15.0
_OVERSEAS_FETCH_DEPTH = 1200
_overseas_bars_cache: dict[str, tuple[float, list[dict[str, Any]], str | None]] = {}
_overseas_bars_lock = threading.Lock()


def _fetch_overseas_5m_bars(
    pair: dict[str, str], *, limit: int = _OVERSEAS_FETCH_DEPTH
) -> tuple[list[dict[str, Any]], str | None]:
    """Prefer Eastmoney (reachable in CN); fall back to Yahoo. TTL-cached for cockpit."""
    fetch_n = min(max(int(limit), 120), 2000)
    cache_key = (
        f"{pair.get('overseas_id')}|{pair.get('eastmoney_secid')}|{pair.get('yahoo_symbol')}"
    )
    now = time.monotonic()
    with _overseas_bars_lock:
        hit = _overseas_bars_cache.get(cache_key)
        if hit is not None and now - hit[0] < _OVERSEAS_BARS_TTL_S:
            cached_bars, source = hit[1], hit[2]
            return (
                (cached_bars[-fetch_n:] if fetch_n < len(cached_bars) else cached_bars),
                source,
            )
    bars, source = _fetch_overseas_5m_bars_impl(
        eastmoney_secid=pair.get("eastmoney_secid") or "",
        yahoo_symbol=pair.get("yahoo_symbol") or "",
        overseas_id=pair.get("overseas_id") or "",
        limit=max(fetch_n, _OVERSEAS_FETCH_DEPTH),
    )
    with _overseas_bars_lock:
        _overseas_bars_cache[cache_key] = (time.monotonic(), bars, source)
    return (bars[-fetch_n:] if fetch_n < len(bars) else bars), source


def _status_from_updated(updated_at: str | None) -> str:
    ts = _parse_ts(updated_at)
    if ts is None:
        return "IDLE"
    age = _utc_now() - ts
    if age <= STALE_AFTER:
        return "RUNNING"
    return "STALE"


def _short_bias_from_closes(closes: list[float], *, lookback: int = 12) -> str:
    """Visual near-term bias from recent closes (for cockpit, not strategy regime)."""
    if len(closes) < 3:
        return "FLAT"
    window = closes[-lookback:]
    start, end = float(window[0]), float(window[-1])
    if start <= 0:
        return "FLAT"
    chg = (end - start) / start
    if chg <= -0.001:
        return "DOWN"
    if chg >= 0.001:
        return "UP"
    return "FLAT"


def _chart_context_from_bars(bars: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Compute strategy regime + short-term bias from the same bars shown on chart."""
    if len(bars) < 60:
        return None
    try:
        import pandas as pd

        from strategies.falcon import compute_indicators, detect_regime
    except Exception:
        return None

    rows = []
    for b in bars:
        ns = b.get("datetime_ns")
        if ns is None and b.get("time") is not None:
            ns = int(b["time"]) * 1_000_000_000
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
    if len(rows) < 60:
        return None
    try:
        df = pd.DataFrame(rows)
        ind = compute_indicators(df)
        regime = detect_regime(ind).value
        closes = [float(x) for x in ind.close.tolist()]
        short_bias = _short_bias_from_closes(closes)
        return {
            "regime": regime,
            "short_bias": short_bias,
            "close": float(ind.close[-1]),
            "ma52": float(ind.ma52[-1]) if ind.ma52[-1] == ind.ma52[-1] else None,
            "adx": float(ind.adx[-1]) if ind.adx[-1] == ind.adx[-1] else None,
            "bar_time": int(rows[-1]["datetime"] // 1_000_000_000),
            "conflict": (
                (regime == "TREND_UP" and short_bias == "DOWN")
                or (regime == "TREND_DOWN" and short_bias == "UP")
            ),
        }
    except Exception:
        return None


def _empty_chart_enrichment() -> dict[str, Any]:
    return {
        "overlays": {"ma7": [], "ma14": [], "ma52": [], "signal": []},
        "bar_meta": [],
        "price_lines": [],
    }


def _load_decisions_for_chart(
    conn: sqlite3.Connection,
    instance_id: str,
    *,
    end_ts: datetime | None = None,
    limit: int = 2000,
) -> list[dict[str, Any]]:
    q = """
        SELECT bar_id, applied_action, target_after, legacy_signal, payload_json, created_at
        FROM decision_event
        WHERE instance_id = ?
    """
    params: list[Any] = [instance_id]
    if end_ts is not None:
        q += " AND created_at <= ?"
        params.append(end_ts.isoformat())
    q += " ORDER BY seq DESC LIMIT ?"
    params.append(int(limit))
    rows = conn.execute(q, params).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        payload = _loads(r["payload_json"])
        factors = (payload.get("factors") or {}) if isinstance(payload, dict) else {}
        out.append(
            {
                "bar_id": r["bar_id"],
                "applied_action": r["applied_action"],
                "target_after": int(r["target_after"]),
                "legacy_signal": int(r["legacy_signal"]),
                "created_at": r["created_at"],
                "regime": factors.get("regime") if isinstance(factors, dict) else None,
                "factor_values": (
                    factors.get("values") if isinstance(factors, dict) else None
                )
                or {},
                "score_parts": (
                    payload.get("legacy_score_parts")
                    if isinstance(payload, dict)
                    else None
                ),
                "payload": payload,
            }
        )
    return out


def _enrich_visible_chart(
    hot_bars: list[dict[str, Any]],
    *,
    signal_symbol: str,
    limit: int,
    before_sec: int | None,
    decisions: list[dict[str, Any]] | None = None,
    price_lines: list[dict[str, Any]] | None = None,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    visible, compute, source = assemble_visible_bars(
        hot_bars,
        signal_symbol=signal_symbol,
        limit=limit,
        before_sec=before_sec,
        use_cache=use_cache,
    )
    enrichment = build_chart_enrichment(
        visible,
        compute,
        decisions=decisions or [],
        price_lines=price_lines or [],
    )
    return visible, enrichment, source


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def _latest_account(conn: sqlite3.Connection, instance_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM account_snapshot_event
        WHERE instance_id = ?
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_id,),
    ).fetchone()
    if row is None:
        return None
    keys = set(row.keys())

    def _f(name: str, default: float = 0.0) -> float:
        if name not in keys or row[name] is None:
            return default
        try:
            return float(row[name])
        except (TypeError, ValueError):
            return default

    return {
        "equity": _f("equity"),
        "available": _f("available"),
        "margin": _f("margin"),
        "margin_ratio": _f("margin_ratio"),
        "realized_pnl_today": _f("realized_pnl_today"),
        "unrealized_pnl": _f("unrealized_pnl"),
        "as_of": row["as_of"] if "as_of" in keys else None,
        "created_at": row["created_at"] if "created_at" in keys else None,
        "payload": _loads(row["payload_json"]) if "payload_json" in keys else {},
    }


def _latest_position(conn: sqlite3.Connection, instance_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM position_snapshot_event
        WHERE instance_id = ?
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_id,),
    ).fetchone()
    if row is None:
        return None
    keys = set(row.keys())
    payload = _loads(row["payload_json"]) if "payload_json" in keys else {}

    def _i(name: str, default: int = 0) -> int:
        if name not in keys or row[name] is None:
            return default
        try:
            return int(row[name])
        except (TypeError, ValueError):
            return default

    def _f(name: str, default: float | None = None) -> float | None:
        if name not in keys or row[name] is None:
            return default
        try:
            return float(row[name])
        except (TypeError, ValueError):
            return default

    avg = _f("avg_entry_price")
    if avg is None and isinstance(payload, dict):
        try:
            raw = payload.get("average_entry_price")
            avg = float(raw) if raw is not None else None
        except (TypeError, ValueError):
            avg = None

    return {
        "symbol": row["symbol"],
        "net_position": _i("net_position"),
        "source": row["source"] if "source" in keys else None,
        "as_of": row["as_of"] if "as_of" in keys else None,
        "created_at": row["created_at"] if "created_at" in keys else None,
        "long_today": _i("long_today"),
        "long_yesterday": _i("long_yesterday"),
        "short_today": _i("short_today"),
        "short_yesterday": _i("short_yesterday"),
        "average_entry_price": avg,
        "unrealized_pnl": float(_f("unrealized_pnl", 0.0) or 0.0),
        "margin": float(
            _f("margin", 0.0)
            or (payload.get("margin") if isinstance(payload, dict) else 0)
            or 0
        ),
        "payload": payload,
    }


def _latest_decision_at(conn: sqlite3.Connection, instance_id: str) -> str | None:
    row = conn.execute(
        """
        SELECT created_at FROM decision_event
        WHERE instance_id = ?
        ORDER BY seq DESC LIMIT 1
        """,
        (instance_id,),
    ).fetchone()
    return None if row is None else str(row["created_at"])


def _resolve_db(instance_id: str) -> Path:
    return resolve_runtime_db(RUNTIME_DIR, instance_id)


def _signal_symbol_for_trade(symbol: str) -> str:
    """Map trade contract or continuous symbol to cache signal symbol."""
    raw = (symbol or "").strip()
    if not raw:
        return "KQ.m@SHFE.au"
    if raw.startswith("KQ.m@"):
        return raw
    # Prefer exact instrument id (au / ag / rb / fg)
    key = raw.lower()
    if key in INSTRUMENTS:
        return INSTRUMENTS[key].signal_symbol
    for spec in INSTRUMENTS.values():
        prefix = f"{spec.exchange}.{spec.id}"
        if raw.startswith(prefix) or raw.startswith(f"{spec.exchange}.{spec.id.upper()}"):
            return spec.signal_symbol
        # SHFE.au2608 / CZCE.FG509 → alphabetic product code
        parts = raw.split(".", 1)
        if len(parts) == 2 and parts[0] == spec.exchange:
            product = "".join(ch for ch in parts[1] if ch.isalpha())
            if product.lower() == spec.id.lower():
                return spec.signal_symbol
    return "KQ.m@SHFE.au"


def _prior_inventory_for_fills(
    conn: sqlite3.Connection, instance_id: str
) -> tuple[int, float | None]:
    """Broker net just before the first real fill (usually startup leftover)."""
    row = conn.execute(
        """
        SELECT net_position, avg_entry_price
        FROM position_snapshot_event
        WHERE instance_id = ?
          AND ABS(COALESCE(net_position, 0)) > 0
          AND COALESCE(source, '') LIKE '%startup%'
        ORDER BY seq ASC
        LIMIT 1
        """,
        (instance_id,),
    ).fetchone()
    if row is None:
        return 0, None
    net = int(row["net_position"] or 0)
    avg = None
    if row["avg_entry_price"] is not None:
        try:
            avg = float(row["avg_entry_price"])
        except (TypeError, ValueError):
            avg = None
    return net, avg


def _load_fills_prepared(
    conn: sqlite3.Connection, instance_id: str
) -> list[dict[str, Any]]:
    fills = conn.execute(
        """
        SELECT symbol, price, qty, fee, side, trade_time, created_at, payload_json
        FROM trade_fill_event
        WHERE instance_id = ?
        ORDER BY seq ASC
        """,
        (instance_id,),
    ).fetchall()
    rows = []
    for f in fills:
        item = dict(f)
        item["payload"] = _loads(item.pop("payload_json", None))
        rows.append(item)
    prior_net, prior_avg = _prior_inventory_for_fills(conn, instance_id)
    return _prepare_fills_for_rounds(rows, prior_net=prior_net, prior_avg_price=prior_avg)


def _load_broker_rounds(
    conn: sqlite3.Connection, instance_id: str
) -> tuple[list[dict[str, Any]], str]:
    """Prefer 天勤 position snapshots; fall back to cleaned fills."""
    pos_rows = conn.execute(
        """
        SELECT symbol, net_position, avg_entry_price, unrealized_pnl, source, as_of, created_at
        FROM position_snapshot_event
        WHERE instance_id = ?
        ORDER BY seq ASC
        """,
        (instance_id,),
    ).fetchall()
    acct_rows = conn.execute(
        """
        SELECT equity, as_of, created_at
        FROM account_snapshot_event
        WHERE instance_id = ?
        ORDER BY seq ASC
        """,
        (instance_id,),
    ).fetchall()
    fill_rows = conn.execute(
        """
        SELECT symbol, price, qty, fee, side, trade_time, created_at, payload_json
        FROM trade_fill_event
        WHERE instance_id = ?
        ORDER BY seq ASC
        """,
        (instance_id,),
    ).fetchall()
    fills: list[dict[str, Any]] = []
    for f in fill_rows:
        item = dict(f)
        item["payload"] = _loads(item.pop("payload_json", None))
        fills.append(item)

    broker_rounds = _iter_closed_rounds_from_broker(
        [dict(r) for r in pos_rows],
        account_snapshots=[dict(r) for r in acct_rows],
        fills=fills,
    )
    if broker_rounds:
        return broker_rounds, "broker_position"

    prepared = _prepare_fills_for_rounds(fills)
    return _iter_closed_rounds(prepared), "fills_fallback"


def _compute_metrics(conn: sqlite3.Connection, instance_id: str) -> dict[str, Any]:
    fill_rows = _load_fills_prepared(conn, instance_id)
    rounds, rounds_source = _load_broker_rounds(conn, instance_id)
    summary = _closed_rounds_summary(rounds)
    # Residual open position after walking fills (for metrics.open_position).
    pos = 0
    for f in fill_rows:
        side = str(f.get("side") or "").upper()
        qty = abs(int(f.get("qty") or 0))
        if side in {"SELL", "SHORT"} or ("SELL" in side or "SHORT" in side):
            pos -= qty
        else:
            pos += qty

    equities = conn.execute(
        """
        SELECT equity, as_of, created_at FROM account_snapshot_event
        WHERE instance_id = ?
        ORDER BY seq ASC
        """,
        (instance_id,),
    ).fetchall()
    equity_curve = [
        {"t": r["as_of"] or r["created_at"], "equity": float(r["equity"])} for r in equities
    ]
    current_equity = float(equities[-1]["equity"]) if equities else DEFAULT_INIT_BALANCE
    peak = DEFAULT_INIT_BALANCE
    max_dd = 0.0
    for pt in equity_curve:
        eq = float(pt["equity"])
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak)

    acct = _latest_account(conn, instance_id)
    pos_snap = _latest_position(conn, instance_id)
    unrealized = 0.0
    if acct is not None:
        current_equity = float(acct["equity"])
        try:
            unrealized = float(acct.get("unrealized_pnl") or 0)
        except (TypeError, ValueError):
            unrealized = 0.0
    if unrealized == 0.0 and pos_snap is not None:
        try:
            unrealized = float(pos_snap.get("unrealized_pnl") or 0)
        except (TypeError, ValueError):
            pass
    if pos_snap is not None:
        try:
            pos = int(pos_snap.get("net_position") or pos)
        except (TypeError, ValueError):
            pass

    pnl = current_equity - DEFAULT_INIT_BALANCE
    realized_account = _account_realized_pnl(
        equity=current_equity,
        init_balance=DEFAULT_INIT_BALANCE,
        unrealized=unrealized,
    )
    realized_fills = float(summary["realized_pnl_proxy"])
    return {
        "equity": current_equity,
        "init_balance": DEFAULT_INIT_BALANCE,
        "pnl": pnl,
        "pnl_pct": pnl / DEFAULT_INIT_BALANCE,
        "realized_pnl_proxy": realized_fills,
        "realized_pnl_closed": realized_account,
        "realized_pnl_fills": realized_fills,
        "unrealized_pnl": unrealized,
        "pnl_residual": realized_account - realized_fills,
        "trade_count": summary["trade_count"],
        "fill_count": len(fill_rows),
        "wins": summary["wins"],
        "losses": summary["losses"],
        "win_rate": summary["win_rate"],
        "max_drawdown_pct": max_dd,
        "open_position": pos,
        "equity_curve": equity_curve[-200:],
        "history_source": rounds_source,
        "pnl_note": (
            "账户盈亏/已实现以天勤权益为准。"
            "持仓历史按开仓¥0 + 平仓价差；若缺本地开平记录会多一行「结转」对齐账户。"
        ),
    }


def _enrich_fills_local(
    conn: sqlite3.Connection, instance_id: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach decision-time signal / stop / take onto fill rows via intent_id."""
    from dashboard.fill_enrichment import (
        apply_entry_stop_fallback,
        enrichment_from_decision_payload,
    )

    if not items:
        return items

    intent_ids = [str(it["intent_id"]) for it in items if it.get("intent_id")]
    intent_to_decision: dict[str, str] = {}
    decisions: dict[str, dict[str, Any]] = {}
    risks: dict[str, Any] = {}
    if intent_ids:
        placeholders = ",".join("?" for _ in intent_ids)
        intent_rows = conn.execute(
            f"""
            SELECT intent_id, decision_id
            FROM order_intent_event
            WHERE instance_id = ? AND intent_id IN ({placeholders})
            """,
            [instance_id, *intent_ids],
        ).fetchall()
        intent_to_decision = {
            str(r["intent_id"]): str(r["decision_id"])
            for r in intent_rows
            if r["decision_id"]
        }
        decision_ids = sorted(set(intent_to_decision.values()))
        if decision_ids:
            d_placeholders = ",".join("?" for _ in decision_ids)
            dec_rows = conn.execute(
                f"""
                SELECT decision_id, legacy_signal, applied_action, payload_json
                FROM decision_event
                WHERE instance_id = ? AND decision_id IN ({d_placeholders})
                """,
                [instance_id, *decision_ids],
            ).fetchall()
            decisions = {
                str(r["decision_id"]): {
                    "legacy_signal": r["legacy_signal"],
                    "applied_action": r["applied_action"],
                    "payload": _loads(r["payload_json"]),
                }
                for r in dec_rows
            }
            risk_rows = conn.execute(
                f"""
                SELECT decision_id, payload_json
                FROM risk_decision_event
                WHERE instance_id = ? AND decision_id IN ({d_placeholders})
                ORDER BY seq ASC
                """,
                [instance_id, *decision_ids],
            ).fetchall()
            for r in risk_rows:
                risks[str(r["decision_id"])] = _loads(r["payload_json"])

    out: list[dict[str, Any]] = []
    for item in items:
        enriched = dict(item)
        did = intent_to_decision.get(str(item.get("intent_id") or ""))
        dec = decisions.get(did or "") if did else None
        if dec:
            enriched.update(
                enrichment_from_decision_payload(
                    decision_id=did,
                    legacy_signal=dec.get("legacy_signal"),
                    applied_action=dec.get("applied_action"),
                    payload=dec.get("payload"),
                    risk_payload=risks.get(did or ""),
                )
            )
        fill_payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if fill_payload.get("source"):
            enriched["fill_source"] = fill_payload.get("source")
        out.append(enriched)

    # Entry levels for fallback onto exit / resync fills with cleared stops.
    entry_rows = conn.execute(
        """
        SELECT decision_id, applied_action, payload_json, created_at
        FROM decision_event
        WHERE instance_id = ?
          AND applied_action IN ('TARGET', 'HOLD')
        ORDER BY seq ASC
        """,
        (instance_id,),
    ).fetchall()
    entry_levels: list[dict[str, Any]] = []
    for r in entry_rows:
        payload = _loads(r["payload_json"])
        lvl = enrichment_from_decision_payload(
            decision_id=str(r["decision_id"]),
            legacy_signal=None,
            applied_action=r["applied_action"],
            payload=payload,
            risk_payload=None,
        )
        if lvl.get("stop_price") is None:
            continue
        entry_levels.append(
            {
                "as_of": r["created_at"],
                "stop_price": lvl.get("stop_price"),
                "take_price": lvl.get("take_price"),
                "entry_price": lvl.get("entry_price"),
            }
        )
    return apply_entry_stop_fallback(out, entry_levels)

def _position_history_from_conn(
    conn: sqlite3.Connection, instance_id: str, *, limit: int = 100
) -> dict[str, Any]:
    rounds, source = _load_broker_rounds(conn, instance_id)
    # Assign round_id for fill-fallback rounds too.
    for i, r in enumerate(rounds):
        if not r.get("round_id"):
            r["round_id"] = f"{source}-{i}-{r.get('opened_at') or i}"
    summary = _closed_rounds_summary(rounds)
    legs = _rounds_to_open_close_legs(rounds, newest_first=True)
    # limit applies to rounds; legs are 2× rounds (newest rounds first).
    max_legs = max(int(limit) * 2, 0)
    legs = legs[:max_legs]

    rounds_price_pnl = float(summary["realized_pnl_proxy"])
    acct = _latest_account(conn, instance_id)
    equity = float(acct["equity"]) if acct is not None else DEFAULT_INIT_BALANCE
    unrealized = 0.0
    if acct is not None:
        try:
            unrealized = float(acct.get("unrealized_pnl") or 0)
        except (TypeError, ValueError):
            unrealized = 0.0
    account_realized = _account_realized_pnl(
        equity=equity,
        init_balance=DEFAULT_INIT_BALANCE,
        unrealized=unrealized,
    )
    as_of = None
    if acct is not None:
        as_of = acct.get("as_of") or acct.get("created_at")
    residual_leg = _make_unattributed_close_leg(
        account_realized=account_realized,
        rounds_price_pnl=rounds_price_pnl,
        as_of=str(as_of) if as_of else None,
    )
    if residual_leg is not None:
        # Keep newest-first: 结转 explains the account gap at the top.
        legs = [residual_leg, *legs]

    return {
        "instance_id": instance_id,
        "count": len(legs),
        "round_count": len(rounds),
        "positions": legs,
        "realized_pnl_total": rounds_price_pnl,
        "account_realized_pnl": float(account_realized),
        "unattributed_pnl": float(residual_leg["realized_pnl"]) if residual_leg else 0.0,
        "history_source": source,
        "history_format": "open_close_legs",
        "fills_prepared": source != "broker_position",
    }


def _decision_row(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    payload = _loads(row["payload_json"])
    risk = conn.execute(
        """
        SELECT action, requested_position, approved_position, rule_hits_json, payload_json, created_at
        FROM risk_decision_event
        WHERE instance_id = ? AND decision_id = ?
        ORDER BY seq DESC LIMIT 1
        """,
        (row["instance_id"], row["decision_id"]),
    ).fetchone()
    risk_out = None
    if risk is not None:
        risk_out = {
            "action": risk["action"],
            "requested_position": int(risk["requested_position"]),
            "approved_position": int(risk["approved_position"]),
            "rule_hits": _loads(risk["rule_hits_json"]) or [],
            "payload": _loads(risk["payload_json"]),
            "created_at": risk["created_at"],
        }
    factors = (payload.get("factors") or {}) if isinstance(payload, dict) else {}
    signal = (payload.get("signal") or {}) if isinstance(payload, dict) else {}
    return {
        "decision_id": row["decision_id"],
        "bar_id": row["bar_id"],
        "symbol": row["symbol"],
        "applied_action": row["applied_action"],
        "target_before": int(row["target_before"]),
        "target_after": int(row["target_after"]),
        "legacy_signal": int(row["legacy_signal"]),
        "created_at": row["created_at"],
        "regime": factors.get("regime"),
        "factor_values": factors.get("values") or {},
        "factor_quality": factors.get("quality"),
        "reason_codes": factors.get("reason_codes") or signal.get("reason_codes") or [],
        "score_parts": payload.get("legacy_score_parts") if isinstance(payload, dict) else None,
        "signal": signal,
        "target": payload.get("target") if isinstance(payload, dict) else None,
        "risk": risk_out,
        "payload": payload,
    }


@router.get("/catalog")
def sim_catalog() -> dict[str, Any]:
    symbols = []
    for s in SYMBOLS.values():
        pair = OVERSEAS_PAIRS.get(s.id)
        symbols.append(
            {
                "id": s.id,
                "name": s.name,
                "signal_symbol": s.signal_symbol,
                "exchange": s.exchange,
                "source": "ignitequant_catalog",
                "source_note": "项目内支持的品种目录（本地缓存 + 天勤连续合约），不是天勤客户端自带品种表。",
                "overseas_pair": pair,
            }
        )
    return {
        "frameworks": [
            {
                "id": "tq",
                "name": "天勤模拟盘",
                "enabled": True,
                "cli": "python strategies/falcon_au_sim.py",
            },
            {
                "id": "mt5",
                "name": "MetaTrader 5（外盘）",
                "enabled": False,
                "note": "即将支持",
            },
        ],
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "ready": s.runner != "run_vwap_stub",
            }
            for s in STRATEGIES.values()
        ],
        "symbols": symbols,
        "launchers": [
            {
                "instance_id": iid,
                "label": meta["label"],
                "symbol_id": meta["symbol_id"],
                "strategy_id": meta["strategy_id"],
                "framework": meta["framework"],
            }
            for iid, meta in SIM_LAUNCHERS.items()
        ],
        "cli_hint": "python strategies/falcon_au_sim.py",
        "runtime_dir": str(RUNTIME_DIR),
        "refresh_hint": "页面按 5 分钟 K 线节奏自动刷新",
        "symbol_catalog_note": "品种来自 IgniteQuant 本地目录（au/ag/rb/fg），映射天勤主力连续合约；K 线优先读 data/market_cache。",
        "data_source": sim_cloud_read.data_source(),
        "read_only": sim_cloud_read.is_cloud(),
        "read_only_hint": (
            "当前为云端只读座舱：会话/决策/意图/成交来自 Supabase 投影；"
            "启动与补跑请在交易机执行。本页可常驻打开，不依赖本机 sqlite。"
            if sim_cloud_read.is_cloud()
            else None
        ),
    }


@router.get("/sessions")
def list_sessions() -> dict[str, Any]:
    if sim_cloud_read.is_cloud():
        return sim_cloud_read.list_sessions_cloud(
            root=ROOT,
            process_status=_process_status,
            launchers=SIM_LAUNCHERS,
        )
    sessions: list[dict[str, Any]] = []
    for path in _discover_dbs():
        instance_id = _instance_id_from_path(path)
        try:
            conn = _open_ro(path)
        except Exception as exc:
            sessions.append(
                {
                    "instance_id": instance_id,
                    "status": "IDLE",
                    "error": f"cannot open db: {exc}",
                }
            )
            continue
        try:
            if not _has_persistence_schema(conn):
                continue
            state = conn.execute(
                """
                SELECT instance_id, strategy_id, account_id, symbol, runtime_state,
                       payload_json, updated_at
                FROM strategy_state WHERE instance_id = ?
                """,
                (instance_id,),
            ).fetchone()
            if state is None:
                # Prefer any row if stem != instance_id stored in table
                state = conn.execute(
                    """
                    SELECT instance_id, strategy_id, account_id, symbol, runtime_state,
                           payload_json, updated_at
                    FROM strategy_state
                    ORDER BY updated_at DESC LIMIT 1
                    """
                ).fetchone()
            if state is None:
                sessions.append(
                    {
                        "instance_id": instance_id,
                        "strategy_id": "falcon_v2" if "falcon" in instance_id else "",
                        "symbol": "",
                        "runtime_state": "IDLE",
                        "status": "IDLE",
                        "updated_at": None,
                        "framework": "tq",
                    }
                )
                continue
            payload = _loads(state["payload_json"])
            updated = state["updated_at"]
            sessions.append(
                {
                    "instance_id": str(state["instance_id"] or instance_id),
                    "strategy_id": state["strategy_id"],
                    "account_id": state["account_id"],
                    "symbol": state["symbol"],
                    "runtime_state": state["runtime_state"],
                    "status": _status_from_updated(updated),
                    "status_label": _status_label(_status_from_updated(updated)),
                    "updated_at": updated,
                    "payload": payload,
                    "framework": "tq",
                    "label": SIM_LAUNCHERS.get(instance_id, {}).get("label") or instance_id,
                    "last_decision_at": _latest_decision_at(
                        conn, str(state["instance_id"] or instance_id)
                    ),
                    **_process_status(str(state["instance_id"] or instance_id)),
                }
            )
        except sqlite3.Error as exc:
            sessions.append(
                {
                    "instance_id": instance_id,
                    "status": "IDLE",
                    "error": str(exc),
                }
            )
        finally:
            conn.close()
    return {"sessions": sessions, "count": len(sessions)}


@router.get("/sessions/{instance_id}/summary")
def session_summary(instance_id: str) -> dict[str, Any]:
    if sim_cloud_read.is_cloud():
        return sim_cloud_read.session_summary_cloud(
            instance_id,
            root=ROOT,
            process_status=_process_status,
            launchers=SIM_LAUNCHERS,
            market_session=_shfe_precious_session_open(),
        )
    path = _resolve_db(instance_id)
    conn = _open_ro(path)
    try:
        state = conn.execute(
            """
            SELECT instance_id, strategy_id, account_id, symbol, runtime_state,
                   payload_json, updated_at
            FROM strategy_state WHERE instance_id = ?
            """,
            (instance_id,),
        ).fetchone()
        if state is None:
            raise HTTPException(404, f"no strategy_state for {instance_id}")
        updated = state["updated_at"]
        status = _status_from_updated(updated)
        proc = _process_status(instance_id)
        # If process is dead, force IDLE for display even if DB looks recent.
        if not proc["process_running"] and status == "RUNNING":
            status = "STALE"
        live = _live_quote(conn, instance_id)
        position = _latest_position(conn, instance_id)
        account = _latest_account(conn, instance_id)
        state_payload = _loads(state["payload_json"])
        session = _shfe_precious_session_open()
        net = int(position["net_position"]) if position else 0
        position_note = None
        if net != 0 and not session["open"]:
            position_note = (
                f"非交易时段仍显示账户留存持仓 {net} 手（来源："
                f"{(position or {}).get('source') or 'broker'}），"
                "不是前端误显示；周末休市不会自动平仓。"
            )
        open_positions = _open_positions_view(
            position=position,
            account=account,
            state_payload=state_payload,
            last_price=live.get("last_price"),
        )
        # Override account margin/ratio from ref_product_margin (TqSim risk_ratio is wrong).
        if account and (position or state["symbol"]):
            from ignitequant.market.margin_rates import apply_ref_margin_to_account

            sym = (position or {}).get("symbol") or state["symbol"]
            confirmed = state_payload.get("confirmed_net")
            try:
                net_for_m = int(confirmed) if confirmed is not None else net
            except (TypeError, ValueError):
                net_for_m = net
            ref_m = apply_ref_margin_to_account(
                equity=float(account.get("equity") or 0),
                symbol=str(sym),
                net_position=net_for_m,
                last_price=live.get("last_price"),
                conn=conn,
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
            "strategy_id": state["strategy_id"],
            "account_id": state["account_id"],
            "symbol": state["symbol"],
            "runtime_state": state["runtime_state"],
            "status": status,
            "status_label": _status_label(status),
            "label": SIM_LAUNCHERS.get(instance_id, {}).get("label") or instance_id,
            "updated_at": updated,
            "payload": state_payload,
            "account": account,
            "position": position,
            "open_positions": open_positions,
            "position_note": position_note,
            "market_session": session,
            "last_decision_at": _latest_decision_at(conn, instance_id),
            "last_price": live["last_price"],
            "last_price_source": live["last_price_source"],
            "last_price_as_of": live["last_price_as_of"],
            "cli_hint": "python strategies/falcon_au_sim.py",
            **proc,
        }
    finally:
        conn.close()


@router.get("/sessions/{instance_id}/process")
def session_process(instance_id: str) -> dict[str, Any]:
    return {"instance_id": instance_id, **_process_status(instance_id)}


@router.post("/sessions/{instance_id}/start")
def session_start(instance_id: str) -> dict[str, Any]:
    """Start local TqKq sim process (CLI equivalent)."""
    from dashboard.safe_path import validate_safe_id

    validate_safe_id(instance_id, field="instance_id")
    launcher = SIM_LAUNCHERS.get(instance_id)
    if not launcher:
        raise HTTPException(400, f"暂不支持从此处启动会话：{instance_id}")
    with _start_lock(instance_id):
        proc = _process_status(instance_id)
        if proc["process_running"]:
            return {
                "ok": True,
                "already_running": True,
                "message": "模拟盘进程已在运行",
                **proc,
            }
        script: Path = launcher["script"]
        if not script.is_file():
            raise HTTPException(500, f"启动脚本不存在：{script}")
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
        env.setdefault("FALCON_PROFILE", "falcon_legacy_v1")
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        log_path = RUNTIME_DIR / f"{instance_id}.launch.log"
        log_f = open(log_path, "a", encoding="utf-8")
        try:
            child = subprocess.Popen(
                [sys.executable, str(script)],
                cwd=str(ROOT),
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                close_fds=os.name != "nt",
                start_new_session=os.name != "nt",
            )
        except Exception as exc:
            log_f.close()
            raise HTTPException(500, f"启动失败：{exc}") from exc
        log_f.close()
        _pid_path(instance_id).write_text(str(child.pid), encoding="utf-8")
        return {
            "ok": True,
            "already_running": False,
            "message": "已启动天勤模拟盘进程",
            "pid": child.pid,
            "log_path": str(log_path),
            "process_running": True,
            "label": launcher["label"],
            "can_start": True,
        }


@router.post("/sessions/{instance_id}/repair-fills")
def session_repair_fills(instance_id: str) -> dict[str, Any]:
    """Backfill missing fills for async TargetPosTask (explicit write; not on GET)."""
    from ignitequant.persistence.repair import repair_missing_fills

    path = _resolve_db(instance_id)
    repaired = repair_missing_fills(path, instance_id)
    return {"instance_id": instance_id, "repaired": repaired}


@router.post("/sessions/{instance_id}/catch-up-bars")
def session_catch_up_bars(instance_id: str) -> dict[str, Any]:
    """Replay missed completed 5m bars into decision chain (local sqlite only).

    Does not place live broker orders from the API. If the sim process is running,
    prefer restarting it (startup catch-up can align orders). This endpoint still
    backfills decision history for the cockpit.
    """
    from dashboard.safe_path import validate_safe_id
    from ignitequant.engine.catch_up import catch_up_session_db

    validate_safe_id(instance_id, field="instance_id")
    if sim_cloud_read.is_cloud():
        # Allow if local sqlite exists (trade PC with cloud default); else 503-ish.
        try:
            path = _resolve_db(instance_id)
        except HTTPException:
            raise HTTPException(
                503,
                "云端只读模式且无本地 sqlite：请在交易机执行补跑（或设 SIM_DATA_SOURCE=local）。",
            ) from None
    else:
        path = _resolve_db(instance_id)

    proc = _process_status(instance_id)
    meta = SIM_LAUNCHERS.get(instance_id) or {}
    signal_symbol = "KQ.m@SHFE.au"
    sid = meta.get("symbol_id") or "au"
    if sid in INSTRUMENTS:
        signal_symbol = INSTRUMENTS[sid].signal_symbol

    result = catch_up_session_db(
        path,
        instance_id,
        runtime_dir=RUNTIME_DIR,
        root=ROOT,
        signal_symbol=signal_symbol,
    )
    body = result.to_dict()
    body["instance_id"] = instance_id
    body["process_running"] = bool(proc.get("process_running"))
    if proc.get("process_running"):
        body["hint"] = (
            "决策链已尽量补写。模拟盘进程仍在内存中运行时，下单状态可能未同步；"
            "建议重启模拟盘以做启动补跑对齐。"
        )
    elif result.final_target != result.confirmed_net and result.missed:
        body["hint"] = (
            f"补跑后策略目标={result.final_target}，净仓={result.confirmed_net}；"
            "请启动模拟盘以对齐下单。"
        )
    else:
        body["hint"] = None
    return body


@router.get("/overseas/bars")
def overseas_bars(
    symbol_id: str = Query("au"),
    limit: int = Query(DEFAULT_VISIBLE_BARS, ge=10, le=2000),
    before: int | None = Query(
        None, description="unix seconds; return bars strictly before this open time"
    ),
    instance_id: str | None = Query(
        None, description="optional session id to overlay live decision signal/regime"
    ),
) -> dict[str, Any]:
    pair = OVERSEAS_PAIRS.get(symbol_id)
    if not pair:
        return {
            "symbol_id": symbol_id,
            "supported": False,
            "bars": [],
            "last_price": None,
            "overlays": {"ma7": [], "ma14": [], "ma52": [], "signal": []},
            "bar_meta": [],
            "has_more": False,
            "hint": "当前品种暂无配置外盘对照。",
        }
    # Deep fetch once (TTL-cached); slice for visible window / before pagination.
    bars_all, source = _fetch_overseas_5m_bars(pair, limit=_OVERSEAS_FETCH_DEPTH)
    pool = list(bars_all) if bars_all else []
    if before is not None:
        before_i = int(before)
        pool = [b for b in pool if int(b["time"]) < before_i]
    visible = list(pool[-limit:]) if pool else []
    has_more = len(pool) > len(visible)
    # Warmup extras for MA when not paginating older history.
    compute = list(bars_all) if bars_all and before is None else (pool or visible)
    decisions: list[dict[str, Any]] = []
    if instance_id and visible:
        try:
            path = _resolve_db(instance_id)
            conn = _open_ro(path)
            try:
                decisions = _load_decisions_for_chart(conn, instance_id, limit=2000)
            finally:
                conn.close()
        except HTTPException:
            decisions = []
        except Exception:
            decisions = []
    enrichment = build_chart_enrichment(
        visible,
        compute or visible,
        decisions=decisions,
        price_lines=None,
    )
    last_price = float(visible[-1]["close"]) if visible else None
    last_open = int(visible[-1]["time"]) if visible else None
    now_ts = time.time()
    # Age past the bar open; also report how late we are vs an ideal live tip.
    lag_seconds = None
    if last_open is not None and before is None:
        lag_seconds = max(0.0, now_ts - float(last_open) - 300.0)
    return {
        "symbol_id": symbol_id,
        "supported": True,
        "pair": pair,
        "bars": visible,
        "overlays": enrichment["overlays"],
        "bar_meta": enrichment["bar_meta"],
        "has_more": has_more,
        "last_price": last_price,
        "last_bar_open": last_open,
        "lag_seconds": lag_seconds,
        "source": source,
        "hint": None
        if visible
        else (
            f"暂时无法拉取 {pair['display_symbol']} 外盘信号行情（Yahoo/东方财富均不可达）。"
            "外盘定价品种 fail-closed：无外盘K线时不开新仓。"
        ),
        "pricing_role": "signal_clock",
        "note": (
            "本品种信号由外盘 5m K 线驱动；内盘休市时信号仍落库，"
            "Risk 记 MARKET_CLOSED，不下单、持仓保留。"
            + (
                f" 当前源={source}，末根延迟约 {int(lag_seconds)}s。"
                if lag_seconds is not None and lag_seconds > 90
                else ""
            )
        ),
    }


@router.get("/market/bars")
def market_bars(
    symbol_id: str = Query("au"),
    limit: int = Query(DEFAULT_VISIBLE_BARS, ge=10, le=2000),
    before: int | None = Query(None, description="unix seconds; return bars strictly before this"),
) -> dict[str, Any]:
    """Sim Cockpit bars: Tq live JSON snapshot, SQLite fallback, then market_cache history."""
    try:
        spec = INSTRUMENTS[symbol_id]
    except KeyError as exc:
        raise HTTPException(404, f"未知品种：{symbol_id}") from exc

    # Pull a wider hot window so assemble_visible can trim + prepend cache.
    hot_limit = min(max(limit + 80, 200), 2000)
    snap = find_snapshot_for_symbol(
        symbol_id,
        SIM_LAUNCHERS,
        runtime_dir=RUNTIME_DIR,
        limit=hot_limit,
    )
    if snap is None:
        # Also accept any runtime *.klines.json whose signal matches.
        for path in RUNTIME_DIR.glob("*.klines.json"):
            iid = path.name.replace(".klines.json", "")
            candidate = load_klines_snapshot(iid, runtime_dir=RUNTIME_DIR, limit=hot_limit)
            if not candidate:
                continue
            if candidate.get("signal_symbol") == spec.signal_symbol:
                snap = candidate
                break

    source = "tqsdk_sim_live"
    if snap is None:
        # L2 fallback: read market_bar from the matching launcher DB.
        from ignitequant.persistence.sqlite import open_sqlite

        for iid, meta in SIM_LAUNCHERS.items():
            if meta.get("symbol_id") != symbol_id:
                continue
            db_path = RUNTIME_DIR / f"{iid}.sqlite"
            if not db_path.is_file():
                continue
            try:
                conn = open_sqlite(db_path)
                try:
                    from ignitequant.persistence.repositories import SqliteTradingRepository

                    repo = SqliteTradingRepository(conn)
                    bars_db = repo.list_market_bars(
                        spec.signal_symbol, duration_sec=300, limit=hot_limit
                    )
                finally:
                    conn.close()
            except Exception:
                bars_db = []
            if bars_db:
                snap = {
                    "signal_symbol": spec.signal_symbol,
                    "trade_symbol": bars_db[-1].get("underlying_symbol") or spec.signal_symbol,
                    "bars": bars_db,
                    "last_price": float(bars_db[-1]["close"]),
                    "updated_at": None,
                    "duration_seconds": 300,
                }
                source = "sqlite_market_bar"
                break

    session = _shfe_precious_session_open()
    hot_bars = list((snap or {}).get("bars") or [])
    visible, enrichment, assembled_source = _enrich_visible_chart(
        hot_bars,
        signal_symbol=spec.signal_symbol,
        limit=limit,
        before_sec=before,
        decisions=None,
        price_lines=None,
        use_cache=True,
    )
    if assembled_source != "tqsdk_sim_live":
        source = assembled_source
    elif not hot_bars and visible:
        source = assembled_source

    if not visible:
        return {
            "symbol_id": symbol_id,
            "name": spec.name,
            "signal_symbol": spec.signal_symbol,
            "trade_symbol": spec.signal_symbol,
            "bars": [],
            "markers": [],
            **_empty_chart_enrichment(),
            "last_price": None,
            "last_price_source": None,
            "hint": "暂无天勤模拟盘 K 线快照，且本地 market_cache 也无可用历史。请先启动模拟盘或下载行情缓存。",
            "source": "tqsdk_sim_live",
            "chart_context": None,
            "market_session": session,
            "has_more": False,
        }

    last_price = (snap or {}).get("last_price") if snap else None
    if last_price is None and visible:
        last_price = float(visible[-1]["close"])
    trade_symbol = str((snap or {}).get("trade_symbol") or "")
    if not trade_symbol and visible:
        trade_symbol = str(visible[-1].get("underlying_symbol") or spec.signal_symbol)

    hint = None
    if source == "sqlite_market_bar":
        hint = "来自 SQLite market_bar（JSON 快照缺失时的回退）"
    elif "market_cache" in source:
        hint = "已拼接本地 market_cache 历史 K 线"

    return {
        "symbol_id": symbol_id,
        "name": spec.name,
        "signal_symbol": str((snap or {}).get("signal_symbol") or spec.signal_symbol),
        "trade_symbol": trade_symbol,
        "bars": visible,
        "markers": [],
        "overlays": enrichment["overlays"],
        "bar_meta": enrichment["bar_meta"],
        "price_lines": enrichment["price_lines"],
        "last_price": float(last_price) if last_price is not None else None,
        "last_price_source": source,
        "updated_at": (snap or {}).get("updated_at"),
        "hint": hint,
        "source": source,
        "chart_context": _chart_context_from_bars(visible),
        "market_session": session,
        "has_more": len(visible) >= limit,
    }


@router.get("/sessions/{instance_id}/metrics")
def session_metrics(instance_id: str) -> dict[str, Any]:
    if sim_cloud_read.is_cloud():
        return sim_cloud_read.session_metrics_cloud(instance_id, root=ROOT)
    path = _resolve_db(instance_id)
    conn = _open_ro(path)
    try:
        metrics = _compute_metrics(conn, instance_id)
        return {"instance_id": instance_id, **metrics}
    finally:
        conn.close()


@router.get("/sessions/{instance_id}/decisions")
def session_decisions(
    instance_id: str,
    limit: int = Query(50, ge=1, le=500),
    before: str | None = None,
) -> dict[str, Any]:
    if sim_cloud_read.is_cloud():
        return sim_cloud_read.session_decisions_cloud(
            instance_id, limit=limit, before=before, root=ROOT
        )
    path = _resolve_db(instance_id)
    conn = _open_ro(path)
    try:
        if before:
            rows = conn.execute(
                """
                SELECT * FROM decision_event
                WHERE instance_id = ? AND created_at < ?
                ORDER BY seq DESC LIMIT ?
                """,
                (instance_id, before, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM decision_event
                WHERE instance_id = ?
                ORDER BY seq DESC LIMIT ?
                """,
                (instance_id, limit),
            ).fetchall()
        items = [_decision_row(conn, r) for r in rows]
        return {"instance_id": instance_id, "count": len(items), "decisions": items}
    finally:
        conn.close()


@router.get("/sessions/{instance_id}/intents")
def session_intents(
    instance_id: str,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    if sim_cloud_read.is_cloud():
        return sim_cloud_read.session_intents_cloud(instance_id, limit=limit, root=ROOT)
    path = _resolve_db(instance_id)
    conn = _open_ro(path)
    try:
        rows = conn.execute(
            """
            SELECT intent_id, decision_id, symbol, current_position, desired_position,
                   urgency, idempotency_key, status, reason_codes_json, payload_json, created_at
            FROM order_intent_event
            WHERE instance_id = ?
            ORDER BY seq DESC LIMIT ?
            """,
            (instance_id, limit),
        ).fetchall()
        items = [
            {
                "intent_id": r["intent_id"],
                "decision_id": r["decision_id"],
                "symbol": r["symbol"],
                "current_position": int(r["current_position"]),
                "desired_position": int(r["desired_position"]),
                "urgency": r["urgency"],
                "idempotency_key": r["idempotency_key"],
                "status": r["status"],
                "reason_codes": _loads(r["reason_codes_json"]) or [],
                "payload": _loads(r["payload_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        return {"instance_id": instance_id, "count": len(items), "intents": items}
    finally:
        conn.close()


@router.get("/sessions/{instance_id}/fills")
def session_fills(
    instance_id: str,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    if sim_cloud_read.is_cloud():
        return sim_cloud_read.session_fills_cloud(instance_id, limit=limit, root=ROOT)
    path = _resolve_db(instance_id)
    conn = _open_ro(path)
    try:
        rows = conn.execute(
            """
            SELECT fill_id, intent_id, symbol, price, qty, fee, side, trade_time,
                   payload_json, created_at
            FROM trade_fill_event
            WHERE instance_id = ?
            ORDER BY seq DESC LIMIT ?
            """,
            (instance_id, limit),
        ).fetchall()
        items = [
            {
                "fill_id": r["fill_id"],
                "intent_id": r["intent_id"],
                "symbol": r["symbol"],
                "price": float(r["price"]),
                "qty": int(r["qty"]),
                "fee": float(r["fee"] or 0),
                "side": r["side"],
                "trade_time": r["trade_time"],
                "payload": _loads(r["payload_json"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]
        items = _enrich_fills_local(conn, instance_id, items)
        return {"instance_id": instance_id, "count": len(items), "fills": items}
    finally:
        conn.close()


@router.get("/sessions/{instance_id}/position-history")
def session_position_history(
    instance_id: str,
    limit: int = Query(100, ge=1, le=500),
) -> dict[str, Any]:
    """Closed round-trip positions (flat cycles) for cockpit history tab."""
    if sim_cloud_read.is_cloud():
        return sim_cloud_read.session_position_history_cloud(
            instance_id, limit=limit, root=ROOT
        )
    path = _resolve_db(instance_id)
    conn = _open_ro(path)
    try:
        return _position_history_from_conn(conn, instance_id, limit=limit)
    finally:
        conn.close()


@router.get("/sessions/{instance_id}/bars")
def session_bars(
    instance_id: str,
    symbol: str | None = None,
    end: str | None = None,
    limit: int = Query(DEFAULT_VISIBLE_BARS, ge=10, le=2000),
    before: int | None = Query(None, description="unix seconds; return bars strictly before this"),
) -> dict[str, Any]:
    """Bars for cockpit: live snapshot + market_cache history + strategy overlays."""
    hot_limit = min(max(limit + 80, 200), 2000)
    if sim_cloud_read.is_cloud():
        trade_symbol = symbol or "KQ.m@SHFE.au"
        last_price = None
        try:
            summary = sim_cloud_read.session_summary_cloud(
                instance_id,
                root=ROOT,
                process_status=_process_status,
                launchers=SIM_LAUNCHERS,
                market_session=_shfe_precious_session_open(),
            )
            trade_symbol = symbol or summary.get("symbol") or trade_symbol
            last_price = summary.get("last_price")
        except HTTPException:
            pass
        signal_symbol = _signal_symbol_for_trade(str(trade_symbol))
        snap = load_klines_snapshot(instance_id, runtime_dir=RUNTIME_DIR, limit=hot_limit)
        hot_bars: list[dict[str, Any]] = list((snap or {}).get("bars") or [])
        if end and hot_bars:
            end_ts = _parse_ts(end)
            if end_ts is not None:
                end_sec = int(end_ts.timestamp())
                hot_bars = [b for b in hot_bars if int(b.get("time") or 0) <= end_sec]
        markers: list[dict[str, Any]] = []
        try:
            fills = sim_cloud_read.session_fills_cloud(instance_id, limit=200, root=ROOT)
            for f in fills.get("fills") or []:
                ts = _parse_ts(f.get("trade_time")) or _parse_ts(f.get("created_at"))
                if ts is None:
                    continue
                side = str(f.get("side") or "").upper()
                is_buy = side in {"BUY", "LONG"} or "BUY" in side
                markers.append(
                    {
                        "time": int(ts.timestamp()),
                        "position": "belowBar" if is_buy else "aboveBar",
                        "color": "#30d158" if is_buy else "#ff453a",
                        "shape": "arrowUp" if is_buy else "arrowDown",
                        "text": f"{'B' if is_buy else 'S'}{abs(int(f.get('qty') or 0))}@{float(f.get('price') or 0):.2f}",
                        "side": "BUY" if is_buy else "SELL",
                        "price": float(f.get("price") or 0),
                        "qty": int(f.get("qty") or 0),
                    }
                )
        except HTTPException:
            pass
        visible, enrichment, assembled_source = _enrich_visible_chart(
            hot_bars,
            signal_symbol=signal_symbol,
            limit=limit,
            before_sec=before,
            decisions=None,
            price_lines=None,
            use_cache=True,
        )
        return {
            "instance_id": instance_id,
            "signal_symbol": signal_symbol,
            "trade_symbol": trade_symbol,
            "bars": visible,
            "markers": markers,
            "overlays": enrichment["overlays"],
            "bar_meta": enrichment["bar_meta"],
            "price_lines": enrichment["price_lines"],
            "last_price": last_price,
            "last_price_source": "cloud_payload" if last_price else None,
            "last_price_as_of": None,
            "hint": (
                None
                if visible
                else "云端只读模式：实时 K 线仅在交易机写入本地快照。可用 market_cache 归档，或在交易机打开座舱查看热 K 线。"
            ),
            "source": assembled_source if visible else "cloud_readonly",
            "data_source": "cloud",
            "has_more": len(visible) >= limit,
            "chart_context": _chart_context_from_bars(visible) if visible else None,
        }
    path = _resolve_db(instance_id)
    conn = _open_ro(path)
    try:
        state = conn.execute(
            "SELECT symbol, payload_json FROM strategy_state WHERE instance_id = ?",
            (instance_id,),
        ).fetchone()
        trade_symbol = symbol or (state["symbol"] if state else "") or "KQ.m@SHFE.au"
        signal_symbol = _signal_symbol_for_trade(trade_symbol)
        live = _live_quote(conn, instance_id)

        snap = load_klines_snapshot(instance_id, runtime_dir=RUNTIME_DIR, limit=hot_limit)
        hot_bars = list((snap or {}).get("bars") or [])
        end_ts = _parse_ts(end)
        if end_ts is not None and hot_bars:
            end_sec = int(end_ts.timestamp())
            hot_bars = [b for b in hot_bars if int(b.get("time") or 0) <= end_sec]

        fill_q = """
            SELECT price, qty, side, trade_time, created_at FROM trade_fill_event
            WHERE instance_id = ?
        """
        params: list[Any] = [instance_id]
        if end_ts is not None:
            fill_q += " AND created_at <= ?"
            params.append(end_ts.isoformat())
        fill_q += " ORDER BY seq ASC"
        markers = []
        for f in conn.execute(fill_q, params).fetchall():
            ts = _parse_ts(f["trade_time"]) or _parse_ts(f["created_at"])
            if ts is None:
                continue
            side = str(f["side"] or "").upper()
            is_buy = side in {"BUY", "LONG"} or "BUY" in side
            markers.append(
                {
                    "time": int(ts.timestamp()),
                    "position": "belowBar" if is_buy else "aboveBar",
                    "color": "#30d158" if is_buy else "#ff453a",
                    "shape": "arrowUp" if is_buy else "arrowDown",
                    "text": f"{'B' if is_buy else 'S'}{abs(int(f['qty']))}@{float(f['price']):.2f}",
                    "side": "BUY" if is_buy else "SELL",
                    "price": float(f["price"]),
                    "qty": int(f["qty"]),
                }
            )

        dec_q = """
            SELECT applied_action, target_after, legacy_signal, created_at, bar_id
            FROM decision_event
            WHERE instance_id = ? AND applied_action IN ('TARGET','STOP_LOSS','TAKE_PROFIT')
        """
        dparams: list[Any] = [instance_id]
        if end_ts is not None:
            dec_q += " AND created_at <= ?"
            dparams.append(end_ts.isoformat())
        dec_q += " ORDER BY seq ASC"
        for d in conn.execute(dec_q, dparams).fetchall():
            ts = _parse_ts(d["created_at"])
            if ts is None:
                continue
            markers.append(
                {
                    "time": int(ts.timestamp()),
                    "position": "aboveBar",
                    "color": "#0a84ff",
                    "shape": "circle",
                    "text": f"{d['applied_action']}:{d['target_after']}",
                    "side": "SIGNAL",
                    "price": None,
                    "qty": int(d["target_after"]),
                }
            )

        decisions = _load_decisions_for_chart(conn, instance_id, end_ts=end_ts)
        price_lines = price_lines_from_strategy_payload(
            _loads(state["payload_json"]) if state is not None else {}
        )
        visible, enrichment, assembled_source = _enrich_visible_chart(
            hot_bars,
            signal_symbol=signal_symbol,
            limit=limit,
            before_sec=before,
            decisions=decisions,
            price_lines=price_lines,
            use_cache=True,
        )

        if not visible:
            return {
                "instance_id": instance_id,
                "signal_symbol": signal_symbol,
                "trade_symbol": trade_symbol,
                "bars": [],
                "markers": markers,
                **_empty_chart_enrichment(),
                "last_price": live["last_price"],
                "last_price_source": live["last_price_source"],
                "last_price_as_of": live["last_price_as_of"],
                "hint": "暂无天勤模拟盘 K 线快照，且本地 market_cache 也无可用历史。请确认模拟盘已启动或先下载行情缓存。",
                "source": "tqsdk_sim_live",
                "has_more": False,
                "chart_context": None,
            }

        snap_price = (snap or {}).get("last_price") if snap else None
        if snap_price is None and visible:
            snap_price = float(visible[-1]["close"])
        last_price = live["last_price"] if live["last_price"] is not None else snap_price
        trade_out = str((snap or {}).get("trade_symbol") or trade_symbol)
        hint = None
        if "market_cache" in assembled_source:
            hint = "已拼接本地 market_cache 历史 K 线"

        return {
            "instance_id": instance_id,
            "signal_symbol": str((snap or {}).get("signal_symbol") or signal_symbol),
            "trade_symbol": trade_out,
            "bars": visible,
            "markers": markers,
            "overlays": enrichment["overlays"],
            "bar_meta": enrichment["bar_meta"],
            "price_lines": enrichment["price_lines"],
            "last_price": float(last_price) if last_price is not None else None,
            "last_price_source": live["last_price_source"] or assembled_source,
            "last_price_as_of": live["last_price_as_of"] or ((snap or {}).get("updated_at")),
            "hint": hint,
            "source": assembled_source,
            "updated_at": (snap or {}).get("updated_at"),
            "has_more": len(visible) >= limit,
            "chart_context": _chart_context_from_bars(visible),
        }
    finally:
        conn.close()


@router.get("/sessions/{instance_id}/replay")
def session_replay(
    instance_id: str,
    at: str = Query(..., description="ISO timestamp"),
) -> dict[str, Any]:
    path = _resolve_db(instance_id)
    at_ts = _parse_ts(at)
    if at_ts is None:
        raise HTTPException(400, "invalid at timestamp")
    at_iso = at_ts.isoformat()
    conn = _open_ro(path)
    try:
        acct = conn.execute(
            """
            SELECT equity, available, margin, margin_ratio, as_of, created_at, payload_json
            FROM account_snapshot_event
            WHERE instance_id = ? AND created_at <= ?
            ORDER BY seq DESC LIMIT 1
            """,
            (instance_id, at_iso),
        ).fetchone()
        pos = conn.execute(
            """
            SELECT symbol, net_position, source, as_of, created_at, payload_json
            FROM position_snapshot_event
            WHERE instance_id = ? AND created_at <= ?
            ORDER BY seq DESC LIMIT 1
            """,
            (instance_id, at_iso),
        ).fetchone()
        dec = conn.execute(
            """
            SELECT * FROM decision_event
            WHERE instance_id = ? AND created_at <= ?
            ORDER BY seq DESC LIMIT 1
            """,
            (instance_id, at_iso),
        ).fetchone()
        fills = conn.execute(
            """
            SELECT fill_id, intent_id, symbol, price, qty, fee, side, trade_time, created_at
            FROM trade_fill_event
            WHERE instance_id = ? AND created_at <= ?
            ORDER BY seq ASC
            """,
            (instance_id, at_iso),
        ).fetchall()
        # Metrics up to at: filter fills temporarily via subquery logic
        # Reuse compute on a filtered set by reading equity at time
        equity = float(acct["equity"]) if acct else DEFAULT_INIT_BALANCE
        decision = _decision_row(conn, dec) if dec is not None else None
        return {
            "instance_id": instance_id,
            "at": at_iso,
            "mode": "replay",
            "account": (
                {
                    "equity": float(acct["equity"]),
                    "available": float(acct["available"]),
                    "margin": float(acct["margin"]),
                    "margin_ratio": float(acct["margin_ratio"]),
                    "as_of": acct["as_of"],
                    "created_at": acct["created_at"],
                }
                if acct
                else None
            ),
            "position": (
                {
                    "symbol": pos["symbol"],
                    "net_position": int(pos["net_position"]),
                    "as_of": pos["as_of"],
                }
                if pos
                else None
            ),
            "decision": decision,
            "fills": [
                {
                    "fill_id": f["fill_id"],
                    "intent_id": f["intent_id"],
                    "symbol": f["symbol"],
                    "price": float(f["price"]),
                    "qty": int(f["qty"]),
                    "fee": float(f["fee"] or 0),
                    "side": f["side"],
                    "trade_time": f["trade_time"],
                    "created_at": f["created_at"],
                }
                for f in fills
            ],
            "metrics_snapshot": {
                "equity": equity,
                "pnl": equity - DEFAULT_INIT_BALANCE,
                "fill_count": len(fills),
            },
        }
    finally:
        conn.close()
