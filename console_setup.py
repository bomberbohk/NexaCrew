#!/usr/bin/env python3
"""NexaCrew — enterprise console-mode setup wizard (TUI).

Runs automatically on Linux servers without X11/Wayland (headless), or on
demand with:  python start.py --console-setup

Features
--------
* Full-screen professional TUI built on curses (no external dependencies).
* Tab bar — switch tabs with ←/→ or by clicking with the MOUSE.
* Field navigation with ↑/↓ or Tab / Shift+Tab, editing with the keyboard;
  every field can also be clicked with the mouse.
* Radio buttons (Space/Enter to select), text fields with cursor editing,
  live validation and inline help for every setting.
* Writes platform/data/config.json — the same file the web UI manages.
* F10 or the [ Save & Install ] button applies and continues installation.
"""

from __future__ import annotations

import curses
import ipaddress
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "platform" / "data" / "config.json"

# ---------------------------------------------------------------- model
DEFAULTS = {
    "deploy_mode": "server",
    "server_bind": "0.0.0.0",
    "server_port": 8600,
    "client_server_ip": "",
    "client_server_port": 8600,
    "license_key": "",
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_FILE.is_file():
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
            cfg.update({k: data[k] for k in DEFAULTS if k in data})
            cfg["_extra"] = {k: v for k, v in data.items() if k not in DEFAULTS}
    except (OSError, ValueError):
        pass
    cfg.setdefault("_extra", {})
    return cfg


def save_config(cfg: dict) -> None:
    out = dict(cfg.get("_extra", {}))
    out.update({k: cfg[k] for k in DEFAULTS})
    out["server_port"] = int(out["server_port"])
    out["client_server_port"] = int(out["client_server_port"])
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(out, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- widgets
class Field:
    """A single editable setting."""

    def __init__(self, key: str, label: str, help_text: str, kind: str = "text",
                 options: "list[tuple[str, str]] | None" = None,
                 validate=None, secret: bool = False):
        self.key = key
        self.label = label
        self.help = help_text
        self.kind = kind            # text | radio
        self.options = options or []
        self.validate = validate
        self.secret = secret
        self.cursor = 0
        self.error = ""
        self.y = 0                  # screen row where drawn (for mouse hits)


def _v_port(s: str) -> str:
    try:
        p = int(s)
        return "" if 1 <= p <= 65535 else "Port must be 1–65535"
    except ValueError:
        return "Port must be a number"


def _v_ip(s: str) -> str:
    if not s:
        return ""
    try:
        ipaddress.ip_address(s)
        return ""
    except ValueError:
        return "" if all(p and p.replace("-", "").isalnum() for p in s.split(".")) \
            else "Enter a valid IPv4/IPv6 address or hostname"


def _v_bind(s: str) -> str:
    if s in ("0.0.0.0", "127.0.0.1", "localhost", ""):
        return ""
    return _v_ip(s)


TABS: "list[tuple[str, list[Field]]]" = [
    ("Deployment", [
        Field("deploy_mode", "Deployment mode",
              "SERVER runs the full platform on this machine. CLIENT connects "
              "to an existing company server and runs nothing locally.",
              kind="radio",
              options=[("server", "Server — run the platform on this machine"),
                       ("client", "Client — connect to a company server")]),
    ]),
    ("Server", [
        Field("server_bind", "Bind address",
              "0.0.0.0 accepts connections from the whole network (recommended "
              "for a company server). 127.0.0.1 = this machine only.",
              validate=_v_bind),
        Field("server_port", "Server port",
              "TCP port for the web UI and the API. Default: 8600.",
              validate=_v_port),
    ]),
    ("Client", [
        Field("client_server_ip", "Company server IP",
              "IP address or hostname of the company server this client "
              "connects to. Only used in CLIENT mode.",
              validate=_v_ip),
        Field("client_server_port", "Company server port",
              "Port of the company server. Default: 8600.",
              validate=_v_port),
    ]),
    ("License", [
        Field("license_key", "License key",
              "Enterprise license key (leave empty for the free tier). "
              "Clients send it to the server on every heartbeat.",
              secret=False),
    ]),
]


# ---------------------------------------------------------------- painting
def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)    # header
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)    # active tab
    curses.init_pair(3, curses.COLOR_CYAN, -1)                    # inactive tab
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)   # focused field
    curses.init_pair(5, curses.COLOR_YELLOW, -1)                  # help
    curses.init_pair(6, curses.COLOR_RED, -1)                     # error
    curses.init_pair(7, curses.COLOR_GREEN, -1)                   # ok / footer keys
    curses.init_pair(8, curses.COLOR_WHITE, curses.COLOR_GREEN)   # save button


