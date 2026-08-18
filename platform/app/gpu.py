"""GPU detection and acceleration policy.

Detects every GPU on this machine (NVIDIA via nvidia-smi, plus generic
detection through WMI on Windows / lspci on Linux / system_profiler on macOS).
If at least one GPU is present, the platform FORCES GPU processing:
subprocesses (Codex CLI, Claude Code CLI, generated Python workloads) are
launched with GPU-enabling environment variables, and generated code is
instructed to use CUDA when available.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import threading
import time

_CACHE: dict = {"at": 0.0, "gpus": None}
_LOCK = threading.Lock()
_IS_WIN = platform.system() == "Windows"
_IS_MAC = platform.system() == "Darwin"


def _run(cmd: list[str], timeout: int = 10) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        return p.stdout or ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _nvidia_gpus() -> list[dict]:
    """Rich detection for NVIDIA GPUs via nvidia-smi."""
    if not shutil.which("nvidia-smi"):
        return []
    out = _run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used,"
                "utilization.gpu,temperature.gpu,driver_version",
                "--format=csv,noheader,nounits"])
    gpus = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 7:
            gpus.append({"index": int(parts[0]), "name": parts[1], "vendor": "NVIDIA",
                         "memory_total_mb": int(float(parts[2])),
                         "memory_used_mb": int(float(parts[3])),
                         "utilization_pct": int(float(parts[4])),
                         "temperature_c": int(float(parts[5])),
                         "driver": parts[6], "cuda": True})
    return gpus


def _generic_gpus() -> list[dict]:
    """Fallback detection for non-NVIDIA GPUs (AMD / Intel / Apple)."""
    gpus: list[dict] = []
    if _IS_WIN:
        out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | "
                    "Select-Object -ExpandProperty Name"], timeout=20)
        names = [l.strip() for l in out.splitlines() if l.strip()]
    elif _IS_MAC:
        out = _run(["system_profiler", "SPDisplaysDataType"], timeout=20)
        names = re.findall(r"Chipset Model:\s*(.+)", out)
    else:
        out = _run(["lspci"], timeout=15)
        names = [m.group(1).strip() for l in out.splitlines()
                 if (m := re.search(r"(?:VGA compatible controller|3D controller):\s*(.+)", l))]
    for i, name in enumerate(names):
        vendor = ("NVIDIA" if "nvidia" in name.lower() else
                  "AMD" if ("amd" in name.lower() or "radeon" in name.lower()) else
                  "Intel" if "intel" in name.lower() else
                  "Apple" if "apple" in name.lower() else "Unknown")
        gpus.append({"index": i, "name": name, "vendor": vendor,
                     "memory_total_mb": None, "memory_used_mb": None,
                     "utilization_pct": None, "temperature_c": None,
                     "driver": None, "cuda": "nvidia" in name.lower()})
    return gpus


def detect_gpus(force_refresh: bool = False) -> list[dict]:
    """All GPUs on this machine (cached for 15 s)."""
    with _LOCK:
        if not force_refresh and _CACHE["gpus"] is not None and time.time() - _CACHE["at"] < 15:
            return _CACHE["gpus"]
        gpus = _nvidia_gpus()
        if not gpus:
            gpus = _generic_gpus()
        else:
            # add non-NVIDIA GPUs that nvidia-smi doesn't see
            seen = {g["name"] for g in gpus}
            gpus += [g for g in _generic_gpus() if g["name"] not in seen and g["vendor"] != "NVIDIA"]
        for g in gpus:
            g.setdefault("index", 0)
        _CACHE.update(at=time.time(), gpus=gpus)
        return gpus


def gpu_summary() -> dict:
    gpus = detect_gpus()
    return {"gpu_count": len(gpus), "gpus": gpus,
            "gpu_enabled": bool(gpus),
            "policy": ("FORCED — all agent subprocesses and generated workloads run "
                       "with GPU acceleration" if gpus else
                       "CPU only — no GPU detected on this machine")}


def gpu_env(base: dict | None = None) -> dict:
    """Environment for subprocesses. If GPUs exist, force GPU usage."""
    env = dict(base if base is not None else os.environ)
    gpus = detect_gpus()
    if not gpus:
        return env
    cuda = [g for g in gpus if g.get("cuda")]
    if cuda:
        env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g["index"]) for g in cuda)
        env["NVIDIA_VISIBLE_DEVICES"] = env["CUDA_VISIBLE_DEVICES"]
    env["MAPSTUDIO_GPU"] = "1"
    env["MAPSTUDIO_GPU_COUNT"] = str(len(gpus))
    env["MAPSTUDIO_GPU_NAMES"] = "; ".join(g["name"] for g in gpus)
    # Common ML frameworks: make sure they don't silently fall back to CPU
    env.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    env.pop("CUDA_DEVICE_ORDER", None)
    return env


def gpu_prompt_directive() -> str:
    """Instruction appended to code-generation prompts to force GPU usage."""
    gpus = detect_gpus()
    if not gpus:
        return ""
    names = ", ".join(g["name"] for g in gpus)
    return ("\n\nHARDWARE POLICY: this server has GPU(s): " + names +
            ". Any generated code that does heavy computation (ML, image/video "
            "processing, data transforms) MUST use GPU acceleration (e.g. CUDA, "
            "torch.device('cuda'), OpenCL) — never fall back to CPU when the GPU "
            "is available.")
