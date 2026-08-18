#!/usr/bin/env python3
"""NexaCrew server-status desktop widget + system tray icon + settings panel.

Launched automatically by start.py:
    python tray_widget.py widget --host <ip> --port 8600 --role server|client
    python tray_widget.py tray   --host <ip> --port 8600 --role server|client
    python tray_widget.py panel  --host <ip> --port 8600 --role server|client

Runs on Windows, macOS and Linux (Linux only when an X server / Wayland
display is available). Each mode is an isolated process so a crash of the
widget can never affect the server.

Double-clicking the tray icon (or the desktop widget) opens the status &
settings panel where the connection status is shown and every deployment
setting (server and client) can be configured.

Developed by Sin Chi Chi · MAP Studio
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

POLL_S = 5
PRODUCT = "NexaCrew"
ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "platform" / "data" / "config.json"


def probe(host: str, port: int, timeout: float = 4.0) -> dict:
    """Return {'ok': bool, 'version': str} from the server health endpoint."""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=timeout) as r:
            d = json.loads(r.read().decode())
            return {"ok": d.get("ok") is True, "version": str(d.get("version", "?"))}
    except Exception:  # noqa: BLE001
        return {"ok": False, "version": "?"}


def load_cfg() -> dict:
    try:
        if CONFIG_FILE.is_file():
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pass
    return {}


def save_cfg(updates: dict) -> None:
    cfg = load_cfg()
    cfg.update(updates)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def open_panel(host: str, port: int, role: str) -> None:
    """Open the status & settings panel as an isolated process (safe to call
    from any GUI thread — pystray's Win32/Cocoa loop must never be blocked)."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "panel",
                      "--host", host, "--port", str(port), "--role", role],
                     creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_updater(host: str, port: int, role: str) -> None:
    """Open the auto-updater window as an isolated process."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "update",
                      "--host", host, "--port", str(port), "--role", role],
                     creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_cameras(host: str, port: int, role: str) -> None:
    """Open the camera settings window as an isolated process."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "cameras",
                      "--host", host, "--port", str(port), "--role", role],
                     creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def local_version() -> str:
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8-sig").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _ver_tuple(v: str):
    out = []
    for part in str(v).strip().split("."):
        try:
            out.append(int(part))
        except ValueError:
            out.append(0)
    return tuple(out)


def _conn_label(role: str, host: str, port: int) -> str:
    if role == "client":
        return f"Server: {host}:{port}"
    return f"This machine ({host}) · port {port}"


def single_instance(mode: str, port: int) -> bool:
    """Only one tray icon / widget per port — duplicates exit silently.
    Uses an abstract localhost TCP lock (freed automatically on exit/crash)."""
    import socket
    import zlib
    # zlib.crc32 is deterministic across processes (hash() is salted!)
    lock_port = 47000 + (zlib.crc32(f"{mode}:{port}".encode()) % 1000)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", lock_port))
        s.listen(1)
        globals()["_LOCK_SOCK"] = s   # keep alive for process lifetime
        return True
    except OSError:
        s.close()
        return False


# --------------------------------------------------------------- widget ----
def run_widget(host: str, port: int, role: str) -> int:
    try:
        import tkinter as tk
    except ImportError:
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:          # no display (headless server)
        return 1

    root.title(f"{PRODUCT} status")
    root.overrideredirect(True)          # frameless widget
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.92)
    except tk.TclError:
        pass
    W, H = 240, 78
    sw = root.winfo_screenwidth()
    root.geometry(f"{W}x{H}+{sw - W - 24}+24")     # top-right corner

    bg = "#0f1626"
    frame = tk.Frame(root, bg=bg, highlightthickness=1, highlightbackground="#334")
    frame.pack(fill="both", expand=True)
    dot = tk.Label(frame, text="●", font=("Segoe UI", 16), fg="#eab308", bg=bg)
    dot.place(x=10, y=8)
    title = tk.Label(frame, text=f"{PRODUCT} — {role}", font=("Segoe UI", 11, "bold"),
                     fg="#e5e7eb", bg=bg)
    title.place(x=36, y=8)
    status = tk.Label(frame, text="checking…", font=("Segoe UI", 9), fg="#94a3b8", bg=bg)
    status.place(x=36, y=32)
    addr = tk.Label(frame, text=_conn_label(role, host, port),
                    font=("Segoe UI", 8), fg="#64748b", bg=bg)
    addr.place(x=36, y=52)

    # draggable + double-click opens the settings panel, right-click closes
    drag = {"x": 0, "y": 0}
    def press(e):
        drag["x"], drag["y"] = e.x, e.y
    def move(e):
        root.geometry(f"+{root.winfo_x() + e.x - drag['x']}+{root.winfo_y() + e.y - drag['y']}")
    for w in (frame, title, status, dot, addr):
        w.bind("<Button-1>", press)
        w.bind("<B1-Motion>", move)
        w.bind("<Double-Button-1>", lambda e: open_panel(host, port, role))
        w.bind("<Button-3>", lambda e: root.destroy())

    state = {"ok": None, "version": "?"}

    def poller():
        while True:
            state.update(probe(host, port))
            time.sleep(POLL_S)

    threading.Thread(target=poller, daemon=True).start()

    def refresh():
        if state["ok"] is True:
            dot.config(fg="#22c55e")
            status.config(text=("Connected to server" if role == "client"
                                else "Server ONLINE") + f" · v{state['version']}")
        elif state["ok"] is False:
            dot.config(fg="#ef4444")
            status.config(text="Server UNREACHABLE" if role == "client" else "Server OFFLINE")
        root.after(2000, refresh)

    refresh()
    root.mainloop()
    return 0


