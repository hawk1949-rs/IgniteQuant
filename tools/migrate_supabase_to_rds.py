#!/usr/bin/env python3
"""Copy IgniteQuant cloud tables from Supabase → Aliyun RDS and reconcile counts.

Requires:
  SOURCE_DATABASE_URL or DATABASE_URL  (Supabase pooler)
  RDS_DATABASE_URL                     (Aliyun RDS PG)

Usage:
  PYTHONPATH=src python tools/migrate_supabase_to_rds.py --status
  PYTHONPATH=src python tools/migrate_supabase_to_rds.py --apply
  PYTHONPATH=src python tools/migrate_supabase_to_rds.py --apply --tables market_bar_archive
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# FK-safe order (parents before children). Unknown tables skipped if absent on source.
TABLE_ORDER: tuple[str, ...] = (
    "profiles",
    "ref_instrument",
    "ref_contract",
    "ref_continuous_map",
    "ref_trading_session",
    "ref_fee_schedule",
    "ref_product_margin",
    "ref_overseas_pair",
    "factor_definition",
    "factor_value",
    "label_value",
    "config_version",
    "backtest_run",
    "backtest_metric",
    "strategy_publication",
    "sim_instance",
    "trading_event_inbox",
    "sim_decision_projection",
    "sim_intent_projection",
    "sim_fill_projection",
    "market_bar_archive",
)

# Tables with BIGSERIAL / identity: reset sequence after copy.
SERIAL_TABLES: dict[str, str] = {
    "ref_continuous_map": "ref_continuous_map_id_seq",
    "ref_trading_session": "ref_trading_session_id_seq",
    "ref_fee_schedule": "ref_fee_schedule_id_seq",
    "factor_value": "factor_value_id_seq",
    "label_value": "label_value_id_seq",
    "backtest_metric": "backtest_metric_id_seq",
    "trading_event_inbox": "trading_event_inbox_id_seq",
    "sim_decision_projection": "sim_decision_projection_id_seq",
    "sim_intent_projection": "sim_intent_projection_id_seq",
    "sim_fill_projection": "sim_fill_projection_id_seq",
    "market_bar_archive": "market_bar_archive_id_seq",
}

BATCH = 2000


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def source_url() -> str:
    raw = (
        os.environ.get("SOURCE_DATABASE_URL", "").strip()
        or os.environ.get("DATABASE_URL", "").strip()
    )
    if not raw:
        return ""
    # Reuse production rewrite: db.*.supabase.co → Session pooler (IPv4).
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from ignitequant.persistence.cloud_sync import (  # noqa: WPS433
            _rewrite_direct_db_to_pooler,
        )

        return _rewrite_direct_db_to_pooler(raw)
    except Exception:
        return raw


def target_url() -> str:
    return os.environ.get("RDS_DATABASE_URL", "").strip()


def connect(url: str):
    import psycopg2

    return psycopg2.connect(url, connect_timeout=40)


def list_public_tables(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
        )
        return {r[0] for r in cur.fetchall()}


def column_list(conn, table: str) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table,),
        )
        return [r[0] for r in cur.fetchall()]


def count_rows(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f'SELECT COUNT(*) FROM public."{table}"')
        return int(cur.fetchone()[0])


def reset_sequence(conn, table: str, seq: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT setval(
                %s,
                COALESCE((SELECT MAX(id) FROM public."{table}"), 1),
                true
            )
            """,
            (f"public.{seq}",),
        )


