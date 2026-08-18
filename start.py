#!/usr/bin/env python3
"""Cross-platform launcher for the Virtual Company AI Agent Platform.

Works on Windows, Linux and macOS (macOS High Sierra 10.13 or newer):
  1. Verifies Python >= 3.9 (prefers 3.12+; offers automatic install via
     winget / brew / apt / dnf when no suitable Python exists).
  2. Creates a virtual environment if missing.
  3. Automatically installs any missing Python libraries (requirements.txt).
  4. Starts the server and opens the web UI in the browser.

Usage:  python start.py [option]

Options:
  (none)        normal start (install/verify environment, run server or client)
  --update      update this install to the newest version (client: from server;
                server: refresh dependencies) and restart
  --restart     restart the program (server + widgets)
  --stop        stop the program and every related process in memory
  --repair      verify & repair the install (venv, dependencies, database),
                then restart
  --status      show CPU / GPU / memory / network usage and program health
  --showclients show connected clients (administrators, server side only)
  --console-setup open the full-screen console configuration wizard (TUI with
                tabs, arrow keys and mouse — ideal for headless Linux servers)
  --console-manage open the full-screen console SERVER MANAGEMENT cockpit
                (dashboard, companies, users, skills, clients, approvals,
                schedules, config, audit — keyboard + mouse, like the web UI)
"""

from __future__ import annotations

import os
import json
import platform
import shutil
import subprocess
import sys
import time
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLATFORM_DIR = ROOT / "platform"
REQS = PLATFORM_DIR / "requirements.txt"
CONFIG_FILE = PLATFORM_DIR / "data" / "config.json"

# Windows consoles default to cp1252/cp437 which cannot encode the emoji /
# symbols used in our log lines — a single log() call then raises
# UnicodeEncodeError and kills the process (this broke client startups).
# Reconfigure stdio to UTF-8 with replacement, never crash on printing.
for _s in (sys.stdout, sys.stderr):
    try:
        if _s and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError, AttributeError):
        pass


def _augment_path() -> None:
    """GUI-launched processes on macOS/Linux get a minimal PATH missing
    Homebrew / MacPorts / nvm / npm-global — add the standard locations so
    brew, node, npm etc. are found even when launched from Finder/desktop."""
    if os.name == "nt":
        return
    home = Path.home()
    extra = ["/opt/homebrew/bin", "/opt/homebrew/sbin",
             "/usr/local/bin", "/usr/local/sbin", "/opt/local/bin",
             str(home / ".local" / "bin"), str(home / "bin"),
             str(home / ".npm-global" / "bin"), "/snap/bin"]
    nvm = home / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        try:
            extra.extend(str(v / "bin") for v in sorted(nvm.iterdir(), reverse=True)
                         if (v / "bin").is_dir())
        except OSError:
            pass
    cur = os.environ.get("PATH", "").split(os.pathsep)
    add = [p for p in extra if p not in cur and Path(p).is_dir()]
    if add:
        os.environ["PATH"] = os.pathsep.join(cur + add)


_augment_path()


def load_deploy_config() -> dict:
    """Deployment settings from platform/data/config.json (web UI → Settings)."""
    cfg = {"deploy_mode": "server", "server_port": 8600, "server_bind": "0.0.0.0",
           "client_server_ip": "", "client_server_port": 8600, "license_key": ""}
    try:
        if CONFIG_FILE.is_file():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
            cfg.update({k: data[k] for k in cfg if k in data})
    except (OSError, ValueError):
        pass
    return cfg


def server_alive(ip: str, port: int, timeout: float = 5.0) -> bool:
    """Probe the company server's health endpoint."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{ip}:{port}/api/health", timeout=timeout) as r:
            return json.loads(r.read().decode()).get("ok") is True
    except Exception:  # noqa: BLE001
        return False


def refresh_backup(ip: str, port: int, backup_file: Path) -> None:
    """Download the latest settings backup from the server (at setup and on
    every start/login) so this client can run standalone if the server dies."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{ip}:{port}/api/client-backup", timeout=10) as r:
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            backup_file.write_bytes(r.read())
        log("Settings backup refreshed from the server ✓")
    except Exception as e:  # noqa: BLE001
        log(f"Could not refresh the settings backup: {e}")


# ---------------- version check & automatic update ----------------
def local_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _ver_tuple(v: str) -> tuple:
    parts = []
    for p in v.split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts + [0] * (3 - len(parts)))


def server_version(ip: str, port: int) -> str:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{ip}:{port}/api/version", timeout=5) as r:
            return json.loads(r.read().decode()).get("version", "0.0.0")
    except Exception:  # noqa: BLE001
        return ""


def auto_update(ip: str, port: int, key: str) -> bool:
    """When the server runs a newer version, download the program package and
    update this install in place (user data / config / venv are preserved).
    Returns True when an update was applied."""
    import io
    import socket
    import urllib.parse
    import urllib.request
    import zipfile

    sv = server_version(ip, port)
    lv = local_version()
    if not sv or _ver_tuple(sv) <= _ver_tuple(lv):
        if sv:
            log(f"Program is up to date (client {lv} / server {sv}) ✓")
        return False
    log(f"⚠ Client version {lv} is older than server version {sv} — updating automatically…")
    if not key:
        log("No license key in config — cannot download the update package. "
            "Add \"license_key\" to platform/data/config.json.")
        return False
    url = (f"http://{ip}:{port}/api/client-package?key="
           + urllib.parse.quote(key.strip().upper())
           + "&host=" + urllib.parse.quote(socket.gethostname()))
    try:
        payload = b""
        for attempt in (1, 2):
            with urllib.request.urlopen(url, timeout=120) as r:
                payload = r.read()
            if zipfile.is_zipfile(io.BytesIO(payload)):
                break
            if attempt == 1:
                log("Update package incomplete — the server may still be building "
                    "it; retrying in 5 s…")
                time.sleep(5)
            else:
                log("Automatic update failed: downloaded package is corrupted — "
                    "will retry on the next heartbeat.")
                return False
        keep = ("platform/data/", ".venv/", ".venv-linux/", ".venv-mac/", "platform/data\\")
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            for info in z.infolist():
                rel = info.filename.replace("\\", "/")
                if info.is_dir() or rel.startswith(keep):
                    continue
                dest = ROOT / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(info))
        log(f"Updated to version {server_version(ip, port) or sv} ✓ "
            "(user data and settings were preserved)")
        return True
    except Exception as e:  # noqa: BLE001
        log(f"Automatic update failed: {e} — continuing with the current version.")
        return False

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