# ----------------------------------------------------------------- tray ----
def run_tray(host: str, port: int, role: str) -> int:
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        # self-heal: install the tray libraries, then retry once
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                            "pystray", "Pillow"], capture_output=True, timeout=300)
            import pystray
            from PIL import Image, ImageDraw
        except Exception:  # noqa: BLE001
            return 1

    def make_icon(color: str) -> "Image.Image":
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((6, 6, 58, 58), fill="#131c30", outline="#4f8ef7", width=3)
        d.ellipse((22, 22, 42, 42), fill=color)
        return img

    state = {"ok": None, "version": "?"}

    def title() -> str:
        where = _conn_label(role, host, port)
        if state["ok"] is True:
            what = "connected" if role == "client" else "ONLINE"
            return f"{PRODUCT} [{role}] — {what} · v{state['version']} · {where}"
        if state["ok"] is False:
            what = "server unreachable" if role == "client" else "server OFFLINE"
            return f"{PRODUCT} [{role}] — {what} · {where}"
        return f"{PRODUCT} [{role}] — checking… · {where}"

    icon = pystray.Icon(
        PRODUCT.lower(), make_icon("#eab308"), title(),
        menu=pystray.Menu(
            pystray.MenuItem(lambda item: title(), None, enabled=False),
            # default=True → activated by double-click on the tray icon
            pystray.MenuItem("🛠 Status & settings…",
                             lambda: open_panel(host, port, role), default=True),
            pystray.MenuItem("📷 Camera settings…",
                             lambda: open_cameras(host, port, role)),
            pystray.MenuItem("⬆ Update program…",
                             lambda: open_updater(host, port, role)),
            pystray.MenuItem("🔄 Restart",
                             lambda: _restart_program(icon)),
            pystray.MenuItem("🌐 Open " + PRODUCT,
                             lambda: webbrowser.open(f"http://{host}:{port}/")),
            pystray.MenuItem("❌ Close status icon", lambda: icon.stop()),
        ))

    def _restart_program(tray_icon) -> None:
        """Relaunch the whole client program (start.py) detached, then exit
        this process — the new instance takes over cleanly."""
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.Popen([sys.executable, str(ROOT / "start.py")],
                             creationflags=flags, cwd=str(ROOT),
                             close_fds=True)
        except OSError as e:
            # keep the current instance alive rather than leaving the user
            # with nothing running
            print(f"restart failed: {e}", file=sys.stderr)
            return
        try:
            tray_icon.stop()
        finally:
            os._exit(0)   # noqa: SLF001 — hard exit after detached relaunch

    def poller():
        last = None
        while True:
            state.update(probe(host, port))
            if state["ok"] != last:
                last = state["ok"]
                icon.icon = make_icon("#22c55e" if state["ok"] else "#ef4444")
            icon.title = title()
            time.sleep(POLL_S)

    threading.Thread(target=poller, daemon=True).start()
    icon.run()   # blocks on the platform-native main loop (Win32/Cocoa/GTK-X11)
    return 0


# ---------------------------------------------------------------- panel ----
PANEL_FIELDS = [
    # (key, label, kind) — kind: text | int | select:…
    ("deploy_mode", "Deployment mode", "select:server,client"),
    ("server_port", "Server port (server mode)", "int"),
    ("server_bind", "Bind address (0.0.0.0 = LAN, 127.0.0.1 = local only)", "text"),
    ("client_server_ip", "Server IP address (client mode)", "text"),
    ("client_server_port", "Server port (client mode)", "int"),
    ("license_key", "Client license key", "text"),
    ("cluster_role", "Cluster role", "select:standalone,controller,worker"),
    ("controller_ip", "Controller IP (worker mode)", "text"),
    ("controller_port", "Controller port (worker mode)", "int"),
    ("cluster_secret", "Cluster shared secret", "text"),
    # ---- cameras of THIS computer (used by the web client) ----
    # Internal camera: operator face capture for the operations log.
    # External camera: serial-number / document capture (and future uses).
    # Value = part of the camera device name, e.g. "integrated" or "USB".
    ("camera_internal", "Internal camera — face capture (name contains)", "text"),
    ("camera_external", "External camera — serial no. capture (name contains)", "text"),
]


