"""Operating-system compatibility layer.

NexaCrew supports old operating systems down to Windows 7 and
macOS 10.8 Mountain Lion. Each OS gets a *tier* that decides which tools
are installed and how AI prompts are executed:

  full            Win 10/11, macOS 10.15+, Linux
                  → Codex CLI + Claude Code CLI + VS Code (Copilot)
  legacy_copilot  macOS 10.13 High Sierra / 10.14 Mojave
                  → Codex/Claude CLIs DON'T run (need newer Node/OS).
                    Prompts are relayed to GitHub Copilot inside VS Code
                    1.85 (the last build for 10.13) via the Copilot relay.
  legacy_api      Windows 7/8/8.1, macOS 10.8–10.12
                  → no modern CLIs and no VS Code. AI runs through the
                    configured AI APIs (Settings → AI APIs); Python 3.4–3.9
                    and Node 12/13 max are installed automatically.
  unsupported     older than Windows 7 / macOS 10.8
                  → installation is refused up-front.

MINIMUM REQUIREMENT (shown in Setup): Windows 7 SP1 / macOS 10.8
Mountain Lion / any Linux with glibc 2.17+, Python 3.4+, 2 GB RAM,
2 GB free disk.

For testing, the environment variable NEXACREW_SIMULATE_OS overrides
detection (values: mountain_lion, high_sierra, win7, win10, linux) — this
is how the High-Sierra relay path is proven in the test-suite simulator.
"""

from __future__ import annotations

import os
import platform

MIN_REQUIREMENTS = {
    "windows": "Windows 7 SP1 (64-bit)",
    "macos": "macOS 10.8 Mountain Lion",
    "linux": "Any distribution with glibc 2.17+ (CentOS 7 / Ubuntu 14.04 or newer)",
    "python": "3.4 or newer (installed automatically)",
    "ram": "2 GB",
    "disk": "2 GB free",
}

# tool versions compatible with each OS tier
TOOL_MATRIX = {
    "full": {
        "python": "3.12", "node": "20 LTS", "vscode": "latest",
        "codex_cli": True, "claude_cli": True,
        "office": "LibreOffice latest",
        "ai_strategy": "cli",   # native Codex/Claude CLIs
    },
    "legacy_copilot": {
        "python": "3.8 (High Sierra) / 3.9 (Mojave)", "node": "16 LTS max",
        "vscode": "1.85.2 (last build for macOS 10.13/10.14)",
        "codex_cli": False, "claude_cli": False,
        "office": "LibreOffice 7.6 max",
        "ai_strategy": "copilot_relay",   # prompts go to Copilot in VS Code
    },
    "legacy_api": {
        "python": "3.4–3.9 (newest the OS supports)",
        "node": "13.14 max (Win7) / 12 max (macOS 10.8–10.12)",
        "vscode": None,   # not installable
        "codex_cli": False, "claude_cli": False,
        "office": "LibreOffice 6.4 max (Win7) / 4.x (macOS 10.8)",
        "ai_strategy": "api",   # Settings → AI APIs only
    },
    "unsupported": {
        "python": None, "node": None, "vscode": None,
        "codex_cli": False, "claude_cli": False, "office": None,
        "ai_strategy": None,
    },
}

_SIM_PROFILES = {
    "mountain_lion": ("Darwin", "10.8.5"),
    "high_sierra": ("Darwin", "10.13.6"),
    "mojave": ("Darwin", "10.14.6"),
    "catalina": ("Darwin", "10.15.7"),
    "win7": ("Windows", "6.1.7601"),
    "win8": ("Windows", "6.2.9200"),
    "win10": ("Windows", "10.0.19045"),
    "linux": ("Linux", "5.15"),
}


def _detect_raw() -> "tuple[str, str]":
    sim = os.environ.get("NEXACREW_SIMULATE_OS", "").strip().lower()
    if sim in _SIM_PROFILES:
        return _SIM_PROFILES[sim]
    system = platform.system()
    if system == "Darwin":
        return system, platform.mac_ver()[0] or "10.15"
    if system == "Windows":
        return system, platform.version() or "10.0"
    return system, platform.release()


def _ver(v: str) -> "tuple[int, ...]":
    out = []
    for part in v.split(".")[:3]:
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def detect() -> dict:
    """Full compatibility profile for the current (or simulated) OS."""
    system, version = _detect_raw()
    tier = "full"
    label = f"{system} {version}"
    if system == "Darwin":
        mv = _ver(version)
        label = f"macOS {version}"
        if mv < (10, 8):
            tier = "unsupported"
        elif mv < (10, 13):
            tier = "legacy_api"       # Mountain Lion … Sierra
        elif mv < (10, 15):
            tier = "legacy_copilot"   # High Sierra / Mojave
    elif system == "Windows":
        wv = _ver(version)
        label = f"Windows ({version})"
        if wv < (6, 1):
            tier = "unsupported"      # Vista/XP
        elif wv < (10, 0):
            tier = "legacy_api"       # 7 / 8 / 8.1
    # Linux → full (package manager provides suitable versions)
    profile = dict(TOOL_MATRIX[tier])
    return {
        "system": system, "version": version, "label": label, "tier": tier,
        "supported": tier != "unsupported",
        "tools": profile,
        "ai_strategy": profile["ai_strategy"],
        "min_requirements": MIN_REQUIREMENTS,
        "simulated": bool(os.environ.get("NEXACREW_SIMULATE_OS")),
    }


def refuse_message(info: dict) -> str:
    return (
        f"❌ {info['label']} is BELOW the minimum requirement — installation refused "
        "to prevent issues.\n"
        f"Minimum: {MIN_REQUIREMENTS['windows']} · {MIN_REQUIREMENTS['macos']} · "
        f"{MIN_REQUIREMENTS['linux']}\n"
        f"Python {MIN_REQUIREMENTS['python']} · RAM {MIN_REQUIREMENTS['ram']} · "
        f"Disk {MIN_REQUIREMENTS['disk']}"
    )
