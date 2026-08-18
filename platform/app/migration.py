"""Migration set builder — move NexaCrew to another computer via USB.

The administrator plugs in a USB flash drive; the platform auto-detects it,
builds a self-contained migration ZIP (whole program + full data backup +
install scripts for Windows / macOS / Linux) and copies it to the drive with
live progress. The install scripts pick the best Python for the target OS —
old systems are supported too (Windows 7 → Python 3.8, macOS 10.8 Mountain
Lion → the newest Python the OS can run, minimum Python 3.4 overall).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import platform
import shutil
import string
import threading
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_EXCLUDE_DIRS = {".venv", ".git", "__pycache__", "node_modules"}

_state_lock = threading.Lock()
_state: dict = {"status": "idle", "percent": 0, "step": "", "error": "",
                "result": None, "started_at": None}


# ---------------- USB detection (Windows / macOS / Linux) ----------------
def detect_usb_drives() -> "list[dict]":
    """Return removable drives currently plugged in."""
    drives: list[dict] = []
    system = platform.system()
    if system == "Windows":
        import ctypes
        get_type = ctypes.windll.kernel32.GetDriveTypeW  # type: ignore[attr-defined]
        DRIVE_REMOVABLE = 2
        # letters of drives that sit on the USB bus but report as FIXED disks
        # (usual for USB SSDs and many large/modern flash drives)
        usb_fixed: set = set()
        try:
            import subprocess as _sp
            r = _sp.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_DiskDrive -Filter \"InterfaceType='USB'\" | "
                 "ForEach-Object { $_ | Get-CimAssociatedInstance -ResultClassName Win32_DiskPartition } | "
                 "ForEach-Object { $_ | Get-CimAssociatedInstance -ResultClassName Win32_LogicalDisk } | "
                 "Select-Object -ExpandProperty DeviceID"],
                capture_output=True, text=True, timeout=15,
                creationflags=_sp.CREATE_NO_WINDOW)
            for line in (r.stdout or "").splitlines():
                line = line.strip().rstrip(":")
                if len(line) == 1 and line.isalpha():
                    usb_fixed.add(line.upper())
        except Exception:  # noqa: BLE001 — PowerShell missing/slow: removable check still works
            pass
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            is_removable = get_type(ctypes.c_wchar_p(root)) == DRIVE_REMOVABLE
            if is_removable or letter in usb_fixed:
                try:
                    usage = shutil.disk_usage(root)
                    drives.append({"path": root, "label": f"{letter}:",
                                   "free_gb": round(usage.free / 1e9, 1),
                                   "total_gb": round(usage.total / 1e9, 1)})
                except OSError:
                    continue
    elif system == "Darwin":
        vol = Path("/Volumes")
        boot = Path("/").resolve()
        if vol.is_dir():
            for p in vol.iterdir():
                try:
                    if not p.is_dir() or p.resolve() == boot:
                        continue
                    usage = shutil.disk_usage(p)
                    drives.append({"path": str(p), "label": p.name,
                                   "free_gb": round(usage.free / 1e9, 1),
                                   "total_gb": round(usage.total / 1e9, 1)})
                except OSError:
                    continue
    else:  # Linux
        user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
        candidates = [Path("/media") / user, Path("/media"),
                      Path("/run/media") / user]
        seen = set()
        for base in candidates:
            if not base.is_dir():
                continue
            for p in base.iterdir():
                try:
                    rp = str(p.resolve())
                    if not p.is_dir() or rp in seen:
                        continue
                    seen.add(rp)
                    usage = shutil.disk_usage(p)
                    drives.append({"path": str(p), "label": p.name,
                                   "free_gb": round(usage.free / 1e9, 1),
                                   "total_gb": round(usage.total / 1e9, 1)})
                except OSError:
                    continue
        drives.extend(_detect_wsl_usb(seen))
    return drives


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def _mounted(mnt: Path) -> bool:
    try:
        return mnt.is_dir() and os.path.ismount(str(mnt))
    except OSError:
        return False


def _mount_wsl_drive(letter: str, mnt: Path) -> None:
    """Mount a Windows drive into WSL. Needs root — try direct mount first
    (works when running as root), then escalate through wsl.exe interop
    (spawns a root session in this distro, no password needed), then
    passwordless sudo."""
    import subprocess as _sp
    cmds = [
        ["mount", "-t", "drvfs", f"{letter}:", str(mnt)],
        ["wsl.exe", "-u", "root", "-e", "sh", "-c",
         f"mkdir -p {mnt} && mount -t drvfs {letter}: {mnt}"],
        ["sudo", "-n", "sh", "-c",
         f"mkdir -p {mnt} && mount -t drvfs {letter}: {mnt}"],
    ]
    try:
        mnt.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    for cmd in cmds:
        try:
            r = _sp.run(cmd, capture_output=True, timeout=20)
            if r.returncode == 0 and _mounted(mnt):
                return
        except Exception:  # noqa: BLE001
            continue


def _detect_wsl_usb(seen: "set[str]") -> "list[dict]":
    """Under WSL, USB drives are not auto-mounted into /media — ask Windows
    (via PowerShell interop) which drive letters are removable / on the USB
    bus, mount them under /mnt/<letter> if needed and report them."""
    if not _is_wsl():
        return []
    drives: list[dict] = []
    letters: list[str] = []
    try:
        import subprocess as _sp
        r = _sp.run(
            ["powershell.exe", "-NoProfile", "-Command",
             # removable-typed logical disks (DriveType 2) …
             "(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=2' | "
             "Select-Object -ExpandProperty DeviceID) + "
             # … plus fixed disks that sit on the USB bus (USB SSD / big sticks)
             "(Get-CimInstance Win32_DiskDrive -Filter \"InterfaceType='USB'\" | "
             "ForEach-Object { $_ | Get-CimAssociatedInstance -ResultClassName Win32_DiskPartition } | "
             "ForEach-Object { $_ | Get-CimAssociatedInstance -ResultClassName Win32_LogicalDisk } | "
             "Select-Object -ExpandProperty DeviceID)"],
            capture_output=True, text=True, timeout=20)
        for line in (r.stdout or "").splitlines():
            line = line.strip().rstrip(":")
            if len(line) == 1 and line.isalpha() and line.upper() not in letters:
                letters.append(line.upper())
    except Exception:  # noqa: BLE001 — interop unavailable
        return []
    for letter in letters:
        mnt = Path(f"/mnt/{letter.lower()}")
        try:
            if not _mounted(mnt):
                _mount_wsl_drive(letter, mnt)
            if not _mounted(mnt):
                continue
            rp = str(mnt.resolve())
            if rp in seen:
                continue
            seen.add(rp)
            usage = shutil.disk_usage(mnt)
            drives.append({"path": str(mnt), "label": f"USB {letter}: (Windows)",
                           "free_gb": round(usage.free / 1e9, 1),
                           "total_gb": round(usage.total / 1e9, 1)})
        except OSError:
            continue
    return drives


# ---------------- install scripts bundled into the migration set ----------------
_INSTALL_BAT = r"""@echo off
echo ==============================================================
echo   NexaCrew - migration installer (Windows)
echo   Developed by Sin Chi Chi - MAP Studio
echo ==============================================================
setlocal EnableDelayedExpansion

