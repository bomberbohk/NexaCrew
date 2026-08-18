# SPDX-License-Identifier: MIT
"""NexaCrew — Enterprise Operations Console (data-center grade).

Transforms the raw uvicorn console into a professional NOC-style
operations interface:

  • Boxed startup banner with full node/runtime inventory
  • Structured, color-coded access log (method / route / status / latency)
  • Rolling telemetry bar: uptime, RPS, error rate, CPU, RAM, traffic
  • Interactive management commands typed straight into the console:
        help status clients visitors audit errors top clear quit

Zero hard dependencies — psutil is used when present (via sysmon),
ANSI colors auto-enable on Windows 10+ and gracefully degrade.
"""
from __future__ import annotations

import collections
import datetime as dt
import logging
import os
import platform as _plat
import re
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

# ------------------------------------------------------------------ ANSI
def _utf8_console() -> None:
    """Windows consoles often default to cp1252 — switch to UTF-8."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass


_utf8_console()


def _enable_vt() -> bool:
    if os.name != "nt":
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        return bool(k32.SetConsoleMode(h, mode.value | 0x0004))
    except Exception:
        return False


_COLOR = _enable_vt() and sys.stdout.isatty()


def _c(code: str, s: str) -> str:
    return f"\x1b[{code}m{s}\x1b[0m" if _COLOR else s


DIM = lambda s: _c("2", s)
BOLD = lambda s: _c("1", s)
GREEN = lambda s: _c("32", s)
YELLOW = lambda s: _c("33", s)
RED = lambda s: _c("31;1", s)
CYAN = lambda s: _c("36", s)
BLUE = lambda s: _c("34;1", s)
MAG = lambda s: _c("35", s)
WHITE = lambda s: _c("97", s)
GREY = lambda s: _c("90", s)

# ------------------------------------------------------------- telemetry
_T0 = time.time()
_STATS = {"req": 0, "err4": 0, "err5": 0, "last_min": []}   # last_min: [(t, ok)]
_LOCK = threading.Lock()
PRODUCT = "NexaCrew"
TAGLINE = "Virtual Company AI Agent Platform"
CREDIT = "Developed by Sin Chi Chi · MAP Studio"


def _version() -> str:
    for p in (Path(__file__).resolve().parents[2] / "VERSION",
              Path(__file__).resolve().parents[1] / "VERSION"):
        try:
            return p.read_text(encoding="utf-8").strip()
        except Exception:
            continue
    return "dev"


def _lan_ips() -> list[str]:
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass
    try:  # UDP trick — finds the outbound interface even with odd resolvers
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip not in ips:
            ips.insert(0, ip)
    except Exception:
        pass
    return ips or ["127.0.0.1"]


def _fmt_uptime() -> str:
    s = int(time.time() - _T0)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    return (f"{d}d {h:02}:{m:02}:{s:02}" if d else f"{h:02}:{m:02}:{s:02}")


def _fmt_bytes(n: float) -> str:
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


# ------------------------------------------------------------ banner
def _banner_lines(port: int = 8600, width: int = 80) -> list[str]:
    ver = _version()
    host = socket.gethostname()
    ips = _lan_ips()
    db = Path(__file__).resolve().parents[1] / "data" / "platform.db"
    W = max(76, width)
    inner = W - 4
    rows: list[str] = []
    bar = "═" * (W - 2)
    rule = "─" * (W - 2)

    def line(s: str = "") -> None:
        s = _clip(s, inner)
        rows.append(GREY("║") + " " + s +
                    " " * max(0, inner - _viz(s)) + " " + GREY("║"))

    def lr(left: str, right: str) -> None:
        gap = inner - _viz(left) - _viz(right)
        line(left + " " * max(2, gap) + right)

    rows.append(GREY(f"╔{bar}╗"))
    lr(BOLD(WHITE(f" {PRODUCT.upper()}")) + GREY(" · ") +
       WHITE(TAGLINE.upper()),
       BOLD(CYAN("ENTERPRISE OPERATIONS CONSOLE ")))
    lr(GREY(f" {CREDIT}"),
       GREY(f"v{ver}  ·  PID {os.getpid()}  ·  NODE {host} "))
    rows.append(GREY(f"╟{rule}╢"))
    lr(f" {CYAN('SYSTEM')}     {WHITE(f'{_plat.system()} {_plat.release()}')}"
       f"  {GREY('·')}  {_plat.machine()}",
       GREY("RUNTIME  ") +
       WHITE(f"Python {_plat.python_version()} ({_plat.python_implementation()}) "))
    tz = time.strftime("%Z") or "local"
    if len(tz) > 5:                       # Windows: "Pacific Daylight Time"
        tz = "".join(w[0] for w in tz.split())
    db_s = "/".join(db.parts[-3:])
    lr(f" {CYAN('STARTED')}    {WHITE(f'{dt.datetime.now():%Y-%m-%d %H:%M:%S}')}"
       f"  {GREY('·')}  TZ {tz}",
       GREY("DATASTORE  ") + WHITE(db_s) + " ")
    eps = (GREY("  │  ")).join(
        GREEN("▸ ") + WHITE(f"http://{ip}:{port}")
        for ip in (ips[:2] + ["127.0.0.1"]))
    line(f" {CYAN('ENDPOINTS')}  " + eps)
    line(f" {CYAN('SERVICES')}   " + (GREY("  ")).join(
        GREEN("●") + " " + WHITE(s) for s in
        ("API", "WORKFORCE", "VISITOR", "POS", "FACE-ID", "SCHEDULER")))
    rows.append(GREY(f"╚{bar}╝"))
    return rows


def print_banner(port: int = 8600) -> None:
    for row in _banner_lines(port, _term_size()[0]):
        print(row)
    sys.stdout.flush()


# ---------------------------------------------------- framed NOC layout
#
#   banner (fixed)
#   ┌─ REAL-TIME STATUS ────────────┐
#   │  scrolling log region (ANSI   │   ← DECSTBM scroll region: only
#   │  scroll region — scrollable)  │     this area scrolls
#   └───────────────────────────────┘
#   ┌─ COMMAND CONSOLE ─────────────┐
#   │ ▸ <type management commands>  │   ← fixed input row
#   └───────────────────────────────┘

class _Layout:
    active = False
    raw = None            # the real stdout
    cols = 100
    rows = 32
    log_top = 0           # first scrolling row (1-based)
    log_bottom = 0        # last scrolling row
    status_row = 0        # live telemetry bar
    prompt_row = 0
    prompt_col = 5


_L = _Layout()
_MIN_ROWS = 26            # below this we fall back to plain output
_CMD_HINT = "help · status · kiosks · agents · clients · config · users · audit · db · backup · quit"
_LOG_HINT = "↑↓ PgUp/PgDn scroll · End = live tail"

# scrollback buffer for the live activity box
_LOG: collections.deque[str] = collections.deque(maxlen=5000)
_SCROLL = [0]             # lines scrolled up from the live tail (0 = follow)


def _prompt_str() -> str:
    return BOLD(CYAN(" " + PRODUCT.upper())) + BOLD(GREEN(" ❯ "))


def _term_size() -> tuple[int, int]:
    try:
        sz = shutil.get_terminal_size((100, 32))
        return sz.columns, sz.lines
    except Exception:
        return 100, 32


def _clip(s: str, width: int) -> str:
    """Clip a string containing ANSI codes to `width` visible cells."""
    if _viz(s) <= width:
        return s
    out, vis, i = [], 0, 0
    while i < len(s) and vis < width - 1:
        m = _ANSI_RE.match(s, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        out.append(s[i])
        vis += 1
        i += 1
    return "".join(out) + ("\x1b[0m" if _COLOR else "") + "…"


def _frame_row(inner: str) -> str:
    w = _L.cols - 4
    inner = _clip(inner, w)
    pad = " " * max(0, w - _viz(inner))
    return GREY("│") + " " + inner + pad + " " + GREY("│")


def _box_top(title: str, hint: str = "") -> str:
    t = BOLD(CYAN(f" {title} "))
    h = GREY(f" {hint} ") if hint else ""
    fill = _L.cols - 4 - _viz(t) - _viz(h)
    if fill < 0:                              # hint doesn't fit — drop it
        h, fill = "", _L.cols - 4 - _viz(t)
    return (GREY("┌──") + t + GREY("─" * max(0, fill)) + h + GREY("┐"))


def _box_bottom() -> str:
    return GREY("└" + "─" * (_L.cols - 2) + "┘")


def _log_header() -> str:
    hdr = f" {'TIME':<8}  {'ST':<3}  {'METHOD':<6} {'ROUTE':<52} CLIENT"
    return BOLD(GREY(hdr))


def _log_title_bar() -> str:
    """Top border of the activity box — shows scroll position when paused."""
    off = _SCROLL[0]
    hint = (_LOG_HINT if not off else
            f"▲ SCROLLED · {off} line(s) above live tail · End = resume")
    title = "LIVE ACTIVITY · REAL-TIME STATUS"
    t = BOLD(CYAN(f" {title} "))
    h = (YELLOW(f" {hint} ") if off else GREY(f" {hint} "))
    fill = _L.cols - 4 - _viz(t) - _viz(h)
    if fill < 0:
        h, fill = "", _L.cols - 4 - _viz(t)
    return GREY("┌──") + t + GREY("─" * max(0, fill)) + h + GREY("┐")


def _log_height() -> int:
    return max(1, _L.log_bottom - _L.log_top + 1)


def _paint_scrollbar() -> None:
    """Draw the vertical scrollbar on the right border of the activity box.
    Caller must hold _LOCK."""
    raw = _L.raw
    h = _log_height()
    total = len(_LOG)
    col = _L.cols
    w = raw.write
    w("\x1b7")
    if total <= h:                      # everything visible — plain border
        for i in range(h):
            w(f"\x1b[{_L.log_top + i};{col}H" + GREY("│"))
        w("\x1b8")
        return
    thumb = max(1, round(h * h / total))
    # scroll offset from the top of the buffer
    top_off = total - h - _SCROLL[0]
    denom = max(1, total - h)
    start = round((h - thumb) * top_off / denom)
    start = max(0, min(h - thumb, start))
    for i in range(h):
        glyph = (CYAN("█") if start <= i < start + thumb else GREY("░"))
        w(f"\x1b[{_L.log_top + i};{col}H" + glyph)
    w("\x1b8")


def _repaint_log() -> None:
    """Redraw the activity viewport from the scrollback buffer.
    Caller must hold _LOCK."""
    raw = _L.raw
    h = _log_height()
    off = min(_SCROLL[0], max(0, len(_LOG) - h))
    _SCROLL[0] = off
    end = len(_LOG) - off
    view = list(_LOG)[max(0, end - h):end]
    w = raw.write
    w("\x1b7")
    w(f"\x1b[{_L.log_top - 2};1H" + _log_title_bar())
    for i in range(h):
        line = view[i] if i < len(view) else ""
        w(f"\x1b[{_L.log_top + i};1H" + _frame_row(line))
    w("\x1b8")
    _paint_scrollbar()
    raw.flush()


def _telemetry_bar() -> str:
    """Full-width, in-place status strip between log box and command bay."""
    seg = GREY("──[ ") + _telemetry_line() + GREY(" ]")
    fill = _L.cols - _viz(seg) - 2
    return " " + seg + GREY("─" * max(0, fill)) + " "


def _draw_frame(port: int) -> bool:
    """Clear screen, draw banner + boxes, set the scroll region."""
    raw = _L.raw
    cols, rows = _term_size()
    _L.cols, _L.rows = cols, rows
    banner = _banner_lines(port, cols)
    need = len(banner) + 11      # banner + headers + borders + prompt area
    if rows < max(_MIN_ROWS, need) or cols < 76:
        return False
    w = raw.write
    w("\x1b[2J\x1b[H\x1b[?25h")              # clear, home, cursor on
    for row in banner:
        w(row + "\r\n")
    b = len(banner)
    hdr_row = b + 2
    _L.log_top = b + 3
    _L.log_bottom = rows - 5
    _L.status_row = rows - 3
    _L.prompt_row = rows - 1
    w(f"\x1b[{b + 1};1H" + _log_title_bar())
    w(f"\x1b[{hdr_row};1H" + _frame_row(_log_header()))
    for r in range(_L.log_top, _L.log_bottom + 1):
        w(f"\x1b[{r};1H" + _frame_row(""))
    w(f"\x1b[{rows - 4};1H" + _box_bottom())
    w(f"\x1b[{_L.status_row};1H" + _telemetry_bar())
    w(f"\x1b[{rows - 2};1H" + _box_top("COMMAND CONSOLE", _CMD_HINT))
    w(f"\x1b[{rows};1H" + _box_bottom())
    # scroll region = interior of the status box
    w(f"\x1b[{_L.log_top};{_L.log_bottom}r")
    _paint_scrollbar()
    _paint_prompt()
    raw.flush()
    return True


def _paint_prompt() -> None:
    raw = _L.raw
    p = _prompt_str()
    raw.write(f"\x1b[{_L.prompt_row};1H" + _frame_row(p))
    _L.prompt_col = 3 + _viz(p)
    raw.write(f"\x1b[{_L.prompt_row};{_L.prompt_col}H")
    raw.flush()


def _paint_telemetry() -> None:
    """Refresh the fixed telemetry strip in place (no scrolling)."""
    if not _L.active:
        return
    bar = _telemetry_bar()          # computed before taking the lock
    with _LOCK:
        raw = _L.raw
        raw.write("\x1b7" + f"\x1b[{_L.status_row};1H\x1b[2K" + bar + "\x1b8")
        raw.flush()


def _emit(line: str) -> None:
    """Write one line into the scrollable status box."""
    if not _L.active:
        print(line)
        return
    with _LOCK:
        raw = _L.raw
        cols, rows = _term_size()
        if (cols, rows) != (_L.cols, _L.rows):    # terminal resized
            try:
                _draw_frame(_PORT[0])
            except Exception:
                pass
        _LOG.append(line)
        if _SCROLL[0]:                            # paused — keep view stable
            _SCROLL[0] = min(_SCROLL[0] + 1, max(0, len(_LOG) - _log_height()))
            raw.write("\x1b7" + f"\x1b[{_L.log_top - 2};1H" +
                      _log_title_bar() + "\x1b8")
            _paint_scrollbar()
            raw.flush()
            return
        w = raw.write                             # live tail — fast scroll
        w("\x1b7")                                # save cursor
        w(f"\x1b[{_L.log_bottom};1H\n")           # scroll region up
        w(f"\x1b[{_L.log_bottom};1H" + _frame_row(line))
        w("\x1b8")                                # restore cursor
        _paint_scrollbar()
        raw.flush()


def _scroll_by(delta: int) -> None:
    """Positive = towards history, negative = towards live tail."""
    if not _L.active:
        return
    with _LOCK:
        old = _SCROLL[0]
        _SCROLL[0] = max(0, min(old + delta, max(0, len(_LOG) - _log_height())))
        if _SCROLL[0] != old:
            _repaint_log()


def _scroll_home_end(home: bool) -> None:
    if not _L.active:
        return
    with _LOCK:
        _SCROLL[0] = max(0, len(_LOG) - _log_height()) if home else 0
        _repaint_log()


class _BoxStream:
    """stdout replacement — routes every completed line into the box."""

    def __init__(self) -> None:
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            _emit(line.rstrip("\r"))
        return len(s)

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return True

    @property
    def encoding(self) -> str:
        return getattr(_L.raw, "encoding", "utf-8")


_PORT = [8600]


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _viz(s: str) -> int:
    return len(_ANSI_RE.sub("", s))


# ------------------------------------------------------- access log
_ACCESS_RE = re.compile(
    r'([\d.:a-fA-F\[\]]+):(\d+) - "(\w+) (.+?) HTTP/[\d.]+" (\d+)')
_QUIET_PATHS = ("/api/health", "/api/client/heartbeat", "/api/kiosk/heartbeat")
_QUIET_HIDE = False        # 'quiet on' suppresses these rows entirely


class _AccessFormatter(logging.Formatter):
    """uvicorn access records → aligned, color-coded NOC rows."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        m = _ACCESS_RE.search(msg)
        ts = GREY(dt.datetime.now().strftime("%H:%M:%S"))
        if not m:
            return f" {ts}  {msg}"
        ip, _port, method, path, status = m.groups()
        code = int(status)
        with _LOCK:
            _STATS["req"] += 1
            if 400 <= code < 500:
                _STATS["err4"] += 1
            elif code >= 500:
                _STATS["err5"] += 1
            _STATS["last_min"].append((time.time(), code < 400))
            cut = time.time() - 60
            _STATS["last_min"] = [x for x in _STATS["last_min"] if x[0] > cut]
        quiet = any(path.startswith(q) for q in _QUIET_PATHS)
        sc = (GREEN(status) if code < 400 else
              YELLOW(status) if code < 500 else RED(status))
        mc = {"GET": CYAN, "POST": GREEN, "PUT": YELLOW,
              "DELETE": RED, "PATCH": MAG}.get(method, WHITE)(f"{method:<6}")
        if len(path) > 52:
            path = path[:49] + "…"
        row = f" {ts}  {sc}  {mc} {path:<52} {GREY(ip)}"
        return GREY(_ANSI_RE.sub("", row)) if quiet else row