def run_presence_beacon(port: int = 8600, server_ip: str = "", server_port: int = 8600,
                        license_key: str = "") -> None:
    """Minimal local HTTP server on 127.0.0.1 answering /api/health so the
    company website can detect that the client program is installed here.
    Also sends a heartbeat to the company server every 30 s so the server's
    Clients list shows this machine as connected.
    Blocks until Ctrl+C (used in client mode while agents run on the server)."""
    import http.server
    import socket
    import threading
    import urllib.parse
    import urllib.request

    state = {"key": (license_key or "").strip()}

    def current_key() -> str:
        """License key, re-read from config.json so a key applied after start
        (tray widget, web page, manual edit) works without restarting."""
        if not state["key"]:
            fresh = str(load_deploy_config().get("license_key") or "").strip()
            if fresh:
                state["key"] = fresh
                log(f"🔑 License key detected in config: {fresh}")
        return state["key"]

    def save_key(key: str) -> None:
        """Persist the license key into platform/data/config.json."""
        data = {}
        try:
            if CONFIG_FILE.is_file():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        data["license_key"] = key
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        state["key"] = key
        log(f"🔑 License key saved to config: {key}")

    def _applied_config_rev() -> int:
        try:
            if CONFIG_FILE.is_file():
                return int(json.loads(
                    CONFIG_FILE.read_text(encoding="utf-8-sig")
                ).get("remote_config_rev") or 0)
        except (OSError, ValueError):
            pass
        return 0

    def _apply_remote_config(cfg: dict, rev: int) -> None:
        """Merge an admin-pushed configuration into config.json and restart
        so every setting takes effect immediately."""
        data = {}
        try:
            if CONFIG_FILE.is_file():
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            data = {}
        for k, v in cfg.items():
            if k in ("license_key", "deploy_mode"):
                continue
            data[k] = v
        data["remote_config_rev"] = rev
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        log(f"⚙ Remote configuration rev {rev} applied from the server "
            f"({', '.join(sorted(cfg.keys()))}) — restarting to take effect…")
        os.execv(sys.executable, [sys.executable, *sys.argv])

    def _local_metrics() -> dict:
        try:
            import psutil  # noqa: PLC0415
            return {"cpu": psutil.cpu_percent(interval=None),
                    "ram": psutil.virtual_memory().percent}
        except Exception:  # noqa: BLE001
            return {}

    _hw_cache: dict = {}

    def _hw_inventory() -> dict:
        """Hardware identity of THIS computer, reported to the server and
        recorded against the license: MAC address of the network card that
        actually connects to the server, OS, CPU serial, system-disk serial
        and the local IP. Collected once (slow OS calls), then cached."""
        if _hw_cache:
            return _hw_cache
        hw: dict = {"os": f"{platform.system()} {platform.release()}",
                    "device_type": "desktop"}
        # local IP of the interface routed to the server + its MAC address
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((server_ip, server_port))
            hw["ip"] = s.getsockname()[0]
            s.close()
        except OSError:
            hw["ip"] = ""
        try:
            import psutil  # noqa: PLC0415
            for nic, addrs in psutil.net_if_addrs().items():
                ips = [a.address for a in addrs if a.family == socket.AF_INET]
                if hw["ip"] and hw["ip"] in ips:
                    for a in addrs:
                        if a.family == psutil.AF_LINK and a.address:
                            hw["mac"] = a.address.replace("-", ":").upper()
                            hw["nic"] = nic
                    break
        except Exception:  # noqa: BLE001
            pass
        if not hw.get("mac"):   # fallback: primary MAC via uuid
            try:
                import uuid as _uuid
                n = _uuid.getnode()
                hw["mac"] = ":".join(f"{(n >> i) & 0xFF:02X}" for i in range(40, -1, -8))
            except Exception:  # noqa: BLE001
                hw["mac"] = ""

        def _cmd(args: list) -> str:
            try:
                import subprocess  # noqa: PLC0415
                flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
                out = subprocess.run(args, capture_output=True, text=True,
                                     timeout=20, creationflags=flags).stdout
                return (out or "").strip()
            except Exception:  # noqa: BLE001
                return ""

        sysname = platform.system()
        if sysname == "Windows":
            cpu = _cmd(["powershell", "-NoProfile", "-Command",
                        "(Get-CimInstance Win32_Processor).ProcessorId"])
            hw["cpu_serial"] = cpu.splitlines()[0].strip() if cpu else ""
            disks = _cmd(["powershell", "-NoProfile", "-Command",
                "(Get-CimInstance Win32_DiskDrive | Sort-Object Index | "
                "Select-Object -First 1).SerialNumber"])
            hw["disk_serial"] = disks.splitlines()[0].strip() if disks else ""
        elif sysname == "Darwin":
            out = _cmd(["system_profiler", "SPHardwareDataType"])
            for line in out.splitlines():
                if "Serial Number" in line:
                    hw["cpu_serial"] = line.split(":", 1)[-1].strip()
            hw["disk_serial"] = _cmd(["/bin/sh", "-c",
                "diskutil info disk0 | awk -F': *' '/Device \\/ Media Name|Volume UUID/{print $2; exit}'"])
        else:   # Linux
            for p in ("/sys/class/dmi/id/product_serial", "/etc/machine-id"):
                try:
                    v = Path(p).read_text(encoding="utf-8", errors="ignore").strip()
                    if v and v.lower() not in ("none", "to be filled by o.e.m."):
                        hw["cpu_serial"] = v
                        break
                except OSError:
                    continue
            hw["disk_serial"] = _cmd(["/bin/sh", "-c",
                "lsblk -dno SERIAL $(findmnt -no SOURCE / | sed 's/[0-9]*$//') 2>/dev/null | head -1"])
        hw.setdefault("cpu_serial", "")
        hw.setdefault("disk_serial", "")
        _hw_cache.update(hw)
        log(f"🪪 Hardware identity: MAC {hw.get('mac') or '?'} · IP {hw.get('ip') or '?'} "
            f"· CPU {hw.get('cpu_serial') or '?'} · DISK {hw.get('disk_serial') or '?'}")
        return _hw_cache

    def _fetch_delivered_files(files: list, key: str) -> None:
        """Download files the agents generated on the server to THIS computer,
        saving each to the path the user asked for (fallback: ~/Desktop)."""
        for f in files:
            try:
                url = (f"http://{server_ip}:{server_port}/api/client/file"
                       f"?key={urllib.parse.quote(key)}&id={urllib.parse.quote(str(f.get('id')))}")
                data = urllib.request.urlopen(url, timeout=60).read()
                dest = Path(os.path.expandvars(str(f.get("dest") or "")))
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                except OSError:
                    dest = Path.home() / "Desktop" / (f.get("name") or "generated.bin")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(data)
                log(f"📥 File delivered from server → {dest}")
            except Exception as e:  # noqa: BLE001
                log(f"⚠ File delivery failed ({f.get('name')}): {e}")

    def heartbeat_loop() -> None:
        if not server_ip:
            return
        url = f"http://{server_ip}:{server_port}/api/client/heartbeat"
        announced = warned = False
        while True:
            key = current_key()
            if not key:
                if not warned:
                    log("⏳ Waiting for a license key — verify one on the company "
                        "website or add \"license_key\" to platform/data/config.json "
                        "(it is picked up automatically, no restart needed).")
                    warned = True
                time.sleep(10)
                continue
            try:
                payload = json.dumps({"key": key,
                                      "hostname": socket.gethostname(),
                                      "version": local_version(),
                                      "os": f"{platform.system()} {platform.release()}",
                                      "config_rev": _applied_config_rev(),
                                      "hw": _hw_inventory(),
                                      "metrics": _local_metrics()}).encode()
                req = urllib.request.Request(
                    url, data=payload, headers={"Content-Type": "application/json"})
                resp = json.loads(urllib.request.urlopen(req, timeout=10).read() or b"{}")
                if not announced:
                    log(f"💓 Heartbeat OK → server sees this client as online ({url})")
                    announced = True
                # forced update: the server compares our reported version with
                # its own and commands an update when we are older
                sv = str(resp.get("server_version") or "")
                if resp.get("update_required") or (
                        sv and _ver_tuple(sv) > _ver_tuple(local_version())):
                    log(f"⬆ Server requires v{sv} (local v{local_version()}) — "
                        "forced update starting…")
                    if auto_update(server_ip, server_port, key):
                        log("♻ Update installed — restarting the client program…")
                        os.execv(sys.executable, [sys.executable, *sys.argv])
                # remote configuration pushed by an administrator
                cfg = resp.get("config")
                rev = int(resp.get("config_rev") or 0)
                if isinstance(cfg, dict) and cfg and rev > _applied_config_rev():
                    _apply_remote_config(cfg, rev)
                # generated files produced on the server for this computer
                files = resp.get("files")
                if isinstance(files, list) and files:
                    _fetch_delivered_files(files, key)
            except Exception as e:  # noqa: BLE001 — server may be briefly down
                if not announced:
                    log(f"⚠ Heartbeat failed ({e}) — retrying every 30 s")
            time.sleep(30)

    threading.Thread(target=heartbeat_loop, daemon=True).start()

    def do_background_update() -> None:
        """Triggered by the web page: update in the background via Python
        (no file downloads in the browser), then restart this program."""
        log("⬆ Update requested from the web page — updating in the background…")
        if auto_update(server_ip, server_port, current_key()):
            log("♻ Update installed — restarting the client program…")
            os.execv(sys.executable, [sys.executable, *sys.argv])
        else:
            log("Update request finished — already up to date or update failed.")

    class Handler(http.server.BaseHTTPRequestHandler):
        def _reply(self, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.startswith("/api/update"):
                # web page asks this client to self-update (background, python)
                threading.Thread(target=do_background_update, daemon=True).start()
                self._reply({"ok": True, "updating": True,
                             "detail": "Background update started — the client "
                                       "restarts itself when finished."})
                return
            if self.path.startswith("/api/license"):
                # web page pushes the verified license key into local config
                import urllib.parse as _up
                qs = _up.parse_qs(_up.urlsplit(self.path).query)
                key = (qs.get("key") or [""])[0].strip().upper()
                if key:
                    try:
                        save_key(key)
                        self._reply({"ok": True, "saved": True, "license_key": key})
                    except OSError as e:
                        self._reply({"ok": False, "detail": str(e)})
                else:
                    self._reply({"ok": bool(state["key"]),
                                 "license_key": state["key"]})
                return
            if self.path.startswith("/api/camera"):
                # web page reads/saves this computer's camera role assignment
                # (internal = face capture, external = serial-number capture)
                import urllib.parse as _up
                qs = _up.parse_qs(_up.urlsplit(self.path).query)
                data = {}
                try:
                    if CONFIG_FILE.is_file():
                        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    data = {}
                changed = False
                for fld in ("internal", "external"):
                    if fld in qs:
                        data["camera_" + fld] = (qs.get(fld) or [""])[0].strip()
                        changed = True
                if changed:
                    try:
                        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                        CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    except OSError as e:
                        self._reply({"ok": False, "detail": str(e)})
                        return
                self._reply({"ok": True,
                             "camera_internal": str(data.get("camera_internal") or ""),
                             "camera_external": str(data.get("camera_external") or "")})
                return
            _cams = {}
            try:
                if CONFIG_FILE.is_file():
                    _c = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
                    _cams = {"camera_internal": str(_c.get("camera_internal") or ""),
                             "camera_external": str(_c.get("camera_external") or "")}
            except (OSError, ValueError):
                pass
            self._reply({"ok": True, "client": True,
                         "version": local_version(),
                         "license_key": current_key(),
                         "server": f"{server_ip}:{server_port}", **_cams})

        def log_message(self, *a):  # silence request logging
            pass

    if state["key"]:
        log(f"🔑 Client license key: {state['key']}")
    else:
        log("⚠ No license key yet — verify one on the company website or add "
            "\"license_key\" to platform/data/config.json. It is picked up "
            "automatically within seconds (no restart needed).")
    try:
        with http.server.HTTPServer(("127.0.0.1", port), Handler) as srv:
            log(f"Client presence beacon running on 127.0.0.1:{port} — "
                "keep this window open. Press Ctrl+C to stop.")
            srv.serve_forever()
    except KeyboardInterrupt:
        pass
    except OSError as e:
        log(f"Presence beacon could not start (port {port} busy?): {e}")


def linux_pkg_cmd(*packages: str, update_first: bool = False) -> list[list[str]] | None:
    """Build install commands for whichever Linux family this is:
    Debian-style (apt: Ubuntu/Debian/Mint) or RedHat-style (dnf/yum:
    Fedora/RHEL/CentOS/Rocky), plus Arch (pacman) and SUSE (zypper).
    Uses sudo only when not already root."""
    is_root = hasattr(os, "geteuid") and os.geteuid() == 0
    sudo = [] if is_root else ["sudo"] if shutil.which("sudo") else []
    if shutil.which("apt-get"):
        cmds = []
        if update_first:
            cmds.append(sudo + ["apt-get", "update", "-y"])
        cmds.append(sudo + ["apt-get", "install", "-y", *packages])
        return cmds
    if shutil.which("dnf"):
        return [sudo + ["dnf", "install", "-y", *packages]]
    if shutil.which("yum"):
        return [sudo + ["yum", "install", "-y", *packages]]
    if shutil.which("pacman"):
        return [sudo + ["pacman", "-S", "--noconfirm", *packages]]
    if shutil.which("zypper"):
        return [sudo + ["zypper", "--non-interactive", "install", *packages]]
    return None


def linux_install(*packages: str, update_first: bool = False) -> bool:
    cmds = linux_pkg_cmd(*packages, update_first=update_first)
    if not cmds:
        log("No supported Linux package manager found (apt/dnf/yum/pacman/zypper).")
        return False
    for cmd in cmds:
        log("Running: " + " ".join(cmd))
        try:
            if subprocess.run(cmd, timeout=1800).returncode != 0:
                return False
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"Install failed: {e}")
            return False
    return True