def verify_admin(host: str, port: int, username: str, password: str) -> tuple[bool, str]:
    """Check the credentials against the server and require an ADMIN account.
    Returns (ok, message) — the message carries the real server error so the
    user can distinguish a wrong password from a lockout or a dead server.
    Uses /api/auth/login + cookie session — no secrets stored."""
    import http.cookiejar
    import urllib.error
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = json.dumps({"username": username, "password": password}).encode()
    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/auth/login", data=body,
                                     headers={"Content-Type": "application/json"})
        with opener.open(req, timeout=10) as r:
            d = json.loads(r.read().decode())
        user = d.get("user") or {}
        ok = bool(user.get("is_admin"))
        try:    # end the session again — the panel only needed the check
            opener.open(urllib.request.Request(
                f"http://{host}:{port}/api/auth/logout", data=b"{}",
                headers={"Content-Type": "application/json"}), timeout=5).read()
        except Exception:  # noqa: BLE001
            pass
        if ok:
            return True, ""
        return False, ("This account is valid but is NOT an administrator.\n"
                       "Sign in with an administrator account.")
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("detail", "")
        except Exception:  # noqa: BLE001
            detail = ""
        if e.code == 429:
            return False, (detail or "Too many failed attempts — the server locked "
                                     "logins from this computer.") + "\nWait 5 minutes and try again."
        if e.code == 401:
            return False, detail or "Invalid username or password."
        return False, f"Server error {e.code}: {detail or e.reason}"
    except Exception as e:  # noqa: BLE001
        return False, (f"Cannot reach the server at {host}:{port} — {e}\n"
                       "Check that the platform is running.")


