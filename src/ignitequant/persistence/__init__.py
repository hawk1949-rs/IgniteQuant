"""Persistence package — SQLite repositories and session facade (Phase 4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ignitequant.persistence.repositories import (
    AuditRecord,
    SqliteTradingRepository,
    StrategyStateRecord,
)
from ignitequant.persistence.schema import SCHEMA_VERSION
from ignitequant.persistence.sqlite import open_sqlite

if TYPE_CHECKING:
    from ignitequant.persistence.session import PersistenceSession
    from ignitequant.persistence.repositories import TradingRepository

__all__ = [
    "SCHEMA_VERSION",
    "AuditRecord",
    "PersistenceSession",
    "SqliteTradingRepository",
    "StrategyStateRecord",
    "TradingRepository",
    "open_sqlite",
]


def __getattr__(name: str) -> Any:
    if name == "PersistenceSession":
        from ignitequant.persistence.session import PersistenceSession as _Session

        return _Session
    if name == "TradingRepository":
        from ignitequant.persistence.repositories import TradingRepository as _Repo

        return _Repo
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