class _QuietFilter(logging.Filter):
    """'quiet on' — drop health-check / heartbeat rows entirely."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not _QUIET_HIDE:
            return True
        msg = record.getMessage()
        return not any(q in msg for q in _QUIET_PATHS)


def _install_log_format() -> None:
    fmt = _AccessFormatter()
    acc = logging.getLogger("uvicorn.access")
    if not acc.handlers:                    # uvicorn not configured yet
        h = logging.StreamHandler(sys.stdout)
        acc.addHandler(h)
        acc.propagate = False
    acc.addFilter(_QuietFilter())
    for h in acc.handlers:
        h.setFormatter(fmt)
        if _L.active and isinstance(h, logging.StreamHandler):
            h.setStream(sys.stdout)         # our _BoxStream

    class _SysFormatter(logging.Formatter):
        def format(self, record):
            ts = GREY(dt.datetime.now().strftime("%H:%M:%S"))
            lvl = {"INFO": BLUE("INFO "), "WARNING": YELLOW("WARN "),
                   "ERROR": RED("ERROR"), "CRITICAL": RED("CRIT ")}.get(
                       record.levelname, record.levelname[:5])
            return f" {ts}  {lvl}  {record.getMessage()}"
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        for h in lg.handlers:
            h.setFormatter(_SysFormatter())
            if _L.active and isinstance(h, logging.StreamHandler):
                h.setStream(sys.stdout)


# ------------------------------------------------------ telemetry bar
def _telemetry_line() -> str:
    from . import sysmon
    cpu = ram = ""
    try:
        s = sysmon.latest() if hasattr(sysmon, "latest") else {}
        if s.get("cpu_total") is not None:
            cpu = f"CPU {s['cpu_total']:.0f}%"
        if s.get("mem_used") is not None:
            ram = f"RAM {_fmt_bytes(s['mem_used'])}/{_fmt_bytes(s.get('mem_total') or 0)}"
    except Exception:
        pass
    if not cpu:
        try:
            import psutil
            cpu = f"CPU {psutil.cpu_percent(interval=None):.0f}%"
            vm = psutil.virtual_memory()
            ram = f"RAM {vm.percent:.0f}%"
        except Exception:
            pass
    with _LOCK:
        rpm = len(_STATS["last_min"])
        req, e4, e5 = _STATS["req"], _STATS["err4"], _STATS["err5"]
    err = e4 + e5
    err_s = (GREEN("0") if not err else
             YELLOW(str(err)) if not e5 else RED(str(err)))
    parts = [BOLD(GREEN("● ONLINE")), f"UP {_fmt_uptime()}",
             f"REQ {req}", f"RPM {rpm}", f"ERR {err_s}"]
    if cpu:
        parts.append(cpu)
    if ram:
        parts.append(ram)
    return GREY(" │ ").join(parts)


def _telemetry_loop(interval: int = 60) -> None:
    while True:
        if _L.active:
            time.sleep(2)                      # live strip — refresh fast
            try:
                _paint_telemetry()
            except Exception:
                pass
        else:
            time.sleep(interval)
            try:
                print(f" {GREY('┈┈')} {_telemetry_line()} {GREY('┈┈')}",
                      flush=True)
            except Exception:
                pass


# ------------------------------------------------- management commands
_HELP = f"""
 {BOLD('MANAGEMENT CONSOLE — COMMAND REFERENCE')}
 {GREY('─' * 72)}
 {BOLD('MONITORING')}
   {CYAN('status')}             node status · uptime · counters · resources
   {CYAN('top')}                process resources (CPU / RAM / threads)
   {CYAN('net')}                listening endpoints · LAN interfaces
   {CYAN('uptime')}             uptime · start time · version
   {CYAN('quiet on|off')}       hide/show health-check & heartbeat noise
 {BOLD('DEVICES & CLIENTS')}
   {CYAN('kiosks')}             connected kiosks — IP · type · status · last seen
   {CYAN('clients')}            client devices (heartbeats)
 {BOLD('AI AGENTS')}
   {CYAN('agents')}             AI agent CLI diagnostics — Codex · Claude · Node · APIs
 {BOLD('BUSINESS')}
   {CYAN('visitors')}           today's visitor register
   {CYAN('users')}              registered platform accounts
   {CYAN('companies')}          virtual companies on this node
 {BOLD('AUDIT & SECURITY')}
   {CYAN('audit [n]')}          last n audit-trail events (default 15)
   {CYAN('errors')}             recent failures / denials from the audit trail
 {BOLD('CONFIGURATION')}
   {CYAN('config')}             list runtime configuration (secrets masked)
   {CYAN('config get <key>')}   show a single configuration value
   {CYAN('config set <key> <value>')}   update & persist a configuration key
 {BOLD('MAINTENANCE')}
   {CYAN('db')}                 datastore statistics (tables · rows · size)
   {CYAN('backup')}             snapshot the datastore to data/backups/
   {CYAN('sessions')}           active authenticated sessions
   {CYAN('clear')}              clear the activity log
   {CYAN('restart')}            restart this node (systemd/supervisor required)
   {CYAN('quit')}               graceful shutdown of this node
