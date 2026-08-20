#!/usr/bin/env python3
"""Inspect GMA domestic/overseas chart overlay payloads on ECS."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from deploy_to_ecs import load_dotenv, put_text, run_ssh, ssh_connect

REMOTE = r'''
import json
from pathlib import Path
from urllib import request

def load_env():
    user = pwd = "admin"
    p = Path(".env")
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("COCKPIT_USER="):
                user = line.split("=", 1)[1].strip().strip('"').strip("'")
            if line.startswith("COCKPIT_PASSWORD="):
                pwd = line.split("=", 1)[1].strip().strip('"').strip("'")
    return user, pwd

user, pwd = load_env()
body = json.dumps({"username": user, "password": pwd}).encode()
req = request.Request(
    "http://127.0.0.1:8787/api/auth/login",
    data=body,
    headers={"Content-Type": "application/json"},
)
tok = json.load(request.urlopen(req, timeout=15))["token"]
H = {"Authorization": f"Bearer {tok}"}

def get(url):
    r = request.Request(url, headers=H)
    return json.load(request.urlopen(r, timeout=90))

for iid in ["gma_au_sim", "gma_v2_au_sim", "falcon_au_sim"]:
    print("=" * 24, iid)
    bars = get(f"http://127.0.0.1:8787/api/sim/sessions/{iid}/bars?limit=80")
    ov = bars.get("overlays") or {}
    specs = bars.get("overlay_specs") or []
    meta = bars.get("bar_meta") or []
    candle_tip = (bars.get("bars") or [{}])[-1]
    print("candle tip", {k: candle_tip.get(k) for k in ("time", "close", "open")})
    print("specs", [(s.get("key"), s.get("label"), s.get("pane")) for s in specs])
    print("overlay lens", {k: len(v or []) for k, v in ov.items()})
    for k, pts in ov.items():
        if pts:
            print(f"  {k}: first={pts[0]} last={pts[-1]}")
    if meta:
        last = meta[-1]
        print(
            "meta last",
            {
                k: last.get(k)
                for k in (
                    "time",
                    "signal",
                    "regime",
                    "gma_fast",
                    "gma_slow",
                    "gma_mid",
                    "gma_poc",
                    "ma7",
                    "ma14",
                    "ma52",
                    "close",
                )
            },
        )
    print("chart_context", bars.get("chart_context"))
    osb = get(
        f"http://127.0.0.1:8787/api/sim/overseas/bars?symbol_id=au&limit=80&instance_id={iid}"
    )
    oov = osb.get("overlays") or {}
    oc = (osb.get("bars") or [{}])[-1]
    print("overseas candle tip", {k: oc.get(k) for k in ("time", "close")})
    print(
        "overseas specs",
        [(s.get("key"), s.get("label")) for s in (osb.get("overlay_specs") or [])],
    )
    print("overseas overlay lens", {k: len(v or []) for k, v in oov.items()})
    for k, pts in oov.items():
        if pts:
            print(f"  os {k}: last={pts[-1]}")
    ometa = osb.get("bar_meta") or []
    if ometa:
        last = ometa[-1]
        print(
            "os meta last",
            {
                k: last.get(k)
                for k in (
                    "time",
                    "gma_fast",
                    "gma_slow",
                    "gma_mid",
                    "gma_poc",
                    "ma7",
                    "signal",
                    "regime",
                )
            },
        )
'''


def main() -> int:
    load_dotenv(ROOT / ".env")
    remote = os.environ.get("ECS_PATH", "/opt/IgniteQuant").strip()
    client, _ = ssh_connect()
    try:
        put_text(client, "/tmp/iq_viz_gma.py", REMOTE)
        return run_ssh(client, f"cd {remote} && .venv/bin/python /tmp/iq_viz_gma.py", timeout=120)
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
