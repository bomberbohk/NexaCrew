"""NexaCrew — Action by Prompt.
Developed by Sin Chi Chi · MAP Studio.

A system-wide "Action by prompt" command:
  •  Global hotkey  Ctrl+Alt+A  — works while ANY software is focused
     (Photoshop, Word, a browser…). Applications do not allow third parties
     to insert items into their own internal right-click menus, so the hotkey
     is the universal trigger inside every program.
  •  Real right-click menu entries where the OS allows them:
       Windows  — Explorer: every file + folder + desktop background
       macOS    — Finder: Quick Actions (Services) on files/folders
       Linux    — Nautilus/Nemo/Caja "Scripts" menu + .desktop entry

When triggered it remembers which application was in the foreground, shows a
prompt box (with file attachments), sends everything to the NexaCrew server
which plans the task with AI, and then executes the plan on this computer by
controlling the keyboard and mouse like a human.

Usage:
    python action_prompt.py listen            # background listener (hotkey)
    python action_prompt.py show [file …]     # open the prompt box now
    python action_prompt.py install-menu      # (re)install right-click menus
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "platform" / "data" / "config.json"
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"
LOG_PREFIX = "[action]"


def log(msg: str) -> None:
    print(f"{LOG_PREFIX} {msg}", flush=True)


def load_cfg() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def server_address() -> tuple:
    """(ip, port) of the NexaCrew server this machine talks to."""
    cfg = load_cfg()
    if str(cfg.get("deploy_mode") or "") == "client":
        return (str(cfg.get("client_server_ip") or "127.0.0.1"),
                int(cfg.get("client_server_port") or 8600))
    return ("127.0.0.1", int(cfg.get("server_port") or 8600))


def ensure_deps() -> None:
    """Auto-install the automation libraries on first run (quiet)."""
    missing = []
    for mod, pkg in (("pyautogui", "pyautogui"), ("pynput", "pynput"),
                     ("PIL", "Pillow")):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        log(f"Installing automation libraries: {', '.join(missing)} …")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *missing],
                       capture_output=True, timeout=600)


# ---------------- foreground application detection ----------------
def active_app() -> dict:
    """Which application is in front right now (before our dialog opens)."""
    info = {"app": "", "title": "", "os": platform.system()}
    try:
        if IS_WIN:
            import ctypes
            import ctypes.wintypes as wt
            u32 = ctypes.windll.user32
            hwnd = u32.GetForegroundWindow()
            buf = ctypes.create_unicode_buffer(512)
            u32.GetWindowTextW(hwnd, buf, 512)
            info["title"] = buf.value
            pid = wt.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
            if h:
                nbuf = ctypes.create_unicode_buffer(512)
                sz = wt.DWORD(512)
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                        h, 0, nbuf, ctypes.byref(sz)):
                    info["app"] = Path(nbuf.value).stem
                ctypes.windll.kernel32.CloseHandle(h)
        elif IS_MAC:
            out = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of first process '
                 'whose frontmost is true'],
                capture_output=True, text=True, timeout=5)
            info["app"] = out.stdout.strip()
        else:  # Linux / X11
            for cmd, key in ((["xdotool", "getactivewindow", "getwindowname"], "title"),
                             (["xdotool", "getactivewindow", "getwindowclassname"], "app")):
                try:
                    out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    info[key] = out.stdout.strip()
                except OSError:
                    break
    except Exception as e:  # noqa: BLE001
        log(f"Could not detect the foreground app: {e}")
    return info


# ---------------- prompt dialog ----------------
def show_prompt_dialog(prefill_files: list) -> "dict | None":
    """Always-on-top prompt box with attachments. Returns
    {"prompt": str, "files": [paths]} or None when cancelled."""
    import tkinter as tk
    from tkinter import filedialog

    result = {}
    win = tk.Tk()
    win.title("Action by prompt — NexaCrew")
    win.attributes("-topmost", True)
    win.geometry("560x380")
    win.configure(bg="#0f172a")

    tk.Label(win, text="⚡ Action by prompt", font=("Segoe UI", 14, "bold"),
             fg="#e2e8f0", bg="#0f172a").pack(anchor="w", padx=14, pady=(12, 2))
    tk.Label(win, text="Describe the task. The AI will control this computer "
                       "like a human to complete it.",
             fg="#94a3b8", bg="#0f172a", wraplength=520,
             justify="left").pack(anchor="w", padx=14)

    txt = tk.Text(win, height=7, font=("Segoe UI", 11), wrap="word",
                  bg="#1e293b", fg="#f1f5f9", insertbackground="#f1f5f9",
                  relief="flat", padx=8, pady=8)
    txt.pack(fill="both", expand=True, padx=14, pady=10)
    txt.focus_set()

    files = list(prefill_files)
    flabel = tk.Label(win, fg="#7dd3fc", bg="#0f172a", anchor="w",
                      wraplength=520, justify="left")
    flabel.pack(anchor="w", padx=14)

    def refresh_files() -> None:
        flabel.config(text=("📎 " + ", ".join(Path(f).name for f in files))
                      if files else "No attachment")
    refresh_files()

    def attach() -> None:
        for f in filedialog.askopenfilenames(parent=win):
            if f not in files:
                files.append(f)
        refresh_files()

    def run(_=None) -> None:
        p = txt.get("1.0", "end").strip()
        if p:
            result["prompt"] = p
            result["files"] = files
            win.destroy()

    bar = tk.Frame(win, bg="#0f172a")
    bar.pack(fill="x", padx=14, pady=(6, 12))
    tk.Button(bar, text="📎 Attach…", command=attach, bg="#334155", fg="#e2e8f0",
              relief="flat", padx=12, pady=4).pack(side="left")
    tk.Button(bar, text="Cancel", command=win.destroy, bg="#334155", fg="#e2e8f0",
              relief="flat", padx=12, pady=4).pack(side="right")
    tk.Button(bar, text="▶ Run task", command=run, bg="#2563eb", fg="white",
              relief="flat", padx=16, pady=4,
              font=("Segoe UI", 10, "bold")).pack(side="right", padx=8)
    win.bind("<Control-Return>", run)
    win.eval("tk::PlaceWindow . center")
    win.mainloop()
    return result if result.get("prompt") else None


# ---------------- ask the server for a plan ----------------
def request_plan(context: dict, prompt: str, files: list) -> dict:
    ip, port = server_address()
    key = str(load_cfg().get("license_key") or "")
    attachments = []
    for f in files:
        p = Path(f)
        entry = {"name": p.name, "path": str(p)}
        try:
            if p.suffix.lower() in (".txt", ".md", ".csv", ".json", ".html", ".docx"):
                if p.suffix.lower() == ".docx":
                    entry["note"] = "Word document — open it in the target app"
                elif p.stat().st_size <= 60_000:
                    entry["text"] = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        attachments.append(entry)
    try:
        import pyautogui
        w, h = pyautogui.size()
    except Exception:  # noqa: BLE001
        w = h = 0
    payload = json.dumps({
        "key": key, "prompt": prompt, "app": context.get("app", ""),
        "title": context.get("title", ""), "os": platform.system(),
        "screen": {"w": w, "h": h}, "attachments": attachments,
    }).encode()
    req = urllib.request.Request(
        f"http://{ip}:{port}/api/action/plan", data=payload,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


# ---------------- execute the plan like a human ----------------
def execute_plan(steps: list) -> None:
    import pyautogui
    pyautogui.FAILSAFE = True          # slam mouse to a corner = emergency stop
    pyautogui.PAUSE = 0.35             # human-like pacing between actions
    log(f"Executing {len(steps)} step(s) — move the mouse to a screen corner "
        "to abort.")
    for i, s in enumerate(steps, 1):
        act = str(s.get("action") or "").lower()
        log(f"  step {i}/{len(steps)}: {act} — {s.get('note', '')}")
        try:
            if act == "wait":
                time.sleep(float(s.get("seconds", 1)))
            elif act == "open_app":
                name = str(s.get("name", ""))
                if IS_WIN:
                    pyautogui.hotkey("win", "s"); time.sleep(1)
                    pyautogui.typewrite(name, interval=0.04); time.sleep(1.2)
                    pyautogui.press("enter")
                elif IS_MAC:
                    subprocess.Popen(["open", "-a", name])
                else:
                    subprocess.Popen([name.lower()])
                time.sleep(float(s.get("seconds", 4)))
            elif act == "open_url":
                import webbrowser
                webbrowser.open(str(s.get("url", "")))
                time.sleep(float(s.get("seconds", 4)))
            elif act == "open_file":
                p = str(s.get("path", ""))
                if IS_WIN:
                    os.startfile(p)  # noqa: S606
                else:
                    subprocess.Popen(["open" if IS_MAC else "xdg-open", p])
                time.sleep(float(s.get("seconds", 4)))
            elif act == "type":
                pyautogui.typewrite(str(s.get("text", "")), interval=0.03)
            elif act == "paste":
                _set_clipboard(str(s.get("text", "")))
                pyautogui.hotkey("command" if IS_MAC else "ctrl", "v")
            elif act == "hotkey":
                keys = [str(k) for k in (s.get("keys") or [])]
                if keys:
                    pyautogui.hotkey(*keys)
            elif act == "press":
                pyautogui.press(str(s.get("key", "enter")),
                                presses=int(s.get("times", 1)))
            elif act == "click":
                pyautogui.click(int(s.get("x", 0)), int(s.get("y", 0)),
                                clicks=int(s.get("times", 1)),
                                button=str(s.get("button", "left")))
            else:
                log(f"    (unknown action '{act}' skipped)")
        except Exception as e:  # noqa: BLE001
            log(f"    step failed: {e} — continuing")
    log("✅ Task finished.")


def _set_clipboard(text: str) -> None:
    try:
        import tkinter as tk
        r = tk.Tk(); r.withdraw()
        r.clipboard_clear(); r.clipboard_append(text)
        r.update(); r.destroy()
    except Exception:  # noqa: BLE001
        pass


def _notify(msg: str) -> None:
    log(msg)
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        messagebox.showinfo("Action by prompt — NexaCrew", msg, parent=r)
        r.destroy()
    except Exception:  # noqa: BLE001
        pass


# ---------------- one full run ----------------
def run_action(prefill_files: list) -> None:
    ctx = active_app()
    log(f"Triggered from: {ctx.get('app') or 'unknown app'} — "
        f"“{ctx.get('title', '')}”")
    ans = show_prompt_dialog(prefill_files)
    if not ans:
        return
    log("🧠 Asking the AI to plan the task…")
    try:
        res = request_plan(ctx, ans["prompt"], ans["files"])
    except Exception as e:  # noqa: BLE001
        _notify(f"Could not reach the server to plan the task: {e}")
        return
    steps = res.get("plan") or []
    if not steps:
        _notify("The AI returned no executable steps: "
                + str(res.get("note") or res.get("detail") or "unknown reason"))
        return
    time.sleep(1.0)   # let the dialog close and focus return
    execute_plan(steps)


# ---------------- right-click menu installation ----------------
def install_menu() -> None:
    py = sys.executable.replace("python.exe", "pythonw.exe") \
        if IS_WIN else sys.executable
    script = str(ROOT / "action_prompt.py")
    if IS_WIN:
        cmd = f'"{py}" "{script}" show "%1"'
        bgcmd = f'"{py}" "{script}" show'
        entries = [("*\\shell\\NexaCrewAction", cmd),
                   ("Directory\\shell\\NexaCrewAction", cmd),
                   ("Directory\\Background\\shell\\NexaCrewAction", bgcmd)]
        for base, c in entries:
            k = f"HKCU\\Software\\Classes\\{base}"
            subprocess.run(["reg", "add", k, "/ve", "/d", "Action by prompt",
                            "/f"], capture_output=True)
            subprocess.run(["reg", "add", k, "/v", "Icon", "/d",
                            "shell32.dll,25", "/f"], capture_output=True)
            subprocess.run(["reg", "add", k + "\\command", "/ve", "/d",
                            c.replace("%1", "%1"), "/f"], capture_output=True)
        log("Right-click menu installed (Explorer: files, folders, desktop).")
    elif IS_MAC:
        wf = (Path.home() / "Library" / "Services"
              / "Action by prompt.workflow" / "Contents")
        try:
            wf.mkdir(parents=True, exist_ok=True)
            (wf / "Info.plist").write_text(_MAC_INFO_PLIST, encoding="utf-8")
            (wf / "document.wflow").write_text(
                _MAC_WFLOW.replace("__CMD__", f"{py} {script} show \"$@\""),
                encoding="utf-8")
            log("Finder Quick Action installed (right-click → Quick Actions "
                "→ Action by prompt).")
        except OSError as e:
            log(f"Could not install the Finder Quick Action: {e}")
    else:
        launcher = f'#!/bin/sh\nexec "{py}" "{script}" show "$@"\n'
        for d in (Path.home() / ".local/share/nautilus/scripts",
                  Path.home() / ".local/share/nemo/scripts",
                  Path.home() / ".config/caja/scripts"):
            try:
                d.mkdir(parents=True, exist_ok=True)
                f = d / "Action by prompt"
                f.write_text(launcher, encoding="utf-8")
                f.chmod(0o755)
            except OSError:
                pass
        log("File-manager Scripts menu installed (right-click → Scripts "
            "→ Action by prompt).")


_MAC_INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>NSServices</key><array><dict>
    <key>NSMenuItem</key><dict><key>default</key>
      <string>Action by prompt</string></dict>
    <key>NSMessage</key><string>runWorkflowAsService</string>
    <key>NSSendFileTypes</key><array><string>public.item</string></array>
  </dict></array>
</dict></plist>
"""