def log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"[{ts}] {msg}", flush=True)
    except (UnicodeEncodeError, OSError, ValueError):
        # legacy console encoding or no console at all (pythonw) — logging
        # must NEVER kill the program
        try:
            print(f"[{ts}] " + msg.encode("ascii", "replace").decode(), flush=True)
        except (OSError, ValueError):
            pass


# ---------------- Python version ----------------
MIN_PY = (3, 4)   # absolute minimum — old OSes supported (Win7, macOS 10.8+)
PREF_PY = (3, 12)  # preferred when available


def find_python312() -> "str | None":
    """Locate the best Python interpreter: prefer >= 3.12, accept >= 3.4 so
    that old operating systems keep working (Windows 7 → 3.8 max,
    macOS 10.8 Mountain Lion → 3.4/3.5, etc.)."""
    if sys.version_info >= PREF_PY:
        return sys.executable
    candidates = ["python3.13", "python3.12", "python3.11", "python3.10",
                  "python3.9", "python3.8", "python3.7", "python3.6",
                  "python3.5", "python3.4", "python3", "python"]
    if IS_WIN:
        candidates = ["py -3.13", "py -3.12", "py -3.11", "py -3.10", "py -3.9",
                      "py -3.8", "py -3"] + candidates
    best = None          # (version_tuple, exe)
    for cand in candidates:
        parts = cand.split()
        exe = shutil.which(parts[0])
        if not exe:
            continue
        try:
            out = subprocess.run([exe, *parts[1:], "-c",
                                  "import sys;print('.'.join(map(str,sys.version_info[:3])));print(sys.executable)"],
                                 capture_output=True, text=True, timeout=15)
            lines = (out.stdout or "").strip().splitlines()
            if len(lines) >= 2:
                ver = tuple(int(x) for x in lines[0].split(".")[:2])
                if ver >= PREF_PY:
                    return lines[1]           # good enough — stop searching
                if ver >= MIN_PY and (best is None or ver > best[0]):
                    best = (ver, lines[1])
        except (OSError, subprocess.TimeoutExpired, ValueError):
            continue
    if sys.version_info >= MIN_PY:
        cur = (sys.version_info[0], sys.version_info[1])
        if best is None or cur >= best[0]:
            return sys.executable
    if best:
        log(f"Python {best[0][0]}.{best[0][1]} found — 3.12+ is preferred but "
            "older versions (>= 3.4) are supported for old operating systems.")
        return best[1]
    return None


def _best_python_for_windows() -> "tuple[str, str]":
    """Pick the newest Python this Windows version supports.
    Windows 7 → 3.8.10 (last with Win7 support); Windows 8/8.1 → 3.9.13;
    Windows 10/11 → 3.12."""
    try:
        rel = platform.release()  # '7', '8', '8.1', '10', '11'
    except Exception:  # noqa: BLE001
        rel = "10"
    if rel == "7":
        return ("3.8.10", "https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe")
    if rel in ("8", "8.1"):
        return ("3.9.13", "https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe")
    return ("3.12.6", "https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe")


def install_python312() -> bool:
    """Install the newest Python this operating system supports —
    automatically, for old and new OS versions alike."""
    log("Python not found — attempting automatic installation…")
    if IS_WIN:
        ver, url = _best_python_for_windows()
        log(f"Detected Windows {platform.release()} → best supported Python is {ver}")
        if shutil.which("winget") and ver.startswith("3.12"):
            cmd = ["winget", "install", "-e", "--id", "Python.Python.3.12",
                   "--accept-package-agreements", "--accept-source-agreements"]
            log("Running: " + " ".join(cmd))
            try:
                if subprocess.run(cmd, timeout=1800).returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired) as e:
                log(f"winget install failed: {e}")
        # direct download from python.org — works on Windows 7/8 too
        try:
            import tempfile
            import urllib.request
            dest = Path(tempfile.gettempdir()) / f"nexacrew_python_{ver}.exe"
            log(f"Downloading Python {ver} from python.org…")
            urllib.request.urlretrieve(url, dest)
            log("Installing Python (silent, adds to PATH)…")
            r = subprocess.run([str(dest), "/quiet", "InstallAllUsers=0",
                                "PrependPath=1", "Include_pip=1"], timeout=1800)
            _refresh_path()
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"Automatic install failed: {e}")
            return False
    if IS_MAC and shutil.which("brew"):
        # Homebrew resolves the newest Python this macOS version supports
        cmd = ["brew", "install", "python@3.12"]
        log("Running: " + " ".join(cmd))
        try:
            if subprocess.run(cmd, timeout=1800).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"brew python@3.12 failed ({e}) — trying generic python3…")
        try:
            return subprocess.run(["brew", "install", "python"], timeout=1800).returncode == 0
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"Automatic install failed: {e}")
            return False
    if IS_MAC:
        log("Homebrew not found. For old macOS (10.8 Mountain Lion+) install "
            "Python from https://www.python.org/downloads/mac-osx/ — "
            "3.4/3.5 installers still run on 10.8.")
        return False
    if IS_LINUX:
        # Debian-style needs the -venv package; RedHat-style bundles venv.
        if shutil.which("apt-get"):
            if linux_install("python3.12", "python3.12-venv", update_first=True):
                return True
            # older Ubuntu/Debian may not have 3.12 packaged — try generic python3
            return linux_install("python3", "python3-venv", "python3-pip")
        if linux_install("python3.12"):
            return True
        return linux_install("python3", "python3-pip")
    log("No supported package manager found (winget/brew/apt/dnf/yum/pacman/zypper).")
    log("Please install Python 3 (>= 3.4) manually from https://www.python.org/downloads/")
    return False