def run_panel(host: str, port: int, role: str) -> int:
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        return 1

    # ---- administrator authorization gate ----
    root.withdraw()
    bg, fg, muted = "#0f1626", "#e5e7eb", "#94a3b8"
    gate = tk.Toplevel(root)
    gate.title(f"{PRODUCT} — administrator authorization")
    gate.geometry("380x230")
    gate.attributes("-topmost", True)
    gate.configure(bg=bg)
    gate.protocol("WM_DELETE_WINDOW", lambda: (gate.destroy(), root.destroy()))
    tk.Label(gate, text="🔒 Administrator authorization required",
             font=("Segoe UI", 11, "bold"), fg=fg, bg=bg).pack(pady=(16, 2))
    tk.Label(gate, text="Enter the administrator username and password\nto open the setup window.",
             font=("Segoe UI", 9), fg=muted, bg=bg).pack()
    fr = tk.Frame(gate, bg=bg)
    fr.pack(pady=8)
    tk.Label(fr, text="Username", font=("Segoe UI", 9), fg=fg, bg=bg).grid(row=0, column=0, sticky="w", pady=3)
    u_var = tk.StringVar()
    tk.Entry(fr, textvariable=u_var, width=24, bg="#131c30", fg=fg,
             insertbackground=fg, relief="flat").grid(row=0, column=1, padx=(8, 0), pady=3)
    tk.Label(fr, text="Password", font=("Segoe UI", 9), fg=fg, bg=bg).grid(row=1, column=0, sticky="w", pady=3)
    p_var = tk.StringVar()
    pw = tk.Entry(fr, textvariable=p_var, width=24, show="•", bg="#131c30", fg=fg,
                  insertbackground=fg, relief="flat")
    pw.grid(row=1, column=1, padx=(8, 0), pady=3)
    err = tk.Label(gate, text="", font=("Segoe UI", 8), fg="#f87171", bg=bg,
                   justify="center", wraplength=340)
    err.pack()
    authed = {"ok": False}

    def attempt():
        btn.config(state="disabled", text="Checking…")
        gate.update_idletasks()
        ok, msg = verify_admin(host, port, u_var.get().strip(), p_var.get())
        if ok:
            authed["ok"] = True
            gate.destroy()
            return
        # stay open — show the REAL reason and let the user try again
        err.config(text=msg)
        btn.config(state="normal", text="🔓 Authorize")
        p_var.set("")
        pw.focus_set()
        gate.geometry("380x290")

    btn = tk.Button(gate, text="🔓 Authorize", command=attempt, bg="#4f8ef7", fg="white",
                    relief="flat", padx=16, pady=6, font=("Segoe UI", 9, "bold"))
    btn.pack(pady=8)
    gate.bind("<Return>", lambda e: attempt())
    fr.winfo_children()[1].focus_set()
    root.wait_window(gate)
    if not authed["ok"]:
        try:
            root.destroy()
        except tk.TclError:
            pass
        return 1
    root.deiconify()

    root.title(f"{PRODUCT} — status & settings ({role} mode)")
    root.geometry("540x600")
    root.attributes("-topmost", True)
    root.configure(bg=bg)

    # ---- connection status section ----
    top = tk.Frame(root, bg=bg)
    top.pack(fill="x", padx=16, pady=(14, 6))
    dot = tk.Label(top, text="●", font=("Segoe UI", 18), fg="#eab308", bg=bg)
    dot.pack(side="left")
    stat = tk.Label(top, text="Checking connection…", font=("Segoe UI", 12, "bold"),
                    fg=fg, bg=bg)
    stat.pack(side="left", padx=8)
    info = tk.Label(root, text="", font=("Segoe UI", 9), fg=muted, bg=bg, justify="left")
    info.pack(fill="x", padx=16)

    state = {"ok": None, "version": "?"}

    def poller():
        while True:
            state.update(probe(host, port))
            time.sleep(POLL_S)

    threading.Thread(target=poller, daemon=True).start()

    def refresh():
        if state["ok"] is True:
            dot.config(fg="#22c55e")
            stat.config(text=("✅ Connected to server" if role == "client"
                              else "✅ Server ONLINE") + f"  ·  v{state['version']}")
        elif state["ok"] is False:
            dot.config(fg="#ef4444")
            stat.config(text="❌ Server unreachable" if role == "client" else "❌ Server OFFLINE")
        info.config(text=f"Mode: {role.upper()}    ·    {_conn_label(role, host, port)}\n"
                         f"Health endpoint: http://{host}:{port}/api/health   ·   refreshes every {POLL_S} s")
        root.after(2000, refresh)

    refresh()

    ttk.Separator(root).pack(fill="x", padx=16, pady=8)

    # ---- settings form ----
    head = tk.Label(root, text="⚙️  Deployment & cluster settings",
                    font=("Segoe UI", 11, "bold"), fg=fg, bg=bg)
    head.pack(anchor="w", padx=16)
    note = tk.Label(root, text="Saved into platform/data/config.json — changes take effect "
                               "the next time the program starts.",
                    font=("Segoe UI", 8), fg=muted, bg=bg)
    note.pack(anchor="w", padx=16, pady=(0, 6))

    form = tk.Frame(root, bg=bg)
    form.pack(fill="both", expand=True, padx=16)
    cfg = load_cfg()
    vars_: dict = {}
    for i, (key, label, kind) in enumerate(PANEL_FIELDS):
        tk.Label(form, text=label, font=("Segoe UI", 9), fg=fg, bg=bg,
                 anchor="w").grid(row=i, column=0, sticky="w", pady=3)
        val = str(cfg.get(key, "") if cfg.get(key) is not None else "")
        v = tk.StringVar(value=val)
        vars_[key] = (v, kind)
        if kind.startswith("select:"):
            opts = kind.split(":", 1)[1].split(",")
            if val not in opts:
                v.set(opts[0])
            w = ttk.Combobox(form, textvariable=v, values=opts, state="readonly", width=24)
        else:
            w = tk.Entry(form, textvariable=v, width=26, bg="#131c30", fg=fg,
                         insertbackground=fg, relief="flat")
        w.grid(row=i, column=1, sticky="ew", pady=3, padx=(10, 0))
    form.columnconfigure(1, weight=1)

    def save():
        updates: dict = {}
        for key, (v, kind) in vars_.items():
            val = v.get().strip()
            if kind == "int":
                try:
                    updates[key] = int(val)
                except ValueError:
                    messagebox.showerror(PRODUCT, f"'{val}' is not a valid number for {key}.")
                    return
            else:
                updates[key] = val
        try:
            save_cfg(updates)
            messagebox.showinfo(PRODUCT, "Settings saved ✓\n\nThey take effect the next "
                                         "time the program starts.")
        except OSError as e:
            messagebox.showerror(PRODUCT, f"Could not save settings:\n{e}")

    btns = tk.Frame(root, bg=bg)
    btns.pack(fill="x", padx=16, pady=12)
    tk.Button(btns, text="💾 Save settings", command=save, bg="#4f8ef7", fg="white",
              relief="flat", padx=14, pady=6, font=("Segoe UI", 9, "bold")).pack(side="left")
    tk.Button(btns, text="📷 Cameras…", relief="flat", padx=12, pady=6,
              command=lambda: open_cameras(host, port, role),
              bg="#131c30", fg=fg).pack(side="left", padx=8)
    tk.Button(btns, text="🌐 Open web UI", relief="flat", padx=12, pady=6,
              command=lambda: webbrowser.open(f"http://{host}:{port}/"),
              bg="#131c30", fg=fg).pack(side="left", padx=8)
    tk.Button(btns, text="Close", relief="flat", padx=12, pady=6,
              command=root.destroy, bg="#131c30", fg=fg).pack(side="right")
    credit = tk.Label(root, text=f"{PRODUCT} · Developed by Sin Chi Chi · MAP Studio",
                      font=("Segoe UI", 8), fg=muted, bg=bg)
    credit.pack(pady=(0, 8))

    root.mainloop()
    return 0


