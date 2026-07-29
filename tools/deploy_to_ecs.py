#!/usr/bin/env python3
"""Deploy IgniteQuant from this machine to Aliyun ECS.

Default mode uploads the current working tree (even if uncommitted), preserves
server `.env` + `data/runtime/*.sqlite`, rebuilds the web UI, restarts API.

  python tools/deploy_to_ecs.py
  python tools/deploy_to_ecs.py --restart-sim
  python tools/deploy_to_ecs.py --via-git --restart-sim
  python tools/deploy_to_ecs.py --setup-git-only
  python tools/deploy_to_ecs.py --skip-web

Env (optional; can live in local .env — never commit secrets):
  ECS_HOST=8.159.133.212
  ECS_USER=root
  ECS_PASSWORD=...
  ECS_SSH_KEY=C:/Users/you/.ssh/id_ed25519_ecs
  ECS_PATH=/opt/IgniteQuant
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EXCLUDE_DIR_NAMES = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cursor",
    "agent-transcripts",
    "terminals",
    "apple-design-skill",
    "LLMQuant-skills",
    ".agents",
    "market_cache",
    "dist",
}
EXCLUDE_SUFFIXES = {".pyc", ".xlsx", ".xls", ".zip", ".7z", ".mp4"}
EXCLUDE_NAMES = {
    ".env",
    "falcon_au_sim.sqlite",
    "falcon_au_sim.sqlite-wal",
    "falcon_au_sim.sqlite-shm",
    "falcon_au_sim.pid",
}


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def should_skip(rel: Path) -> bool:
    if any(part in EXCLUDE_DIR_NAMES for part in rel.parts):
        return True
    if rel.name in EXCLUDE_NAMES or rel.name.startswith("tmp_"):
        return True
    if rel.suffix.lower() in EXCLUDE_SUFFIXES:
        return True
    if len(rel.parts) >= 2 and rel.parts[0] == "data" and rel.parts[1] == "runtime":
        if rel.suffix in {".log", ".pid"} or "sqlite" in rel.name:
            return True
    return False


def make_tarball() -> bytes:
    buf = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if should_skip(rel):
                continue
            tar.add(path, arcname=str(rel).replace("\\", "/"))
            count += 1
    data = buf.getvalue()
    print(f"packaged {count} files ({len(data) / 1024 / 1024:.1f} MiB)", flush=True)
    return data


def ssh_connect():
    import paramiko

    host = os.environ.get("ECS_HOST", "8.159.133.212").strip()
    user = os.environ.get("ECS_USER", "root").strip()
    password = os.environ.get("ECS_PASSWORD", "").strip()
    key_path = os.environ.get("ECS_SSH_KEY", "").strip()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs: dict = {
        "hostname": host,
        "username": user,
        "timeout": 40,
        "allow_agent": True,
        "look_for_keys": True,
    }
    if key_path:
        kwargs["key_filename"] = str(Path(key_path).expanduser())
        kwargs["allow_agent"] = False
        kwargs["look_for_keys"] = False
    if password:
        kwargs["password"] = password
        kwargs["allow_agent"] = False
        kwargs["look_for_keys"] = False
    client.connect(**kwargs)
    return client, host


def run_ssh(client, cmd: str, timeout: int = 900) -> int:
    print(f"\n$ {cmd}", flush=True)
    _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace")
    err = stderr.read().decode("utf-8", "replace")
    code = stdout.channel.recv_exit_status()
    text = (out + err).strip()
    if text:
        print(text[-8000:].encode("ascii", "replace").decode("ascii"), flush=True)
    print(f"exit={code}", flush=True)
    return code


def put_text(client, remote: str, content: str) -> None:
    sftp = client.open_sftp()
    with sftp.file(remote, "w") as f:
        f.write(content)
    sftp.close()


def put_bytes(client, remote: str, data: bytes) -> None:
    sftp = client.open_sftp()
    with sftp.file(remote, "wb") as f:
        f.write(data)
    sftp.close()


def ensure_remote_git(client, remote_path: str) -> int:
    script = f"""#!/bin/bash
set -eu
cd "{remote_path}"
if [ ! -d .git ]; then
  git init -b master
  git remote add origin https://github.com/hawk1949-rs/IgniteQuant.git
  git fetch origin master
  git reset --mixed origin/master
  echo GIT_INIT_OK
else
  git remote set-url origin https://github.com/hawk1949-rs/IgniteQuant.git || true
  git fetch origin master
  echo GIT_ALREADY
