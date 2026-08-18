#!/usr/bin/env python3
"""NexaCrew — enterprise console-mode SERVER MANAGEMENT (TUI).

The full management cockpit for headless Linux servers (no X11/Wayland):
everything the web UI can do, driven from the console over the same REST API.

  python start.py --console-manage        (or: python console_manager.py)

Controls
--------
  ←/→ or Tab .... switch management tabs        (mouse: click a tab)
  ↑/↓ .......... move through rows / fields    (mouse: click a row)
  PgUp/PgDn ..... scroll long lists
  Enter/Space ... primary action on the selected row (toggle / approve / edit)
  e ............. edit selected item      d ..... delete (with confirmation)
  n ............. create new item         F5 .... refresh data
  F10 / q ....... quit                    ESC ... cancel dialog
  Mouse ......... full support — tabs, rows, buttons, dialogs

Tabs: Dashboard · Companies · Users · Skills · Clients · Approvals ·
      Schedules · Config · Audit
"""

from __future__ import annotations

import curses
import json
import os
import sys
import textwrap
import urllib.error
import urllib.request
from datetime import datetime
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "platform" / "data" / "config.json"


# ================================================================ API client
class Api:
    """Session-cookie REST client for the platform API."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.user: "dict | None" = None

    def call(self, method: str, path: str, body: "dict | None" = None,
             timeout: int = 20):
        url = f"{self.base}/api{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode()).get("detail", str(e))
            except Exception:  # noqa: BLE001
                detail = str(e)
            raise ApiError(f"{e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ApiError(f"server unreachable ({e})") from e

    def get(self, path):  return self.call("GET", path)
    def post(self, path, body=None): return self.call("POST", path, body or {})
    def put(self, path, body=None):  return self.call("PUT", path, body or {})
    def delete(self, path): return self.call("DELETE", path)

    def upload(self, path: str, filename: str, data: bytes, timeout: int = 120):
        """multipart/form-data file upload (backup restore etc.)."""
        boundary = "----NexaCrewConsole" + os.urandom(8).hex()
        body = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: application/json\r\n\r\n").encode() + data + \
               f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self.base}/api{path}", data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with self.opener.open(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read().decode()).get("detail", str(e))
            except Exception:  # noqa: BLE001
                detail = str(e)
            raise ApiError(f"{e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ApiError(f"server unreachable ({e})") from e

    def login(self, username: str, password: str) -> None:
        r = self.post("/auth/login", {"username": username, "password": password})
        self.user = r.get("user")

    def needs_setup(self) -> bool:
        return bool(self.get("/auth/me").get("needs_setup"))

    def first_admin(self, username: str, password: str) -> None:
        r = self.post("/auth/setup", {"username": username, "password": password})
        self.user = r.get("user")


class ApiError(Exception):
    pass


def server_url() -> str:
    # explicit override for remote management: NEXACREW_SERVER=http://host:port
    env = os.environ.get("NEXACREW_SERVER", "").strip()
    if env:
        return env if env.startswith("http") else f"http://{env}"
    port = 8600
    try:
        if CONFIG_FILE.is_file():
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
            if cfg.get("deploy_mode") == "client" and cfg.get("client_server_ip"):
                return f"http://{cfg['client_server_ip']}:{cfg.get('client_server_port', 8600)}"
            port = int(cfg.get("server_port", 8600))
    except (OSError, ValueError):
        pass
    return f"http://127.0.0.1:{port}"


# ================================================================ tab model
class Tab:
    """One management tab: fetches rows, renders columns, offers actions."""
    name = "?"
    columns: "list[tuple[str, int]]" = []          # (header, width)

    def __init__(self, api: Api):
        self.api = api
        self.rows: list = []
        self.error = ""

    def refresh(self) -> None: ...
    def cells(self, row) -> "list[str]": return []
    def actions(self) -> "list[tuple[str, str]]": return []   # (key, label)
    def act(self, key: str, row, ui) -> str: return ""        # returns status msg


def _ts(s: str) -> str:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "")).strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(s or "")[:16]


class DashboardTab(Tab):
    name = "Dashboard"
    columns = [("Metric", 34), ("Value", 60)]

    def refresh(self):
        d = self.api.get("/dashboard")
        s = self.api.get("/system-status")
        h = self.api.get("/health")
        v = self.api.get("/version")
        self.rows = [("Platform version", v.get("version", "?")),
                     ("Server health", "ONLINE ✔" if h.get("ok") else "DEGRADED ✖")]
        for k, val in d.items():
            if isinstance(val, (int, float, str)):
                self.rows.append((k.replace("_", " ").title(), str(val)))
        for k in ("cpu_percent", "memory_percent", "disk_percent"):
            if k in s:
                self.rows.append((k.replace("_", " ").title(), f"{s[k]}%"))

    def cells(self, row): return [row[0], row[1]]


class CompaniesTab(Tab):
    name = "Companies"
    columns = [("Name", 26), ("Industry", 18), ("Employees", 10), ("Created", 14)]

    def refresh(self):
        self.rows = self.api.get("/companies")

    def cells(self, r):
        return [r.get("name", ""), r.get("industry", ""),
                str(r.get("employee_count", r.get("employees", ""))), _ts(r.get("created_at", ""))]

    def actions(self): return [("d", "Delete")]

    def act(self, key, row, ui):
        if key == "d" and ui.confirm(f"Delete company '{row['name']}'?"):
            self.api.delete(f"/companies/{row['id']}")
            return f"Company '{row['name']}' deleted"
        return ""


class UsersTab(Tab):
    name = "Users"
    columns = [("Username", 22), ("Role", 14), ("Created", 14)]

    def refresh(self):
        self.rows = self.api.get("/users")

    def cells(self, r):
        return [r.get("username", ""), "administrator" if r.get("is_admin") else "user",
                _ts(r.get("created_at", ""))]

    def actions(self): return [("n", "New user"), ("d", "Delete")]

    def act(self, key, row, ui):
        if key == "n":
            name = ui.prompt("New username:")
            if not name:
                return ""
            pw = ui.prompt("Password:", secret=True)
            if not pw:
                return ""
            admin = ui.confirm("Grant administrator rights?")
            self.api.post("/users", {"username": name, "password": pw, "is_admin": admin})
            return f"User '{name}' created"
        if key == "d" and row and ui.confirm(f"Delete user '{row['username']}'?"):
            self.api.delete(f"/users/{row['id']}")
            return f"User '{row['username']}' deleted"
        return ""


class SkillsTab(Tab):
    name = "Skills"
    columns = [("Skill", 34), ("Target", 10), ("State", 10), ("Description", 40)]

    def refresh(self):
        self.rows = self.api.get("/skills")

    def cells(self, r):
        return [r.get("name", ""), r.get("target", ""),
                "enabled ✔" if r.get("enabled") else "disabled",
                (r.get("description") or "")[:40]]

    def actions(self): return [("\n", "Toggle enable"), ("d", "Delete")]

    def act(self, key, row, ui):
        if not row:
            return ""
        if key in ("\n", " "):
            body = {k: row[k] for k in ("name", "description", "instructions", "target")}
            body["enabled"] = not row.get("enabled")
            self.api.put(f"/skills/{row['id']}", body)
            return f"Skill '{row['name']}' {'enabled' if body['enabled'] else 'disabled'}"
        if key == "d" and ui.confirm(f"Delete skill '{row['name']}'?"):
            self.api.delete(f"/skills/{row['id']}")
            return f"Skill '{row['name']}' deleted"
        return ""


class ClientsTab(Tab):
    name = "Clients"
    columns = [("Hostname", 20), ("IP", 15), ("Version", 12), ("Status", 10), ("Last seen", 14)]

    def refresh(self):
        self.rows = self.api.get("/clients")
        if isinstance(self.rows, dict):
            self.rows = self.rows.get("clients", [])

    def cells(self, r):
        ver = r.get("version") or "?"
        if r.get("outdated"):
            ver += " ⬆"          # older than server — forced update on next heartbeat
        return [r.get("hostname", "?"), r.get("ip", ""), ver,
                r.get("status", "online" if r.get("online") else "offline"),
                _ts(r.get("last_seen_at") or r.get("last_seen", ""))]


class ApprovalsTab(Tab):
    name = "Approvals"
    columns = [("Requested", 14), ("Action", 44), ("Status", 12)]

    def refresh(self):
        self.rows = self.api.get("/approvals")
        if isinstance(self.rows, dict):
            self.rows = self.rows.get("approvals", self.rows.get("items", []))

    def cells(self, r):
        return [_ts(r.get("created_at", "")), (r.get("action") or r.get("summary", ""))[:44],
                r.get("status", "pending")]

    def actions(self): return [("a", "Approve"), ("r", "Reject")]

    def act(self, key, row, ui):
        if not row:
            return ""
        if key == "a" and ui.confirm("Approve this request?"):
            self.api.post(f"/approvals/{row['id']}/approve")
            return "Approved ✔"
        if key == "r" and ui.confirm("Reject this request?"):
            self.api.post(f"/approvals/{row['id']}/reject")
            return "Rejected"
        return ""


class SchedulesTab(Tab):
    name = "Schedules"
    columns = [("Job", 30), ("Schedule", 20), ("Enabled", 10), ("Next run", 16)]

    def refresh(self):
        self.rows = self.api.get("/schedules")
        if isinstance(self.rows, dict):
            self.rows = self.rows.get("jobs", self.rows.get("schedules", []))

    def cells(self, r):
        return [r.get("name", r.get("title", "")), r.get("cron", r.get("schedule", "")),
                "yes" if r.get("enabled", True) else "no", _ts(r.get("next_run", ""))]

    def actions(self): return [("d", "Delete")]

    def act(self, key, row, ui):
        if key == "d" and row and ui.confirm(f"Delete schedule '{row.get('name', '?')}'?"):
            self.api.delete(f"/schedules/{row['id']}")
            return "Schedule deleted"
        return ""


class ConfigTab(Tab):
    """Server configuration — every node from the config JSON, grouped by
    category, with labels from the server's FIELD_META. Enter / double-click
    edits a value (select options cycle, numbers validated, secrets masked)."""
    name = "Config"
    columns = [("Setting", 34), ("Value", 26), ("Description", 50)]
    GROUP_LABELS = {"deploy": "DEPLOYMENT", "cluster": "CLUSTER", "agents": "AGENTS",
                    "mobile": "MOBILE / MESSAGING", "smtp": "EMAIL (SMTP)",
                    "security": "SECURITY", "backup": "BACKUP", "ui": "USER INTERFACE"}

    def refresh(self):
        r = self.api.get("/config")
        self.cfg = r.get("config", {}) if isinstance(r, dict) else {}
        self.meta = r.get("meta", {}) if isinstance(r, dict) else {}
        if not self.cfg and isinstance(r, dict):     # older servers: flat dict
            self.cfg = {k: v for k, v in r.items() if k not in ("meta",)}
        # group keys by their meta group; unknown keys go to OTHER
        groups: "dict[str, list[str]]" = {}
        for k in self.cfg:
            if str(k).startswith("_"):
                continue
            g = (self.meta.get(k) or {}).get("group", "other")
            groups.setdefault(g, []).append(k)
        self.rows = []
        for g in sorted(groups, key=lambda x: (x == "other", x)):
            label = self.GROUP_LABELS.get(g, g.upper())
            self.rows.append(("header", f"── {label} ──"))
            for k in sorted(groups[g]):
                self.rows.append(("item", k))

    def _secret(self, k: str) -> bool:
        return "password" in k or "secret" in k or "token" in k

    def cells(self, r):
        if r[0] == "header":
            return [r[1], "", ""]
        k = r[1]
        v = self.cfg.get(k, "")
        shown = "••••••" if (self._secret(k) and str(v)) else str(v)
        m = self.meta.get(k) or {}
        return [k, shown[:26], (m.get("label") or "")[:50]]

    def actions(self): return [("\n", "Edit value")]

    def act(self, key, row, ui):
        if key not in ("\n", " ") or not row or row[0] == "header":
            return ""
        k = row[1]
        v = self.cfg.get(k, "")
        m = self.meta.get(k) or {}
        # select fields: cycle through the allowed options — no typing needed
        if m.get("type") == "select" and m.get("options"):
            opts = m["options"]
            try:
                val = opts[(opts.index(v) + 1) % len(opts)]
            except ValueError:
                val = opts[0]
        else:
            new = ui.prompt(f"{m.get('label', k)}\n{k} =", default="" if self._secret(k) else str(v),
                            secret=self._secret(k))
            if new is None:
                return ""
            if m.get("type") == "number":
                try:
                    val = int(new)
                except ValueError:
                    return f"✖ '{k}' must be a number"
                lo, hi = m.get("min"), m.get("max")
                if lo is not None and val < lo or hi is not None and val > hi:
                    return f"✖ '{k}' must be between {lo} and {hi}"
            elif isinstance(v, bool):
                val = new.strip().lower() in ("1", "true", "yes", "on")
            elif isinstance(v, int) and new.strip().lstrip("-").isdigit():
                val = int(new)
            else:
                val = new
        self.cfg[k] = val
        self.api.put("/config", self.cfg)
        return f"Config '{k}' saved ✔"


class AuditTab(Tab):
    name = "Audit"
    columns = [("Time", 14), ("Action", 28), ("Detail", 52)]

    def refresh(self):
        self.rows = self.api.get("/audit")
        if isinstance(self.rows, dict):
            self.rows = self.rows.get("events", self.rows.get("items", []))

    def cells(self, r):
        return [_ts(r.get("created_at", "")), r.get("action", ""),
                (r.get("detail") or "")[:52]]


class BackupTab(Tab):
    """Backup & restore — same functions as the web UI: export a full JSON
    backup to a file, restore from a backup file, server-side snapshot."""
    name = "Backup"
    columns = [("Action", 30), ("Description", 66)]

    def refresh(self):
        self.rows = [
            {"id": "export", "a": "💾 Export backup → file",
             "d": "Download a full JSON backup and save it to a local path"},
            {"id": "import", "a": "♻ Restore backup ← file",
             "d": "Import a previously exported backup file (after reinstall etc.)"},
            {"id": "snapshot", "a": "📸 Server-side snapshot",
             "d": "Write a snapshot file on the server (platform/data/backups)"},
        ]

    def cells(self, r): return [r["a"], r["d"]]

    def actions(self): return [("\n", "Run action")]

    def act(self, key, row, ui):
        if key not in ("\n", " ") or not row:
            return ""
        if row["id"] == "export":
            doc = self.api.get("/backup/export")
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default = str(Path.home() / f"agentai_backup_{stamp}.json")
            dest = ui.prompt("Save backup to:", default=default)
            if not dest:
                return ""
            try:
                Path(dest).expanduser().parent.mkdir(parents=True, exist_ok=True)
                Path(dest).expanduser().write_text(
                    json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError as e:
                return f"✖ cannot write file: {e}"
            return f"Backup exported ✔ → {dest}"
        if row["id"] == "import":
            src = ui.prompt("Backup file to restore:", default=str(Path.home()))
            if not src:
                return ""
            p = Path(src).expanduser()
            if not p.is_file():
                return f"✖ file not found: {p}"
            if not ui.confirm(f"Restore '{p.name}' into the live server?"):
                return ""
            r = self.api.upload("/backup/import", p.name, p.read_bytes())
            counts = r.get("restored", {})
            summary = ", ".join(f"{k}:{v}" for k, v in counts.items()) or "done"
            return f"Backup restored ✔ ({summary})"
        if row["id"] == "snapshot":
            r = self.api.post("/backup/snapshot")
            return f"Snapshot written ✔ → {r.get('path', '?')}"
        return ""


class MigrationTab(Tab):
    """Migration set — build program+backup+installers ZIP onto a USB drive,
    with live progress; identical to the web UI's migration feature."""
    name = "Migration"
    columns = [("USB drive", 34), ("Size", 12), ("Status", 48)]

    def refresh(self):
        self.state = {}
        try:
            self.state = self.api.get("/migration/status") or {}
        except ApiError:
            pass
        drives = self.api.get("/migration/usb").get("drives", [])
        self.rows = drives or []

    def cells(self, r):
        status = ""
        if self.state.get("running"):
            status = f"⏳ {self.state.get('step', 'working')} {self.state.get('percent', 0)}%"
        elif self.state.get("done"):
            status = "✔ last migration finished"
        elif self.state.get("error"):
            status = f"✖ {self.state['error']}"
        return [r.get("path", "?"), r.get("size", r.get("label", "")), status]

    def actions(self): return [("\n", "Start migration to drive"), ("s", "Status")]

    def act(self, key, row, ui):
        if key == "s":
            st = self.api.get("/migration/status")
            ui.detail(st)
            return ""
        if key in ("\n", " "):
            if not row:
                return "✖ no USB drive detected — plug one in and press F5"
            path = row.get("path", "")
            if not ui.confirm(f"Build the migration set on '{path}'? "
                              "(program + full backup + OS installers)"):
                return ""
            self.api.post("/migration/start", {"usb_path": path})
            return f"Migration started → {path} — press [s] or F5 for progress"
        return ""