# -------------------------------------------------------------- updater ----
def run_updater(host: str, port: int, role: str) -> int:
    """Auto-updater with live progress: checks versions, downloads the
    package from the server (with a progress bar), extracts it in place
    (user data preserved) and restarts the client program."""
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        return 1

    bg, fg, muted = "#0f1626", "#e5e7eb", "#94a3b8"
    root.title(f"{PRODUCT} — program update")
    root.geometry("460x260")
    root.attributes("-topmost", True)
    root.configure(bg=bg)
    tk.Label(root, text=f"⬆ {PRODUCT} update", font=("Segoe UI", 12, "bold"),
             fg=fg, bg=bg).pack(pady=(16, 4))
    status = tk.Label(root, text="Checking versions…", font=("Segoe UI", 10),
                      fg=fg, bg=bg)
    status.pack(pady=2)
    detail = tk.Label(root, text="", font=("Segoe UI", 9), fg=muted, bg=bg)
    detail.pack()
    bar = ttk.Progressbar(root, length=380, mode="determinate", maximum=100)
    bar.pack(pady=12)
    pct = tk.Label(root, text="", font=("Segoe UI", 9), fg=muted, bg=bg)
    pct.pack()
    close_btn = tk.Button(root, text="Close", relief="flat", padx=14, pady=6,
                          command=root.destroy, bg="#131c30", fg=fg)

    def ui(fn, *a):
        root.after(0, fn, *a)

    def set_status(s, d=""):
        ui(status.config, {"text": s})
        ui(detail.config, {"text": d})

    def set_pct(p, label=""):
        ui(bar.config, {"value": p})
        ui(pct.config, {"text": label or f"{int(p)} %"})

    def finish(ok, msg):
        set_status(msg, "")
        set_pct(100 if ok else bar["value"])
        ui(close_btn.pack, {"pady": 8})

    def worker():
        import io
        import urllib.parse
        import zipfile
        cfg = load_cfg()
        # in client mode update from the company server; server mode has no upstream
        sip = str(cfg.get("client_server_ip") or "").strip() or host
        sport = int(cfg.get("client_server_port") or port)
        key = str(cfg.get("license_key") or "").strip()
        lv = local_version()
        info = probe(sip, sport)
        if not info["ok"]:
            finish(False, "❌ Server unreachable — cannot check for updates.")
            return
        sv = info["version"]
        set_pct(10, "checked")
        if _ver_tuple(sv) <= _ver_tuple(lv):
            finish(True, f"✅ Already up to date (v{lv}).")
            return
        if not key and role == "client":
            finish(False, "❌ No license key in config — cannot download the update.")
            return
        set_status(f"Downloading update v{lv} → v{sv}…", "The program package is being fetched from the server.")
        import platform as _plat
        url = (f"http://{sip}:{sport}/api/client-package?key="
               + urllib.parse.quote(key.upper())
               + "&host=" + urllib.parse.quote(_plat.node() or ""))
        try:
            buf = None
            for attempt in (1, 2):
                with urllib.request.urlopen(url, timeout=300) as r:
                    total = int(r.headers.get("Content-Length") or 0)
                    buf = io.BytesIO()
                    read = 0
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        buf.write(chunk)
                        read += len(chunk)
                        if total:
                            set_pct(10 + read / total * 60,
                                    f"{read // 1024} / {total // 1024} KB")
                # verify the archive is complete before touching any file
                buf.seek(0)
                if zipfile.is_zipfile(buf):
                    break
                if attempt == 1:
                    set_status("Package incomplete — retrying download…",
                               "The server may still be building the update package.")
                    time.sleep(5)
                else:
                    finish(False, "❌ Update failed: the downloaded package is corrupted — "
                                  "try again in a minute.")
                    return
            set_status("Installing update…", "Extracting files — user data and settings are preserved.")
            keep = ("platform/data/", ".venv/", ".venv-linux/", ".venv-mac/")
            with zipfile.ZipFile(buf) as z:
                infos = [i for i in z.infolist()
                         if not i.is_dir() and not i.filename.replace("\\", "/").startswith(keep)]
                for n, i in enumerate(infos):
                    dest = ROOT / i.filename.replace("\\", "/")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(z.read(i))
                    set_pct(70 + (n + 1) / max(len(infos), 1) * 25,
                            f"{n + 1} / {len(infos)} files")
            set_status(f"✅ Updated to v{sv} ✓", "Restarting the program…")
            set_pct(100)
            # restart the whole client program so the new code runs
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.Popen([sys.executable, str(ROOT / "start.py")],
                             creationflags=flags, cwd=str(ROOT))
            time.sleep(2)
            ui(root.destroy)
        except Exception as e:  # noqa: BLE001
            import urllib.error
            if isinstance(e, urllib.error.HTTPError):
                try:
                    detail = json.loads(e.read().decode()).get("detail", "")
                except Exception:  # noqa: BLE001
                    detail = ""
                finish(False, f"❌ Update refused by the server: {detail or e}")
            else:
                finish(False, f"❌ Update failed: {e}")

    threading.Thread(target=worker, daemon=True).start()
    root.mainloop()
    return 0