# ---------------- Node.js + npm ----------------
def os_compat() -> dict:
    """Detect the OS compatibility tier (same rules as platform/app/oscompat.py,
    duplicated here so the launcher works before any dependencies exist).
    Tiers: full | legacy_copilot (macOS 10.13/10.14) | legacy_api
    (Win 7/8/8.1, macOS 10.8-10.12) | unsupported (below Win7 / macOS 10.8)."""
    sim = os.environ.get("NEXACREW_SIMULATE_OS", "").lower()
    system, ver = platform.system(), ""
    if sim == "mountain_lion":
        system, ver = "Darwin", "10.8.5"
    elif sim == "high_sierra":
        system, ver = "Darwin", "10.13.6"
    elif sim == "win7":
        system, ver = "Windows", "6.1.7601"
    elif system == "Darwin":
        ver = platform.mac_ver()[0] or "10.15"
    elif system == "Windows":
        ver = platform.version() or "10.0"
    tier = "full"
    try:
        v = tuple(int(x) for x in ver.split(".")[:2])
    except ValueError:
        v = (99,)
    if system == "Darwin":
        if v < (10, 8):
            tier = "unsupported"
        elif v < (10, 13):
            tier = "legacy_api"
        elif v < (10, 15):
            tier = "legacy_copilot"
    elif system == "Windows":
        if v < (6, 1):
            tier = "unsupported"
        elif v < (10, 0):
            tier = "legacy_api"
    return {"system": system, "version": ver, "tier": tier}


def os_gate() -> dict:
    """Refuse to run on operating systems below the minimum requirement,
    and announce the compatibility mode on legacy systems."""
    info = os_compat()
    if info["tier"] == "unsupported":
        print("=" * 62)
        print("  ❌ OPERATING SYSTEM NOT SUPPORTED — installation refused")
        print("=" * 62)
        log(f"Detected: {info['system']} {info['version']}")
        log("Minimum requirement: Windows 7 SP1 · macOS 10.8 Mountain Lion · "
            "Linux glibc 2.17+ · Python 3.4+ · 2 GB RAM · 2 GB free disk")
        log("NexaCrew cannot run here — aborting to prevent issues.")
        sys.exit(2)
    if info["tier"] == "legacy_copilot":
        log(f"ℹ Legacy macOS detected ({info['version']}) — Codex/Claude CLIs are "
            "not supported here. Prompts will be relayed to GitHub Copilot in "
            "VS Code 1.85.2 automatically (or use AI APIs in Settings).")
    elif info["tier"] == "legacy_api":
        log(f"ℹ Legacy OS detected ({info['system']} {info['version']}) — "
            "Codex/Claude CLIs and VS Code are not supported here. "
            "Configure an AI API in Settings → AI APIs (OpenAI/Anthropic/Ollama…).")
    return info


def _refresh_path() -> None:
    """Pick up PATH changes made by a fresh install (Windows)."""
    if not IS_WIN:
        return
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Environment]::GetEnvironmentVariable('Path','Machine') + ';' + "
             "[Environment]::GetEnvironmentVariable('Path','User')"],
            capture_output=True, text=True, timeout=20)
        if out.stdout.strip():
            os.environ["PATH"] = out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass


def ensure_nodejs() -> bool:
    """Check Node.js + npm; install a version compatible with THIS OS.
    Old systems get the newest Node they can run: Windows 7 → 13.14,
    macOS 10.8-10.12 → 12.x, macOS 10.13/10.14 → 16.x, modern → LTS."""
    node = shutil.which("node") or shutil.which("node.exe")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if node and npm:
        try:
            ver = subprocess.run([node, "--version"], capture_output=True, text=True,
                                 timeout=10).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            ver = "?"
        log(f"Node.js {ver} + npm found ✓")
        return True
    tier = os_compat()["tier"]
    log("Node.js + npm not found — installing automatically…")
    if tier == "legacy_api" and IS_WIN:
        # Windows 7/8: node 13.14.0 is the last MSI that runs there
        url = "https://nodejs.org/dist/v13.14.0/node-v13.14.0-x64.msi"
        log(f"Legacy Windows → installing Node.js 13.14 (newest compatible): {url}")
        try:
            import tempfile
            import urllib.request
            msi = Path(tempfile.gettempdir()) / "nexacrew_node13.msi"
            urllib.request.urlretrieve(url, msi)
            ok = subprocess.run(["msiexec", "/i", str(msi), "/qn"], timeout=1800).returncode == 0
            _refresh_path()
            if ok and (shutil.which("node") or shutil.which("node.exe")):
                log("Node.js 13.14 installed ✓")
                return True
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"Legacy Node.js install failed: {e}")
        return False
    if tier in ("legacy_api", "legacy_copilot") and IS_MAC:
        want = "node@16" if tier == "legacy_copilot" else "node@12"
        if shutil.which("brew"):
            log(f"Legacy macOS → installing {want} (newest compatible)…")
            try:
                if subprocess.run(["brew", "install", want], timeout=1800).returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired) as e:
                log(f"brew {want} failed: {e}")
        log(f"Install Node manually: https://nodejs.org/dist/ (pick {want.split('@')[1]}.x for this macOS).")
        return False
    if IS_WIN and shutil.which("winget"):
        cmd = ["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
               "--accept-package-agreements", "--accept-source-agreements"]
    elif IS_MAC and shutil.which("brew"):
        cmd = ["brew", "install", "node"]
    elif IS_LINUX:
        ok = linux_install("nodejs", "npm", update_first=True)
        if not ok and shutil.which("dnf"):
            # RedHat-style: npm is bundled inside the nodejs module
            ok = linux_install("nodejs")
        if ok:
            _refresh_path()
            if shutil.which("node"):
                log("Node.js + npm installed ✓")
                return True
        log("Node.js install did not complete — install manually from https://nodejs.org/")
        return False
    else:
        log("No supported package manager found — install Node.js LTS manually "
            "from https://nodejs.org/ (needed for the Codex / Claude Code CLIs).")
        return False
    log("Running: " + " ".join(cmd))
    try:
        ok = subprocess.run(cmd, timeout=1800).returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"Node.js install failed: {e}")
        return False
    _refresh_path()
    node = shutil.which("node") or shutil.which("node.exe")
    if ok and node:
        log("Node.js + npm installed ✓")
        return True
    log("Node.js install finished but the command is not on PATH yet — "
        "a restart of this terminal (or the computer) may be required.")
    return False


# ---------------- venv + dependencies ----------------
def venv_dir() -> Path:
    """OS-specific venv. A venv created by one OS is unusable from another
    (Windows/WSL/macOS layouts differ), so each OS keeps its own."""
    if IS_WIN:
        return ROOT / ".venv"
    if platform.system() == "Darwin":
        return ROOT / ".venv-mac"
    return ROOT / ".venv-linux"


def venv_python(vdir: Path) -> Path:
    return vdir / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")


