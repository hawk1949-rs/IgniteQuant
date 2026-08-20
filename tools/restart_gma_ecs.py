#!/usr/bin/env python3
"""Restart GMA sim processes on ECS after code deploy."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from deploy_to_ecs import load_dotenv, put_text, run_ssh, ssh_connect


def main() -> int:
    load_dotenv(ROOT / ".env")
    remote = os.environ.get("ECS_PATH", "/opt/IgniteQuant").strip()
    script = f"""#!/bin/bash
set -euo pipefail
cd "{remote}"
pkill -f 'strategies/gma_au_sim.py' 2>/dev/null || true
pkill -f 'strategies/gma_v2_sim.py' 2>/dev/null || true
sleep 2
pkill -9 -f 'strategies/gma_au_sim.py' 2>/dev/null || true
pkill -9 -f 'strategies/gma_v2_sim.py' 2>/dev/null || true
sleep 1
export IQ_SIM_ACCOUNT=tqsim
nohup .venv/bin/python strategies/gma_au_sim.py >> data/runtime/gma_au_sim.launch.log 2>&1 &
echo $! > data/runtime/gma_au_sim.pid
nohup .venv/bin/python strategies/gma_v2_sim.py >> data/runtime/gma_v2_au_sim.launch.log 2>&1 &
echo $! > data/runtime/gma_v2_au_sim.pid
sleep 25
echo "=== procs ==="
ps aux | grep -E 'gma_.*sim.py' | grep -v grep || echo none
echo "=== boot markers ==="
grep -E "启动外盘窗口|启动评估|启动补跑|tip=" data/runtime/gma_au_sim.launch.log | tail -20
echo "---"
grep -E "启动外盘窗口|启动评估|启动补跑|tip=" data/runtime/gma_v2_au_sim.launch.log | tail -20
"""
    client, host = ssh_connect()
    try:
        put_text(client, "/tmp/iq_restart_gma2.sh", script)
        print(f"host={host}", flush=True)
        return run_ssh(client, "bash /tmp/iq_restart_gma2.sh", timeout=120)
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
