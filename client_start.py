#!/usr/bin/env python3
"""NexaCrew — CLIENT starter.

Run this file on a CLIENT computer to connect it to the company server:

    python client_start.py --server 192.168.1.50 --port 8600 --key XXXXX-XXXXX-XXXXX-XXXXX

Without arguments it asks interactively (only the first time — afterwards the
saved configuration is reused). It writes platform/data/config.json with
deploy_mode=client and then hands over to start.py, which installs everything
needed, shows the system-tray icon and keeps the connection alive.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "platform" / "data" / "config.json"

# never crash on emoji/symbols under legacy Windows console encodings
for _s in (sys.stdout, sys.stderr):
    try:
        if _s and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError, AttributeError):
        pass


def load_cfg() -> dict:
    try:
        if CONFIG_FILE.is_file():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pass
    return {}


def save_cfg(cfg: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def ask(prompt: str, default: str = "") -> str:
    tip = f" [{default}]" if default else ""
    val = input(f"{prompt}{tip}: ").strip()
    return val or default


def main() -> None:
    ap = argparse.ArgumentParser(description="Start NexaCrew in CLIENT mode.")
    ap.add_argument("--server", help="server IP address (e.g. 192.168.1.50)")
    ap.add_argument("--port", type=int, help="server port (default 8600)")
    ap.add_argument("--key", help="license key XXXXX-XXXXX-XXXXX-XXXXX")
    args = ap.parse_args()

    cfg = load_cfg()
    server = args.server or str(cfg.get("client_server_ip") or "")
    port = args.port or int(cfg.get("client_server_port") or 8600)
    key = (args.key or str(cfg.get("license_key") or "")).strip().upper()

    interactive = sys.stdin.isatty()
    if not server and interactive:
        server = ask("Server IP address")
    if not key and interactive:
        key = ask("License key (XXXXX-XXXXX-XXXXX-XXXXX)").upper()
    if not server:
        print("ERROR: no server IP. Run:  python client_start.py --server <ip> "
              "--port 8600 --key <license-key>")
        sys.exit(2)
    if key and not re.fullmatch(r"[A-F0-9]{5}(-[A-F0-9]{5}){3}", key):
        print(f"WARNING: '{key}' does not look like a license key — saved anyway.")

    cfg.update(deploy_mode="client", client_server_ip=server,
               client_server_port=int(port))
    if key:
        cfg["license_key"] = key
    save_cfg(cfg)
    print(f"✓ Client configuration saved — server {server}:{port}"
          + (f" · key {key}" if key else ""))

    # hand over to the full launcher (venv, dependencies, tray icon, beacon)
    start = ROOT / "start.py"
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, str(start)])


if __name__ == "__main__":
    main()
