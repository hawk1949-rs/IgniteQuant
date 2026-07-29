"""Overseas (外盘) instrument catalog + domestic pairing for research / cockpit."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverseasInstrumentSpec:
    id: str
    name: str
    signal_symbol: str  # archive / Yahoo symbol, e.g. GC=F
    exchange: str
    yahoo_symbol: str
    eastmoney_secid: str
    display_symbol: str
    currency: str = "USD"
    multiplier: float = 100.0
    tick_size: float = 0.1
    note: str = ""


@dataclass(frozen=True)
class OverseasPair:
    domestic_id: str
    overseas_id: str


# COMEX / NYMEX continuous futures via Yahoo + Eastmoney mirrors.
OVERSEAS_INSTRUMENTS: dict[str, OverseasInstrumentSpec] = {
    "gc": OverseasInstrumentSpec(
        id="gc",
        name="COMEX黄金",
        signal_symbol="GC=F",
        exchange="COMEX",
        yahoo_symbol="GC=F",
        eastmoney_secid="101.GC00Y",
        display_symbol="XAUUSD/GC",
        multiplier=100.0,
        tick_size=0.1,
        note="COMEX Gold continuous; 对照沪金 au",
    ),
    "si": OverseasInstrumentSpec(
        id="si",
        name="COMEX白银",
        signal_symbol="SI=F",
        exchange="COMEX",
        yahoo_symbol="SI=F",
        eastmoney_secid="101.SI00Y",
        display_symbol="XAGUSD/SI",
        multiplier=5000.0,
        tick_size=0.005,
        note="COMEX Silver continuous; 对照沪银 ag",
    ),
    "hg": OverseasInstrumentSpec(
        id="hg",
        name="COMEX铜",
        signal_symbol="HG=F",
        exchange="COMEX",
        yahoo_symbol="HG=F",
        eastmoney_secid="101.HG00Y",
        display_symbol="HG",
        multiplier=25000.0,
        tick_size=0.0005,
        note="COMEX Copper continuous",
    ),
    "cl": OverseasInstrumentSpec(
        id="cl",
        name="NYMEX原油",
        signal_symbol="CL=F",
        exchange="NYMEX",
        yahoo_symbol="CL=F",
        eastmoney_secid="102.CL00Y",
        display_symbol="CL",
        multiplier=1000.0,
        tick_size=0.01,
        note="NYMEX WTI continuous",
    ),
}


# Domestic cockpit symbol_id → overseas id (for dual-chart / paired research).
OVERSEAS_PAIRS: dict[str, OverseasPair] = {
    "au": OverseasPair(domestic_id="au", overseas_id="gc"),
    "ag": OverseasPair(domestic_id="ag", overseas_id="si"),
}


def overseas_by_id(product_id: str) -> OverseasInstrumentSpec:
    key = product_id.strip().lower()
    if key not in OVERSEAS_INSTRUMENTS:
        raise KeyError(f"unsupported overseas id: {product_id}")
    return OVERSEAS_INSTRUMENTS[key]


def overseas_pair_for_domestic(domestic_id: str) -> dict[str, str] | None:
    """Research helper: domestic id → overseas instrument fields."""
    pair = OVERSEAS_PAIRS.get(domestic_id.strip().lower())
    if pair is None:
        return None
    spec = OVERSEAS_INSTRUMENTS[pair.overseas_id]
    return {
        "id": spec.id,
        "name": spec.name,
        "display_symbol": spec.display_symbol,
        "yahoo_symbol": spec.yahoo_symbol,
        "eastmoney_secid": spec.eastmoney_secid,
        "signal_symbol": spec.signal_symbol,
        "exchange": spec.exchange,
        "note": spec.note,
    }


def cockpit_overseas_pair(domestic_id: str) -> dict[str, str] | None:
    """Catalog payload matching legacy OVERSEAS_PAIRS fields."""
    pair = OVERSEAS_PAIRS.get(domestic_id.strip().lower())
    if pair is None:
        return None
    spec = OVERSEAS_INSTRUMENTS[pair.overseas_id]
    legacy = {
        "gc": {
            "id": "xauusd",
            "name": "国际黄金 XAUUSD",
            "display_symbol": "XAUUSD",
            "note": (
                "外盘对照：以 COMEX 黄金期货（GC00Y / GC=F）近似 XAUUSD；"
                "非天勤/MT5 实盘账户。历史归档见 market_bar_archive symbol=GC=F。"
            ),
        },
        "si": {
            "id": "xagusd",
            "name": "国际白银 XAGUSD",
            "display_symbol": "XAGUSD",
            "note": (
                "外盘对照：以 COMEX 白银期货（SI00Y / SI=F）近似 XAGUSD；"
                "非天勤/MT5 实盘账户。历史归档见 market_bar_archive symbol=SI=F。"
            ),
        },
    }.get(spec.id, {})
    return {
        "id": legacy.get("id", spec.id),
        "overseas_id": spec.id,
        "name": legacy.get("name", spec.name),
        "display_symbol": legacy.get("display_symbol", spec.display_symbol),
        "yahoo_symbol": spec.yahoo_symbol,
        "eastmoney_secid": spec.eastmoney_secid,
        "signal_symbol": spec.signal_symbol,
        "note": legacy.get("note", spec.note),
    }