def _venv_ok(vpy: Path) -> bool:
    """True when the venv interpreter actually runs and has pip."""
    if not vpy.is_file():
        return False
    try:
        r = subprocess.run([str(vpy), "-m", "pip", "--version"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_environment() -> Path:
    py = find_python312()
    if not py:
        if install_python312():
            py = find_python312()
        if not py:
            log("ERROR: Python 3.4+ is required (3.12+ recommended). "
                "Install it, then re-run: python start.py")
            sys.exit(1)
    log(f"Using Python: {py}")

    vdir = venv_dir()
    vpy = venv_python(vdir)
    if not _venv_ok(vpy):
        if vdir.exists():
            log(f"Virtual environment {vdir.name} is broken or from another OS — recreating…")
            shutil.rmtree(vdir, ignore_errors=True)
        log(f"Creating virtual environment ({vdir.name})…")
        if Path(py).resolve() == Path(sys.executable).resolve():
            venv.EnvBuilder(with_pip=True).create(vdir)
        else:
            subprocess.run([py, "-m", "venv", str(vdir)], check=True)
        vpy = venv_python(vdir)

    # Automatically install any missing libraries
    log("Checking / installing required libraries…")
    # 1) modern pip first — old pips don't know new macOS/ARM wheel tags and
    #    then try to compile packages (cryptography needs a Rust toolchain).
    #    setuptools stays < 81: newer releases removed pkg_resources, which
    #    the optional face-recognition stack still imports.
    subprocess.run([str(vpy), "-m", "pip", "install", "-q", "--upgrade",
                    "pip", "setuptools<81", "wheel"], capture_output=True, text=True)
    # 2) prefer prebuilt wheels — never compile from source when a wheel exists
    r = subprocess.run([str(vpy), "-m", "pip", "install", "-q", "--prefer-binary",
                        "-r", str(REQS)], capture_output=True, text=True)
    if r.returncode != 0 and "cryptography" in (r.stderr or "") + (r.stdout or ""):
        # 3) no cryptography wheel for this Python/OS (e.g. brand-new Python on
        #    an Intel Mac) → step back through releases that still ship wheels
        log("cryptography has no prebuilt wheel for this Python — "
            "trying older wheel-only releases…")
        for pin in ("cryptography<45", "cryptography<44", "cryptography<43",
                    "cryptography<42"):
            r2 = subprocess.run([str(vpy), "-m", "pip", "install", "-q",
                                 "--only-binary", "cryptography", pin],
                                capture_output=True, text=True)
            if r2.returncode == 0:
                log(f"Installed {pin} (prebuilt wheel) ✓")
                r = subprocess.run([str(vpy), "-m", "pip", "install", "-q",
                                    "--prefer-binary", "--only-binary", "cryptography",
                                    "-r", str(REQS)], capture_output=True, text=True)
                break
    if r.returncode != 0:
        out = (r.stderr or r.stdout)[-2000:]
        log("pip install failed:\n" + out)
        if "cryptography" in out and platform.system() == "Darwin":
            log("Fix on macOS: this Python has no cryptography wheel. Either")
            log("  a) install Python 3.12:  brew install python@3.12  "
                "(then delete .venv-linux/.venv and re-run), or")
            log("  b) install Rust so it can compile:  brew install rust")
        sys.exit(1)
    log("All libraries present ✓")
    _install_face_stack(vpy)
    return vpy


def _install_face_stack(vpy) -> None:
    """BEST-EFFORT server-side face recognition (dlib). Never blocks the
    install: dlib has no official wheels, so try the prebuilt 'dlib-bin'
    first and fall back to compiling only if a toolchain exists. The app
    degrades gracefully (OpenCV pipeline) when this is absent."""
    chk = subprocess.run([str(vpy), "-c", "import face_recognition"],
                         capture_output=True, text=True)
    if chk.returncode == 0:
        return
    log("Installing optional face-recognition stack (best-effort)…")
    try:
        if subprocess.run([str(vpy), "-m", "pip", "install", "-q",
                           "--prefer-binary", "dlib-bin"],
                          capture_output=True, text=True, timeout=900).returncode == 0:
            # --no-deps: face_recognition declares 'dlib', already satisfied
            # by dlib-bin (same module, different distribution name)
            subprocess.run([str(vpy), "-m", "pip", "install", "-q", "--no-deps",
                            "face-recognition", "face-recognition-models"],
                           capture_output=True, text=True, timeout=900)
        else:
            subprocess.run([str(vpy), "-m", "pip", "install", "-q",
                            "--prefer-binary", "face-recognition",
                            "face-recognition-models"],
                           capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"face stack install skipped: {e}")
    ok = subprocess.run([str(vpy), "-c", "import face_recognition"],
                        capture_output=True, text=True).returncode == 0
    log("Face recognition (dlib) ready ✓" if ok else
        "Face recognition unavailable — visitor kiosk uses the OpenCV fallback.")


# ---------------- run server ----------------
def _gui_available() -> bool:
    """Windows/macOS always have a desktop; Linux only when X11/Wayland runs."""
    if platform.system() in ("Windows", "Darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _widget_python(preferred: Path) -> Path:
    """Best interpreter for the tray widget. Client mode never builds the
    venv, so the system Python may lack pystray/Pillow — verify and
    auto-install them quietly when missing (the tray icon depends on them)."""
    candidates = [venv_python(venv_dir()), preferred, Path(sys.executable)]
    for py in candidates:
        if not py.is_file():
            continue
        chk = subprocess.run([str(py), "-c", "import pystray, PIL"],
                             capture_output=True, timeout=30)
        if chk.returncode == 0:
            return py
    # none has the tray deps — install into the preferred interpreter
    py = preferred if preferred.is_file() else Path(sys.executable)
    log("Installing tray-icon libraries (pystray, Pillow)…")
    subprocess.run([str(py), "-m", "pip", "install", "-q", "pystray", "Pillow"],
                   capture_output=True, timeout=300)
    return py


def launch_status_widgets(py: Path, host: str, port: int, role: str = "server") -> None:
    """Start the desktop widget + system-tray icon as isolated processes.
    They show live server status (green=online / red=offline) and the server
    address; double-click opens the status & settings panel. A crash of a
    widget can never affect the server. Skipped on headless Linux."""
    if not _gui_available():
        log("No graphical display detected — status widget/tray skipped (headless).")
        return
    script = ROOT / "tray_widget.py"
    if not script.is_file():
        return
    py = _widget_python(py)   # ensure interpreter has pystray/Pillow for the tray icon
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for mode in ("widget", "tray"):
        try:
            subprocess.Popen([str(py), str(script), mode,
                              "--host", host, "--port", str(port), "--role", role],
                             creationflags=flags,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log(f"Status {mode} could not start ({e}) — continuing without it.")
    log("🖥 Desktop status widget + system tray icon started — "
        "double-click them for the status & settings panel.")


def launch_action_prompt(py: Path) -> None:
    """Start the system-wide \"Action by prompt\" listener (global hotkey
    Ctrl+Alt+A in every software + right-click menu entries in the OS file
    manager). Runs isolated \u2014 a crash never affects the platform."""
    if not _gui_available():
        return
    script = ROOT / "action_prompt.py"
    if not script.is_file():
        return
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        subprocess.Popen([str(py), str(script), "listen"], creationflags=flags,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("\u26a1 'Action by prompt' active \u2014 press Ctrl+Alt+A in any software or "
            "right-click in the file manager to give the AI a task.")
    except OSError as e:
        log(f"Action-by-prompt listener could not start ({e}).")


def kill_tree(proc: "subprocess.Popen") -> None:
    """Destroy a process AND all of its children (agent CLIs, npm, node…).
    A plain kill() leaves children holding the port, which made restarts fail
    and looked like a permanent freeze."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (OSError, ProcessLookupError):
                proc.kill()
    except (OSError, subprocess.TimeoutExpired):
        try:
            proc.kill()
        except OSError:
            pass
    try:
        proc.wait(timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        pass


def wait_port_free(port: int, timeout: float = 30.0) -> bool:
    """Wait until the TCP port can be bound again (all old sockets released)."""
    import socket
    end = time.time() + timeout
    while time.time() < end:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port))
            s.close()
            return True
        except OSError:
            s.close()
            time.sleep(1)
    return False


def install_autostart() -> None:
    """Register this program to start automatically at login/boot as a
    background service, on every OS. Users never need to start it manually.
      Windows: registry Run key (per-user, no admin needed) + hidden window
      macOS:   LaunchAgent plist (~/Library/LaunchAgents), KeepAlive
      Linux:   systemd --user service when available, else XDG autostart"""
    py = str(venv_python(venv_dir()) if venv_python(venv_dir()).is_file()
             else Path(sys.executable))
    script = str(ROOT / "start.py")
    try:
        if IS_WIN:
            import winreg
            pyw = py.replace("python.exe", "pythonw.exe")   # no console window
            if not Path(pyw).is_file():
                pyw = py
            cmd = f'"{pyw}" "{script}"'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run",
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "NexaCrew", 0, winreg.REG_SZ, cmd)
            log("🚀 Auto-start installed (Windows Run key) — NexaCrew starts at every login.")
        elif IS_MAC:
            # Under sudo, target the real login user — a root-owned agent in the
            # user's session can't start and the program files become unreadable.
            sudo_user = os.environ.get("SUDO_USER", "")
            home = Path("/Users") / sudo_user if sudo_user else Path.home()
            plist = home / "Library" / "LaunchAgents" / "com.mapstudio.nexacrew.plist"
            plist.parent.mkdir(parents=True, exist_ok=True)
            log_file = ROOT / "platform" / "data" / "nexacrew_launchd.log"
            log_file.parent.mkdir(parents=True, exist_ok=True)
            # launchd starts jobs with PATH=/usr/bin:/bin — brew's node/npm/git
            # would be invisible.  Give the agent a full PATH, and resolve the
            # interpreter AT LAUNCH TIME (venv if it exists by then) via a
            # bash -c launcher, so a plist written before the venv was created
            # still picks the right python at the next boot.
            env_path = ("/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:"
                        f"{home}/.npm-global/bin:/usr/bin:/bin:/usr/sbin:/sbin")
            launcher = (f'V="{venv_python(venv_dir())}"; '
                        f'[ -x "$V" ] || V="$(command -v python3)"; '
                        f'exec "$V" "{script}"')
            plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.mapstudio.nexacrew</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>-c</string><string>{launcher}</string>
  </array>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>{env_path}</string>
    <key>HOME</key><string>{home}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>15</integer>
  <key>WorkingDirectory</key><string>{ROOT}</string>
  <key>StandardOutPath</key><string>{log_file}</string>
  <key>StandardErrorPath</key><string>{log_file}</string>
</dict></plist>
""", encoding="utf-8")
            if sudo_user and hasattr(os, "geteuid") and os.geteuid() == 0:
                import pwd
                u = pwd.getpwnam(sudo_user)
                os.chown(plist, u.pw_uid, u.pw_gid)
                uid = u.pw_uid
            else:
                uid = os.getuid()
            svc = f"gui/{uid}/com.mapstudio.nexacrew"
            # re-enable in case the label was disabled earlier (disabled labels
            # are remembered by launchd forever and silently never start again)
            subprocess.run(["launchctl", "enable", svc],
                           capture_output=True, timeout=30)
            # bootout a stale registration so the fresh plist is picked up,
            # then bootstrap into the user's GUI session (modern launchctl);
            # fall back to legacy load for older macOS
            subprocess.run(["launchctl", "bootout", svc],
                           capture_output=True, timeout=30)
            r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)],
                               capture_output=True, timeout=30)
            if r.returncode != 0:
                r = subprocess.run(["launchctl", "load", "-w", str(plist)],
                                   capture_output=True, timeout=30)
            if r.returncode == 0:
                log("🚀 Auto-start installed (macOS LaunchAgent) — NexaCrew starts at every login.")
            else:
                err = (r.stderr or b"").decode(errors="replace").strip()
                log(f"Auto-start registered; launchctl said: {err or r.returncode} "
                    "(the agent will still load at the next login).")
        elif IS_LINUX:
            # Under sudo, install for the real login user, not root.
            sudo_user = os.environ.get("SUDO_USER", "")
            if sudo_user and hasattr(os, "geteuid") and os.geteuid() == 0:
                import pwd
                u = pwd.getpwnam(sudo_user)
                user_home, user_uid = Path(u.pw_dir), u.pw_uid
            else:
                sudo_user, user_home, user_uid = "", Path.home(), os.getuid()

            def _user_ctl(*args):
                """systemctl --user for the target user, with the XDG runtime
                dir set — without it 'systemctl --user' fails over SSH/sudo."""
                env = dict(os.environ,
                           XDG_RUNTIME_DIR=f"/run/user/{user_uid}",
                           DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{user_uid}/bus")
                cmd = ["systemctl", "--user", *args]
                if sudo_user:
                    cmd = ["sudo", "-u", sudo_user,
                           f"XDG_RUNTIME_DIR=/run/user/{user_uid}",
                           f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{user_uid}/bus",
                           "systemctl", "--user", *args]
                return subprocess.run(cmd, capture_output=True, timeout=30, env=env)

            unit_ok = False
            if shutil.which("systemctl"):
                unit = user_home / ".config" / "systemd" / "user" / "nexacrew.service"
                unit.parent.mkdir(parents=True, exist_ok=True)
                env_path = (f"{user_home}/.npm-global/bin:"
                            "/home/linuxbrew/.linuxbrew/bin:"
                            "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin")
                unit.write_text(f"""[Unit]
Description=NexaCrew — Virtual Company AI Agent Platform (Sin Chi Chiu · MAP Studio)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/bin/bash -c 'V="{venv_python(venv_dir())}"; [ -x "$V" ] || V="$(command -v python3)"; exec "$V" "{script}"'
WorkingDirectory={ROOT}
Environment=PATH={env_path}
Environment=HOME={user_home}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
""", encoding="utf-8")
                if sudo_user:
                    import pwd
                    u = pwd.getpwnam(sudo_user)
                    for p in (unit, unit.parent, unit.parent.parent,
                              unit.parent.parent.parent):
                        try:
                            os.chown(p, u.pw_uid, u.pw_gid)
                        except OSError:
                            pass
                _user_ctl("daemon-reload")
                r = _user_ctl("enable", "nexacrew.service")
                unit_ok = r.returncode == 0
                # start it now (idempotent — already-running instance keeps the
                # port; the unit retries after we exit)
                _user_ctl("start", "nexacrew.service")
                # user services only run at BOOT (before login) with lingering
                if shutil.which("loginctl"):
                    lc = ["loginctl", "enable-linger", sudo_user or os.environ.get("USER", "")]
                    if os.geteuid() != 0:
                        lc = ["sudo", "-n"] + lc
                    subprocess.run([a for a in lc if a], capture_output=True, timeout=30)
                if unit_ok:
                    log("🚀 Auto-start installed (systemd user service + linger) — "
                        "NexaCrew starts at every boot.")
            if not unit_ok:
                # no working user-systemd (container/SSH/minimal distro):
                # fall back to XDG autostart so it at least starts at login
                desk = user_home / ".config" / "autostart" / "nexacrew.desktop"
                desk.parent.mkdir(parents=True, exist_ok=True)
                desk.write_text(f"""[Desktop Entry]
Type=Application
Name=NexaCrew
Exec={py} {script}
Path={ROOT}
X-GNOME-Autostart-enabled=true
""", encoding="utf-8")
                if sudo_user:
                    import pwd
                    u = pwd.getpwnam(sudo_user)
                    try:
                        os.chown(desk, u.pw_uid, u.pw_gid)
                        os.chown(desk.parent, u.pw_uid, u.pw_gid)
                    except OSError:
                        pass
                log("🚀 Auto-start installed (XDG autostart) — NexaCrew starts at every login.")
    except Exception as e:  # noqa: BLE001 — never block startup because of this
        log(f"Auto-start setup failed ({e}) — you can still run start.py manually.")


# ==================== command-line management interface ====================
def _find_our_pids() -> list:
    """PIDs of every process belonging to this program (uvicorn server,
    tray/widget, presence beacons, other start.py instances) — excluding us."""
    me = os.getpid()
    out = []
    root_str = str(ROOT).lower()
    if IS_WIN:
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | "
                 "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }"],
                capture_output=True, text=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW)
            rows = r.stdout
        except (OSError, subprocess.TimeoutExpired):
            rows = ""
        for line in rows.splitlines():
            if "|" not in line:
                continue
            pid_s, _, cmdline = line.partition("|")
            pid_s = pid_s.strip()
            if not pid_s.isdigit():
                continue
            low = cmdline.lower()
            if not any(k in low for k in ("uvicorn", "tray_widget", "start.py")):
                continue
            if "app.main:app" not in low and root_str not in low:
                continue
            pid = int(pid_s)
            if pid != me:
                out.append(pid)
    else:
        try:
            r = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True,
                               text=True, timeout=30)
            for line in r.stdout.splitlines():
                low = line.lower()
                if any(k in low for k in ("uvicorn", "tray_widget", "start.py")) and \
                        ("app.main:app" in low or root_str in low):
                    pid = int(line.strip().split()[0])
                    if pid != me:
                        out.append(pid)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return sorted(set(out))