class AboutTab(Tab):
    name = "About"
    columns = [("", 24), ("", 60)]

    def refresh(self):
        try:
            version = self.api.get("/version").get("version", "?")
        except ApiError:
            version = "?"
        self.rows = [
            ("", ""),
            ("  █▀█ NexaCrew", "Virtual Company AI Agent Platform"),
            ("", ""),
            ("  Version", version),
            ("  Developed by", "Sin Chi Chiu · MAP Studio"),
            ("", ""),
            ("  ☎ Support telephone", "+1-949-331-6528"),
            ("  ✉ Support email", "Peterchiu@mapstudiousa.com"),
            ("  🌐 Web site", "www.mapstudiousa.com"),
            ("", ""),
            ("  ©", "MAP Studio — all rights reserved"),
        ]

    def cells(self, r):
        return [r[0], r[1]]


TAB_CLASSES = [DashboardTab, CompaniesTab, UsersTab, SkillsTab, ClientsTab,
               ApprovalsTab, SchedulesTab, ConfigTab, BackupTab, MigrationTab,
               AuditTab, AboutTab]


# ================================================================ UI shell
def _init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(5, curses.COLOR_YELLOW, -1)
    curses.init_pair(6, curses.COLOR_RED, -1)
    curses.init_pair(7, curses.COLOR_GREEN, -1)


