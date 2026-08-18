#!/usr/bin/env python3
"""NexaCrew — Enterprise Installation Wizard (console TUI).

Launched by install_windows.bat / install_macos.sh / install_linux.sh after
the base tooling is installed. Data-center-grade console interface:

  · full-screen ANSI panels with box-drawing frames
  · selectable option BLOCKS driven by ←→/↑↓ arrows, TAB and ENTER
  · SERVER install  → deploy_mode=server (the server always includes the
    client capability — one machine can serve and operate at once)
  · CLIENT install  → automatic LAN discovery of running NexaCrew servers
    (UDP MAPSTUDIO-DISCOVER-V1 broadcast + HTTP /api/health subnet sweep),
    arrow-key server selection, license key entry, config written, connect.

Zero third-party dependencies — works in cmd.exe, Windows Terminal,
PowerShell, macOS Terminal and every Linux console.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "platform" / "data" / "config.json"
DISCOVER_MAGIC = "MAPSTUDIO-DISCOVER-V1"
IS_WIN = os.name == "nt"

# ---------------- ANSI console primitives ----------------
CSI = "\x1b["
RESET, BOLD, DIM = CSI + "0m", CSI + "1m", CSI + "2m"
FG_CYAN, FG_BLUE, FG_GREEN, FG_YELLOW, FG_RED, FG_WHITE, FG_GREY = (
    CSI + "36m", CSI + "94m", CSI + "92m", CSI + "93m", CSI + "91m",
    CSI + "97m", CSI + "90m")
BG_SEL = CSI + "44m"          # selected block background
HIDE_CUR, SHOW_CUR = CSI + "?25l", CSI + "?25h"

for _s in (sys.stdout, sys.stderr):
    try:
        if _s and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError, AttributeError):
        pass


def _enable_vt() -> None:
    """Enable ANSI escape processing in classic Windows consoles."""
    if not IS_WIN:
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(h, ctypes.byref(mode)):
            k32.SetConsoleMode(h, mode.value | 0x0004)  # VT processing
    except Exception:  # noqa: BLE001
        pass


def term_size() -> tuple[int, int]:
    try:
        c = os.get_terminal_size()
        return max(78, c.columns), max(24, c.lines)
    except OSError:
        return 100, 30


def clear() -> None:
    sys.stdout.write(CSI + "2J" + CSI + "H")
    sys.stdout.flush()


# ---------------- raw key input (cross-platform, no deps) ----------------
def read_key() -> str:
    """Return: 'up','down','left','right','tab','enter','esc','backspace'
    or the literal character typed."""
    if IS_WIN:
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            return {"H": "up", "P": "down", "K": "left", "M": "right"}.get(code, "")
        return {"\r": "enter", "\t": "tab", "\x1b": "esc", "\x08": "backspace"}.get(ch, ch)
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            # possible escape sequence
            import select
            if select.select([sys.stdin], [], [], 0.05)[0]:
                seq = sys.stdin.read(2)
                return {"[A": "up", "[B": "down", "[D": "left", "[C": "right"}.get(seq, "esc")
            return "esc"
        return {"\r": "enter", "\n": "enter", "\t": "tab", "\x7f": "backspace"}.get(ch, ch)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---------------- framed rendering ----------------
def banner(subtitle: str) -> list[str]:
    W = term_size()[0] - 2
    bar = "═" * W
    line = "─" * W
    def c(txt, colour=FG_WHITE):
        pad = W - _vislen(txt)
        return f"{FG_BLUE}║{RESET}{colour}{txt}{' ' * max(0, pad)}{RESET}{FG_BLUE}║{RESET}"
    return [
        f"{FG_BLUE}╔{bar}╗{RESET}",
        c(f"  {BOLD}█▀█  NEXACREW · VIRTUAL COMPANY AI AGENT PLATFORM{RESET}", FG_CYAN),
        c(f"       ENTERPRISE DEPLOYMENT INSTALLER · DATA-CENTER CONSOLE", FG_CYAN),
        f"{FG_BLUE}╟{line}╢{RESET}",
        c(f"  {subtitle}", FG_GREY),
        c(f"  Developed by Sin Chi Chiu · MAP Studio · www.mapstudiousa.com", FG_GREY),
        f"{FG_BLUE}╚{bar}╝{RESET}",
        "",
    ]


def _vislen(s: str) -> int:
    """Visible length: strip ANSI sequences."""
    import re
    return len(re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", s))


def footer(keys: str) -> str:
    W = term_size()[0] - 2
    txt = f"  {keys}"
    return f"{FG_GREY}{'─' * W}\n{txt}{RESET}"


# ---------------- selectable blocks ----------------
def choose_block(subtitle: str, prompt: str, options: list[dict],
                 footer_keys: str = "←→/↑↓/TAB select · ENTER confirm · ESC quit") -> int:
    """Full-screen chooser. `options`: [{title, lines: [...], badge}].
    Blocks are rendered side-by-side (2-up) or stacked when narrow.
    Returns the selected index (or exits on ESC)."""
    sel = 0
    while True:
        clear()
        out = banner(subtitle)
        out.append(f"  {BOLD}{prompt}{RESET}")
        out.append("")
        W = term_size()[0]
        bw = min(46, (W - 8) // 2)          # block width
        two_up = W >= (bw * 2 + 10) and len(options) > 1
        rows = [options[i:i + 2] for i in range(0, len(options), 2)] if two_up \
            else [[o] for o in options]
        idx = 0
        for row in rows:
            blocks = []
            for o in row:
                is_sel = idx == sel
                col = BG_SEL + FG_WHITE + BOLD if is_sel else FG_GREY
                edge = FG_CYAN if is_sel else FG_GREY
                mark = "▶" if is_sel else " "
                lines = [f"{edge}┌{'─' * (bw - 2)}┐{RESET}"]
                title = f"{mark} {o['title']}"
                badge = o.get("badge", "")
                pad = bw - 4 - _vislen(title) - len(badge)
                lines.append(f"{edge}│{RESET}{col} {title}{' ' * max(1, pad)}{badge} {RESET}{edge}│{RESET}")
                lines.append(f"{edge}├{'─' * (bw - 2)}┤{RESET}")
                for ln in o["lines"]:
                    body = ln[:bw - 4]
                    lines.append(f"{edge}│{RESET} {DIM if not is_sel else ''}{body}"
                                 f"{' ' * max(0, bw - 4 - _vislen(body))}{RESET} {edge}│{RESET}")
                lines.append(f"{edge}└{'─' * (bw - 2)}┘{RESET}")
                blocks.append(lines)
                idx += 1
            h = max(len(b) for b in blocks)
            for b in blocks:
                while len(b) < h:
                    b.append(" " * bw)
            for li in range(h):
                out.append("   " + "   ".join(b[li] for b in blocks))
            out.append("")
        out.append(footer(footer_keys))
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()
        k = read_key()
        if k in ("right", "down", "tab"):
            sel = (sel + 1) % len(options)
        elif k in ("left", "up"):
            sel = (sel - 1) % len(options)
        elif k == "enter":
            return sel
        elif k == "esc":
            sys.stdout.write(SHOW_CUR + RESET + "\n")
            print("Installation cancelled.")
            sys.exit(1)


def text_input(subtitle: str, prompt: str, hint: str, initial: str = "",
               mask_license: bool = False) -> str:
    """Full-screen single-field text input with live echo."""
    buf = list(initial)
    while True:
        clear()
        out = banner(subtitle)
        out.append(f"  {BOLD}{prompt}{RESET}")
        out.append(f"  {DIM}{hint}{RESET}")
        out.append("")
        shown = "".join(buf)
        if mask_license:
            raw = "".join(c for c in shown.upper() if c.isalnum())[:20]
            shown = "-".join(raw[i:i + 5] for i in range(0, len(raw), 5))
        W = term_size()[0]
        bw = min(56, W - 10)
        out.append(f"   {FG_CYAN}┌{'─' * bw}┐{RESET}")
        out.append(f"   {FG_CYAN}│{RESET} {FG_WHITE}{BOLD}{shown}{RESET}"
                   f"{FG_CYAN}▌{RESET}{' ' * max(0, bw - 3 - _vislen(shown))}{FG_CYAN}│{RESET}")
        out.append(f"   {FG_CYAN}└{'─' * bw}┘{RESET}")
        out.append("")
        out.append(footer("Type · BACKSPACE erase · ENTER confirm · ESC skip (empty)"))
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()
        k = read_key()
        if k == "enter":
            return shown.strip()
        if k == "esc":
            return ""
        if k == "backspace":
            if buf:
                buf.pop()
        elif len(k) == 1 and k.isprintable():
            buf.append(k)


def progress_screen(subtitle: str, title: str, worker, poll_state: dict) -> None:
    """Animated progress panel while `worker` (a Thread) runs.
    poll_state: {'msg': str, 'done': bool} updated by the worker."""
    frames = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    while not poll_state.get("done"):
        clear()
        out = banner(subtitle)
        out.append(f"  {BOLD}{title}{RESET}")
        out.append("")
        out.append(f"   {FG_CYAN}{frames[i % len(frames)]}{RESET}  {poll_state.get('msg', '…')}")
        out.append("")
        out.append(footer("Please wait — this is automatic"))
        sys.stdout.write("\n".join(out) + "\n")
        sys.stdout.flush()
        i += 1
        time.sleep(0.12)
    worker.join(timeout=1)


# ---------------- LAN server discovery ----------------
def _local_ips() -> list[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips or ["192.168.1.100"]


def _http_health(ip: str, port: int = 8600, timeout: float = 1.2) -> dict | None:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{ip}:{port}/api/health", timeout=timeout) as r:
            d = json.loads(r.read().decode())
            if d.get("ok") and d.get("product"):
                return {"host": ip, "port": port, "name": d.get("node") or ip,
                        "version": d.get("version", "?"), "src": "http"}
    except Exception:  # noqa: BLE001
        return None
    return None


def discover_servers(state: dict) -> list[dict]:
    """UDP broadcast probe (fast) + parallel HTTP sweep of the local /24
    subnets on port 8600 (thorough). Deduplicated by host:port."""
    found: dict[str, dict] = {}

    # 1) UDP broadcast — servers answer instantly
    state["msg"] = "Broadcasting discovery probe (UDP 8601)…"
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.4)
        targets = ["255.255.255.255", "<broadcast>"]
        for ip in _local_ips():
            targets.append(".".join(ip.split(".")[:3]) + ".255")
        for t in targets:
            try:
                sock.sendto(DISCOVER_MAGIC.encode(), (t, 8601))
            except OSError:
                continue
        end = time.time() + 2.0
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(4096)
                info = json.loads(data.decode("utf-8", "ignore"))
                if info.get("magic") == DISCOVER_MAGIC:
                    host = info.get("host") or addr[0]
                    found[f"{host}:{info.get('port', 8600)}"] = {
                        "host": host, "port": int(info.get("port", 8600)),
                        "name": info.get("name", host), "version": "",
                        "src": "udp"}
            except (socket.timeout, ValueError, OSError):
                continue
        sock.close()
    except OSError:
        pass

    # 2) HTTP sweep of every local /24 on port 8600 (finds servers whose
    #    UDP responder is blocked by a firewall)
    subnets = sorted({".".join(ip.split(".")[:3]) for ip in _local_ips()})
    lock = threading.Lock()
    scanned = {"n": 0}
    total = 254 * len(subnets)

    def probe(ip: str) -> None:
        r = _http_health(ip)
        with lock:
            scanned["n"] += 1
            state["msg"] = (f"Scanning network for NexaCrew servers… "
                            f"{scanned['n']}/{total} hosts checked · "
                            f"{len(found)} found")
            if r:
                key = f"{r['host']}:{r['port']}"
                if key not in found or not found[key].get("version"):
                    found[key] = r

    threads = []
    for net in subnets:
        for i in range(1, 255):
            th = threading.Thread(target=probe, args=(f"{net}.{i}",), daemon=True)
            threads.append(th)
    # bounded concurrency: 64 at a time
    for i in range(0, len(threads), 64):
        batch = threads[i:i + 64]
        for th in batch:
            th.start()
        for th in batch:
            th.join(timeout=3)

    # enrich UDP finds with version info
    for rec in list(found.values()):
        if not rec.get("version"):
            h = _http_health(rec["host"], rec["port"])
            if h:
                rec["version"] = h["version"]
    return sorted(found.values(), key=lambda r: r["host"])


# ---------------- config ----------------
def write_config(updates: dict) -> None:
    cfg = {}
    try:
        if CONFIG_FILE.is_file():
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        cfg = {}
    cfg.update(updates)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


# ---------------- wizard flow ----------------
def main() -> None:
    _enable_vt()
    if not (sys.stdin and sys.stdin.isatty()):
        # unattended install (no console) → default to SERVER role
        write_config({"deploy_mode": "server"})
        print("[wizard] no interactive console detected -> SERVER role configured")
        os.chdir(ROOT)
        os.execv(sys.executable, [sys.executable, str(ROOT / "start.py")])
        return
    sys.stdout.write(HIDE_CUR)
    try:
        sub = "ROLE SELECTION — how will this computer be used?"
        role = choose_block(
            sub,
            "Select the deployment role of THIS computer:",
            [
                {"title": "🏢 SERVER", "badge": "RECOMMENDED FIRST",
                 "lines": [
                     "Runs the platform for the whole company.",
                     "Includes the full CLIENT capability too —",
                     "this machine can also be used as a normal",
                     "operator workstation at the same time.",
                     "Web UI, agents, POS, workforce, database.",
                 ]},
                {"title": "🖥 CLIENT", "badge": "WORKSTATION",
                 "lines": [
                     "Connects this computer to an existing",
                     "NexaCrew server on your network.",
                     "The wizard scans the LAN automatically",
                     "and lists every server it finds.",
                     "Requires a license key from your admin.",
                 ]},
            ])

        if role == 0:
            # ---------------- SERVER ----------------
            write_config({"deploy_mode": "server"})
            clear()
            out = banner("SERVER INSTALLATION")
            out.append(f"  {FG_GREEN}✔ Configured as SERVER (server + client capability).{RESET}")
            out.append(f"  {DIM}The platform now installs its environment and starts —")
            out.append(f"  the web console opens automatically at http://127.0.0.1:8600{RESET}")
            out.append("")
            out.append(footer("Starting…"))
            sys.stdout.write("\n".join(out) + "\n" + SHOW_CUR + RESET)
            sys.stdout.flush()
            time.sleep(1.5)
        else:
            # ---------------- CLIENT ----------------
            state = {"msg": "Starting discovery…", "done": False, "servers": []}

            def scan():
                state["servers"] = discover_servers(state)
                state["done"] = True

            th = threading.Thread(target=scan, daemon=True)
            th.start()
            progress_screen("CLIENT INSTALLATION — network discovery",
                            "Searching your network for NexaCrew servers…", th, state)
            servers = state["servers"]

            opts = []
            for s_ in servers:
                opts.append({"title": f"🌐 {s_['host']}:{s_['port']}",
                             "badge": s_.get("version") and f"v{s_['version']}" or "",
                             "lines": [f"Node: {s_.get('name', '?')}",
                                       f"Found via {('UDP broadcast' if s_.get('src') == 'udp' else 'HTTP scan')}",
                                       "ENTER to connect this workstation."]})
            opts.append({"title": "✎ Enter server address manually", "badge": "",
                         "lines": ["Type the IP address of the server",
                                   "if it is on another subnet or VPN."]})
            opts.append({"title": "⟳ Scan the network again", "badge": "",
                         "lines": ["Repeat the automatic discovery."]})

            while True:
                pick = choose_block(
                    f"CLIENT INSTALLATION — {len(servers)} server(s) found on your network",
                    "Select the company server this workstation must connect to:",
                    opts)
                if pick < len(servers):
                    server_ip = servers[pick]["host"]
                    server_port = int(servers[pick]["port"])
                    break
                if pick == len(servers):  # manual
                    addr = text_input("CLIENT INSTALLATION — manual server address",
                                      "Server IP address (and optional :port):",
                                      "Example: 192.168.1.50   or   192.168.1.50:8600")
                    if addr:
                        server_ip, _, p = addr.partition(":")
                        server_port = int(p or 8600)
                        break
                else:  # rescan
                    state.update(msg="Restarting discovery…", done=False)
                    th = threading.Thread(target=scan, daemon=True)
                    th.start()
                    progress_screen("CLIENT INSTALLATION — network discovery",
                                    "Searching your network for NexaCrew servers…", th, state)
                    servers = state["servers"]
                    opts = opts[:0]
                    for s_ in servers:
                        opts.append({"title": f"🌐 {s_['host']}:{s_['port']}",
                                     "badge": s_.get("version") and f"v{s_['version']}" or "",
                                     "lines": [f"Node: {s_.get('name', '?')}",
                                               f"Found via {('UDP broadcast' if s_.get('src') == 'udp' else 'HTTP scan')}",
                                               "ENTER to connect this workstation."]})
                    opts.append({"title": "✎ Enter server address manually", "badge": "",
                                 "lines": ["Type the IP address of the server."]})
                    opts.append({"title": "⟳ Scan the network again", "badge": "",
                                 "lines": ["Repeat the automatic discovery."]})

            key = text_input("CLIENT INSTALLATION — license key",
                             "License key for this workstation:",
                             "Format XXXXX-XXXXX-XXXXX-XXXXX — provided by your administrator. "
                             "ESC to skip (can be entered later in the web page).",
                             mask_license=True)

            write_config({"deploy_mode": "client",
                          "client_server_ip": server_ip,
                          "client_server_port": server_port,
                          **({"license_key": key} if key else {})})
            clear()
            out = banner("CLIENT INSTALLATION — complete")
            out.append(f"  {FG_GREEN}✔ Configured as CLIENT of {server_ip}:{server_port}"
                       + (f" · license {key}" if key else "") + f"{RESET}")
            out.append(f"  {DIM}The program now starts, connects to the server and puts")
            out.append(f"  its icon into the system tray / menu bar.{RESET}")
            out.append("")
            out.append(footer("Starting…"))
            sys.stdout.write("\n".join(out) + "\n" + SHOW_CUR + RESET)
            sys.stdout.flush()
            time.sleep(1.5)
    finally:
        sys.stdout.write(SHOW_CUR + RESET)
        sys.stdout.flush()

    # hand over to the launcher (venv, dependencies, tray, beacon/server)
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, str(ROOT / "start.py")])


if __name__ == "__main__":
    main()