class Wizard:
    def __init__(self, stdscr):
        self.s = stdscr
        self.cfg = load_config()
        self.tab = 0
        self.row = 0                 # focused field index inside the tab
        self.on_save_btn = False
        self.msg = ""
        self.tab_spans: "list[tuple[int, int, int]]" = []   # (x0, x1, idx)
        self.btn_span = (0, 0, 0)    # y, x0, x1

    # ---------- drawing ----------
    def draw(self) -> None:
        s = self.s
        s.erase()
        h, w = s.getmaxyx()
        # header — enterprise NOC bar
        left = " █▀█ NEXACREW · ENTERPRISE DEPLOYMENT CONSOLE · CONFIGURATION "
        right = " ● LOCAL NODE "
        pad = max(1, w - 1 - len(left) - len(right))
        s.attron(curses.color_pair(1) | curses.A_BOLD)
        s.addstr(0, 0, (left + " " * pad + right)[: w - 1])
        s.attroff(curses.color_pair(1) | curses.A_BOLD)
        sub = " HEADLESS SETUP · ←→ TABS · ↑↓ FIELDS · TYPE TO EDIT · F10 SAVE · MOUSE ENABLED "
        s.addstr(1, 0, sub[: w - 1], curses.color_pair(5))
        # tab bar
        x = 2
        self.tab_spans = []
        for i, (name, _) in enumerate(TABS):
            label = f"  {name}  "
            attr = curses.color_pair(2) | curses.A_BOLD if i == self.tab else curses.color_pair(3)
            if x + len(label) < w:
                s.addstr(3, x, label, attr)
            self.tab_spans.append((x, x + len(label), i))
            x += len(label) + 1
        s.hline(4, 1, curses.ACS_HLINE, w - 2)
        # fields of active tab
        fields = TABS[self.tab][1]
        y = 6
        for i, f in enumerate(fields):
            f.y = y
            focused = (i == self.row) and not self.on_save_btn
            s.addstr(y, 4, f.label + ":", curses.A_BOLD)
            if f.kind == "radio":
                for j, (val, text) in enumerate(f.options):
                    mark = "(•)" if self.cfg[f.key] == val else "( )"
                    attr = curses.color_pair(4) if focused and self.cfg.get("_radio", 0) == j and focused else 0
                    line = f"  {mark} {text}"
                    s.addstr(y + 1 + j, 6, line[: w - 8],
                             curses.color_pair(4) if focused and self._radio_idx(f) == j else 0)
                y += 1 + len(f.options)
            else:
                val = str(self.cfg[f.key])
                shown = ("•" * len(val)) if f.secret else val
                box = f" {shown.ljust(max(28, len(shown) + 1))} "
                s.addstr(y + 1, 6, box[: w - 8],
                         curses.color_pair(4) if focused else curses.A_UNDERLINE)
                if focused:
                    cx = 7 + min(f.cursor, len(shown))
                    if cx < w - 2:
                        s.move(y + 1, cx)
                y += 2
            if f.error:
                s.addstr(y, 6, "✖ " + f.error[: w - 10], curses.color_pair(6))
                y += 1
            y += 1
        # help panel for the focused field
        if not self.on_save_btn and fields:
            f = fields[self.row]
            s.hline(h - 6, 1, curses.ACS_HLINE, w - 2)
            s.addstr(h - 5, 2, "ℹ Help", curses.color_pair(5) | curses.A_BOLD)
            for k, chunk in enumerate(_wrap(f.help, w - 6)[:2]):
                s.addstr(h - 4 + k, 4, chunk, curses.color_pair(5))
        # save button
        btn = "  💾 Save & Install (F10)  "
        bx = max(2, (w - len(btn)) // 2)
        by = h - 2
        self.btn_span = (by, bx, bx + len(btn))
        s.addstr(by, bx, btn, (curses.color_pair(8) | curses.A_BOLD)
                 if self.on_save_btn else curses.color_pair(7) | curses.A_REVERSE)
        # status message
        if self.msg:
            s.addstr(h - 3, 2, self.msg[: w - 4], curses.color_pair(7) | curses.A_BOLD)
        s.refresh()

    def _radio_idx(self, f: Field) -> int:
        for j, (val, _) in enumerate(f.options):
            if self.cfg[f.key] == val:
                return j
        return 0

    # ---------- events ----------
    def handle_key(self, ch: int) -> "bool | None":
        fields = TABS[self.tab][1]
        f = fields[self.row] if fields else None
        if ch in (curses.KEY_F10,):
            return self.save()
        if ch == 27:                                   # ESC
            return False
        if ch == curses.KEY_LEFT and (f is None or f.kind == "radio" or self.on_save_btn):
            self.tab = (self.tab - 1) % len(TABS); self.row = 0; self.on_save_btn = False; return None
        if ch == curses.KEY_RIGHT and (f is None or f.kind == "radio" or self.on_save_btn):
            self.tab = (self.tab + 1) % len(TABS); self.row = 0; self.on_save_btn = False; return None
        if ch in (curses.KEY_DOWN, 9):                 # down / Tab
            if self.on_save_btn:
                self.on_save_btn = False; self.row = 0
            elif self.row < len(fields) - 1:
                self.row += 1
            else:
                self.on_save_btn = True
            return None
        if ch in (curses.KEY_UP, curses.KEY_BTAB):
            if self.on_save_btn:
                self.on_save_btn = False; self.row = len(fields) - 1
            elif self.row > 0:
                self.row -= 1
            return None
        if self.on_save_btn:
            if ch in (10, 13, curses.KEY_ENTER, 32):
                return self.save()
            return None
        if f is None:
            return None
        if f.kind == "radio":
            if ch in (32, 10, 13, curses.KEY_ENTER):
                j = (self._radio_idx(f) + 1) % len(f.options)
                self.cfg[f.key] = f.options[j][0]
            return None
        # ---- text editing ----
        val = str(self.cfg[f.key])
        if ch == curses.KEY_LEFT:
            f.cursor = max(0, f.cursor - 1)
        elif ch == curses.KEY_RIGHT:
            f.cursor = min(len(val), f.cursor + 1)
        elif ch in (curses.KEY_HOME,):
            f.cursor = 0
        elif ch in (curses.KEY_END,):
            f.cursor = len(val)
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            if f.cursor > 0:
                self.cfg[f.key] = val[: f.cursor - 1] + val[f.cursor:]
                f.cursor -= 1
        elif ch == curses.KEY_DC:
            self.cfg[f.key] = val[: f.cursor] + val[f.cursor + 1:]
        elif 32 <= ch < 127:
            self.cfg[f.key] = val[: f.cursor] + chr(ch) + val[f.cursor:]
            f.cursor += 1
        f.error = f.validate(str(self.cfg[f.key])) if f.validate else ""
        return None

    def handle_mouse(self) -> "bool | None":
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return None
        if not (bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED
                          | curses.BUTTON1_RELEASED)):
            return None
        # tab bar click
        if my == 3:
            for x0, x1, i in self.tab_spans:
                if x0 <= mx < x1:
                    self.tab = i; self.row = 0; self.on_save_btn = False
                    return None
        # save button click
        by, bx0, bx1 = self.btn_span
        if my == by and bx0 <= mx < bx1:
            return self.save()
        # field click
        fields = TABS[self.tab][1]
        for i, f in enumerate(fields):
            span = 1 + (len(f.options) if f.kind == "radio" else 1)
            if f.y <= my <= f.y + span:
                self.row = i; self.on_save_btn = False
                if f.kind == "radio":
                    j = my - (f.y + 1)
                    if 0 <= j < len(f.options):
                        self.cfg[f.key] = f.options[j][0]
                else:
                    f.cursor = len(str(self.cfg[f.key]))
                return None
        return None

    # ---------- actions ----------
    def save(self) -> "bool | None":
        # validate everything
        for tname, fields in TABS:
            for f in fields:
                if f.validate:
                    err = f.validate(str(self.cfg[f.key]))
                    f.error = err
                    if err:
                        self.tab = [t for t, _ in TABS].index(tname)
                        self.row = fields.index(f)
                        self.on_save_btn = False
                        self.msg = f"⚠ Fix the highlighted problem in the {tname} tab first."
                        return None
        if self.cfg["deploy_mode"] == "client" and not str(self.cfg["client_server_ip"]).strip():
            self.tab = 2; self.row = 0; self.on_save_btn = False
            self.msg = "⚠ CLIENT mode needs the company server IP (Client tab)."
            return None
        save_config(self.cfg)
        self.msg = f"✔ Configuration saved to {CONFIG_FILE}"
        return True

    # ---------- main loop ----------
    def run(self) -> bool:
        curses.curs_set(1)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        # enable xterm mouse (also inside tmux/screen/WSL consoles)
        print("\033[?1003h", end="", flush=True)
        try:
            while True:
                self.draw()
                ch = self.s.getch()
                if ch == curses.KEY_MOUSE:
                    r = self.handle_mouse()
                else:
                    r = self.handle_key(ch)
                if r is True:
                    self.draw()
                    curses.napms(700)
                    return True
                if r is False:
                    return False
        finally:
            print("\033[?1003l", end="", flush=True)