# ---------------------------------------------------------- camera setup ----
def _camera_names() -> list[str]:
    """Best-effort OS-level camera device names, in enumeration order."""
    names: list[str] = []
    try:
        if os.name == "nt":
            # DirectShow enumeration order matches OpenCV CAP_DSHOW indexes
            try:
                from pygrabber.dshow_graph import FilterGraph  # type: ignore
            except ImportError:
                subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                                "pygrabber", "comtypes"],
                               capture_output=True, timeout=300)
                from pygrabber.dshow_graph import FilterGraph  # type: ignore
            try:
                names = list(FilterGraph().get_input_devices())
            except Exception:  # noqa: BLE001
                # last resort: PnP camera classes only (order NOT guaranteed)
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-CimInstance Win32_PnPEntity | Where-Object "
                     "{ $_.PNPClass -in @('Camera','Image') } | "
                     "Select-Object -ExpandProperty Name"],
                    capture_output=True, text=True, timeout=20,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                names = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
        elif sys.platform == "darwin":
            out = subprocess.run(["system_profiler", "SPCameraDataType"],
                                 capture_output=True, text=True, timeout=20)
            names = [ln.strip().rstrip(":") for ln in out.stdout.splitlines()
                     if ln.endswith(":") and ln.startswith("    ")
                     and not ln.strip().startswith(("Model", "Unique"))]
        else:
            import glob
            for p in sorted(glob.glob("/sys/class/video4linux/video*/name")):
                try:
                    names.append(Path(p).read_text().strip())
                except OSError:
                    pass
    except Exception:  # noqa: BLE001
        pass
    return names


def detect_cameras(max_index: int = 8) -> list[dict]:
    """Camera list AS REPORTED BY THE OPERATING SYSTEM — every video device
    the OS knows about is shown, whether or not this program can open it.
    Windows: DirectShow device enumeration (same order OpenCV uses).
    macOS:   system_profiler camera inventory (AVFoundation order).
    Linux:   /dev/videoN kernel devices (index = N).
    OpenCV probing is used ONLY as a last resort when the OS reports nothing.
    Returns [{'index': int, 'name': str}]."""
    if os.name != "nt" and sys.platform != "darwin":
        # Linux: kernel device list, index = the real /dev/videoN number
        import glob
        cams = []
        for p in sorted(glob.glob("/sys/class/video4linux/video*")):
            try:
                n = int(Path(p).name.replace("video", ""))
                name = (Path(p) / "name").read_text().strip() or f"Camera {n}"
            except (OSError, ValueError):
                continue
            cams.append({"index": n, "name": name})
        if cams:
            return cams
    else:
        names = _camera_names()
        if names:
            # OS enumeration order == capture index order (DirectShow /
            # AVFoundation) — list EVERY device the OS reports
            return [{"index": i, "name": n} for i, n in enumerate(names)]

    # ---- fallback only: OS gave us nothing, probe indexes with OpenCV ----
    try:
        import cv2  # type: ignore
    except ImportError:
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                            "opencv-python", "Pillow"], capture_output=True, timeout=600)
            import cv2  # type: ignore
        except Exception:  # noqa: BLE001
            return []
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    found = []
    misses = 0
    for i in range(max_index):
        cap = cv2.VideoCapture(i, backend)
        opened = cap.isOpened()
        cap.release()
        if opened:
            found.append({"index": i, "name": f"Camera {i}"})
            misses = 0
        else:
            misses += 1
            if misses >= 3:
                break
    return found


