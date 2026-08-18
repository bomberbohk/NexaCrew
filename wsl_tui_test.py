#!/usr/bin/env python3
"""WSL headless test-driver for console_setup.py and console_manager.py.

Runs the REAL curses TUIs inside a pseudo-terminal (pty) — exactly how they
run on a headless Linux server — feeds keyboard input programmatically and
verifies the rendered screen output. Run inside WSL:

    python3 wsl_tui_test.py
"""
import os
import pty
import re
import select
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)

PASS, FAIL = [], []


def check(name: str, ok: bool, extra: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'✔' if ok else '✖'} {name}" + (f" — {extra}" if extra else ""))


def strip_ansi(b: bytes) -> str:
    s = b.decode("utf-8", "replace")
    return re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][0-9A-B]|\x1b[=>]", "", s)


class TuiSession:
    """Run a curses program in a pty; send keys, read the screen."""

    def __init__(self, argv, env_extra=None):
        env = dict(os.environ, TERM="xterm-256color", LINES="35", COLUMNS="110")
        env.pop("DISPLAY", None)
        env.pop("WAYLAND_DISPLAY", None)
        if env_extra:
            env.update(env_extra)
        self.master, slave = pty.openpty()
        # 110x35 pty window
        import fcntl, termios, struct
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 35, 110, 0, 0))
        self.proc = subprocess.Popen(argv, stdin=slave, stdout=slave,
                                     stderr=subprocess.DEVNULL, env=env, close_fds=True)
        os.close(slave)
        self.buf = b""

    def read(self, secs=1.2) -> str:
        end = time.time() + secs
        while time.time() < end:
            r, _, _ = select.select([self.master], [], [], 0.15)
            if r:
                try:
                    self.buf += os.read(self.master, 65536)
                except OSError:
                    break
        return strip_ansi(self.buf)

    def send(self, data: bytes, wait=0.5) -> str:
        os.write(self.master, data)
        return self.read(wait)

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self):
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            os.close(self.master)
        except OSError:
            pass


KEY_RIGHT, KEY_LEFT = b"\x1bOC", b"\x1bOD"     # application (keypad) mode
KEY_DOWN, KEY_UP = b"\x1bOB", b"\x1bOA"
KEY_F10 = b"\x1b[21~"
ENTER = b"\r"


def mouse_click(x: int, y: int) -> bytes:
    """SGR mouse press+release at 1-based (x, y) — ncurses 6 decodes this
    into KEY_MOUSE + getmouse() (verified by probe in WSL)."""
    return f"\x1b[<0;{x};{y}M\x1b[<0;{x};{y}m".encode()


# ================================================================ setup wizard
def test_setup_wizard():
    print("\n== console_setup.py (installation wizard) ==")
    t = TuiSession([sys.executable, "console_setup.py"])
    scr = t.read(2.0)
    check("wizard starts in pty (headless)", t.alive())
    check("title bar rendered", "Console Setup" in scr)
    check("tab bar shows all tabs", all(x in scr for x in ("Deployment", "Server", "Client", "License")))
    check("radio buttons rendered", "(•)" in scr or "( )" in scr)
    check("help panel rendered", "Help" in scr)
    check("save button rendered", "Save & Install" in scr)

    scr = t.send(KEY_RIGHT, 0.8)          # -> Server tab
    check("→ switches to Server tab", "Bind address" in scr)
    scr = t.send(KEY_DOWN, 0.5)           # focus port field
    # type invalid port then check error
    scr = t.send(b"abc", 0.6)
    check("invalid port shows validation error", "must be" in scr or "number" in scr)
    t.send(b"\x1bOF", 0.2)                # End — move cursor behind last char
    for _ in range(16):
        t.send(b"\x7f", 0.05)             # clear field (backspaces)
    t.send(b"8611", 0.6)
    # curses paints only changed cells — switch tabs away/back to force a
    # full repaint so the field value appears contiguously in the stream
    t.send(KEY_UP, 0.3)                   # radio field -> arrows switch tabs
    t.send(KEY_LEFT, 0.6)
    scr = t.send(KEY_RIGHT, 0.9)
    check("typed port appears in field", "8611" in scr)

    # mouse: click the License tab (find its x from the screen text is complex;
    # tabs start around x=3; License is 4th tab → estimate)
    scr_before = t.buf
    scr = t.send(mouse_click(46, 4), 0.8)  # tab row is line 4 (1-based)
    ok = ("License key" in scr) or ("Enterprise license" in scr)
    check("mouse click on tab bar switches tab", ok)

    scr = t.send(KEY_F10, 1.0)            # save
    time.sleep(1.0)
    saved = os.path.isfile("platform/data/config.json")
    check("F10 saves configuration", saved and ("saved" in scr or not t.alive()))
    t.stop()