"""


def _cmd_status() -> None:
    print(f"\n {_telemetry_line()}\n")


def _cmd_top() -> None:
    try:
        import psutil
        p = psutil.Process(os.getpid())
        with p.oneshot():
            cpu = p.cpu_percent(interval=0.3)
            mem = p.memory_info().rss
            thr = p.num_threads()
        print(f"\n  {BOLD('PROCESS')}  PID {os.getpid()}  CPU {cpu:.1f}%  "
              f"RSS {_fmt_bytes(mem)}  THREADS {thr}\n")
    except Exception as e:
        print(f"  psutil unavailable: {e}")


def _cmd_visitors() -> None:
    try:
        from .db import SessionLocal, Visit
        db = SessionLocal()
        today = dt.datetime.now().date()
        rows = [v for v in db.query(Visit).order_by(Visit.created_at.desc())
                .limit(200) if v.created_at.date() == today]
        print(f"\n  {BOLD('VISITORS TODAY')} — {len(rows)}")
        for v in rows[:15]:
            st = {"checked_in": GREEN("IN "), "checked_out": GREY("OUT"),
                  "approved": CYAN("APPR")}.get(v.status, v.status[:4])
            print(f"   {v.created_at:%H:%M}  {st}  {v.visitor_name:<24} "
                  f"{GREY((getattr(v, 'company', '') or '')[:20]):<20} {v.host or ''}")
        print()
        db.close()
    except Exception as e:
        print(f"  db error: {e}")


def _cmd_audit(errors_only: bool = False, limit: int = 15) -> None:
    try:
        from .db import SessionLocal, AuditEvent
        db = SessionLocal()
        q = db.query(AuditEvent).order_by(AuditEvent.id.desc())
        rows = []
        for r in q.limit(500):
            if errors_only and not any(k in (r.action or "")
                                       for k in ("fail", "error", "denied", "miss")):
                continue
            rows.append(r)
            if len(rows) >= (10 if errors_only else max(1, min(limit, 100))):
                break
        print(f"\n  {BOLD('AUDIT TRAIL' + (' — ERRORS' if errors_only else ''))}")
        for r in rows:
            print(f"   {GREY(f'{r.created_at:%m-%d %H:%M:%S}')}  "
                  f"{CYAN((r.action or '')[:34]):<34}  {(r.detail or '')[:60]}")
        print()
        db.close()
    except Exception as e:
        print(f"  db error: {e}")


def _cmd_clients() -> None:
    try:
        from .db import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        try:
            rows = db.execute(text(
                "SELECT hostname, ip, platform, last_seen FROM client_devices "
                "ORDER BY last_seen DESC LIMIT 20")).fetchall()
        except Exception:
            rows = []
        print(f"\n  {BOLD('CLIENT DEVICES')} — {len(rows)}")
        for r in rows:
            print(f"   {GREEN('●')}  {str(r[0])[:22]:<22} {GREY(str(r[1])):<16} "
                  f"{str(r[2])[:18]:<18} {GREY(str(r[3])[:19])}")
        print()
        db.close()
    except Exception as e:
        print(f"  db error: {e}")


def _cell(text: str, width: int, color=None) -> str:
    """Fixed-width table cell — pad the plain text FIRST, then colorize,
    so ANSI codes never break the column alignment."""
    s = str(text or "—")
    if len(s) > width:
        s = s[:width - 1] + "…"
    s = s.ljust(width)
    return color(s) if color else s


_KIOSK_HDR = ("STATE", 10), ("KIOSK NAME", 22), ("TYPE", 10), \
             ("IP ADDRESS", 16), ("SITE / LOCATION", 18), ("LAST SEEN", 19)


def _kiosk_hdr_row() -> str:
    return BOLD(GREY("   " + " ".join(n.ljust(w) for n, w in _KIOSK_HDR)))


def _kiosk_state(age: float | None, active: bool = True,
                 status: str = "") -> str:
    if status == "revoked":
        return _cell("● REVOKED", 10, RED)
    if status == "pending":
        return _cell("◌ PENDING", 10, YELLOW)
    if not active:
        return _cell("● DISABLED", 10, GREY)
    if age is None:
        return _cell("○ NEVER", 10, GREY)
    if age <= 60:
        return _cell("● ONLINE", 10, GREEN)
    if age <= 300:
        return _cell("● DEGRADED", 10, YELLOW)
    return _cell("● OFFLINE", 10, RED)


_IP_TAG_RE = re.compile(r"ip=([0-9a-fA-F.:]+)")


def _cmd_kiosks() -> None:
    """Connected kiosk fleet — IP address, kiosk type, status, last seen."""
    import json as _json
    try:
        from .db import SessionLocal, PosObject
        db = SessionLocal()
        now = dt.datetime.utcnow()

        def row(state: str, name: str, ktype: str, ip: str,
                site: str, seen: str) -> None:
            print("   " + state + " " +
                  _cell(name, 22, WHITE) + " " +
                  _cell(ktype, 10, CYAN) + " " +
                  _cell(ip, 16, WHITE) + " " +
                  _cell(site, 18, GREY) + " " +
                  _cell(seen, 19, GREY))

        # ---- POS kiosks -------------------------------------------------
        rows = (db.query(PosObject).filter(PosObject.kind == "kiosk")
                .order_by(PosObject.sort, PosObject.created_at).all())
        print(f"\n  {BOLD('POS KIOSKS')} — {len(rows)} registered")
        print(_kiosk_hdr_row())
        for k in rows:
            try:
                kd = _json.loads(k.data or "{}")
            except Exception:
                kd = {}
            last = kd.get("last_online") or ""
            age = None
            if last:
                try:
                    age = (now - dt.datetime.fromisoformat(
                        last.replace("Z", ""))).total_seconds()
                except Exception:
                    age = None
            row(_kiosk_state(age, active=bool(k.active)),
                k.name, "POS",
                kd.get("client_ip") or "—",
                kd.get("location") or "—",
                last.replace("T", " ")[:19] if last else "—")

        # ---- workforce check-in & visitor kiosks ------------------------
        try:
            from .db import DeviceEnrollment
            rows2 = (db.query(DeviceEnrollment)
                     .order_by(DeviceEnrollment.created_at).all())
            print(f"\n  {BOLD('CHECK-IN / VISITOR KIOSKS')} — "
                  f"{len(rows2)} enrolled")
            print(_kiosk_hdr_row())
            for d in rows2:
                age = ((now - d.last_seen_at).total_seconds()
                       if d.last_seen_at else None)
                info = d.client_info or ""
                m = _IP_TAG_RE.search(info)
                ip = m.group(1) if m else "—"
                ktype = {"checkin": "CHECK-IN",
                         "visitor": "VISITOR"}.get(
                             d.kind, (d.kind or "?").upper())
                row(_kiosk_state(age, status=d.status),
                    d.name or d.id[:8], ktype, ip, d.site or "—",
                    f"{d.last_seen_at:%Y-%m-%d %H:%M:%S}"
                    if d.last_seen_at else "—")
        except Exception as e:
            print(GREY(f"   enrollment query failed: {e}"))

        # ---- other kiosk-like heartbeat clients --------------------------
        try:
            from sqlalchemy import text
            cd = db.execute(text(
                "SELECT hostname, ip, platform, last_seen FROM client_devices "
                "WHERE lower(platform) LIKE '%kiosk%' "
                "ORDER BY last_seen DESC LIMIT 20")).fetchall()
            if cd:
                print(f"\n  {BOLD('OTHER KIOSK CLIENTS')} — {len(cd)}")
                print(_kiosk_hdr_row())
                for r in cd:
                    row(_cell("● ONLINE", 10, GREEN), str(r[0]),
                        "CLIENT", str(r[1]), "—", str(r[3])[:19])
        except Exception:
            pass
        print()
        db.close()
    except Exception as e:
        print(f"  db error: {e}")


def _cmd_agents() -> None:
    """AI agent CLI diagnostics — what powers this node's agents."""
    import shutil as _sh
    import subprocess as _sp

    def probe(label: str, names: tuple[str, ...],
              version_args: tuple[str, ...] = ("--version",)) -> None:
        path = next((p for n in names if (p := _sh.which(n))), None)
        if not path:
            print(f"   {RED('●'):<2} {_cell(label, 16, WHITE)} "
                  f"{_cell('NOT INSTALLED', 14, RED)} "
                  f"{GREY('not found on PATH')}")
            return
        ver = ""
        try:
            r = _sp.run([path, *version_args], capture_output=True,
                        text=True, timeout=15, shell=False)
            ver = (r.stdout or r.stderr).strip().splitlines()[0][:40] if \
                (r.stdout or r.stderr).strip() else ""
        except Exception as e:
            ver = f"probe failed: {e}"[:40]
        print(f"   {GREEN('●'):<2} {_cell(label, 16, WHITE)} "
              f"{_cell(ver or 'installed', 40, CYAN)} {GREY(path)}")

    print(f"\n  {BOLD('AI AGENT RUNTIME — CLI DIAGNOSTICS')}")
    print(BOLD(GREY("   ●  " + "CLI".ljust(15) + " " +
                    "VERSION".ljust(40) + " PATH")))
    probe("Codex CLI", ("codex.cmd", "codex.exe", "codex"))
    probe("Claude Code", ("claude.cmd", "claude.exe", "claude"))
    probe("Node.js", ("node.exe", "node"))
    probe("npm", ("npm.cmd", "npm"))
    probe("VS Code", ("code.cmd", "code"))
    probe("git", ("git.exe", "git"))

    # provider availability as the platform itself sees it
    try:
        from . import providers as _prov
        cdx = _prov.CodexProvider()
        cld = _prov.ClaudeCodeProvider()
        api_ok = _prov.ApiAgentProvider.configured()
        print(f"\n  {BOLD('PROVIDER STATUS')} — as seen by the platform")
        for name, ok, note in (
                ("Codex provider", cdx.available,
                 cdx.cli or "CLI missing"),
                ("Claude provider", cld.available,
                 cld.cli or "CLI missing"),
                ("Custom AI API", api_ok,
                 "configured in Settings → AI APIs" if api_ok
                 else "none configured")):
            dot = GREEN("● READY   ") if ok else RED("● OFFLINE ")
            print(f"   {dot} {_cell(name, 18, WHITE)} {GREY(str(note)[:70])}")
    except Exception as e:
        print(GREY(f"   provider check failed: {e}"))

    # recent agent usage counters
    try:
        from . import providers as _prov
        u = _prov.get_usage()
        if u:
            print(f"\n  {BOLD('AGENT USAGE')} — since start")
            for agent, s in u.items():
                print(f"   {CYAN('▸')} {_cell(agent, 14, WHITE)} "
                      f"{GREY('calls')} {s.get('calls', 0):>4}   "
                      f"{GREY('in')} {_fmt_bytes(s.get('prompt_chars', 0))}   "
                      f"{GREY('out')} {_fmt_bytes(s.get('output_chars', 0))}")
    except Exception:
        pass
    print()


