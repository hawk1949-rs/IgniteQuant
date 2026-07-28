"""SQLite WAL connection helpers with incremental schema migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ignitequant.persistence.schema import (
    BASE_DDL,
    SCHEMA_VERSION,
    V2_ADD_COLUMNS,
    V2_NEW_TABLES_DDL,
    V3_NEW_TABLES_DDL,
    V4_ADD_COLUMNS,
    V5_NEW_TABLES_DDL,
)


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
    try:
        from ignitequant.persistence.ref_cache import seed_ref_tables

        seed_ref_tables(conn)
    except Exception:
        # Reference seed must not block trading DB open.
        pass
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r["name"]) for r in rows}


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, columns: list[tuple[str, str]]
) -> None:
    existing = _table_columns(conn, table)
    if not existing:
        return
    for name, decl in columns:
        if name in existing:
            continue
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _apply_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(V2_NEW_TABLES_DDL)
    for table, cols in V2_ADD_COLUMNS.items():
        _add_missing_columns(conn, table, cols)


def _apply_v3(conn: sqlite3.Connection) -> None:
    conn.executescript(V3_NEW_TABLES_DDL)


def _apply_v4(conn: sqlite3.Connection) -> None:
    for table, cols in V4_ADD_COLUMNS.items():
        _add_missing_columns(conn, table, cols)


def migrate(conn: sqlite3.Connection) -> None:
    """Apply BASE_DDL then any pending versioned upgrades."""
    conn.executescript(BASE_DDL)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    current = int(row["v"] or 0) if row is not None else 0

    if current < 1:
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
            "VALUES (1, datetime('now'))"
        )
        current = max(current, 1)

    if current < 2:
        _apply_v2(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
            "VALUES (2, datetime('now'))"
        )
        current = 2

    if current < 3:
        _apply_v3(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
            "VALUES (3, datetime('now'))"
        )
        current = 3

    if current < 4:
        _apply_v4(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
            "VALUES (4, datetime('now'))"
        )
        current = 4

    if current < 5:
        conn.executescript(V5_NEW_TABLES_DDL)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) "
            "VALUES (5, datetime('now'))"
        )
        current = 5

    if current < SCHEMA_VERSION:
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
            (SCHEMA_VERSION,),
        )

    conn.commit()
