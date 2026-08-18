"""Cron scheduler for agent tasks.

A lightweight 5-field cron evaluator (min hour dom month dow) runs in a
background thread; when a ScheduledJob matches the current local minute the
job's prompt is executed through the normal agent pipeline in its chat.
"""

from __future__ import annotations

import datetime as dt
import re
import threading
import time

_started = False


# ---------------- cron parsing ----------------
def _parse_field(field: str, lo: int, hi: int) -> set[int] | None:
    """Parse one cron field. Returns the set of matching values or None (invalid)."""
    vals: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_s = part.split("/", 1)
            if not step_s.isdigit() or int(step_s) < 1:
                return None
            step = int(step_s)
        if part in ("*", ""):
            rng = range(lo, hi + 1)
        elif "-" in part:
            a, b = part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                return None
            rng = range(int(a), int(b) + 1)
        elif part.isdigit():
            rng = range(int(part), int(part) + 1)
        else:
            return None
        for v in rng:
            if lo <= v <= hi and (v - lo) % step == 0:
                vals.add(v)
    return vals or None


def validate_cron(expr: str) -> bool:
    if expr.startswith("once:"):
        try:
            dt.datetime.strptime(expr[5:].strip(), "%Y-%m-%dT%H:%M")
            return True
        except ValueError:
            return False
    parts = expr.split()
    if len(parts) != 5:
        return False
    bounds = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
    return all(_parse_field(p, lo, hi) is not None for p, (lo, hi) in zip(parts, bounds))


def cron_matches(expr: str, when: dt.datetime) -> bool:
    if expr.startswith("once:"):
        try:
            target = dt.datetime.strptime(expr[5:].strip(), "%Y-%m-%dT%H:%M")
        except ValueError:
            return False
        return when.strftime("%Y-%m-%dT%H:%M") == target.strftime("%Y-%m-%dT%H:%M")
    parts = expr.split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    checks = [
        (minute, 0, 59, when.minute),
        (hour, 0, 23, when.hour),
        (dom, 1, 31, when.day),
        (month, 1, 12, when.month),
        (dow, 0, 6, when.isoweekday() % 7),  # 0 = Sunday
    ]
    for field, lo, hi, val in checks:
        vals = _parse_field(field, lo, hi)
        if vals is None or val not in vals:
            return False
    return True


def describe_cron(expr: str) -> str:
    """Best-effort human description."""
    if expr.startswith("once:"):
        return "once at " + expr[5:].strip().replace("T", " ")
    try:
        m, h, dom, mon, dow = expr.split()
        days = {"0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday",
                "4": "Thursday", "5": "Friday", "6": "Saturday"}
        if dom == "*" and mon == "*" and dow == "*" and m.isdigit() and h.isdigit():
            return f"every day at {int(h):02d}:{int(m):02d}"
        if dow in days and dom == "*" and m.isdigit() and h.isdigit():
            return f"every {days[dow]} at {int(h):02d}:{int(m):02d}"
        if m.startswith("*/"):
            return f"every {m[2:]} minutes"
        return expr
    except ValueError:
        return expr


# ---------------- background runner ----------------
def _run_job(job_id: str) -> None:
    from .db import Chat, ScheduledJob, SessionLocal
    from .services import run_agent_message
    db = SessionLocal()
    try:
        job = db.get(ScheduledJob, job_id)
        if not job or not job.enabled or job.deleted_at:
            return
        chat = db.get(Chat, job.chat_id)
        if not chat:
            job.last_status = "error: chat deleted"
            db.commit()
            return
        prompt = f"[SCHEDULED TASK — {job.name}] {job.prompt}"
        run_agent_message(db, chat, prompt, job.user_id)
        job.last_run_at = dt.datetime.utcnow()
        job.last_status = "ok"
        if job.cron.startswith("once:"):
            job.enabled = False
            job.last_status = "ok — ✔ executed (one-time)"
        db.commit()
    except Exception as e:  # noqa: BLE001
        try:
            job = db.get(ScheduledJob, job_id)
            if job:
                job.last_run_at = dt.datetime.utcnow()
                job.last_status = f"error: {str(e)[:300]}"
                db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()


def _loop() -> None:
    from .db import ScheduledJob, SessionLocal
    last_minute = None
    while True:
        now = dt.datetime.now()
        minute_key = now.strftime("%Y%m%d%H%M")
        if minute_key != last_minute:
            last_minute = minute_key
            try:
                db = SessionLocal()
                jobs = (db.query(ScheduledJob)
                        .filter(ScheduledJob.enabled.is_(True),
                                ScheduledJob.deleted_at.is_(None)).all())
                due = [j.id for j in jobs if cron_matches(j.cron, now)]
                db.close()
                for jid in due:
                    threading.Thread(target=_run_job, args=(jid,), daemon=True).start()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(5)


def start_scheduler() -> None:
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, daemon=True, name="cron-scheduler").start()


# ---------------- prompt → cron (agent-assisted) ----------------
SCHEDULE_INTENT = re.compile(
    r"\b(every\s+(day|week|month|hour|monday|tuesday|wednesday|thursday|friday|saturday|sunday|morning|night|\d+\s*(minutes?|hours?)))\b"
    r"|\b(schedule|cron|daily|weekly|monthly|hourly|each day|each week|at \d{1,2}(:\d{2})?\s*(am|pm)?\s+every)\b"
    # one-time: "at 7:55PM on 8/8/2026", "on 8/8/2026 at 19:55", "tomorrow at 9am", "tonight at 8"
    r"|\bat\s+\d{1,2}(:\d{2})?\s*(am|pm)?\s+on\s+\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b"
    r"|\bon\s+\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\s+at\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b"
    r"|\b(tomorrow|tonight)\s+at\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b",
    re.IGNORECASE,
)