def _cmd_users() -> None:
    try:
        from .db import SessionLocal, User
        db = SessionLocal()
        rows = db.query(User).order_by(User.id).limit(50).all()
        print(f"\n  {BOLD('PLATFORM ACCOUNTS')} — {len(rows)}")
        for u in rows:
            role = getattr(u, "role", "") or "user"
            active = getattr(u, "active", True)
            st = GREEN("●") if active else GREY("○")
            print(f"   {st}  #{u.id:<4} {WHITE(str(u.username)[:24]):<24} "
                  f"{CYAN(str(role)[:12]):<12} "
                  f"{GREY(f'created {u.created_at:%Y-%m-%d}' if getattr(u, 'created_at', None) else '')}")
        print()
        db.close()
    except Exception as e:
        print(f"  db error: {e}")


def _cmd_companies() -> None:
    try:
        from .db import SessionLocal, VirtualCompany
        db = SessionLocal()
        rows = db.query(VirtualCompany).order_by(VirtualCompany.id).limit(50).all()
        print(f"\n  {BOLD('VIRTUAL COMPANIES')} — {len(rows)}")
        for c in rows:
            print(f"   {GREEN('●')}  #{c.id:<4} {WHITE(str(c.name)[:32]):<32} "
                  f"{GREY((getattr(c, 'industry', '') or '')[:24])}")
        print()
        db.close()
    except Exception as e:
        print(f"  db error: {e}")