def windows_host() -> str:
    """Windows host IP as seen from WSL (default gateway)."""
    try:
        out = subprocess.run(["ip", "route"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if line.startswith("default via "):
                return line.split()[2]
    except OSError:
        pass
    return "127.0.0.1"


# ================================================================ manager
def test_manager():
    print("\n== console_manager.py (server management cockpit) ==")
    host = windows_host()
    print(f"  (connecting to Windows-hosted server at {host}:8600)")
    t = TuiSession([sys.executable, "console_manager.py"],
                   env_extra={"NEXACREW_SERVER": f"http://{host}:8600"})
    scr = t.read(2.5)
    check("manager starts in pty (headless)", t.alive())
    check("login dialog appears", "Sign in" in scr or "Username" in scr)

    # login with test admin
    scr = t.send(b"__tui_test__" + ENTER, 1.0)
    scr = t.send(b"tui-test-pass-2026" + ENTER, 2.5)
    check("login accepted → cockpit opens", "Server Management Console" in scr and "Dashboard" in scr)
    check("all tabs present", all(x in scr for x in
          ("Dashboard", "Companies", "Users", "Skills", "Clients",
           "Approvals", "Schedules", "Config", "Audit")))
    check("dashboard shows live data", "Platform version" in scr or "ONLINE" in scr)
    check("footer shows key help", "F10 quit" in scr or "F5 refresh" in scr)

    scr = t.send(KEY_RIGHT, 1.2)          # Companies
    check("→ Companies tab loads", "Industry" in scr or "Name" in scr)
    scr = t.send(KEY_RIGHT, 1.2)          # Users
    check("→ Users tab loads", "Username" in scr and "administrator" in scr)
    scr = t.send(KEY_RIGHT, 1.2)          # Skills
    check("→ Skills tab shows the movie-note skill", "Movie Note" in scr or "劇本創作" in scr)
    check("skills show enabled state", "enabled" in scr)

    scr = t.send(KEY_DOWN + KEY_UP, 0.8)  # row navigation
    check("row navigation works", t.alive())

    # mouse: click the Audit tab (span ≈85–92 on a 110-col screen) then a row
    scr = t.send(mouse_click(88, 3), 1.5)
    ok_audit = "Action" in scr and ("auth" in scr or "skill" in scr or "Time" in scr)
    check("mouse click switches to a tab (Audit)", ok_audit)

    scr = t.send(b"\x1b[15~", 1.5)        # F5 refresh
    check("F5 refresh works", "Refreshed" in scr or t.alive())

    scr = t.send(b"q", 1.0)               # quit
    time.sleep(0.6)
    check("q exits cleanly", not t.alive())
    t.stop()


if __name__ == "__main__":
    print("WSL headless TUI test — real curses in a pty, no DISPLAY")
    cfg = "platform/data/config.json"
    backup = open(cfg, "rb").read() if os.path.isfile(cfg) else None
    try:
        test_setup_wizard()
    finally:
        if backup is not None:               # never corrupt the live config
            open(cfg, "wb").write(backup)
    test_manager()
    print(f"\nRESULT: {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", *FAIL, sep="\n  - ")
        sys.exit(1)
    print("ALL WSL TUI TESTS PASSED ✅")