def _kill_pid(pid: int) -> None:
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        pass


def cli_stop() -> None:
    """--stop : stop the program and all related processes in memory."""
    print("Stopping NexaCrew and all related processes…")
    pids = _find_our_pids()
    if not pids:
        print("  Nothing is running.")
        return
    for pid in pids:
        _kill_pid(pid)
        print(f"  ✓ stopped PID {pid}")
    cfg = load_deploy_config()
    port = int(cfg.get("server_port") or 8600)
    if wait_port_free(port, timeout=15):
        print(f"  ✓ port {port} released")
    print("Stopped.")


def cli_restart() -> None:
    """--restart : stop everything, then start again detached."""
    cli_stop()
    print("Restarting…")
    time.sleep(2)
    flags = subprocess.CREATE_NEW_CONSOLE if IS_WIN else 0
    subprocess.Popen([sys.executable, str(ROOT / "start.py")],
                     cwd=str(ROOT), creationflags=flags if IS_WIN else 0,
                     start_new_session=not IS_WIN)
    print("✓ A new instance has been launched.")


def cli_update() -> None:
    """--update : update client & server program to the newest version."""
    cfg = load_deploy_config()
    if cfg["deploy_mode"] == "client":
        ip, port = str(cfg["client_server_ip"]).strip(), int(cfg["client_server_port"])
        if not ip:
            print("ERROR: client mode but no server IP configured.")
            sys.exit(1)
        if not server_alive(ip, port):
            print(f"ERROR: server {ip}:{port} is not reachable.")
            sys.exit(1)
        sv, lv = server_version(ip, port), local_version()
        print(f"Local version:  {lv}")
        print(f"Server version: {sv}")
        if _ver_tuple(sv) <= _ver_tuple(lv):
            print("✓ Already up to date.")
            return
        if auto_update(ip, port, str(cfg.get("license_key") or "")):
            print("✓ Updated — restarting…")
            cli_restart()
        else:
            print("ERROR: update failed — see messages above.")
            sys.exit(1)
    else:
        print(f"Server install — version {local_version()}.")
        print("The server is the version source for clients; refreshing its "
              "dependencies to the newest allowed releases…")
        vpy = venv_python(venv_dir())
        if not vpy.is_file():
            vpy = Path(sys.executable)
        r = subprocess.run([str(vpy), "-m", "pip", "install", "-q", "--upgrade",
                            "-r", str(REQS)], timeout=900)
        print("✓ Dependencies refreshed." if r.returncode == 0
              else "⚠ Some dependencies could not be refreshed.")
        print("Restarting with the refreshed environment…")
        cli_restart()