def _cmd_sessions() -> None:
    try:
        from .db import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        rows = []
        for tbl, cols in (("sessions", "user_id, created_at"),
                          ("auth_sessions", "user_id, created_at")):
            try:
                rows = db.execute(text(
                    f"SELECT {cols} FROM {tbl} ORDER BY created_at DESC LIMIT 20"
                )).fetchall()
                break
            except Exception:
                continue
        print(f"\n  {BOLD('ACTIVE SESSIONS')} — {len(rows)}")
        for r in rows:
            print(f"   {GREEN('●')}  user #{r[0]}   {GREY(str(r[1])[:19])}")
        if not rows:
            print(GREY("   no session table exposed — sessions are cookie-based"))
        print()
        db.close()
    except Exception as e:
        print(f"  db error: {e}")


_SECRET_KEY_RE = re.compile(r"(secret|password|token|key|sid)", re.I)


def _mask(key: str, val) -> str:
    s = str(val)
    if _SECRET_KEY_RE.search(key) and s:
        return s[:3] + "•" * min(8, max(1, len(s) - 3))
    return s if len(s) <= 46 else s[:43] + "…"


def _cmd_config(args: list[str]) -> None:
    try:
        from . import config as _cfg
        cfg = _cfg.get_config()
        if not args:                                   # list all
            print(f"\n  {BOLD('RUNTIME CONFIGURATION')} — "
                  f"{GREY(str(_cfg.CONFIG_FILE))}")
            grp = None
            for k in sorted(cfg, key=lambda x: (
                    _cfg.FIELD_META.get(x, {}).get("group", "zz"), x)):
                g = _cfg.FIELD_META.get(k, {}).get("group", "other")
                if g != grp:
                    grp = g
                    print(f"   {BOLD(CYAN(grp.upper()))}")
                print(f"     {WHITE(k):<28} {GREY('=')} {_mask(k, cfg[k])}")
            print(f"\n  {GREY('config set <key> <value> to change · secrets are masked')}\n")
            return
        if args[0] == "get" and len(args) >= 2:
            k = args[1]
            if k not in cfg:
                print(RED(f"  unknown key '{k}'"))
                return
            print(f"\n   {WHITE(k)} {GREY('=')} {_mask(k, cfg[k])}\n")
            return
        if args[0] == "set" and len(args) >= 3:
            k, v = args[1], " ".join(args[2:])
            if k not in _cfg.DEFAULTS:
                print(RED(f"  unknown key '{k}' — 'config' lists valid keys"))
                return
            cur = _cfg.DEFAULTS[k]
            try:
                if isinstance(cur, bool):
                    val = v.lower() in ("1", "true", "yes", "on")
                elif isinstance(cur, int):
                    val = int(v)
                elif isinstance(cur, list):
                    import json as _json
                    val = _json.loads(v)
                else:
                    val = v
            except Exception as e:
                print(RED(f"  invalid value: {e}"))
                return
            _cfg.save_config({k: val})
            print(GREEN(f"  ✓ {k} = {_mask(k, val)} — saved") +
                  GREY("  (some keys take effect on next start)"))
            return
        print(GREY("  usage: config | config get <key> | config set <key> <value>"))
    except Exception as e:
        print(f"  config error: {e}")