def run_cameras(host: str, port: int, role: str) -> int:
    """Camera assignment window: auto-detected camera list, live preview and
    local persistence (platform/data/config.json — read by the presence
    beacon /api/camera on clients and /api/cameras on the server, which the
    web app uses whenever an operation needs a camera)."""
    try:
        import tkinter as tk
        from tkinter import messagebox, ttk
    except ImportError:
        return 1
    try:
        root = tk.Tk()
    except tk.TclError:
        return 1

    bg, fg, muted = "#0f1626", "#e5e7eb", "#94a3b8"
    root.title(f"{PRODUCT} — camera settings ({role} mode)")
    root.geometry("560x640")
    root.attributes("-topmost", True)
    root.configure(bg=bg)
    tk.Label(root, text="📷 Camera assignment", font=("Segoe UI", 12, "bold"),
             fg=fg, bg=bg).pack(pady=(14, 2))
    tk.Label(root, text="Assign the cameras of THIS computer. Saved locally and used\n"
                        "automatically by every operation that opens a camera.",
             font=("Segoe UI", 9), fg=muted, bg=bg, justify="center").pack()

    cfg = load_cfg()
    cams: list[dict] = []
    combo_vals: list[str] = []

    form = tk.Frame(root, bg=bg)
    form.pack(fill="x", padx=16, pady=10)
    rows = [
        ("camera_internal", "🙂 Internal camera — face recognition capture"),
        ("camera_external", "🔍 External camera — serial number capture"),
    ]
    vars_: dict[str, tk.StringVar] = {}
    combos: dict[str, "ttk.Combobox"] = {}
    for r, (key, label) in enumerate(rows):
        tk.Label(form, text=label, font=("Segoe UI", 9, "bold"), fg=fg, bg=bg,
                 anchor="w").grid(row=r * 2, column=0, sticky="w", pady=(8, 2), columnspan=2)
        v = tk.StringVar(value="detecting cameras…")
        vars_[key] = v
        cb = ttk.Combobox(form, textvariable=v, state="readonly", width=42)
        cb.grid(row=r * 2 + 1, column=0, sticky="ew", pady=2)
        combos[key] = cb
        tk.Button(form, text="▶ Preview", relief="flat", padx=10, pady=3,
                  bg="#131c30", fg=fg,
                  command=lambda k=key: start_preview(k)).grid(
            row=r * 2 + 1, column=1, padx=(8, 0))
    form.columnconfigure(0, weight=1)

    # ---- live preview area ----
    prev_head = tk.Label(root, text="Preview — select a camera and press ▶",
                         font=("Segoe UI", 9), fg=muted, bg=bg)
    prev_head.pack(pady=(6, 2))
    preview = tk.Label(root, bg="#060b16", width=64, height=17)
    preview.pack(padx=16, pady=4, fill="both", expand=True)
    prev = {"cap": None, "run": False, "img": None}

    def stop_preview():
        prev["run"] = False
        cap = prev.pop("cap", None)
        if cap is not None:
            try:
                cap.release()
            except Exception:  # noqa: BLE001
                pass
        prev["cap"] = None

    def _sel_index(key: str) -> int | None:
        sel = combos[key].current()
        if sel < 0 or sel >= len(cams):
            return None
        return cams[sel]["index"]

    def start_preview(key: str):
        idx = _sel_index(key)
        if idx is None:
            messagebox.showwarning(PRODUCT, "Select a detected camera first.", parent=root)
            return
        stop_preview()
        try:
            import cv2  # type: ignore
            from PIL import Image, ImageTk
        except ImportError:
            messagebox.showerror(PRODUCT, "Preview needs opencv-python + Pillow "
                                          "(installing in the background — try again "
                                          "in a minute).", parent=root)
            threading.Thread(target=lambda: subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q",
                 "opencv-python", "Pillow"], capture_output=True), daemon=True).start()
            return
        cam_name = vars_[key].get()
        prev_head.config(text=f"Opening {cam_name}…")
        preview.config(image="")
        prev["img"] = None
        root.update_idletasks()

        def opener():
            # try every capture backend the OS offers — different cameras
            # need different ones (e.g. virtual cams: DirectShow only;
            # some sensors: Media Foundation only)
            if os.name == "nt":
                backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
            elif sys.platform == "darwin":
                backends = [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
            else:
                backends = [cv2.CAP_V4L2, cv2.CAP_ANY]
            cap = None
            opened_no_frame = False
            for b in backends:
                c = cv2.VideoCapture(idx, b)
                if not c.isOpened():
                    c.release()
                    continue
                # warm-up: some cameras need a moment before the first frame
                got = False
                deadline = time.time() + 3.0
                while time.time() < deadline:
                    got, _ = c.read()
                    if got:
                        break
                    time.sleep(0.1)
                if got:
                    cap = c
                    break
                opened_no_frame = True
                c.release()

            def done():
                if cap is None:
                    if opened_no_frame:
                        messagebox.showerror(
                            PRODUCT,
                            f"{cam_name} opens but delivers NO video image.\n\n"
                            "This is normal for sensor devices (e.g. depth/IR "
                            "streams) — they are not picture cameras and cannot "
                            "be used for face or serial-number capture.\n"
                            "Choose a different camera.", parent=root)
                    else:
                        messagebox.showerror(
                            PRODUCT,
                            f"{cam_name} could not be opened.\n\n"
                            "Most common cause: the camera is IN USE by another "
                            "program (browser, OBS, Teams, the web page preview…).\n"
                            "Close the other program and press ▶ again.", parent=root)
                    prev_head.config(text="Preview — select a camera and press ▶")
                    return
                prev.update(cap=cap, run=True)
                prev_head.config(text=f"Live preview: {cam_name}   ·   press another "
                                      f"▶ to switch · closes with the window")
                frame()

            root.after(0, done)

        threading.Thread(target=opener, daemon=True).start()

        def frame():
            if not prev["run"] or prev["cap"] is None:
                return
            ok, img = prev["cap"].read()
            if ok:
                h, w = img.shape[:2]
                tw = max(preview.winfo_width(), 320)
                th = max(preview.winfo_height(), 240)
                scale = min(tw / w, th / h)
                img = cv2.resize(img, (int(w * scale), int(h * scale)))
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                photo = ImageTk.PhotoImage(Image.fromarray(img))
                prev["img"] = photo          # keep a reference alive
                preview.config(image=photo)
            root.after(66, frame)            # ~15 fps

    # ---- background auto-detection ----
    def detect():
        nonlocal cams, combo_vals
        cams = detect_cameras()
        # The OS often reports IDENTICAL names for several cameras (two equal
        # webcams, hubs, virtual cams). Give duplicates a stable unique name
        # — "USB Camera #1", "USB Camera #2" … (order = OS device order) — so
        # the saved assignment can never be confused between them.
        totals: dict[str, int] = {}
        for c in cams:
            totals[c["name"]] = totals.get(c["name"], 0) + 1
        seen: dict[str, int] = {}
        for c in cams:
            if totals[c["name"]] > 1:
                seen[c["name"]] = seen.get(c["name"], 0) + 1
                c["name"] = f"{c['name']} #{seen[c['name']]}"
        combo_vals = [f"[{c['index']}] {c['name']}" for c in cams]

        def apply():
            for key, cb in combos.items():
                cb.config(values=combo_vals or ["(no camera detected)"])
                saved = str(cfg.get(key) or "").strip().lower()
                saved_idx = cfg.get(key + "_index")
                pick = -1
                for n, c in enumerate(cams):
                    if saved and saved in c["name"].lower():
                        pick = n
                        break
                if pick < 0 and isinstance(saved_idx, int):
                    for n, c in enumerate(cams):
                        if c["index"] == saved_idx:
                            pick = n
                            break
                if pick < 0 and cams:
                    # sensible defaults: first camera = internal, last = external
                    pick = 0 if key == "camera_internal" else len(cams) - 1
                if pick >= 0:
                    cb.current(pick)
                else:
                    vars_[key].set("(no camera detected)")
        root.after(0, apply)

    threading.Thread(target=detect, daemon=True).start()

    def save():
        updates = {}
        for key in vars_:
            sel = combos[key].current()
            if 0 <= sel < len(cams):
                updates[key] = cams[sel]["name"]
                updates[key + "_index"] = cams[sel]["index"]
        if not updates:
            messagebox.showwarning(PRODUCT, "No camera selected.", parent=root)
            return
        try:
            save_cfg(updates)   # local persistence — server AND client
        except OSError as e:
            messagebox.showerror(PRODUCT, f"Could not save settings:\n{e}", parent=root)
            return
        # notify the local beacon (client mode) so the web app picks it up
        # instantly; on the server the config file itself is authoritative
        try:
            import urllib.parse
            q = urllib.parse.urlencode({
                "internal": updates.get("camera_internal", ""),
                "external": updates.get("camera_external", "")})
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/camera?{q}",
                                   timeout=3).read()
        except Exception:  # noqa: BLE001
            pass
        messagebox.showinfo(PRODUCT, "Camera settings saved ✓\n\nEvery face-capture "
                                     "and serial-scan operation now uses these cameras.",
                            parent=root)

    btns = tk.Frame(root, bg=bg)
    btns.pack(fill="x", padx=16, pady=10)
    tk.Button(btns, text="💾 Save camera settings", command=save, bg="#4f8ef7",
              fg="white", relief="flat", padx=14, pady=6,
              font=("Segoe UI", 9, "bold")).pack(side="left")
    tk.Button(btns, text="⟳ Re-detect", relief="flat", padx=12, pady=6,
              bg="#131c30", fg=fg,
              command=lambda: threading.Thread(target=detect, daemon=True).start()
              ).pack(side="left", padx=8)
    tk.Button(btns, text="Close", relief="flat", padx=12, pady=6,
              command=lambda: (stop_preview(), root.destroy()),
              bg="#131c30", fg=fg).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", lambda: (stop_preview(), root.destroy()))
    root.mainloop()
    stop_preview()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["widget", "tray", "panel", "update", "cameras"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8600)
    ap.add_argument("--role", default="server", choices=["server", "client"])
    a = ap.parse_args()
    if a.mode in ("widget", "tray") and not single_instance(a.mode, a.port):
        return 0    # another instance is already showing this widget
    fn = {"widget": run_widget, "tray": run_tray, "panel": run_panel,
          "update": run_updater, "cameras": run_cameras}[a.mode]
    return fn(a.host, a.port, a.role)


if __name__ == "__main__":
    sys.exit(main())
