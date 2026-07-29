#!/usr/bin/env python3
"""Upload market_cache / runtime sqlite backups to Aliyun OSS.

Env:
  OSS_ENDPOINT=https://oss-cn-shanghai.aliyuncs.com
  OSS_BUCKET=ignitequant
  OSS_ACCESS_KEY_ID=...
  OSS_ACCESS_KEY_SECRET=...

Usage:
  pip install oss2
  PYTHONPATH=src python tools/sync_files_to_oss.py --status
  PYTHONPATH=src python tools/sync_files_to_oss.py --upload-cache
  PYTHONPATH=src python tools/sync_files_to_oss.py --upload-runtime
  PYTHONPATH=src python tools/sync_files_to_oss.py --all
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
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


def oss_client():
    try:
        import oss2
    except ImportError as exc:
        raise SystemExit("ERROR: pip install oss2") from exc

    endpoint = os.environ.get("OSS_ENDPOINT", "https://oss-cn-shanghai.aliyuncs.com").strip()
    bucket_name = os.environ.get("OSS_BUCKET", "ignitequant").strip()
    key_id = os.environ.get("OSS_ACCESS_KEY_ID", "").strip()
    key_secret = os.environ.get("OSS_ACCESS_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise SystemExit("ERROR: OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET required")

    auth = oss2.Auth(key_id, key_secret)
    return oss2.Bucket(auth, endpoint, bucket_name)


def iter_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    if not root.is_dir():
        return out
    for pat in patterns:
        out.extend(p for p in root.rglob(pat) if p.is_file())
    return sorted(set(out))


def upload_tree(bucket, local_root: Path, prefix: str, patterns: tuple[str, ...]) -> int:
    files = iter_files(local_root, patterns)
    n = 0
    for path in files:
        rel = path.relative_to(local_root).as_posix()
        key = f"{prefix.rstrip('/')}/{rel}"
        print(f"  put {key} ({path.stat().st_size} bytes)", flush=True)
        bucket.put_object_from_file(key, str(path))
        n += 1
    return n


def upload_runtime(bucket, runtime_dir: Path) -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    n = 0
    for name in ("falcon_au_sim.sqlite", "falcon_au_sim.klines.json"):
        path = runtime_dir / name
        if not path.is_file():
            print(f"  skip missing {path}", flush=True)
            continue
        key = f"runtime_backup/{stamp}/{name}"
        print(f"  put {key} ({path.stat().st_size} bytes)", flush=True)
        bucket.put_object_from_file(key, str(path))
        # also refresh "latest" pointer
        latest = f"runtime_backup/latest/{name}"
        bucket.put_object_from_file(latest, str(path))
        n += 2
    return n


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="List a few OSS keys")
    parser.add_argument("--upload-cache", action="store_true")
    parser.add_argument("--upload-runtime", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--cache-dir",
        default=str(ROOT / "data" / "market_cache"),
    )
    parser.add_argument(
        "--runtime-dir",
        default=str(ROOT / "data" / "runtime"),
    )
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")

    if not (args.status or args.upload_cache or args.upload_runtime or args.all):
        parser.error("specify --status / --upload-cache / --upload-runtime / --all")

    bucket = oss_client()
    print(f"OSS bucket={os.environ.get('OSS_BUCKET', 'ignitequant')}", flush=True)

    if args.status:
        print("Listing up to 30 objects…", flush=True)
        try:
            import oss2

            count = 0
            for obj in oss2.ObjectIterator(bucket):
                print(f"  {obj.key}\t{obj.size}", flush=True)
                count += 1
                if count >= 30:
                    print("  …", flush=True)
                    break
            if count == 0:
                bucket.get_bucket_info()
                print("  bucket reachable, empty", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", flush=True)
            return 1

    if args.upload_cache or args.all:
        cache_dir = Path(args.cache_dir)
        print(f"Uploading market_cache from {cache_dir}…", flush=True)
        n = upload_tree(
            bucket,
            cache_dir,
            "market_cache",
            ("*.csv", "*.json", "*.meta.json"),
        )
        print(f"  uploaded {n} files", flush=True)

    if args.upload_runtime or args.all:
        runtime_dir = Path(args.runtime_dir)
        print(f"Uploading runtime backup from {runtime_dir}…", flush=True)
        n = upload_runtime(bucket, runtime_dir)
        print(f"  uploaded {n} objects", flush=True)

    print("OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
