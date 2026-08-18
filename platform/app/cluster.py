"""Enterprise clustering: controller/worker roles, LAN auto-discovery and
load-balanced dispatch of agent workloads across multiple servers.

Roles (Settings → Deployment):
  standalone — single server, no clustering (default)
  controller — the master node; workers register here, heavy agent runs are
               load-balanced to the least-busy online worker
  worker     — registers with the controller and executes agent runs on its
               own CPU with its own local CLIs (Codex / Claude Code)

LAN auto-discovery protocol ("MAPSTUDIO-DISCOVER v1"):
  Controllers listen on UDP <discovery_port> (default 8601). Clients broadcast
  a probe and every controller replies with a JSON datagram containing its
  name, host, port and role — so client installs can find the company server
  with one click, no IP typing needed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
import socket
import threading
import time
import urllib.request
import uuid

from .config import get_config

DISCOVER_MAGIC = "MAPSTUDIO-DISCOVER-V1"
NODE_ID = uuid.uuid4().hex[:12]
STARTED_AT = time.time()


def _read_version() -> str:
    try:
        from pathlib import Path
        return (Path(__file__).resolve().parent.parent.parent / "VERSION"
                ).read_text(encoding="utf-8-sig").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = _read_version()


def _ver_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).strip().split("."))
    except ValueError:
        return (0,)


# set by main.py: called when a cluster peer runs a newer version — wakes the
# portal auto-updater immediately so clustered servers converge fast
on_update_available = None

# Controller-side registry: node_id -> node dict
NODES: dict[str, dict] = {}
_NODES_LOCK = threading.Lock()

# Local execution counters (reported in heartbeats; used for load balancing)
_ACTIVE_JOBS = 0
_TOTAL_JOBS = 0
_JOBS_LOCK = threading.Lock()

_THREADS_STARTED = False


# ---------------- local node info ----------------
def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def job_started() -> None:
    global _ACTIVE_JOBS, _TOTAL_JOBS
    with _JOBS_LOCK:
        _ACTIVE_JOBS += 1
        _TOTAL_JOBS += 1


def job_finished() -> None:
    global _ACTIVE_JOBS
    with _JOBS_LOCK:
        _ACTIVE_JOBS = max(0, _ACTIVE_JOBS - 1)


def node_info() -> dict:
    cfg = get_config()
    try:
        import psutil  # optional, richer metrics if installed
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
    except Exception:  # noqa: BLE001
        cpu = mem = None
    return {
        "node_id": NODE_ID,
        "version": APP_VERSION,
        "name": cfg.get("node_name") or socket.gethostname(),
        "host": _local_ip(),
        "port": int(cfg.get("server_port", 8600)),
        "role": cfg.get("cluster_role", "standalone"),
        "os": f"{platform.system()} {platform.release()}",
        "cpu_percent": cpu,
        "mem_percent": mem,
        "cpu_count": os.cpu_count(),
        "gpu_count": _gpu_count(),
        "gpu_names": _gpu_names(),
        "active_jobs": _ACTIVE_JOBS,
        "total_jobs": _TOTAL_JOBS,
        "uptime_s": int(time.time() - STARTED_AT),
    }


def _gpu_count() -> int:
    try:
        from .gpu import detect_gpus
        return len(detect_gpus())
    except Exception:  # noqa: BLE001
        return 0


def _gpu_names() -> str:
    try:
        from .gpu import detect_gpus
        return "; ".join(g["name"] for g in detect_gpus())
    except Exception:  # noqa: BLE001
        return ""


# ---------------- controller: registry ----------------
def register_heartbeat(info: dict) -> None:
    with _NODES_LOCK:
        NODES[info["node_id"]] = {**info, "last_seen": time.time()}


def online_workers() -> list[dict]:
    now = time.time()
    with _NODES_LOCK:
        return [n for n in NODES.values()
                if n.get("role") == "worker" and now - n["last_seen"] < 30]


def cluster_status() -> dict:
    cfg = get_config()
    me = node_info()
    now = time.time()
    with _NODES_LOCK:
        nodes = [{**n, "online": now - n["last_seen"] < 30,
                  "outdated": _ver_tuple(n.get("version") or "0") < _ver_tuple(APP_VERSION),
                  "last_seen_s": int(now - n["last_seen"])} for n in NODES.values()]
    return {"role": cfg.get("cluster_role", "standalone"), "self": me,
            "controller_ip": cfg.get("controller_ip", ""),
            "controller_port": cfg.get("controller_port", 8600),
            "nodes": sorted(nodes, key=lambda n: n["name"])}


# ---------------- worker → controller heartbeat ----------------
def _heartbeat_loop() -> None:
    while True:
        cfg = get_config()
        if cfg.get("cluster_role") == "worker" and cfg.get("controller_ip"):
            url = (f"http://{cfg['controller_ip']}:{cfg.get('controller_port', 8600)}"
                   "/api/cluster/heartbeat")
            try:
                req = urllib.request.Request(
                    url, data=json.dumps(node_info()).encode(),
                    headers={"Content-Type": "application/json",
                             "X-Cluster-Secret": cfg.get("cluster_secret", "")})
                resp = json.loads(urllib.request.urlopen(req, timeout=8).read()
                                  .decode("utf-8", "ignore") or "{}")
                cv = str(resp.get("version") or "")
                if cv and _ver_tuple(cv) > _ver_tuple(APP_VERSION) and on_update_available:
                    on_update_available()  # controller is newer — update now
            except Exception:  # noqa: BLE001 — controller may be down; retry
                pass
        time.sleep(10)


# ---------------- LAN discovery ----------------
def _discovery_responder() -> None:
    """Controllers/standalone servers answer LAN discovery probes."""
    cfg = get_config()
    port = int(cfg.get("discovery_port", 8601))
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("", port))
    except OSError:
        return  # port busy (another instance on this machine answers)
    while True:
        try:
            data, addr = sock.recvfrom(2048)
            if data.decode("utf-8", "ignore").strip() != DISCOVER_MAGIC:
                continue
            cfg = get_config()
            if cfg.get("cluster_role", "standalone") == "worker":
                continue  # only controllers / standalone servers announce
            reply = json.dumps({
                "magic": DISCOVER_MAGIC, "name": cfg.get("node_name") or socket.gethostname(),
                "host": _local_ip(), "port": int(cfg.get("server_port", 8600)),
                "role": cfg.get("cluster_role", "standalone"),
                "product": "Virtual Company AI Agent Platform · MAP Studio",
            }).encode()
            sock.sendto(reply, addr)
        except Exception:  # noqa: BLE001
            time.sleep(1)


def discover_servers(timeout: float = 2.5) -> list[dict]:
    """Broadcast a discovery probe and collect every server that answers."""
    cfg = get_config()
    port = int(cfg.get("discovery_port", 8601))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(0.5)
    found: dict[str, dict] = {}
    targets = ["255.255.255.255", "<broadcast>"]
    # also directed broadcast of the local /24
    ip = _local_ip()
    if ip.count(".") == 3:
        targets.append(".".join(ip.split(".")[:3]) + ".255")
    deadline = time.time() + timeout
    try:
        for t in targets:
            try:
                sock.sendto(DISCOVER_MAGIC.encode(), (t, port))
            except OSError:
                continue
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
                info = json.loads(data.decode("utf-8", "ignore"))
                if info.get("magic") == DISCOVER_MAGIC:
                    info["host"] = info.get("host") or addr[0]
                    info.pop("magic", None)
                    found[f"{info['host']}:{info['port']}"] = info
            except (socket.timeout, ValueError):
                continue
    finally:
        sock.close()
    return list(found.values())


# ---------------- load-balanced remote dispatch ----------------
def remote_run(kind: str, prompt: str, system: str = "",
               allow_write: bool = False) -> str | None:
    """On a controller with online workers, execute the agent run on the
    least-busy worker. Returns the output, or None → caller runs locally."""
    cfg = get_config()
    if cfg.get("cluster_role") != "controller":
        return None
    workers = online_workers()
    if not workers:
        return None
    # Prefer GPU-equipped workers, then least busy, then most CPU cores
    worker = min(workers, key=lambda w: (-(w.get("gpu_count") or 0),
                                         w.get("active_jobs", 0),
                                         -(w.get("cpu_count") or 1)))
    url = f"http://{worker['host']}:{worker['port']}/api/cluster/execute"
    timeout = int(cfg.get("claude_timeout" if kind == "claude" else "codex_timeout", 600))
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"kind": kind, "prompt": prompt, "system": system,
                                  "allow_write": allow_write}).encode(),
            headers={"Content-Type": "application/json",
                     "X-Cluster-Secret": cfg.get("cluster_secret", "")})
        with urllib.request.urlopen(req, timeout=timeout + 30) as resp:
            data = json.loads(resp.read().decode())
        if data.get("ok"):
            return str(data.get("output", ""))
    except Exception:  # noqa: BLE001 — worker failed: fall back to local run
        pass
    return None


# ---------------- startup ----------------
def start_cluster() -> None:
    global _THREADS_STARTED
    if _THREADS_STARTED:
        return
    _THREADS_STARTED = True
    threading.Thread(target=_discovery_responder, daemon=True,
                     name="cluster-discovery").start()
    threading.Thread(target=_heartbeat_loop, daemon=True,
                     name="cluster-heartbeat").start()