rem ---- minimum requirement gate: Windows 7 (6.1) or newer ----
for /f "tokens=4-5 delims=. " %%i in ('ver') do (set WINMAJ=%%i& set WINMIN=%%j)
if %WINMAJ% LSS 6 goto :toolow
if %WINMAJ%==6 if %WINMIN% LSS 1 goto :toolow
goto :okos
:toolow
echo ERROR: This Windows version is BELOW the minimum requirement.
echo Minimum: Windows 7 SP1. Installation refused to prevent issues.
pause
exit /b 2
:okos

set "DEST=%USERPROFILE%\NexaCrew"
echo Installing to %DEST% ...
if not exist "%DEST%" mkdir "%DEST%"
xcopy /E /I /Y /Q "%~dp0program" "%DEST%" >nul
echo Files copied.

rem ---- pick the right Python for THIS Windows version ----
rem Windows 7 (6.1) supports up to Python 3.8; Windows 8/8.1 up to 3.12 (3.9 ok);
rem Windows 10/11 use the latest 3.12.
for /f "tokens=4-5 delims=. " %%i in ('ver') do (set WINMAJ=%%i& set WINMIN=%%j)
set "PYURL=https://www.python.org/ftp/python/3.12.6/python-3.12.6-amd64.exe"
if "%WINMAJ%"=="6" (
  rem Windows 7 / 8 family
  if "%WINMIN%"=="1" set "PYURL=https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe"
  if "%WINMIN%"=="2" set "PYURL=https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe"
  if "%WINMIN%"=="3" set "PYURL=https://www.python.org/ftp/python/3.9.13/python-3.9.13-amd64.exe"
)

where python >nul 2>&1
if %errorlevel%==0 goto :havepython
echo Downloading Python installer for your Windows version...
powershell -Command "Invoke-WebRequest -UseBasicParsing '%PYURL%' -OutFile $env:TEMP\nexacrew_python.exe"
echo Installing Python (silent, adds to PATH)...
"%TEMP%\nexacrew_python.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_pip=1
set "PATH=%LOCALAPPDATA%\Programs\Python\Python312;%LOCALAPPDATA%\Programs\Python\Python312\Scripts;%LOCALAPPDATA%\Programs\Python\Python38;%LOCALAPPDATA%\Programs\Python\Python39;%PATH%"
:havepython
echo Starting NexaCrew (start.py finishes the setup automatically)...
cd /d "%DEST%"
python start.py
pause
"""

_INSTALL_SH = r"""#!/bin/sh
# NexaCrew - migration installer (macOS 10.8+ / Linux)
# Developed by Sin Chi Chi - MAP Studio
echo "=============================================================="
echo "  NexaCrew - migration installer ($(uname -s))"
echo "=============================================================="
DEST="$HOME/NexaCrew"
SRC="$(cd "$(dirname "$0")" && pwd)/program"