def copy_table(src, dst, table: str) -> int:
    from psycopg2.extras import Json

    src_cols = column_list(src, table)
    dst_cols = column_list(dst, table)
    cols = [c for c in src_cols if c in set(dst_cols)]
    if not cols:
        print(f"  SKIP {table}: no overlapping columns", flush=True)
        return 0

    def adapt(value):
        if isinstance(value, (dict, list)):
            return Json(value)
        return value

    col_sql = ", ".join(f'"{c}"' for c in cols)
    placeholders = ", ".join(["%s"] * len(cols))
    select_sql = f'SELECT {col_sql} FROM public."{table}"'
    insert_sql = (
        f'INSERT INTO public."{table}" ({col_sql}) VALUES ({placeholders}) '
        f"ON CONFLICT DO NOTHING"
    )

    total = 0
    # Unnamed cursor: works with autocommit / pooler transaction modes.
    with src.cursor() as scur:
        scur.execute(select_sql)
        with dst.cursor() as dcur:
            while True:
                rows = scur.fetchmany(BATCH)
                if not rows:
                    break
                adapted = [tuple(adapt(v) for v in row) for row in rows]
                dcur.executemany(insert_sql, adapted)
                total += len(rows)
                if total % (BATCH * 5) == 0:
                    dst.commit()
                    print(f"    {table}: {total} rows…", flush=True)
            dst.commit()

    if table in SERIAL_TABLES:
        reset_sequence(dst, table, SERIAL_TABLES[table])
        dst.commit()
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="Compare row counts only")
    parser.add_argument("--apply", action="store_true", help="Copy missing/all rows")
    parser.add_argument(
        "--tables",
        default="",
        help="Comma-separated subset (default: all known tables present on both)",
    )
    parser.add_argument(
        "--truncate-target",
        action="store_true",
        help="TRUNCATE target tables before copy (destructive)",
    )
    args = parser.parse_args()

    if not args.status and not args.apply:
        parser.error("specify --status and/or --apply")

    load_dotenv(ROOT / ".env")
    src_url = source_url()
    dst_url = target_url()
    if not src_url:
        print("ERROR: SOURCE_DATABASE_URL or DATABASE_URL (Supabase) required", flush=True)
        return 1
    if not dst_url:
        print("ERROR: RDS_DATABASE_URL required", flush=True)
        return 1
    if "supabase.co" in dst_url.lower():
        print("ERROR: RDS_DATABASE_URL must not point at Supabase", flush=True)
        return 1

    try:
        import psycopg2  # noqa: F401
    except ImportError:
        print("ERROR: pip install psycopg2-binary", flush=True)
        return 1

    print("Connecting source (Supabase)…", flush=True)
    src = connect(src_url)
    print("Connecting target (RDS)…", flush=True)
    dst = connect(dst_url)
    src.autocommit = True
    dst.autocommit = False

    src_tables = list_public_tables(src)
    dst_tables = list_public_tables(dst)
    wanted = [t.strip() for t in args.tables.split(",") if t.strip()] or list(TABLE_ORDER)
    tables = [t for t in wanted if t in src_tables and t in dst_tables]
    missing_src = [t for t in wanted if t not in src_tables]
    missing_dst = [t for t in wanted if t not in dst_tables]
    if missing_src:
        print(f"NOTE: absent on source: {', '.join(missing_src)}", flush=True)
    if missing_dst:
        print(f"NOTE: absent on target (apply RDS schema first): {', '.join(missing_dst)}", flush=True)

    print("\nRow counts:", flush=True)
    print(f"{'table':<28} {'source':>10} {'target':>10}", flush=True)
    mismatches: list[str] = []
    for table in tables:
        sc = count_rows(src, table)
        tc = count_rows(dst, table)
        flag = "" if sc == tc else "  <<<"
        if sc != tc:
            mismatches.append(table)
        print(f"{table:<28} {sc:>10} {tc:>10}{flag}", flush=True)

    if args.status and not args.apply:
        src.close()
        dst.close()
        return 0 if not mismatches else 2

    if args.apply:
        if args.truncate_target:
            print("\nTruncating target tables (CASCADE)…", flush=True)
            with dst.cursor() as cur:
                for table in reversed(tables):
                    cur.execute(f'TRUNCATE TABLE public."{table}" CASCADE')
            dst.commit()

        print("\nCopying…", flush=True)
        for table in tables:
            print(f"  {table}", flush=True)
            n = copy_table(src, dst, table)
            print(f"    inserted≈{n} (ON CONFLICT DO NOTHING)", flush=True)

        print("\nPost-copy counts:", flush=True)
        mismatches = []
        for table in tables:
            sc = count_rows(src, table)
            tc = count_rows(dst, table)
            flag = "" if sc == tc else "  <<<"
            if sc != tc:
                mismatches.append(table)
            print(f"{table:<28} {sc:>10} {tc:>10}{flag}", flush=True)

    src.close()
    dst.close()
    if mismatches:
        print(
            f"\nWARN: count mismatch on: {', '.join(mismatches)} "
            "(may be OK if source grew during copy; re-run --apply)",
            flush=True,
        )
        return 2
    print("\nOK: source and target counts match", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
