#!/usr/bin/env python3
"""One-shot cutover helper: schema → copy → optional OSS → print ECS steps.

Does NOT rewrite .env automatically (avoids clobbering secrets). After success:
  1) Set DATABASE_URL=RDS_DATABASE_URL on ECS and local
  2) systemctl restart ignitequant-api ignitequant-sim
  3) Freeze Supabase writes

Usage:
  PYTHONPATH=src python tools/cutover_to_aliyun_rds.py --dry-run
  PYTHONPATH=src python tools/cutover_to_aliyun_rds.py --apply
  PYTHONPATH=src python tools/cutover_to_aliyun_rds.py --apply --with-oss
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--with-oss", action="store_true")
    parser.add_argument("--skip-truncate", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error("specify --dry-run or --apply")

    load_dotenv(ROOT / ".env")
    src = os.environ.get("SOURCE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    rds = os.environ.get("RDS_DATABASE_URL", "")
    print("SOURCE set:", bool(src and src.strip()))
    print("RDS_DATABASE_URL set:", bool(rds.strip()))
    print(
        "OSS keys set:",
        bool(os.environ.get("OSS_ACCESS_KEY_ID"))
        and bool(os.environ.get("OSS_ACCESS_KEY_SECRET")),
    )

    if args.dry_run:
        run([sys.executable, "tools/apply_rds_schema.py", "--dry-run"])
        return 0

    if not rds.strip():
        print("ERROR: RDS_DATABASE_URL missing in .env", flush=True)
        return 1
    if not src or not str(src).strip():
        print("ERROR: SOURCE_DATABASE_URL or DATABASE_URL missing", flush=True)
        return 1

    # Ensure source stays Supabase during copy even if operator already swapped names.
    env = os.environ.copy()
    if "supabase.co" not in str(src).lower() and "supabase.co" in os.environ.get(
        "DATABASE_URL", ""
    ).lower():
        env["SOURCE_DATABASE_URL"] = os.environ["DATABASE_URL"]

    code = run([sys.executable, "tools/apply_rds_schema.py"])
    if code != 0:
        return code

    mig = [
        sys.executable,
        "tools/migrate_supabase_to_rds.py",
        "--apply",
    ]
    if not args.skip_truncate:
        mig.append("--truncate-target")
    code = run(mig)
    if code not in (0, 2):
        return code

    if args.with_oss:
        code = run([sys.executable, "tools/sync_files_to_oss.py", "--all"])
        if code != 0:
            print("WARN: OSS upload failed; RDS cutover can still proceed", flush=True)

    print(
        """
=== NEXT (manual / ECS) ===
1. Keep SOURCE_DATABASE_URL=<old Supabase> for a while (optional rollback).
2. Set DATABASE_URL=<same as RDS_DATABASE_URL> on:
     - local .env
     - ECS /opt/IgniteQuant/.env
3. On ECS:
     systemctl restart ignitequant-api ignitequant-sim
     journalctl -u ignitequant-sim -n 30 --no-pager
4. Open http://ECS_IP/#/sim and confirm RUNNING + fresh updated_at.
5. Stop writing to Supabase (do not point tools at old DATABASE_URL).
""",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