fi
git rev-parse --abbrev-ref HEAD || true
git rev-parse --short HEAD || true
git status -sb | head -25 || true
exit 0
"""
    put_text(client, "/tmp/iq_setup_git.sh", script)
    return run_ssh(client, "bash /tmp/iq_setup_git.sh", timeout=180)


def rebuild_and_restart(client, remote_path: str, build_web: bool, restart_sim: bool) -> int:
    web = "1" if build_web else "0"
    sim = "1" if restart_sim else "0"
    script = f"""#!/bin/bash
set -euo pipefail
cd "{remote_path}"
.venv/bin/pip install -q -r requirements.txt
if [ "{web}" = "1" ]; then
  cd web
  if [ ! -d node_modules ]; then npm ci; fi
  npx vite build
  cd ..
fi
systemctl restart ignitequant-api
if [ "{sim}" = "1" ]; then
  systemctl restart ignitequant-sim
fi
sleep 4
systemctl is-active ignitequant-api
if [ "{sim}" = "1" ]; then
  systemctl is-active ignitequant-sim
fi
curl -sS -m 10 http://127.0.0.1:8787/api/health
echo
curl -sS -m 10 http://127.0.0.1:8787/api/auth/status
echo
# 有鉴权时 summary 需 Token；这里只做进程探测
if systemctl is-active --quiet ignitequant-sim; then
  echo SIM_ACTIVE
fi
"""
    put_text(client, "/tmp/iq_rebuild.sh", script)
    return run_ssh(client, "bash /tmp/iq_rebuild.sh", timeout=1200)


def deploy_worktree(client, remote_path: str, build_web: bool, restart_sim: bool) -> int:
    data = make_tarball()
    put_bytes(client, "/tmp/ignitequant_deploy.tgz", data)
    extract = f"""#!/bin/bash
set -euo pipefail
cd "{remote_path}"
# never extract over .env; tarball excludes it anyway
tar -xzf /tmp/ignitequant_deploy.tgz
rm -f /tmp/ignitequant_deploy.tgz
mkdir -p data/runtime
echo EXTRACT_OK
"""
    put_text(client, "/tmp/iq_extract.sh", extract)
    code = run_ssh(client, "bash /tmp/iq_extract.sh", timeout=180)
    if code != 0:
        return code
    return rebuild_and_restart(client, remote_path, build_web, restart_sim)


def deploy_via_git(client, remote_path: str, build_web: bool, restart_sim: bool) -> int:
    print("\n== git push origin HEAD:master ==", flush=True)
    push = subprocess.run(
        ["git", "push", "origin", "HEAD:master"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if push.stdout:
        print(push.stdout, flush=True)
    if push.stderr:
        print(push.stderr, flush=True)
    if push.returncode != 0:
        print(
            "ERROR: git push failed. Commit locally first, or use default worktree mode.",
            flush=True,
        )
        return push.returncode

    pull = f"""#!/bin/bash
set -euo pipefail
cd "{remote_path}"
# .env and sqlite are gitignored / excluded — hard reset is OK for tracked files
git fetch origin master
git reset --hard origin/master
echo PULL_OK
git rev-parse --short HEAD
"""
    put_text(client, "/tmp/iq_pull.sh", pull)
    code = run_ssh(client, "bash /tmp/iq_pull.sh", timeout=180)
    if code != 0:
        return code
    return rebuild_and_restart(client, remote_path, build_web, restart_sim)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--via-git",
        action="store_true",
        help="git push then remote reset --hard to origin/master",
    )
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--restart-sim", action="store_true")
    parser.add_argument("--setup-git-only", action="store_true")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    os.environ.setdefault("ECS_HOST", "8.159.133.212")
    os.environ.setdefault("ECS_USER", "root")

    try:
        import paramiko  # noqa: F401
    except ImportError:
        print("ERROR: pip install paramiko", flush=True)
        return 1

    if not os.environ.get("ECS_PASSWORD") and not os.environ.get("ECS_SSH_KEY"):
        print(
            "NOTE: set ECS_PASSWORD or ECS_SSH_KEY in .env for non-interactive deploy",
            flush=True,
        )

    remote_path = os.environ.get("ECS_PATH", "/opt/IgniteQuant").strip()
    client, host = ssh_connect()
    print(f"connected {os.environ.get('ECS_USER', 'root')}@{host}:{remote_path}", flush=True)
    try:
        code = ensure_remote_git(client, remote_path)
        if code != 0:
            return code
        if args.setup_git_only:
            print("\nDone: ECS git attached to GitHub.", flush=True)
            return 0
        build_web = not args.skip_web
        if args.via_git:
            code = deploy_via_git(client, remote_path, build_web, args.restart_sim)
        else:
            code = deploy_worktree(client, remote_path, build_web, args.restart_sim)
        if code == 0:
            print(f"\nOK — http://{host}/#/sim", flush=True)
        return code
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
