"""SQLite WAL connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ignitequant.persistence.schema import DDL, SCHEMA_VERSION


def open_sqlite(path: str | Path, *, wal: bool = True) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if wal:
        conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(DDL)
    row = conn.execute(
        "SELECT MAX(version) AS v FROM schema_migrations"
    ).fetchone()
    current = int(row["v"] or 0) if row is not None else 0
    if current < SCHEMA_VERSION:
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
            (SCHEMA_VERSION,),
        )
        conn.commit()