_MAC_WFLOW = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>actions</key><array><dict><key>action</key><dict>
    <key>ActionParameters</key><dict>
      <key>COMMAND_STRING</key><string>__CMD__</string>
      <key>inputMethod</key><integer>1</integer>
      <key>shell</key><string>/bin/sh</string>
    </dict>
    <key>BundleIdentifier</key>
    <string>com.apple.RunShellScript</string>
  </dict></dict></array>
</dict></plist>
"""


# ---------------- global hotkey listener ----------------
def listen() -> None:
    ensure_deps()
    install_menu()
    from pynput import keyboard
    busy = {"v": False}

    def trigger() -> None:
        if busy["v"]:
            return
        busy["v"] = True
        try:
            run_action([])
        finally:
            busy["v"] = False

    def on_activate() -> None:
        threading.Thread(target=trigger, daemon=True).start()

    hotkey = "<ctrl>+<alt>+a"
    log("⚡ Action by prompt is active — press Ctrl+Alt+A inside ANY software "
        "(Photoshop, Word, a browser…) or use the right-click menu of your "
        "file manager. The AI will control this computer like a human.")
    with keyboard.GlobalHotKeys({hotkey: on_activate}) as h:
        h.join()


def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else "listen"
    if mode == "install-menu":
        install_menu()
    elif mode == "show":
        ensure_deps()
        files = [a for a in args[1:] if a and Path(a).exists()]
        run_action(files)
    else:
        listen()


if __name__ == "__main__":
    main()