def cli_repair() -> None:
    """--repair : verify and repair venv, dependencies and database, then restart."""
    print("Repairing NexaCrew…")
    cli_stop()
    # 1. virtual environment
    vdir = venv_dir()
    vpy = venv_python(vdir)
    if not vpy.is_file():
        print("  venv missing/broken — recreating…")
        shutil.rmtree(vdir, ignore_errors=True)
        venv.EnvBuilder(with_pip=True).create(vdir)
        vpy = venv_python(vdir)
    print("  ✓ virtual environment present")
    # 2. dependencies (force re-check every requirement)
    r = subprocess.run([str(vpy), "-m", "pip", "install", "-q",
                        "--upgrade", "-r", str(REQS)], timeout=900)
    print("  ✓ dependencies verified" if r.returncode == 0
          else "  ⚠ some dependencies failed to install")
    # 3. program files parse-check
    bad = []
    for pyf in (PLATFORM_DIR / "app").glob("*.py"):
        rr = subprocess.run([str(vpy), "-c",
                             f"import ast;ast.parse(open(r'{pyf}',encoding='utf-8').read())"],
                            capture_output=True, timeout=60)
        if rr.returncode != 0:
            bad.append(pyf.name)
    print("  ✓ program files OK" if not bad
          else f"  ❌ corrupted files: {', '.join(bad)} — reinstall the program package")
    # 4. database integrity
    dbf = PLATFORM_DIR / "data" / "platform.db"
    if dbf.is_file():
        import sqlite3
        try:
            con = sqlite3.connect(str(dbf))
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            con.close()
            print("  ✓ database integrity OK" if ok == "ok"
                  else f"  ⚠ database check: {ok}")
        except sqlite3.Error as e:
            print(f"  ❌ database unreadable: {e} — restore from Backup & Restore")
    else:
        print("  (no database yet — will be created at first start)")
    print("Repair finished — starting the program…")
    cli_restart()


def cli_status() -> None:
    """--status : CPU, GPU, memory, network information & bandwidth, health."""
    cfg = load_deploy_config()
    port = int(cfg.get("server_port") or 8600)
    print("=" * 62)
    print("  █▀█ NEXACREW · NODE STATUS REPORT · MAP Studio")
    print("=" * 62)
    print(f"Version:  {local_version()}   Mode: {cfg['deploy_mode']}")
    alive = server_alive("127.0.0.1", port, timeout=4)
    pids = _find_our_pids()
    print(f"Server:   {'🟢 RUNNING' if alive else '🔴 NOT RESPONDING'} on port {port}")
    print(f"Processes: {len(pids)} related ({', '.join(map(str, pids)) or 'none'})")
    # psutil (best source) — fall back to stdlib if unavailable
    try:
        vpy = venv_python(venv_dir())
        py = str(vpy if vpy.is_file() else sys.executable)
        code = (
            "import json,time\n"
            "try:\n"
            " import psutil\n"
            "except ImportError:\n"
            " print(json.dumps({'no_psutil':True})); raise SystemExit\n"
            "cpu=psutil.cpu_percent(interval=1)\n"
            "m=psutil.virtual_memory()\n"
            "n1=psutil.net_io_counters(); time.sleep(1); n2=psutil.net_io_counters()\n"
            "import socket\n"
            "ifs={k:[a.address for a in v if a.family==socket.AF_INET]\n"
            "     for k,v in psutil.net_if_addrs().items()}\n"
            "ifs={k:v for k,v in ifs.items() if v}\n"
            "print(json.dumps({'cpu':cpu,'mem_used':m.used,'mem_total':m.total,'mem_pct':m.percent,\n"
            " 'tx':n2.bytes_sent-n1.bytes_sent,'rx':n2.bytes_recv-n1.bytes_recv,\n"
            " 'tx_total':n2.bytes_sent,'rx_total':n2.bytes_recv,'ifs':ifs}))\n")
        r = subprocess.run([py, "-c", code], capture_output=True, text=True, timeout=30)
        info = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except Exception:  # noqa: BLE001
        info = {}
    gb = 1024 ** 3
    if info and not info.get("no_psutil"):
        print(f"CPU:      {info['cpu']:.0f} %")
        print(f"Memory:   {info['mem_used']/gb:.1f} / {info['mem_total']/gb:.1f} GB "
              f"({info['mem_pct']:.0f} %)")
        print(f"Network bandwidth (last second): ↑ {info['tx']/1024:.1f} KB/s   "
              f"↓ {info['rx']/1024:.1f} KB/s")
        print(f"Network totals since boot:       ↑ {info['tx_total']/gb:.2f} GB   "
              f"↓ {info['rx_total']/gb:.2f} GB")
        print("Network interfaces:")
        for name, addrs in (info.get("ifs") or {}).items():
            if addrs:
                print(f"  · {name}: {', '.join(addrs)}")
    else:
        print("(install 'psutil' in the venv for CPU/memory/network details: "
              ".venv/Scripts/pip install psutil)")
    # GPU — NVIDIA first, generic fallback
    gpu_done = False
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,"
                                "memory.used,memory.total,temperature.gpu",
                                "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=20)
            for line in r.stdout.strip().splitlines():
                nm, ut, mu, mt, tp = [x.strip() for x in line.split(",")]
                print(f"GPU:      {nm} — {ut}% load, {mu}/{mt} MB VRAM, {tp}°C")
                gpu_done = True
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    if not gpu_done and IS_WIN:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "(Get-CimInstance Win32_VideoController).Name"],
                               capture_output=True, text=True, timeout=20,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            names = [x.strip() for x in r.stdout.splitlines() if x.strip()]
            for nm in names:
                print(f"GPU:      {nm} (usage metrics need an NVIDIA GPU / nvidia-smi)")
                gpu_done = True
        except (OSError, subprocess.TimeoutExpired):
            pass
    if not gpu_done:
        print("GPU:      none detected")
    print("=" * 62)


def cli_showclients() -> None:
    """--showclients : admin-only, server side — live client connection list."""
    import getpass
    import urllib.request
    cfg = load_deploy_config()
    if cfg["deploy_mode"] != "server":
        print("ERROR: --showclients only works on the SERVER installation.")
        sys.exit(1)
    port = int(cfg.get("server_port") or 8600)
    if not server_alive("127.0.0.1", port, timeout=4):
        print(f"ERROR: the server is not running on port {port} — start it first.")
        sys.exit(1)
    print("Administrator sign-in required.")
    username = input("  Username: ").strip()
    if sys.stdin.isatty():
        password = getpass.getpass("  Password: ")
    else:  # piped/scripted input
        password = input("  Password: ").strip()
    base = f"http://127.0.0.1:{port}"
    try:
        req = urllib.request.Request(
            base + "/api/auth/login", method="POST",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            cookie = r.headers.get("Set-Cookie", "").split(";")[0]
        req = urllib.request.Request(base + "/api/clients",
                                     headers={"Cookie": cookie})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode())
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "401" in msg or "403" in msg:
            print("ERROR: sign-in failed or the account is not an administrator.")
        else:
            print(f"ERROR: {msg}")
        sys.exit(1)
    clients = data.get("clients", [])
    print("=" * 78)
    print(f"  Connected clients ({sum(1 for c in clients if c['online'])} online "
          f"/ {len(clients)} licensed)")
    print("=" * 78)
    if not clients:
        print("  No client licenses issued yet (Settings → Deployment → licenses).")
        return
    fmt = "  {:<8} {:<16} {:<18} {:<12} {}"
    print(fmt.format("STATUS", "IP", "HOSTNAME", "LAST SEEN", "LICENSE"))
    for c in clients:
        icon = {"online": "🟢", "offline": "⚪", "revoked": "🔴"}.get(c["status"], "◌")
        seen = (c["last_seen_at"] or "never")[:16].replace("T", " ")
        print(fmt.format(f"{icon} {c['status'][:6]}", c["ip"] or "-",
                         (c["hostname"] or "-")[:17], seen,
                         c["license_key"][:18] + "…"))
    print("=" * 78)


def cli_console_setup() -> None:
    """--console-setup : open the full-screen console configuration wizard
    (TUI — tabs, arrow keys, mouse). Works on any terminal, ideal for
    headless Linux servers without X11."""
    from console_setup import run_console_setup
    ok = run_console_setup()
    print(f"[setup] {'Configuration saved ✓ — start with: python start.py' if ok else 'Cancelled — nothing was changed.'}")


def cli_console_manage() -> None:
    """--console-manage : full-screen console server-management cockpit —
    everything the web UI does (dashboard, companies, users, skills, clients,
    approvals, schedules, config, audit) with keyboard + mouse control."""
    from console_manager import run_console_manager
    run_console_manager()