# ---- minimum requirement gate: macOS 10.8 Mountain Lion or newer ----
if [ "$(uname -s)" = "Darwin" ]; then
  MACVER=$(sw_vers -productVersion 2>/dev/null || echo 99)
  MAJ=$(echo "$MACVER" | cut -d. -f1)
  MIN=$(echo "$MACVER" | cut -d. -f2)
  if [ "$MAJ" -eq 10 ] && [ "$MIN" -lt 8 ]; then
    echo "ERROR: macOS $MACVER is BELOW the minimum requirement (10.8 Mountain Lion)."
    echo "Installation refused to prevent issues."
    exit 2
  fi
  if [ "$MAJ" -eq 10 ] && [ "$MIN" -ge 13 ] && [ "$MIN" -lt 15 ]; then
    echo "NOTE: macOS $MACVER - Codex/Claude CLIs are not supported here."
    echo "NexaCrew will relay prompts to GitHub Copilot in VS Code 1.85.2"
    echo "(download: https://update.code.visualstudio.com/1.85.2/darwin/stable)."
  elif [ "$MAJ" -eq 10 ] && [ "$MIN" -lt 13 ]; then
    echo "NOTE: macOS $MACVER - CLIs and VS Code are not supported here."
    echo "Configure an AI API inside NexaCrew (Settings -> AI APIs) instead."
  fi
fi

echo "Installing to $DEST ..."
mkdir -p "$DEST"
cp -R "$SRC/." "$DEST/"
echo "Files copied."

# ---- find or install the best Python this OS supports (minimum 3.4) ----
PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3.8 python3.7 python3.6 python3.5 python3.4 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
  OS="$(uname -s)"
  if [ "$OS" = "Darwin" ]; then
    # macOS: 10.8 Mountain Lion and newer. Homebrew installs the newest
    # Python the OS supports; very old systems can use the python.org
    # 3.4/3.5 mac installers manually.
    if command -v brew >/dev/null 2>&1; then
      echo "Installing Python via Homebrew..."
      brew install python || true
    else
      echo "Homebrew not found - please install Python 3 (>= 3.4) from"
      echo "https://www.python.org/downloads/mac-osx/ (choose the newest"
      echo "version compatible with your macOS - 3.4/3.5 work on 10.8)."
      exit 1
    fi
  else
    # Linux: use the native package manager
    if command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
    elif command -v dnf  >/dev/null 2>&1; then sudo dnf install -y python3 python3-pip
    elif command -v yum  >/dev/null 2>&1; then sudo yum install -y python3 python3-pip
    elif command -v pacman >/dev/null 2>&1; then sudo pacman -Sy --noconfirm python python-pip
    elif command -v zypper >/dev/null 2>&1; then sudo zypper install -y python3 python3-pip
    else echo "No known package manager - install Python 3 (>= 3.4) manually."; exit 1
    fi
  fi
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
fi

if [ -z "$PY" ]; then echo "Python installation failed."; exit 1; fi
echo "Using Python: $($PY --version 2>&1)"
echo "Starting NexaCrew (start.py finishes the setup automatically)..."
cd "$DEST"
exec "$PY" start.py
"""

_README = """NexaCrew — MIGRATION SET
=========================================
Developed by Sin Chi Chi · MAP Studio

MINIMUM REQUIREMENTS
--------------------
• Windows 7 SP1 (64-bit)   • macOS 10.8 Mountain Lion   • Linux glibc 2.17+
• Python 3.4+ (installed automatically)  • 2 GB RAM  • 2 GB free disk
Below these the installer refuses to run, to prevent issues.

COMPATIBILITY MODES
-------------------
• Windows 10/11, macOS 10.15+, Linux — full mode (Codex + Claude CLIs + VS Code)
• macOS 10.13 High Sierra / 10.14    — CLIs not supported; prompts are relayed
  to GitHub Copilot inside VS Code 1.85.2 automatically
• Windows 7/8/8.1, macOS 10.8-10.12  — CLIs & VS Code not supported; use
  Settings → AI APIs (OpenAI / Anthropic / Ollama …)

This USB drive contains everything needed to move NexaCrew to a new
computer: the whole program, a full data backup (settings, users, chats,
skills, companies …) and installers for all operating systems.""" + """

