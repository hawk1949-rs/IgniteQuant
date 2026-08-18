#!/usr/bin/env python3
"""Upload local overseas market_cache CSVs to Aliyun ECS.

  python tools/upload_overseas_cache_to_ecs.py
  python tools/upload_overseas_cache_to_ecs.py --ids gc,si
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    import sys

    sys.path.insert(0, str(ROOT))
    from tools.deploy_to_ecs import load_dotenv, ssh_connect

    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default="gc,si")
    args = parser.parse_args()
    ids = [x.strip().lower() for x in args.ids.split(",") if x.strip()]

    sys.path.insert(0, str(ROOT / "src"))
    from ignitequant.market.cache import cache_path
    from ignitequant.market.overseas import overseas_by_id

    client, host = ssh_connect()
    remote_root = os.environ.get("ECS_PATH", "/opt/IgniteQuant").rstrip("/")
    sftp = client.open_sftp()
    uploaded = 0
    try:
        for pid in ids:
            spec = overseas_by_id(pid)
            local = cache_path(spec.signal_symbol, duration_seconds=300)
            if not local.is_file():
                print(f"[MISS] local {local}", flush=True)
                continue
            rel = local.relative_to(ROOT).as_posix()
            remote = f"{remote_root}/{rel}"
            remote_dir = remote.rsplit("/", 1)[0]
            # mkdir -p via sftp
            parts = remote_dir.split("/")
            cur = ""
            for part in parts:
                if not part:
                    cur = "/"
                    continue
                cur = f"{cur.rstrip('/')}/{part}"
                try:
                    sftp.stat(cur)
                except OSError:
                    sftp.mkdir(cur)
            print(f"put {local} -> {host}:{remote}", flush=True)
            sftp.put(str(local), remote)
            uploaded += 1
            meta = local.with_name(f"{local.stem}.meta.json")
            if meta.is_file():
                print(f"put {meta} -> {host}:{remote_dir}/{meta.name}", flush=True)
                sftp.put(str(meta), f"{remote_dir}/{meta.name}")
            legacy_meta = local.with_name("meta.json")
            if legacy_meta.is_file():
                sftp.put(str(legacy_meta), f"{remote_dir}/meta.json")
    finally:
        sftp.close()
        client.close()
    print(f"uploaded={uploaded}", flush=True)
    return 0 if uploaded else 1


if __name__ == "__main__":
    raise SystemExit(main())