def _wrap(text: str, width: int) -> "list[str]":
    words, lines, cur = text.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > width:
            lines.append(cur); cur = wd
        else:
            cur = (cur + " " + wd).strip()
    if cur:
        lines.append(cur)
    return lines


def run_console_setup() -> bool:
    """Launch the TUI. Returns True when the user saved the configuration,
    False when they cancelled (ESC)."""
    try:
        return bool(curses.wrapper(_main))
    except curses.error as e:
        print(f"[setup] Console UI unavailable ({e}) — falling back to plain prompts.")
        return _plain_fallback()


def _main(stdscr) -> bool:
    _init_colors()
    return Wizard(stdscr).run()


def _plain_fallback() -> bool:
    """Minimal Q&A fallback for exotic terminals without curses support."""
    cfg = load_config()
    print("\n=== NexaCrew console setup (plain mode) ===")
    mode = input(f"Deployment mode [server/client] ({cfg['deploy_mode']}): ").strip() or cfg["deploy_mode"]
    cfg["deploy_mode"] = "client" if mode.lower().startswith("c") else "server"
    if cfg["deploy_mode"] == "server":
        cfg["server_bind"] = input(f"Bind address ({cfg['server_bind']}): ").strip() or cfg["server_bind"]
        cfg["server_port"] = input(f"Port ({cfg['server_port']}): ").strip() or cfg["server_port"]
    else:
        cfg["client_server_ip"] = input(f"Server IP ({cfg['client_server_ip']}): ").strip() or cfg["client_server_ip"]
        cfg["client_server_port"] = input(f"Server port ({cfg['client_server_port']}): ").strip() or cfg["client_server_port"]
    cfg["license_key"] = input(f"License key ({cfg['license_key'] or 'none'}): ").strip() or cfg["license_key"]
    save_config(cfg)
    print(f"[setup] Configuration saved to {CONFIG_FILE}")
    return True


if __name__ == "__main__":
    ok = run_console_setup()
    raise SystemExit(0 if ok else 1)
