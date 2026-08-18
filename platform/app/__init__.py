"""App package init.

On macOS/Linux, processes launched from the GUI, launchd or as a service get a
minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin), so Homebrew, nvm-managed Node and
the VS Code CLI are invisible to shutil.which(). Add the standard tool
locations to PATH before any module performs detection.
"""

import os
from pathlib import Path


def _augment_path() -> None:
    if os.name == "nt":
        return
    extra: list[str] = [
        "/opt/homebrew/bin", "/opt/homebrew/sbin",          # Homebrew (Apple Silicon)
        "/usr/local/bin", "/usr/local/sbin",                # Homebrew (Intel) / npm -g
        "/Applications/Visual Studio Code.app/Contents/Resources/app/bin",  # `code` CLI
    ]
    # Per-user tool dirs — scan all homes because the server may run as root.
    # Every probe is wrapped: a service account (e.g. systemd user `nexacrew`)
    # may lack permission to stat other users' homes, and PATH augmentation
    # must NEVER be fatal to server startup.
    homes = [Path.home()]
    for root in (Path("/Users"), Path("/home")):
        try:
            if root.is_dir():
                homes += [p for p in root.iterdir() if p.is_dir()]
        except OSError:
            pass
    for home in homes:
        try:
            node_versions = home / ".nvm" / "versions" / "node"
            if node_versions.is_dir():
                bins = sorted(node_versions.glob("*/bin"), reverse=True)
                if bins:
                    extra.append(str(bins[0]))              # newest nvm Node
        except OSError:
            pass                                            # unreadable home — skip
        extra.append(str(home / ".local" / "bin"))          # pipx / native installers
        extra.append(str(home / "Applications" / "Visual Studio Code.app"
                          / "Contents" / "Resources" / "app" / "bin"))
    cur = os.environ.get("PATH", "").split(os.pathsep)
    add = []
    for d in extra:
        try:
            if d not in cur and Path(d).is_dir():
                add.append(d)
        except OSError:
            pass
    if add:
        os.environ["PATH"] = os.pathsep.join([p for p in cur if p] + add)


try:
    _augment_path()
except Exception:  # noqa: BLE001 — best-effort PATH help must never block startup
    pass