class Manager:
    def __init__(self, stdscr, api: Api):
        self.s = stdscr
        self.api = api
        self.tabs = [cls(api) for cls in TAB_CLASSES]
        self.ti = 0
        self.sel = 0
        self.top = 0
        self.msg = ""
        self.tab_spans: "list[tuple[int, int, int]]" = []
        self.row_y0 = 6
        try:
            self.version = self.api.get("/version").get("version", "?")
        except Exception:  # noqa: BLE001
            self.version = "?"
        self.refresh_tab()

    @property
    def tab(self) -> Tab:
        return self.tabs[self.ti]

    def refresh_tab(self):
        try:
            self.tab.refresh()
            self.tab.error = ""
        except ApiError as e:
            self.tab.error = str(e)
        except Exception as e:  # noqa: BLE001
            self.tab.error = f"unexpected: {e}"
        self.sel = min(self.sel, max(0, len(self.tab.rows) - 1))
        self.sel = self._skip_headers(self.sel, 1)
        self.top = 0

    # ------------- drawing -------------
    def draw(self):
        s = self.s
        s.erase()
        h, w = s.getmaxyx()
        who = self.api.user.get("username", "?") if self.api.user else "?"
        # ---- enterprise NOC header: product block + right-aligned link state
        left = f" █▀█ NEXACREW · ENTERPRISE MANAGEMENT CONSOLE · v{self.version} "
        right = f" ● LINK UP · {self.api.base.replace('http://', '')} · OPERATOR {who.upper()} "
        pad = max(1, w - 1 - len(left) - len(right))
        s.attron(curses.color_pair(1) | curses.A_BOLD)
        s.addstr(0, 0, (left + " " * pad + right)[: w - 1])
        s.attroff(curses.color_pair(1) | curses.A_BOLD)
        s.addstr(1, 1, ("─" * (w - 2))[: w - 2], curses.color_pair(3))
        # tab bar — boxed active tab, dimmed separators
        x = 1
        self.tab_spans = []
        for i, t in enumerate(self.tabs):
            label = f" {t.name} "
            attr = curses.color_pair(2) | curses.A_BOLD if i == self.ti else curses.color_pair(3)
            if x + len(label) < w:
                s.addstr(2, x, label, attr)
                if i < len(self.tabs) - 1 and x + len(label) + 1 < w:
                    s.addstr(2, x + len(label), "│", curses.color_pair(3) | curses.A_DIM)
            self.tab_spans.append((x, x + len(label), i))
            x += len(label) + 1
        s.hline(3, 1, curses.ACS_HLINE, w - 2)
        # column headers — last visible column shrinks to fit the terminal
        widths = self._fit_columns(w)
        cx = 2
        for (hd, _), cw in zip(self.tab.columns, widths):
            if cw <= 0:
                break
            s.addstr(4, cx, hd[:cw].ljust(cw), curses.A_BOLD | curses.A_UNDERLINE)
            cx += cw + 2
        # rows
        self.row_y0 = 6
        vis = h - self.row_y0 - 4
        if self.sel < self.top:
            self.top = self.sel
        if self.sel >= self.top + vis:
            self.top = self.sel - vis + 1
        if self.tab.error:
            s.addstr(self.row_y0, 2, "✖ " + self.tab.error[: w - 6], curses.color_pair(6) | curses.A_BOLD)
        elif not self.tab.rows:
            s.addstr(self.row_y0, 2, "(no entries)", curses.color_pair(5))
        else:
            for i, row in enumerate(self.tab.rows[self.top: self.top + vis]):
                y = self.row_y0 + i
                idx = self.top + i
                if isinstance(row, tuple) and len(row) >= 1 and row[0] == "header":
                    s.addstr(y, 2, str(row[1])[: w - 4], curses.color_pair(3) | curses.A_BOLD)
                    continue
                attr = curses.color_pair(4) if idx == self.sel else 0
                cx = 2
                cells = self.tab.cells(row)
                for cw, cell in zip(widths, cells):
                    if cw <= 0:
                        break
                    s.addstr(y, cx, str(cell)[:cw].ljust(cw), attr)
                    cx += cw + 2
        # footer: actions + global keys
        acts = " · ".join(f"[{'Enter' if k == chr(10) else k}] {lbl}" for k, lbl in self.tab.actions())
        if not any(k == "\n" for k, _ in self.tab.actions()):
            acts = ("[Enter] details" + (" · " + acts if acts else ""))
        foot = f" ←→ TABS · ↑↓ ROWS · F5 REFRESH · F10 EXIT {('· ' + acts) if acts else ''} · MOUSE ENABLED "
        s.hline(h - 3, 1, curses.ACS_HLINE, w - 2)
        s.addstr(h - 2, 1, foot[: w - 2], curses.color_pair(7))
        if self.msg:
            s.addstr(h - 4, 2, self.msg[: w - 4], curses.color_pair(7) | curses.A_BOLD)
        s.refresh()

    def _fit_columns(self, w: int) -> "list[int]":
        """Column widths adapted to the terminal: columns keep their preferred
        width when possible; the last visible column shrinks to use exactly
        the remaining space, so content is never silently dropped."""
        widths: list[int] = []
        cx = 2
        for i, (_, cw) in enumerate(self.tab.columns):
            remaining = w - cx - 1
            if remaining < 6:                 # no room left at all
                widths.append(0)
                continue
            widths.append(min(cw, remaining))
            cx += widths[-1] + 2
        return widths

    def detail(self, row) -> None:
        """Full-content popup for the selected row (Enter on info tabs)."""
        h, w = self.s.getmaxyx()
        bw, bh = min(90, w - 4), min(24, h - 4)
        win = curses.newwin(bh, bw, (h - bh) // 2, (w - bw) // 2)
        win.box()
        win.addstr(0, 2, f" {self.tab.name} — details (any key to close) ")
        if isinstance(row, dict):
            pairs = [(k, v) for k, v in row.items() if not str(k).startswith("_")]
        elif isinstance(row, (tuple, list)) and len(row) == 2:
            pairs = [(str(row[0]), row[1])]
        else:
            pairs = [("value", row)]
        y = 1
        for k, v in pairs:
            if y >= bh - 1:
                break
            label = f"{k}: "
            for j, line in enumerate(textwrap.wrap(str(v), bw - 6 - len(label)) or [""]):
                if y >= bh - 1:
                    break
                win.addstr(y, 3, (label if j == 0 else " " * len(label)) + line, 
                           curses.A_BOLD if j == 0 else 0)
                y += 1
        win.refresh()
        win.getch()

    # ------------- dialogs -------------
    def prompt(self, label: str, default: str = "", secret: bool = False) -> "str | None":
        h, w = self.s.getmaxyx()
        lines = label.split("\n")
        bw = min(76, w - 6)
        bh = 5 + (len(lines) - 1)
        win = curses.newwin(bh, bw, h // 2 - bh // 2, (w - bw) // 2)
        win.box()
        win.addstr(0, 2, " Input — Enter=OK · ESC=cancel ")
        for i, ln in enumerate(lines):
            win.addstr(1 + i, 2, ln[: bw - 4], curses.A_BOLD if i == len(lines) - 1 else 0)
        buf = list(default)
        cur = len(buf)
        curses.curs_set(1)
        try:
            while True:
                shown = ("•" * len(buf)) if secret else "".join(buf)
                win.addstr(len(lines) + 1, 2, shown[: bw - 4].ljust(bw - 4))
                win.move(len(lines) + 1, 2 + min(cur, bw - 5))
                win.refresh()
                ch = win.getch()
                if ch in (10, 13, curses.KEY_ENTER):
                    return "".join(buf)
                if ch == 27:
                    return None
                if ch in (curses.KEY_BACKSPACE, 127, 8) and cur > 0:
                    buf.pop(cur - 1); cur -= 1
                elif ch == curses.KEY_LEFT:
                    cur = max(0, cur - 1)
                elif ch == curses.KEY_RIGHT:
                    cur = min(len(buf), cur + 1)
                elif ch == curses.KEY_DC and cur < len(buf):
                    buf.pop(cur)
                elif 32 <= ch < 127:
                    buf.insert(cur, chr(ch)); cur += 1
        finally:
            curses.curs_set(0)

    def confirm(self, question: str) -> bool:
        h, w = self.s.getmaxyx()
        bw = min(64, w - 6)
        win = curses.newwin(5, bw, h // 2 - 2, (w - bw) // 2)
        win.box()
        win.addstr(0, 2, " Confirm ")
        for i, line in enumerate(textwrap.wrap(question, bw - 6)[:2]):
            win.addstr(1 + i, 3, line, curses.A_BOLD)
        win.addstr(3, 3, "[y] Yes    [n/ESC] No", curses.color_pair(7))
        win.refresh()
        while True:
            ch = win.getch()
            if ch in (ord("y"), ord("Y")):
                return True
            if ch in (ord("n"), ord("N"), 27):
                return False

    # ------------- events -------------
    def handle_key(self, ch: int) -> bool:
        """Returns False to quit."""
        if ch in (curses.KEY_F10, ord("q"), ord("Q")):
            return False
        if ch == curses.KEY_F5:
            self.refresh_tab(); self.msg = "Refreshed ✔"; return True
        if ch in (curses.KEY_LEFT, curses.KEY_BTAB):
            self.ti = (self.ti - 1) % len(self.tabs); self.sel = 0; self.refresh_tab(); return True
        if ch in (curses.KEY_RIGHT, 9):
            self.ti = (self.ti + 1) % len(self.tabs); self.sel = 0; self.refresh_tab(); return True
        if ch == curses.KEY_UP:
            self.sel = self._skip_headers(max(0, self.sel - 1), -1); return True
        if ch == curses.KEY_DOWN:
            self.sel = self._skip_headers(min(max(0, len(self.tab.rows) - 1), self.sel + 1), 1); return True
        if ch == curses.KEY_PPAGE:
            self.sel = max(0, self.sel - 10); return True
        if ch == curses.KEY_NPAGE:
            self.sel = min(max(0, len(self.tab.rows) - 1), self.sel + 10); return True
        # tab-specific action keys
        key = "\n" if ch in (10, 13, curses.KEY_ENTER, 32) else (chr(ch) if 32 < ch < 127 else "")
        if key:
            row = self.tab.rows[self.sel] if self.tab.rows else None
            try:
                msg = self.tab.act(key.lower(), row, self)
                if msg:
                    self.msg = msg
                    self.refresh_tab()
                elif key == "\n" and row is not None:
                    # no primary action on this tab → show full row details
                    self.detail(row)
            except ApiError as e:
                self.msg = f"✖ {e}"
        return True

    def _skip_headers(self, idx: int, step: int) -> int:
        """Category header rows are labels, not selectable — hop over them."""
        rows = self.tab.rows
        while 0 <= idx < len(rows) and isinstance(rows[idx], tuple) \
                and len(rows[idx]) >= 1 and rows[idx][0] == "header":
            nxt = idx + step
            if not (0 <= nxt < len(rows)):
                break
            idx = nxt
        return idx

    def handle_mouse(self) -> bool:
        try:
            _, mx, my, _, bstate = curses.getmouse()
        except curses.error:
            return True
        if not (bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED
                          | curses.BUTTON1_RELEASED | curses.BUTTON1_DOUBLE_CLICKED)):
            return True
        if my == 2:                                        # tab bar
            for x0, x1, i in self.tab_spans:
                if x0 <= mx < x1:
                    self.ti = i; self.sel = 0; self.refresh_tab(); return True
        idx = self.top + (my - self.row_y0)
        if self.row_y0 <= my and 0 <= idx < len(self.tab.rows):
            row = self.tab.rows[idx]
            if isinstance(row, tuple) and len(row) >= 1 and row[0] == "header":
                return True                       # category labels are not clickable
            already = (idx == self.sel)
            self.sel = idx
            if (bstate & curses.BUTTON1_DOUBLE_CLICKED) or already:
                # double-click (or second click on the same row) = primary
                # action: edit value / toggle / open details
                return self.handle_key(10)
        return True

    def run(self) -> None:
        curses.curs_set(0)
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        curses.mouseinterval(250)          # enables double-click detection
        # enable xterm mouse reporting explicitly — button events (1002) with
        # SGR extended coordinates (1006); works in Windows Terminal, WSL,
        # PuTTY, xterm, tmux …
        sys.stdout.write("\x1b[?1002h\x1b[?1006h")
        sys.stdout.flush()
        try:
            while True:
                self.draw()
                ch = self.s.getch()
                cont = self.handle_mouse() if ch == curses.KEY_MOUSE else self.handle_key(ch)
                if not cont:
                    return
        finally:
            sys.stdout.write("\x1b[?1002l\x1b[?1006l")
            sys.stdout.flush()


# ================================================================ login flow
def _login_flow(stdscr, api: Api) -> bool:
    """Console login (or first-admin creation) before the manager opens."""
    _init_colors()
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
    stdscr.addstr(0, 0, " █▀█ NEXACREW · ENTERPRISE MANAGEMENT CONSOLE · OPERATOR AUTHENTICATION ".ljust(w - 1)[: w - 1])
    stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)
    stdscr.addstr(1, 1, ("─" * (w - 2))[: w - 2], curses.color_pair(3))
    stdscr.refresh()
    mgr = Manager.__new__(Manager)           # borrow the prompt dialog only
    mgr.s = stdscr
    try:
        needs = api.needs_setup()
    except ApiError as e:
        stdscr.addstr(2, 2, f"✖ Cannot reach the server at {api.base}: {e}", curses.color_pair(6))
        stdscr.addstr(4, 2, "Start it first:  python start.py    (press any key to exit)")
        stdscr.getch()
        return False
    for attempt in range(3):
        u = mgr.prompt("Administrator username:" if needs else "Username:")
        if u is None:
            return False
        p = mgr.prompt("Choose a password:" if needs else "Password:", secret=True)
        if p is None:
            return False
        try:
            (api.first_admin if needs else api.login)(u, p)
            return True
        except ApiError as e:
            stdscr.addstr(2, 2, f"✖ {e} (attempt {attempt + 1}/3)".ljust(w - 4), curses.color_pair(6))
            stdscr.refresh()
    return False


def _main(stdscr) -> None:
    api = Api(server_url())
    if not _login_flow(stdscr, api):
        return
    _init_colors()
    Manager(stdscr, api).run()


def run_console_manager() -> None:
    curses.wrapper(_main)


if __name__ == "__main__":
    run_console_manager()