def _cmd_db() -> None:
    try:
        from .db import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        dbf = Path(__file__).resolve().parents[1] / "data" / "platform.db"
        size = dbf.stat().st_size if dbf.exists() else 0
        tables = [r[0] for r in db.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")).fetchall()]
        print(f"\n  {BOLD('DATASTORE')}  {GREY(str(dbf))}")
        print(f"   SIZE {WHITE(_fmt_bytes(size))}   TABLES {WHITE(str(len(tables)))}")
        stats = []
        for t in tables:
            try:
                n = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                stats.append((t, n or 0))
            except Exception:
                continue
        stats.sort(key=lambda x: -x[1])
        for t, n in stats[:18]:
            print(f"     {WHITE(t[:34]):<34} {GREY('rows')} {n:>8,}")
        if len(stats) > 18:
            print(GREY(f"     … and {len(stats) - 18} more tables"))
        print()
        db.close()
    except Exception as e:
        print(f"  db error: {e}")


def _cmd_backup() -> None:
    try:
        import shutil as _sh
        src = Path(__file__).resolve().parents[1] / "data" / "platform.db"
        dstdir = src.parent / "backups"
        dstdir.mkdir(parents=True, exist_ok=True)
        dst = dstdir / f"platform_{dt.datetime.now():%Y%m%d_%H%M%S}.db"
        _sh.copy2(src, dst)
        print(GREEN(f"  ✓ datastore snapshot → {dst.name} "
                    f"({_fmt_bytes(dst.stat().st_size)})"))
    except Exception as e:
        print(RED(f"  backup failed: {e}"))


def _cmd_net(port: int) -> None:
    print(f"\n  {BOLD('NETWORK')}")
    for ip in _lan_ips():
        print(f"   {GREEN('▸')} http://{ip}:{port}   {GREY('console · kiosk · api')}")
    print(f"   {GREEN('▸')} http://127.0.0.1:{port}   {GREY('loopback')}")
    try:
        import psutil
        conns = [c for c in psutil.net_connections(kind="tcp")
                 if c.status == "ESTABLISHED" and c.laddr and
                 c.laddr.port == port]
        peers = sorted({c.raddr.ip for c in conns if c.raddr})
        print(f"   {BOLD('ESTABLISHED')}  {len(conns)} connection(s) "
              f"from {len(peers)} peer(s)")
        for p in peers[:12]:
            print(f"     {GREY('•')} {p}")
    except Exception:
        pass
    print()


def _cmd_uptime() -> None:
    print(f"\n   {BOLD('UPTIME')}  {_fmt_uptime()}   "
          f"{GREY('since')} {dt.datetime.fromtimestamp(_T0):%Y-%m-%d %H:%M:%S}   "
          f"{GREY('version')} {_version()}\n")


def _cmd_quiet(args: list[str]) -> None:
    global _QUIET_HIDE
    if args and args[0] in ("on", "off"):
        _QUIET_HIDE = args[0] == "on"
    print(GREEN(f"  ✓ noise filter {'ON — health/heartbeat hidden' if _QUIET_HIDE else 'OFF — all requests shown'}"))


def _cmd_restart() -> None:
    print(YELLOW(" ▸ restart requested — exiting with code 3 "
                 "(service manager should relaunch)"))
    if _L.active:
        try:
            _L.raw.write("\x1b[r\x1b[2J\x1b[H")
            _L.raw.flush()
        except Exception:
            pass
    os._exit(3)


def _clear_log_box() -> None:
    if not _L.active:
        os.system("cls" if os.name == "nt" else "clear")
        return
    with _LOCK:
        _LOG.clear()
        _SCROLL[0] = 0
        _repaint_log()


# ------------------------------------------------- keyboard input
def _getkey() -> str:
    """Blocking single-key read. Returns printable char or a key name:
    UP DOWN PGUP PGDN HOME END ENTER BACKSPACE ESC or '' (ignored)."""
    if os.name == "nt":
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):                  # extended key prefix
            ch2 = msvcrt.getwch()
            return {"H": "UP", "P": "DOWN", "I": "PGUP", "Q": "PGDN",
                    "G": "HOME", "O": "END"}.get(ch2, "")
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("\x08", "\x7f"):
            return "BACKSPACE"
        if ch == "\x1b":
            return "ESC"
        if ch == "\x03":                            # Ctrl+C
            raise KeyboardInterrupt
        return ch if ch.isprintable() else ""
    # POSIX — raw mode + ANSI escape parsing
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            seq = sys.stdin.read(1)
            if seq == "[":
                seq2 = sys.stdin.read(1)
                if seq2 in "0123456789":
                    seq3 = sys.stdin.read(1)        # e.g. 5~ / 6~
                    code = seq2 + seq3
                    return {"5~": "PGUP", "6~": "PGDN",
                            "1~": "HOME", "4~": "END"}.get(code, "")
                return {"A": "UP", "B": "DOWN",
                        "H": "HOME", "F": "END"}.get(seq2, "")
            return "ESC"
        if ch in ("\r", "\n"):
            return "ENTER"
        if ch in ("\x08", "\x7f"):
            return "BACKSPACE"
        if ch == "\x03":
            raise KeyboardInterrupt
        return ch if ch.isprintable() else ""
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _paint_input(buf: str) -> None:
    """Render the command line inside the console bay."""
    with _LOCK:
        raw = _L.raw
        p = _prompt_str()
        raw.write(f"\x1b[{_L.prompt_row};1H" +
                  _frame_row(p + WHITE(buf)))
        raw.write(f"\x1b[{_L.prompt_row};{3 + _viz(p) + len(buf)}H")
        raw.flush()


