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


# Overseas gold/silver: live signal clock prefers London spot (东财 122.XAU/XAG).
# COMEX continuous (GC00Y) trades at a futures premium and must not be labeled as XAUUSD.
OVERSEAS_INSTRUMENTS: dict[str, OverseasInstrumentSpec] = {
    "gc": OverseasInstrumentSpec(
        id="gc",
        name="伦敦金（现货黄金）",
        signal_symbol="XAUUSD",
        exchange="OTC",
        yahoo_symbol="XAUUSD=X",
        eastmoney_secid="122.XAU",
        display_symbol="XAUUSD",
        multiplier=100.0,
        tick_size=0.01,
        note="伦敦金现货（东财 122.XAU）；对照沪金 au。非 COMEX 期货 GC00Y。",
    ),
    "si": OverseasInstrumentSpec(
        id="si",
        name="伦敦银（现货白银）",
        signal_symbol="XAGUSD",
        exchange="OTC",
        yahoo_symbol="XAGUSD=X",
        eastmoney_secid="122.XAG",
        display_symbol="XAGUSD",
        multiplier=5000.0,
        tick_size=0.001,
        note="伦敦银现货（东财 122.XAG）；对照沪银 ag。非 COMEX 期货 SI00Y。",
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
            "name": "伦敦金（现货黄金）",
            "display_symbol": "XAUUSD",
            "note": (
                "外盘信号时钟：伦敦金现货（东财 122.XAU / XAUUSD）；"
                "不是 COMEX 期货 GC00Y（期货相对现货常有升水）。"
            ),
        },
        "si": {
            "id": "xagusd",
            "name": "伦敦银（现货白银）",
            "display_symbol": "XAGUSD",
            "note": (
                "外盘信号时钟：伦敦银现货（东财 122.XAG / XAGUSD）；"
                "不是 COMEX 期货 SI00Y。"
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
