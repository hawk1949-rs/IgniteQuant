"""Local read-through cache for instrument reference data (architecture L3).

Seeds ``ref_*`` tables from ``INSTRUMENTS`` so runners work offline. The same
shape is applied to Supabase via ``supabase/migrations/``.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from ignitequant.market.symbols import INSTRUMENTS

# SHFE precious / black day sessions (local wall-clock seconds from midnight).
# Includes mid-morning break 10:15–10:30 and lunch 11:30–13:30.
_DEFAULT_SESSIONS: list[tuple[str, int, int]] = [
    ("day_open", 9 * 3600, 10 * 3600 + 15 * 60),
    ("day_mid", 10 * 3600 + 30 * 60, 11 * 3600 + 30 * 60),
    ("day_afternoon", 13 * 3600 + 30 * 60, 15 * 3600),
    ("night", 21 * 3600, 24 * 3600 + 2 * 3600 + 30 * 60),  # crosses midnight conceptually
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_ref_tables(conn: sqlite3.Connection) -> int:
    """Upsert product / fee / session / margin rows from the local catalogs."""
    now = _utc_now()
    n = 0
    for spec in INSTRUMENTS.values():
        conn.execute(
            """
            INSERT INTO ref_instrument(
                product_id, exchange_id, name, multiplier, price_tick,
                default_margin_rate, currency, signal_symbol, active,
                payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'CNY', ?, 1, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                exchange_id=excluded.exchange_id,
                name=excluded.name,
                multiplier=excluded.multiplier,
                price_tick=excluded.price_tick,
                signal_symbol=excluded.signal_symbol,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at,
                active=1
            """,
            (
                spec.id,
                spec.exchange,
                spec.name,
                float(spec.multiplier),
                float(spec.tick_size),
                None,
                spec.signal_symbol,
                json.dumps(
                    {
                        "open_fee_per_lot": spec.open_fee_per_lot,
                        "close_fee_per_lot": spec.close_fee_per_lot,
                        "close_today_fee_per_lot": spec.close_today_fee_per_lot,
                    },
                    sort_keys=True,
                ),
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO ref_fee_schedule(
                product_id, valid_from, valid_to, open_fee, close_fee,
                close_today_fee, fee_type
            ) VALUES (?, '1970-01-01', NULL, ?, ?, ?, 'per_lot')
            ON CONFLICT(product_id, valid_from) DO UPDATE SET
                open_fee=excluded.open_fee,
                close_fee=excluded.close_fee,
                close_today_fee=excluded.close_today_fee
            """,
            (
                spec.id,
                float(spec.open_fee_per_lot),
                float(spec.close_fee_per_lot),
                float(spec.close_today_fee_per_lot),
            ),
        )
        for session_id, open_sec, close_sec in _DEFAULT_SESSIONS:
            conn.execute(
                """
                INSERT INTO ref_trading_session(
                    product_id, exchange_id, session_id, weekday_mask,
                    open_sec, close_sec, timezone
                ) VALUES (?, ?, ?, '1,2,3,4,5', ?, ?, 'Asia/Shanghai')
                ON CONFLICT(product_id, session_id) DO UPDATE SET
                    open_sec=excluded.open_sec,
                    close_sec=excluded.close_sec,
                    exchange_id=excluded.exchange_id
                """,
                (spec.id, spec.exchange, session_id, int(open_sec), int(close_sec)),
            )
        # Continuous map sentinel (as_of epoch) — real underlying filled at runtime.
        conn.execute(
            """
            INSERT INTO ref_continuous_map(
                signal_symbol, as_of, underlying_symbol, roll_reason
            ) VALUES (?, '1970-01-01T00:00:00+00:00', ?, 'catalog_seed')
            ON CONFLICT(signal_symbol, as_of) DO UPDATE SET
                underlying_symbol=excluded.underlying_symbol,
                roll_reason=excluded.roll_reason
            """,
            (spec.signal_symbol, spec.signal_symbol),
        )
        n += 1
    seed_product_margin_rates(conn)
    conn.commit()
    return n


def seed_product_margin_rates(conn: sqlite3.Connection) -> int:
    """Upsert ref_product_margin (+ instrument default_margin_rate) from bundled JSON."""
    from ignitequant.market.margin_rates import _DATA_PATH, _bundled_rates

    if not _DATA_PATH.is_file():
        return 0
    try:
        payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    now = _utc_now()
    source = str(payload.get("source") or "bundled_json")
    as_of = str(payload.get("as_of") or "")
    n = 0
    for (exchange, product), rate in _bundled_rates().items():
        pct = float(rate) * 100.0
        conn.execute(
            """
            INSERT INTO ref_product_margin(
                exchange_id, product_id, margin_rate_pct, margin_rate,
                source, as_of, notes, payload_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?)
            ON CONFLICT(exchange_id, product_id) DO UPDATE SET
                margin_rate_pct=excluded.margin_rate_pct,
                margin_rate=excluded.margin_rate,
                source=excluded.source,
                as_of=excluded.as_of,
                updated_at=excluded.updated_at
            """,
            (exchange, product, pct, float(rate), source, as_of, "bundled_seed", now),
        )
        conn.execute(
            """
            UPDATE ref_instrument
            SET default_margin_rate = ?, updated_at = ?
            WHERE LOWER(product_id) = ? AND UPPER(exchange_id) = ?
            """,
            (float(rate), now, product, exchange),
        )
        n += 1
    return n


def load_ref_instrument(conn: sqlite3.Connection, product_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM ref_instrument WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    return dict(row) if row else None