HOW TO MIGRATE TO THE NEW COMPUTER
----------------------------------
1. Plug this USB drive into the NEW computer.
2. Unzip nexacrew_migration_<date>.zip anywhere (e.g. the Desktop).
3. Run the installer for your operating system:
   • Windows  : double-click  install_windows.bat
   • macOS    : open Terminal, run  sh install_mac_linux.sh
   • Linux    : open a terminal, run  sh install_mac_linux.sh
4. The installer copies the program to your home folder, detects your OS
   version and automatically installs a compatible Python:
   • Windows 7        → Python 3.8   • Windows 8/8.1 → Python 3.9
   • Windows 10/11    → Python 3.12  • macOS 10.8+   → newest supported
   • Linux            → distro package (python3)
   (Minimum supported Python: 3.4)
5. NexaCrew starts automatically. All your data is already inside
   (platform/data). Sign in with your existing username and password.

If anything is missing, the Backup page (💾) inside NexaCrew can restore
the included backup file: platform/data/backups/ (latest snapshot).
"""


# ---------------- migration build (background, with progress) ----------------
def get_state() -> dict:
    with _state_lock:
        return dict(_state)


def _set(status: str | None = None, percent: int | None = None, step: str | None = None,
         error: str | None = None, result: dict | None = None) -> None:
    with _state_lock:
        if status is not None:
            _state["status"] = status
        if percent is not None:
            _state["percent"] = percent
        if step is not None:
            _state["step"] = step
        if error is not None:
            _state["error"] = error
        if result is not None:
            _state["result"] = result


def start_migration(usb_path: str, backup_doc: dict) -> bool:
    """Kick off the migration build in a background thread."""
    with _state_lock:
        if _state["status"] == "running":
            return False
        _state.update(status="running", percent=0, step="Preparing…", error="",
                      result=None, started_at=dt.datetime.utcnow().isoformat())
    threading.Thread(target=_build, args=(usb_path, backup_doc), daemon=True,
                     name="migration-builder").start()
    return True


def _build(usb_path: str, backup_doc: dict) -> None:
    try:
        usb = Path(usb_path)
        if not usb.is_dir():
            raise ValueError("USB drive is no longer available — plug it in again")

        # 1) collect program files
        _set(step="Scanning program files…", percent=2)
        files: list[tuple[Path, str]] = []
        total_bytes = 0
        for p in ROOT_DIR.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(ROOT_DIR)
            if any(part in _EXCLUDE_DIRS for part in rel.parts):
                continue
            if rel.suffix in (".zip", ".pyc"):
                continue
            files.append((p, f"program/{rel.as_posix()}"))
            total_bytes += p.stat().st_size

        # 2) build the zip locally first (fast disk), then copy to USB
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp_zip = DATA_DIR / f"nexacrew_migration_{stamp}.zip"
        tmp_zip.parent.mkdir(parents=True, exist_ok=True)
        done_bytes = 0
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for i, (p, arc) in enumerate(files):
                z.write(p, arc)
                done_bytes += p.stat().st_size
                if i % 25 == 0:
                    pct = 5 + int(60 * done_bytes / max(1, total_bytes))
                    _set(step=f"Packing program… ({i + 1}/{len(files)} files)", percent=pct)
            _set(step="Adding data backup…", percent=66)
            z.writestr("program/platform/data/backups/migration_backup.json",
                       json.dumps(backup_doc, indent=1, default=str))
            _set(step="Adding OS installers (Windows / macOS / Linux)…", percent=70)
            z.writestr("install_windows.bat", _INSTALL_BAT.replace("\n", "\r\n"))
            z.writestr("install_mac_linux.sh", _INSTALL_SH)
            z.writestr("README_MIGRATION.txt", _README)

        # 3) copy to the USB drive with progress
        size = tmp_zip.stat().st_size
        free = shutil.disk_usage(usb).free
        if free < size + 50 * 1024 * 1024:
            raise ValueError(f"USB drive is full — needs {size / 1e9:.1f} GB free")
        dest = usb / tmp_zip.name
        _set(step=f"Copying to USB drive ({size / 1e6:.0f} MB)…", percent=72)
        copied = 0
        with open(tmp_zip, "rb") as src, open(dest, "wb") as out:
            while True:
                chunk = src.read(4 * 1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                copied += len(chunk)
                _set(percent=72 + int(26 * copied / max(1, size)))
        try:
            tmp_zip.unlink()
        except OSError:
            pass
        _set(status="done", percent=100, step="Migration set ready ✓",
             result={"file": str(dest), "size_mb": round(size / 1e6, 1),
                     "files": len(files),
                     "finished_at": dt.datetime.utcnow().isoformat()})
    except Exception as e:  # noqa: BLE001
        _set(status="error", step="Failed", error=str(e)[:500])
