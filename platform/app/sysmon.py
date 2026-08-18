"""System status monitor — real-time CPU, GPU, RAM and network telemetry.

Enterprise-grade monitoring for the platform itself and the whole host:
  * process-level: CPU%, RSS memory, threads, open files, child processes
    (agent CLI subprocesses are included in the totals)
  * host-level: per-core CPU, load average, RAM, swap, disks
  * GPU: reuses app.gpu detection (utilization / VRAM / temperature)
  * network: host bandwidth (up/down bit-rate) + bytes served by this app
A background sampler keeps a rolling 5-minute history (1 sample/second)
so the dashboard can draw live charts.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

try:
    import psutil
except ImportError:  # graceful degradation
    psutil = None

_PROC = psutil.Process(os.getpid()) if psutil else None
_HISTORY: deque = deque(maxlen=300)  # 5 min at 1 Hz
_LOCK = threading.Lock()
_STARTED = False

# App-level traffic counters (fed by the HTTP middleware)
_APP_NET = {"bytes_in": 0, "bytes_out": 0, "requests": 0}
_APP_NET_LOCK = threading.Lock()


def track_request(bytes_in: int, bytes_out: int) -> None:
    with _APP_NET_LOCK:
        _APP_NET["bytes_in"] += max(0, bytes_in)
        _APP_NET["bytes_out"] += max(0, bytes_out)
        _APP_NET["requests"] += 1


def _process_tree_stats() -> dict:
    """CPU% / RSS for this process plus all children (agent CLIs)."""
    if not _PROC:
        return {"cpu_percent": None, "rss_mb": None, "threads": None,
                "children": 0, "open_files": None}
    cpu = rss = 0.0
    threads = children = 0
    try:
        procs = [_PROC] + _PROC.children(recursive=True)
        children = len(procs) - 1
        for p in procs:
            try:
                cpu += p.cpu_percent(interval=None)
                rss += p.memory_info().rss
                threads += p.num_threads()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    try:
        if os.name == "nt":
            # NEVER use open_files() on Windows: psutil's NtQueryObject call can
            # deadlock forever on named-pipe handles (created by agent CLI
            # subprocesses), freezing thread creation for the whole process and
            # hanging the server. num_handles() is a fast, safe kernel counter.
            open_files = _PROC.num_handles()
        else:
            open_files = len(_PROC.open_files())
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, AttributeError):
        open_files = None
    ncpu = os.cpu_count() or 1
    return {"cpu_percent": round(min(cpu, 100.0 * ncpu), 1), "rss_mb": round(rss / 1048576, 1),
            "threads": threads, "children": children, "open_files": open_files}


def _sample() -> dict:
    now = time.time()
    s: dict = {"t": now}
    if psutil:
        s["cpu_total"] = psutil.cpu_percent(interval=None)
        s["cpu_per_core"] = psutil.cpu_percent(interval=None, percpu=True)
        vm = psutil.virtual_memory()
        s["ram_used_mb"] = round((vm.total - vm.available) / 1048576)
        s["ram_total_mb"] = round(vm.total / 1048576)
        s["ram_percent"] = vm.percent
        sw = psutil.swap_memory()
        s["swap_percent"] = sw.percent
        io = psutil.net_io_counters()
        s["net_sent"] = io.bytes_sent
        s["net_recv"] = io.bytes_recv
        try:
            la = os.getloadavg()
            s["load_avg"] = [round(x, 2) for x in la]
        except (AttributeError, OSError):
            s["load_avg"] = None
    s["proc"] = _process_tree_stats()
    with _APP_NET_LOCK:
        s["app_net"] = dict(_APP_NET)
    return s


def _sampler_loop() -> None:
    if psutil:
        psutil.cpu_percent(interval=None)  # prime the counters
        if _PROC:
            _PROC.cpu_percent(interval=None)
    while True:
        try:
            with _LOCK:
                _HISTORY.append(_sample())
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)


def start_monitor() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    threading.Thread(target=_sampler_loop, daemon=True, name="sys-monitor").start()


def _rate(new: dict, old: dict, key: str) -> float:
    """bytes/second between two samples."""
    dt_ = new["t"] - old["t"]
    if dt_ <= 0:
        return 0.0
    return max(0.0, (new.get(key, 0) - old.get(key, 0)) / dt_)


def status_snapshot() -> dict:
    """Current status + rolling history for charts."""
    with _LOCK:
        hist = list(_HISTORY)
    if not hist:
        hist = [_sample()]
    cur = hist[-1]
    prev = hist[-2] if len(hist) > 1 else cur

    net_up_bps = _rate(cur, prev, "net_sent") if psutil else 0.0
    net_down_bps = _rate(cur, prev, "net_recv") if psutil else 0.0
    app_prev, app_cur = prev.get("app_net", {}), cur.get("app_net", {})
    dt_ = max(cur["t"] - prev["t"], 1e-6)
    app_up_bps = max(0.0, (app_cur.get("bytes_out", 0) - app_prev.get("bytes_out", 0)) / dt_)
    app_down_bps = max(0.0, (app_cur.get("bytes_in", 0) - app_prev.get("bytes_in", 0)) / dt_)

    try:
        from .gpu import detect_gpus
        gpus = detect_gpus()
    except Exception:  # noqa: BLE001
        gpus = []

    disks = []
    if psutil:
        for part in psutil.disk_partitions(all=False):
            try:
                du = psutil.disk_usage(part.mountpoint)
                disks.append({"mount": part.mountpoint, "total_gb": round(du.total / 2**30, 1),
                              "used_gb": round(du.used / 2**30, 1), "percent": du.percent})
            except (PermissionError, OSError):
                continue

    # compact history series for charts (last 120 s)
    series = [{"t": h["t"],
               "cpu": h.get("cpu_total"),
               "ram": h.get("ram_percent"),
               "proc_cpu": (h.get("proc") or {}).get("cpu_percent"),
               "proc_rss": (h.get("proc") or {}).get("rss_mb"),
               "up": _rate(h, hist[i - 1], "net_sent") if i > 0 else 0,
               "down": _rate(h, hist[i - 1], "net_recv") if i > 0 else 0}
              for i, h in enumerate(hist[-120:])]

    return {
        "available": psutil is not None,
        "host": {
            "cpu_total": cur.get("cpu_total"),
            "cpu_per_core": cur.get("cpu_per_core"),
            "cpu_count": os.cpu_count(),
            "load_avg": cur.get("load_avg"),
            "ram_used_mb": cur.get("ram_used_mb"),
            "ram_total_mb": cur.get("ram_total_mb"),
            "ram_percent": cur.get("ram_percent"),
            "swap_percent": cur.get("swap_percent"),
            "disks": disks,
        },
        "process": cur.get("proc", {}),
        "gpus": gpus,
        "network": {
            "host_up_bps": round(net_up_bps),
            "host_down_bps": round(net_down_bps),
            "app_up_bps": round(app_up_bps),
            "app_down_bps": round(app_down_bps),
            "app_bytes_in": app_cur.get("bytes_in", 0),
            "app_bytes_out": app_cur.get("bytes_out", 0),
            "app_requests": app_cur.get("requests", 0),
        },
        "series": series,
    }