def _read_command() -> str:
    """Interactive line editor — scroll keys drive the activity viewport."""
    buf = ""
    _paint_input(buf)
    page = max(1, _log_height() - 1)
    while True:
        try:
            key = _getkey()
        except KeyboardInterrupt:
            buf = ""
            _paint_input(buf)
            continue
        if key == "ENTER":
            return buf.strip()
        if key == "BACKSPACE":
            if buf:
                buf = buf[:-1]
                _paint_input(buf)
            continue
        if key == "UP":
            _scroll_by(1)
            _paint_input(buf)
            continue
        if key == "DOWN":
            _scroll_by(-1)
            _paint_input(buf)
            continue
        if key == "PGUP":
            _scroll_by(page)
            _paint_input(buf)
            continue
        if key == "PGDN":
            _scroll_by(-page)
            _paint_input(buf)
            continue
        if key == "HOME":
            _scroll_home_end(home=True)
            _paint_input(buf)
            continue
        if key == "END" or key == "ESC":
            _scroll_home_end(home=False)
            _paint_input(buf)
            continue
        if key and len(key) == 1:
            buf += key
            _paint_input(buf)


def _repl_loop() -> None:
    while True:
        try:
            if _L.active:
                raw_cmd = _read_command()
            else:
                raw_cmd = input().strip()
        except (EOFError, OSError):
            return                              # no interactive stdin
        except KeyboardInterrupt:
            continue
        if _L.active:
            _scroll_home_end(home=False)        # command → resume live tail
        if _L.active and raw_cmd:
            _emit(_prompt_str() + WHITE(raw_cmd))      # echo into status box
        if not raw_cmd:
            continue
        parts = raw_cmd.split()
        cmd, args = parts[0].lower(), parts[1:]
        try:
            if cmd in ("help", "?", "h"):
                print(_HELP)
            elif cmd == "status":
                _cmd_status()
            elif cmd == "top":
                _cmd_top()
            elif cmd == "uptime":
                _cmd_uptime()
            elif cmd == "net":
                _cmd_net(_PORT[0])
            elif cmd == "quiet":
                _cmd_quiet(args)
            elif cmd == "kiosks":
                _cmd_kiosks()
            elif cmd in ("agents", "cli", "ai"):
                _cmd_agents()
            elif cmd == "clients":
                _cmd_clients()
            elif cmd == "visitors":
                _cmd_visitors()
            elif cmd == "users":
                _cmd_users()
            elif cmd == "companies":
                _cmd_companies()
            elif cmd == "sessions":
                _cmd_sessions()
            elif cmd == "audit":
                _cmd_audit(limit=int(args[0]) if args and args[0].isdigit() else 15)
            elif cmd == "errors":
                _cmd_audit(errors_only=True)
            elif cmd == "config":
                _cmd_config(args)
            elif cmd == "db":
                _cmd_db()
            elif cmd == "backup":
                _cmd_backup()
            elif cmd == "restart":
                _cmd_restart()
            elif cmd in ("clear", "cls"):
                _clear_log_box()
            elif cmd in ("quit", "exit", "shutdown"):
                print(YELLOW(" ▸ graceful shutdown requested from management console"))
                if _L.active:
                    try:
                        _L.raw.write("\x1b[r\x1b[2J\x1b[H")   # reset scroll region
                        _L.raw.flush()
                    except Exception:
                        pass
                os._exit(0)
            else:
                print(GREY(f"  unknown command '{cmd}' — type 'help'"))
        except Exception as e:                     # never kill the console
            print(RED(f"  command failed: {e}"))


# --------------------------------------------------------------- install
_INSTALLED = False


def install(port: int = 8600) -> None:
    """Call once at app import — sets up the full operations console."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _PORT[0] = port
    interactive = bool(sys.stdin and sys.stdin.isatty()
                       and sys.stdout.isatty() and _COLOR)
    if interactive:
        _L.raw = sys.stdout
        if _draw_frame(port):
            _L.active = True
            sys.stdout = _BoxStream()          # route prints into the box
        else:
            print_banner(port)                 # terminal too small — fallback
    else:
        print_banner(port)
    _install_log_format()
    threading.Thread(target=_telemetry_loop, daemon=True,
                     name="ops-telemetry").start()
    if sys.stdin and sys.stdin.isatty():
        threading.Thread(target=_repl_loop, daemon=True,
                         name="ops-console").start()
