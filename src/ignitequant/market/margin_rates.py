"""Product margin rates — prefer ref table / bundled seed over TqSdk risk_ratio."""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from ignitequant.engine.reconciliation import contract_product_key
from ignitequant.market.symbols import INSTRUMENTS

_DATA_PATH = Path(__file__).resolve().parent / "data" / "product_margin_rates.json"


def parse_exchange_product(symbol: str) -> tuple[str, str]:
    """SHFE.au2608 / KQ.m@SHFE.au → ('SHFE', 'au')."""
    key = contract_product_key(symbol)
    if not key or "." not in key:
        return "", ""
    exchange, product = key.split(".", 1)
    return exchange.upper(), product.lower()


@lru_cache(maxsize=1)
def _bundled_rates() -> dict[tuple[str, str], float]:
    if not _DATA_PATH.is_file():
        return {}
    payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    out: dict[tuple[str, str], float] = {}
    for row in payload.get("rows") or []:
        ex = str(row.get("exchange_id") or "").strip().upper()
        pid = str(row.get("product_id") or "").strip().lower()
        rate = row.get("margin_rate")
        if rate is None and row.get("margin_rate_pct") is not None:
            rate = float(row["margin_rate_pct"]) / 100.0
        if not ex or not pid or rate is None:
            continue
        out[(ex, pid)] = float(rate)
    return out


def multiplier_for_symbol(symbol: str) -> float | None:
    _, product = parse_exchange_product(symbol)
    if not product:
        return None
    spec = INSTRUMENTS.get(product)
    if spec is not None:
        return float(spec.multiplier)
    return None


def margin_rate_for_symbol(
    symbol: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> float | None:
    """Return fraction (e.g. 0.16). Prefer SQLite ref_product_margin, else bundled JSON."""
    exchange, product = parse_exchange_product(symbol)
    if not exchange or not product:
        return None
    if conn is not None:
        try:
            row = conn.execute(
                """
                SELECT margin_rate FROM ref_product_margin
                WHERE UPPER(exchange_id) = ? AND LOWER(product_id) = ?
                """,
                (exchange, product),
            ).fetchone()
            if row is not None and row[0] is not None:
                return float(row[0])
            row2 = conn.execute(
                """
                SELECT default_margin_rate FROM ref_instrument
                WHERE LOWER(product_id) = ? AND default_margin_rate IS NOT NULL
                """,
                (product,),
            ).fetchone()
            if row2 is not None and row2[0] is not None:
                return float(row2[0])
        except sqlite3.Error:
            pass
    return _bundled_rates().get((exchange, product))


def estimate_margin(
    *,
    price: float,
    lots: int | float,
    multiplier: float,
    margin_rate: float,
) -> float:
    """Occupied margin ≈ |lots| × price × multiplier × rate."""
    if price <= 0 or multiplier <= 0 or margin_rate <= 0:
        return 0.0
    return abs(float(lots)) * float(price) * float(multiplier) * float(margin_rate)


def estimate_margin_for_symbol(
    symbol: str,
    *,
    price: float,
    lots: int | float,
    conn: sqlite3.Connection | None = None,
    multiplier: float | None = None,
) -> tuple[float | None, float | None, float]:
    """Return (margin_or_None, rate_or_None, multiplier_used)."""
    rate = margin_rate_for_symbol(symbol, conn=conn)
    mult = multiplier if multiplier is not None else multiplier_for_symbol(symbol)
    if rate is None or mult is None:
        return None, rate, float(mult or 0)
    return estimate_margin(price=price, lots=lots, multiplier=mult, margin_rate=rate), rate, float(mult)


def apply_ref_margin_to_account(
    *,
    equity: float,
    symbol: str,
    net_position: int,
    last_price: float | None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    """Compute margin + margin_ratio from ref rates; empty if rate/price missing."""
    if not last_price or last_price <= 0 or int(net_position) == 0:
        return {
            "margin": 0.0,
            "margin_ratio": 0.0,
            "margin_rate": margin_rate_for_symbol(symbol, conn=conn),
            "margin_source": "ref_flat",
        }
    margin, rate, _mult = estimate_margin_for_symbol(
        symbol, price=float(last_price), lots=int(net_position), conn=conn
    )
    if margin is None or rate is None:
        return {
            "margin": None,
            "margin_ratio": None,
            "margin_rate": rate,
            "margin_source": "tq_fallback",
        }
    eq = float(equity or 0)
    ratio = (margin / eq) if eq > 0 else 0.0
    return {
        "margin": float(margin),
        "margin_ratio": float(ratio),
        "margin_rate": float(rate),
        "margin_rate_pct": float(rate) * 100.0,
        "margin_source": "ref_product_margin",
    }