def handle_cli() -> bool:
    """Process management arguments; returns True when handled (skip normal start)."""
    args = [a.lower() for a in sys.argv[1:]]
    if not args:
        return False
    # Windows consoles may use cp1252 — never crash on ✓/emoji output
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    cmd = args[0]
    actions = {"--update": cli_update, "--restart": cli_restart, "--stop": cli_stop,
               "--repair": cli_repair, "--status": cli_status,
               "--showclients": cli_showclients,
               "--console-setup": cli_console_setup,
               "--console-manage": cli_console_manage}
    if cmd in ("--help", "-h", "/?"):
        print(__doc__)
        return True
    fn = actions.get(cmd)
    if fn is None:
        print(f"Unknown option: {sys.argv[1]}")
        print("Valid options: --update  --restart  --stop  --repair  --status  "
              "--showclients  --console-setup  --console-manage")
        sys.exit(2)
    fn()
    return True


def main() -> None:
    v = local_version()
    bar = "═" * 66
    print(f"""\
╔{bar}╗
║  █▀█  NEXACREW · VIRTUAL COMPANY AI AGENT PLATFORM               ║
║       ENTERPRISE DEPLOYMENT CONSOLE · v{v:<26}║
╟{'─' * 66}╢
║  Developed by Sin Chi Chiu · MAP Studio                          ║
║  ☎ +1-949-331-6528 · ✉ peterchiu@mapstudiousa.com                ║
║  🌐 www.mapstudiousa.com                                         ║
╚{bar}╝""")
    log(f"NODE  {platform.node()} · {platform.system()} {platform.release()} · Python {platform.python_version()}")

    os_gate()        # refuse unsupported OSes; announce legacy compatibility mode

    # -------- headless Linux (no X11/Wayland): enterprise console setup TUI --------
    # On a fresh install without a saved configuration, open the full-screen
    # console wizard (arrow keys + mouse) instead of relying on the web UI.
    if platform.system() == "Linux" and not _gui_available() and not CONFIG_FILE.is_file():
        log("Headless Linux detected (no X11/Wayland) — launching the console "
            "setup wizard…  (←→ tabs · ↑↓ fields · mouse supported · F10 saves)")
        try:
            from console_setup import run_console_setup
            if not run_console_setup():
                log("Setup cancelled — exiting. Run again anytime: python start.py")
                sys.exit(0)
            log("Console setup complete ✓ — continuing installation…")
        except Exception as e:  # noqa: BLE001 — never block installation
            log(f"Console wizard unavailable ({e}) — continuing with defaults.")

    ensure_nodejs()  # Node.js + npm are required for the agent CLIs
    install_autostart()  # run at every login/boot as a service — no manual start needed

    cfg = load_deploy_config()

    # ---------- CLIENT MODE: connect to a remote server, run nothing locally ----------
    if cfg["deploy_mode"] == "client":
        ip, port = str(cfg["client_server_ip"]).strip(), cfg["client_server_port"]
        if not ip:
            log("ERROR: client mode is selected but no server IP is configured.")
            log("Fix: edit platform/data/config.json → \"client_server_ip\": \"<server ip>\",")
            log("or set it in the web UI (Settings → Deployment) on the server machine.")
            sys.exit(1)
        url = f"http://{ip}:{port}/"
        backup_file = PLATFORM_DIR / "data" / "server_backup.json"
        if server_alive(ip, port):
            log(f"CLIENT mode — server is UP at {url}")
            # compare versions with the server; auto-update when older
            auto_update(ip, port, str(cfg.get("license_key") or ""))
            refresh_backup(ip, port, backup_file)
            # Prefer the HTTPS listener (:8443) — camera access on phones and
            # encrypted transport. Fall back to HTTP only when TLS is down.
            open_url = url
            try:
                import ssl as _ssl
                import urllib.request as _urlreq
                _sctx = _ssl.create_default_context()
                _sctx.check_hostname = False              # self-signed LAN cert
                _sctx.verify_mode = _ssl.CERT_NONE
                https_port = int(cfg.get("https_port") or 8443)
                with _urlreq.urlopen(
                        f"https://{ip}:{https_port}/api/health",
                        timeout=4, context=_sctx) as _r:
                    if _r.status == 200:
                        open_url = f"https://{ip}:{https_port}/"
            except Exception:  # noqa: BLE001 — TLS listener absent → HTTP
                log("HTTPS listener not reachable — opening HTTP page instead.")
            webbrowser.open(open_url)
            log(f"Browser opened at {open_url}. All agents run on the server; "
                "nothing runs on this machine.")
            launch_status_widgets(Path(sys.executable), ip, int(port), role="client")
            launch_action_prompt(Path(sys.executable))
            # Keep a tiny local beacon on 127.0.0.1:8600 so the website can
            # detect that the client program is installed on this computer,
            # and heartbeat the server so its Clients list shows us online.
            run_presence_beacon(server_ip=ip, server_port=int(port),
                                license_key=str(cfg.get("license_key") or ""))
            return
        # -------- SERVER IS DOWN: run locally from the backup settings --------
        print("=" * 62)
        print("  ⚠️  SERVER IS DOWN — switching to LOCAL FALLBACK mode")
        print("=" * 62)
        log(f"Could not reach the company server at {url}.")
        if backup_file.is_file():
            try:
                backup = json.loads(backup_file.read_text(encoding="utf-8-sig"))
                bcfg = backup.get("config", {})
                local_cfg = {}
                if CONFIG_FILE.is_file():
                    local_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
                # keep client-mode fields so we reconnect when the server returns
                merged = {**bcfg, **{k: local_cfg[k] for k in
                          ("deploy_mode", "client_server_ip", "client_server_port")
                          if k in local_cfg}}
                merged["_fallback"] = True
                CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                CONFIG_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")
                log(f"Restored settings from server backup ({backup.get('backed_up_at', 'unknown time')}).")
            except (OSError, ValueError) as e:
                log(f"Backup could not be read ({e}) — using local defaults.")
        else:
            log("No server backup found yet — using local defaults.")
        log("Starting the platform LOCALLY so you can keep working. "
            "Next start will reconnect to the server automatically if it is back.")
        cfg = {**cfg, "server_port": 8600, "server_bind": "127.0.0.1"}
        # fall through to server mode below

    # ---------- SERVER MODE ----------
    port = int(cfg["server_port"])
    bind = str(cfg["server_bind"]) or "0.0.0.0"
    url = f"http://127.0.0.1:{port}/"
    vpy = ensure_environment()
    log(f"SERVER mode — starting on {bind}:{port} (browse locally at {url})")
    if bind == "0.0.0.0":
        log("Clients on your network can connect with this machine's IP address "
            f"and port {port} (client mode in their Settings).")
    proc = subprocess.Popen([str(vpy), "-m", "uvicorn", "app.main:app",
                             "--host", bind, "--port", str(port),
                             "--app-dir", str(PLATFORM_DIR)])
    time.sleep(3)
    if proc.poll() is not None:
        log("ERROR: server exited immediately — check the logs above.")
        log(f"Tip: if the port is busy, change \"server_port\" in {CONFIG_FILE}")
        sys.exit(1)
    webbrowser.open(url)
    launch_status_widgets(vpy, "127.0.0.1", port, role="server")
    launch_action_prompt(vpy)
    log("Server running. The Setup page in the web UI checks the agent CLIs "
        "(Codex / Claude Code / VS Code) and can install & login them automatically.")
    if platform.system() == "Linux" and not _gui_available():
        log("🖥 Headless server: manage everything from this console with "
            "  python start.py --console-manage  "
            "(full-screen cockpit — tabs, arrow keys and mouse).")
    log("🐶 Watchdog active — if the server crashes or freezes it is destroyed "
        "and restarted automatically.")
    log("Press Ctrl+C to stop.")

    def start_server():
        return subprocess.Popen([str(vpy), "-m", "uvicorn", "app.main:app",
                                 "--host", bind, "--port", str(port),
                                 "--app-dir", str(PLATFORM_DIR)])

    def restart_server(old: "subprocess.Popen") -> "subprocess.Popen":
        kill_tree(old)                       # kill server + ALL children
        if not wait_port_free(port):          # make sure the port is released
            log(f"🐶 Watchdog: port {port} still busy — waiting a little longer…")
            time.sleep(5)
        p = start_server()
        log("🐶 Watchdog: server restarted ✓")
        return p

    fails = 0
    try:
        while True:
            time.sleep(10)
            if proc.poll() is not None:              # process died → restart
                log(f"🐶 Watchdog: server process exited (code {proc.returncode}) — restarting…")
                proc = restart_server(proc)
                fails = 0
                continue
            # health probe — detects a FROZEN (hung) process, not just a dead one
            if server_alive("127.0.0.1", port, timeout=15):
                fails = 0
                continue
            fails += 1
            log(f"🐶 Watchdog: health check failed ({fails}/3)…")
            if fails >= 3:                            # ~40 s unresponsive → frozen
                log("🐶 Watchdog: server is FROZEN — destroying the whole process tree and restarting…")
                proc = restart_server(proc)
                fails = 0
    except KeyboardInterrupt:
        kill_tree(proc)


if __name__ == "__main__":
    if not handle_cli():
        main()
