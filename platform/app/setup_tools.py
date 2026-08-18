"""Environment setup: detect / install / login for Codex, Claude Code and VS Code.

This platform can be deployed on any Windows machine — on first run the web UI
checks that all required agent CLIs are present and authenticated, offers
one-click install (npm/winget) and opens interactive login windows.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from pathlib import Path

_install_state: dict[str, dict] = {}   # tool -> {status, log}
_LOCK = threading.Lock()

CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
CREATE_NEW_CONSOLE = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0


def _augment_path() -> None:
    """GUI-launched processes on macOS/Linux get a minimal PATH that misses
    Homebrew, MacPorts, nvm and npm-global directories — so brew/node/npm
    look 'not installed' even when they are. Add the standard locations."""
    if os.name == "nt":
        return
    home = Path.home()
    extra = [
        "/opt/homebrew/bin", "/opt/homebrew/sbin",      # Homebrew (Apple Silicon)
        "/usr/local/bin", "/usr/local/sbin",            # Homebrew (Intel) / generic
        "/opt/local/bin",                               # MacPorts
        str(home / ".local" / "bin"),
        str(home / "bin"),
        str(home / ".npm-global" / "bin"),              # npm prefix installs
        "/usr/local/opt/node/bin",
        "/snap/bin",                                    # Linux snap
    ]
    # nvm: every installed version's bin dir (newest first)
    nvm = home / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        try:
            versions = sorted(nvm.iterdir(), reverse=True)
            extra.extend(str(v / "bin") for v in versions if (v / "bin").is_dir())
        except OSError:
            pass
    cur = os.environ.get("PATH", "").split(os.pathsep)
    add = [p for p in extra if p not in cur and Path(p).is_dir()]
    if add:
        os.environ["PATH"] = os.pathsep.join(cur + add)


_augment_path()


# absolute fallback locations for tools when PATH lookup fails (GUI-launched
# server on macOS/Linux, or brew installed after the server started)
_TOOL_HINTS: dict[str, list[str]] = {
    "brew": ["/opt/homebrew/bin/brew", "/usr/local/bin/brew", "/opt/local/bin/brew"],
    "node": ["/opt/homebrew/bin/node", "/usr/local/bin/node", "/opt/homebrew/opt/node/bin/node",
             "/usr/local/opt/node/bin/node", "/snap/bin/node"],
    "npm": ["/opt/homebrew/bin/npm", "/usr/local/bin/npm", "/opt/homebrew/opt/node/bin/npm",
            "/usr/local/opt/node/bin/npm", "/snap/bin/npm"],
    "codex": ["/opt/homebrew/bin/codex", "/usr/local/bin/codex",
              str(Path.home() / ".npm-global" / "bin" / "codex")],
    "claude": ["/opt/homebrew/bin/claude", "/usr/local/bin/claude",
               str(Path.home() / ".npm-global" / "bin" / "claude"),
               str(Path.home() / ".claude" / "local" / "claude")],
    "code": ["/opt/homebrew/bin/code", "/usr/local/bin/code",
             "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"],
}


def _which(*names: str) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    # PATH lookup failed — try absolute well-known locations
    for n in names:
        base = n.rsplit(".", 1)[0]  # strip .cmd/.exe suffix
        for cand in _TOOL_HINTS.get(base, []):
            if Path(cand).is_file() and os.access(cand, os.X_OK):
                return cand
    return None


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout,
                              creationflags=CREATE_NO_WINDOW)
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


# ---------------- detection ----------------
def _candidate_homes() -> "list[Path]":
    """Home dirs to inspect for CLI credentials. The server may run as root
    (launchd/service), so also scan real user homes under /Users and /home."""
    homes = [Path.home()]
    for root in (Path("/Users"), Path("/home")):
        if root.is_dir():
            try:
                homes += [p for p in root.iterdir()
                          if p.is_dir() and not p.name.startswith(".") and p.name != "Shared"]
            except OSError:
                pass
    seen: set = set()
    return [h for h in homes if not (str(h) in seen or seen.add(str(h)))]


def _codex_logged_in() -> bool:
    # Codex stores OAuth tokens in ~/.codex/auth.json
    for home in _candidate_homes():
        try:
            auth = home / ".codex" / "auth.json"
            if auth.is_file() and auth.stat().st_size > 10:
                return True
        except OSError:
            pass
    cli = _which("codex.cmd", "codex.exe", "codex")
    if not cli:
        return False
    code, out = _run([cli, "login", "status"])
    return code == 0 and "not logged in" not in out.lower()


def _claude_logged_in() -> bool:
    # Claude Code: ~/.claude/.credentials.json on Windows/Linux; on macOS the
    # token lives in the Keychain and ~/.claude.json records the OAuth account.
    for home in _candidate_homes():
        try:
            cred = home / ".claude" / ".credentials.json"
            if cred.is_file() and cred.stat().st_size > 10:
                return True
            cfg = home / ".claude.json"
            if cfg.is_file() and "oauthAccount" in cfg.read_text(encoding="utf-8", errors="replace"):
                return True
        except OSError:
            pass
    cli = _which("claude.cmd", "claude.exe", "claude")
    if not cli:
        return False
    code, out = _run([cli, "auth", "status"], timeout=20)
    return code == 0 and ("logged in" in out.lower() or "authenticated" in out.lower())


def _vscode_os_supported() -> "tuple[bool, str]":
    """VS Code needs macOS 10.15+; on older macOS (e.g. 10.8 Mountain Lion)
    the platform automatically uses a fallback editor for coding handoffs."""
    import platform as _p
    if _p.system() != "Darwin":
        return True, ""
    ver = _p.mac_ver()[0]
    try:
        parts = tuple(int(x) for x in ver.split(".")[:2])
    except ValueError:
        return True, ""
    if parts and parts < (10, 15):
        return False, (f"macOS {ver} cannot run VS Code (needs 10.15+) — the "
                       "platform automatically uses the system text editor / "
                       "Sublime / TextMate for coding handoffs instead. "
                       "Nothing to install; this step is complete.")
    return True, ""


def setup_status() -> dict:
    from .oscompat import detect as _os_detect
    _augment_path()          # PATH may change while the server runs (brew install …)
    osinfo = _os_detect()
    tier = osinfo["tier"]
    node = _which("node.exe", "node")
    npm = _which("npm.cmd", "npm")
    codex = _which("codex.cmd", "codex.exe", "codex")
    claude = _which("claude.cmd", "claude.exe", "claude")
    vscode = _which("code.cmd", "code")
    vscode_ok, vscode_note = _vscode_os_supported()
    office = _detect_office()
    cli_ok = osinfo["tools"]["codex_cli"]        # CLIs runnable on this OS?
    tools = {
        "node": {"label": "Node.js + npm", "installed": bool(node and npm), "path": node,
                 "logged_in": None, "required_for": "installing the agent CLIs"
                 if cli_ok else f"limited on this OS — max version: {osinfo['tools']['node']}"},
        "codex": {"label": "OpenAI Codex CLI" if cli_ok else "OpenAI Codex CLI (not supported on this OS)",
                  "installed": bool(codex) or not cli_ok, "path": codex,
                  "logged_in": (_codex_logged_in() if codex else False) if cli_ok else None,
                  "required_for": "planning, Q&A, image & file generation (or use a custom AI API in Settings)"
                  if cli_ok else _strategy_note(osinfo)},
        "claude": {"label": "Claude Code CLI" if cli_ok else "Claude Code CLI (not supported on this OS)",
                   "installed": bool(claude) or not cli_ok, "path": claude,
                   "logged_in": (_claude_logged_in() if claude else False) if cli_ok else None,
                   "required_for": "implementation & verification stages (or use a custom AI API in Settings)"
                   if cli_ok else _strategy_note(osinfo)},
        "vscode": {"label": "Visual Studio Code" if vscode_ok else "Code editor (VS Code fallback)",
                   "installed": bool(vscode) or not vscode_ok, "path": vscode,
                   "logged_in": None,
                   "required_for": vscode_note or ("final code generation handoff (Copilot)"
                   if tier != "legacy_copilot" else
                   "VS Code 1.85.2 — last build for macOS 10.13/10.14; used for the GitHub Copilot relay")},
        "office": {"label": f"Office suite ({office[1]})" if office[0] else "Office suite (LibreOffice)",
                   "installed": bool(office[0]), "path": office[0],
                   "logged_in": None, "required_for": "document generation (Word/Excel/PDF conversion)"
                   + ("" if tier == "full" else f" — compatible version: {osinfo['tools']['office']}")},
    }
    # No MS Office / WPS / LibreOffice found → auto-install LibreOffice once
    if not office[0]:
        _auto_install_office()
    with _LOCK:
        for name, st in _install_state.items():
            if name in tools:
                tools[name]["install"] = {"status": st["status"], "log": st["log"][-1500:]}
    # completion: every tool installed + codex/claude logged in (full tier);
    # on legacy tiers unsupported tools count as complete automatically
    steps_total = 7  # node, codex inst, codex login, claude inst, claude login, vscode, office
    steps_done = sum([
        tools["node"]["installed"],
        tools["codex"]["installed"],
        bool(tools["codex"]["logged_in"]) if cli_ok else 1,
        tools["claude"]["installed"],
        bool(tools["claude"]["logged_in"]) if cli_ok else 1,
        tools["vscode"]["installed"],
        tools["office"]["installed"],
    ])
    return {"tools": tools, "steps_done": steps_done, "steps_total": steps_total,
            "complete": steps_done == steps_total, "os": osinfo}


def _strategy_note(osinfo: dict) -> str:
    if osinfo["ai_strategy"] == "copilot_relay":
        return ("not installable on this macOS — prompts are relayed to GitHub "
                "Copilot inside VS Code automatically. Nothing to install here.")
    return ("not installable on this OS — configure an AI API in Settings → AI APIs "
            "(OpenAI, Anthropic, Ollama, …). Nothing to install here.")


# ---------------- install ----------------
import platform as _platform
_SYS = _platform.system()  # Windows / Linux / Darwin


def _detect_office() -> tuple[str | None, str]:
    """Detect an installed office suite: MS Office, WPS Office or LibreOffice.
    Returns (path, name) or (None, '')."""
    # LibreOffice / anything on PATH first
    p = _which("soffice.exe", "soffice", "libreoffice")
    if p:
        return p, "LibreOffice"
    p = _which("wps.exe", "wps")
    if p:
        return p, "WPS Office"
    if _SYS == "Windows":
        candidates = [
            (r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE", "Microsoft Office"),
            (r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE", "Microsoft Office"),
            (r"C:\Program Files\LibreOffice\program\soffice.exe", "LibreOffice"),
            (str(Path(os.environ.get("LOCALAPPDATA", "")) / "Kingsoft" / "WPS Office" / "ksolaunch.exe"), "WPS Office"),
        ]
        for path, name in candidates:
            if Path(path).is_file():
                return path, name
    elif _SYS == "Darwin":
        for path, name in [("/Applications/Microsoft Word.app", "Microsoft Office"),
                           ("/Applications/LibreOffice.app", "LibreOffice"),
                           ("/Applications/wpsoffice.app", "WPS Office")]:
            if Path(path).exists():
                return path, name
    return None, ""


_OFFICE_AUTO_TRIGGERED = False


def _auto_install_office() -> None:
    """No office suite found → kick off a LibreOffice install automatically."""
    global _OFFICE_AUTO_TRIGGERED
    if _OFFICE_AUTO_TRIGGERED:
        return
    _OFFICE_AUTO_TRIGGERED = True
    start_install("office")


if _SYS == "Windows":
    _NATIVE_INSTALL = {
        "vscode": ["winget", "install", "-e", "--id", "Microsoft.VisualStudioCode",
                   "--accept-package-agreements", "--accept-source-agreements"],
        "node": ["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                 "--accept-package-agreements", "--accept-source-agreements"],
        "office": ["winget", "install", "-e", "--id", "TheDocumentFoundation.LibreOffice",
                   "--accept-package-agreements", "--accept-source-agreements"],
    }
elif _SYS == "Darwin":
    _NATIVE_INSTALL = {
        "vscode": ["brew", "install", "--cask", "visual-studio-code"],
        "node": ["brew", "install", "node"],
        "office": ["brew", "install", "--cask", "libreoffice"],
    }
else:  # Linux — supports both major families: Debian-style (apt) and
       # RedHat-style (dnf/yum), plus Arch (pacman) and SUSE (zypper)
    def _linux_cmd(*pkgs: str) -> list[str]:
        is_root = hasattr(os, "geteuid") and os.geteuid() == 0
        sudo = [] if is_root else ["sudo"] if shutil.which("sudo") else []
        if shutil.which("apt-get"):
            return sudo + ["apt-get", "install", "-y", *pkgs]
        if shutil.which("dnf"):
            return sudo + ["dnf", "install", "-y", *pkgs]
        if shutil.which("yum"):
            return sudo + ["yum", "install", "-y", *pkgs]
        if shutil.which("pacman"):
            return sudo + ["pacman", "-S", "--noconfirm", *pkgs]
        if shutil.which("zypper"):
            return sudo + ["zypper", "--non-interactive", "install", *pkgs]
        return ["sh", "-c", "echo 'No supported package manager (apt/dnf/yum/pacman/zypper)'; exit 1"]

    _NATIVE_INSTALL = {
        # snap works across both families when present; else native repo
        "vscode": (["sudo", "snap", "install", "code", "--classic"]
                   if shutil.which("snap") else _linux_cmd("code")),
        "node": _linux_cmd("nodejs", "npm") if shutil.which("apt-get")
                else _linux_cmd("nodejs"),  # RedHat-style bundles npm in nodejs
        "office": _linux_cmd("libreoffice"),
    }

_INSTALL_CMDS = {
    "codex": ["npm", "install", "-g", "@openai/codex"],
    "claude": ["npm", "install", "-g", "@anthropic-ai/claude-code"],
    **_NATIVE_INSTALL,
}


# ---------------- fully-automatic install pipelines ----------------
def _log_append(tool: str, line: str) -> None:
    with _LOCK:
        st = _install_state.setdefault(tool, {"status": "running", "log": ""})
        st["log"] = (st["log"] + line + "\n")[-8000:]


def _sh(tool: str, cmd: list[str], timeout: int = 1800, env: dict | None = None) -> bool:
    """Run one pipeline step, streaming a header + result into the tool log."""
    _log_append(tool, "$ " + " ".join(cmd))
    exe = _which(cmd[0] + ".cmd", cmd[0] + ".exe", cmd[0]) or cmd[0]
    full_env = {**os.environ, **(env or {})}
    try:
        proc = subprocess.run([exe] + cmd[1:], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              env=full_env, creationflags=CREATE_NO_WINDOW)
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if out:
            _log_append(tool, out[-2000:])
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        _log_append(tool, f"ERROR: {e}")
        return False


def _ensure_brew(tool: str) -> bool:
    """macOS/Linux: install Homebrew automatically when missing (official
    non-interactive installer), then put it on PATH for this process."""
    if _which("brew"):
        return True
    _log_append(tool, "Homebrew not found — installing automatically…")
    ok = _sh(tool, ["/bin/bash", "-c",
                    'curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh '
                    '-o /tmp/brew-install.sh && /bin/bash /tmp/brew-install.sh'],
             env={"NONINTERACTIVE": "1", "CI": "1"})
    # Linuxbrew default location
    for p in ("/opt/homebrew/bin", "/usr/local/bin", "/home/linuxbrew/.linuxbrew/bin",
              str(Path.home() / ".linuxbrew" / "bin")):
        if Path(p, "brew").is_file():
            os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
    _augment_path()
    return ok and _which("brew") is not None


def _ensure_node(tool: str) -> bool:
    """Ensure node+npm exist, installing them automatically per-OS."""
    if _which("npm.cmd", "npm"):
        return True
    _log_append(tool, "Node.js/npm not found — installing automatically…")
    if _SYS == "Windows":
        ok = _sh(tool, ["winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                        "--silent", "--accept-package-agreements", "--accept-source-agreements"])
        # winget puts node in Program Files — add for this process
        for p in (r"C:\Program Files\nodejs", r"C:\Program Files (x86)\nodejs",
                  str(Path.home() / "AppData" / "Roaming" / "npm")):
            if Path(p).is_dir():
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")
        return ok and _which("npm.cmd", "npm") is not None
    # macOS / Linux — per requirement: brew first, then brew install node
    if not _ensure_brew(tool):
        return False
    _sh(tool, ["brew", "install", "node"])
    _augment_path()
    return _which("npm") is not None


def _npm_global(tool: str, pkg: str) -> bool:
    """npm install -g without sudo: user-level prefix on POSIX."""
    if not _ensure_node(tool):
        return False
    env = {}
    if _SYS != "Windows":
        prefix = Path.home() / ".npm-global"
        prefix.mkdir(exist_ok=True)
        env["NPM_CONFIG_PREFIX"] = str(prefix)
        os.environ["PATH"] = str(prefix / "bin") + os.pathsep + os.environ.get("PATH", "")
    return _sh(tool, ["npm", "install", "-g", pkg], env=env)


def _pipeline(tool: str) -> bool:
    """The fully-automatic story per tool per OS. Returns overall success."""
    if tool == "node":
        return _ensure_node(tool) and _which("node.exe", "node") is not None
    if tool == "codex":
        # macOS/Linux: brew first (official formula), npm fallback; Windows: npm
        if _SYS != "Windows" and _ensure_brew(tool) and _sh(tool, ["brew", "install", "codex"]):
            _augment_path()
            if _which("codex"):
                return True
        return _npm_global(tool, "@openai/codex")
    if tool == "claude":
        if _SYS != "Windows" and _ensure_brew(tool):
            if _sh(tool, ["brew", "install", "--cask", "claude-code"]) or \
               _sh(tool, ["brew", "install", "claude-code"]):
                _augment_path()
                if _which("claude"):
                    return True
        return _npm_global(tool, "@anthropic-ai/claude-code")
    if tool == "vscode":
        if _SYS == "Windows":
            ok = _sh(tool, ["winget", "install", "-e", "--id", "Microsoft.VisualStudioCode",
                            "--silent", "--accept-package-agreements", "--accept-source-agreements"])
            return ok
        if _SYS == "Darwin":
            return _ensure_brew(tool) and _sh(tool, ["brew", "install", "--cask", "visual-studio-code"])
        # Linux: brew casks don't exist — brew formula 'code' unavailable;
        # use snap/native repo automatically instead.
        if shutil.which("snap") and _sh(tool, ["sudo", "snap", "install", "code", "--classic"]):
            return True
        return _sh(tool, _linux_cmd("code"))
    # anything else (office…) keeps the single-command behaviour
    cmd = _INSTALL_CMDS.get(tool)
    return bool(cmd) and _sh(tool, list(cmd))


def start_install(tool: str) -> dict:
    if tool not in _INSTALL_CMDS and tool not in ("node", "codex", "claude", "vscode"):
        return {"ok": False, "error": f"Unknown tool: {tool}"}
    with _LOCK:
        cur = _install_state.get(tool)
        if cur and cur["status"] == "running":
            return {"ok": True, "status": "running"}
        _install_state[tool] = {"status": "running", "log": ""}

    def worker() -> None:
        _augment_path()      # pick up tools installed after the server started
        try:
            ok = _pipeline(tool)
        except Exception as e:  # noqa: BLE001
            _log_append(tool, f"FATAL: {e}")
            ok = False
        _augment_path()
        with _LOCK:
            st = _install_state.setdefault(tool, {"status": "running", "log": ""})
            st["status"] = "done" if ok else "error"
            if ok:
                st["log"] += "\n✔ installation completed"

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "status": "running"}


# ---------------- login ----------------
def _open_terminal(command: str) -> bool:
    """Open a real interactive terminal running `command` (needed for OAuth flows)."""
    try:
        if _SYS == "Windows":
            subprocess.Popen(["cmd", "/k", command], creationflags=CREATE_NEW_CONSOLE)
        elif _SYS == "Darwin":
            subprocess.Popen(["osascript", "-e",
                              f'tell application "Terminal" to do script "{command}"'])
        else:
            for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
                if shutil.which(term):
                    subprocess.Popen([term, "-e", f"bash -c '{command}; exec bash'"])
                    break
            else:
                return False
        return True
    except OSError:
        return False


def start_login(tool: str) -> dict:
    """Open an interactive terminal so the user can complete OAuth login."""
    if tool == "codex":
        cli = _which("codex.cmd", "codex.exe", "codex")
        if not cli:
            return {"ok": False, "error": "Codex CLI is not installed yet"}
        cmd = f'"{cli}" login'
    elif tool == "claude":
        cli = _which("claude.cmd", "claude.exe", "claude")
        if not cli:
            return {"ok": False, "error": "Claude Code CLI is not installed yet"}
        cmd = f'"{cli}" login'
    elif tool == "vscode":
        cli = _which("code.cmd", "code")
        if not cli:
            return {"ok": False, "error": "VS Code is not installed yet"}
        subprocess.Popen([cli], creationflags=CREATE_NO_WINDOW)
        return {"ok": True, "message": "VS Code opened — sign in to GitHub Copilot inside VS Code (Accounts icon, bottom-left)."}
    else:
        return {"ok": False, "error": f"Unknown tool: {tool}"}
    if not _open_terminal(cmd):
        return {"ok": False, "error": "Could not open a terminal — run this manually: " + cmd}
    return {"ok": True, "message": "A terminal window opened — follow the login instructions there, then click Re-check."}
