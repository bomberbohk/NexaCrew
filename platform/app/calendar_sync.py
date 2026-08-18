"""Calendar service — local events + synchronization with external calendars.

Providers:
  google     — user signs in with their Google account (OAuth 2.0); the consent
               screen asks for Calendar permission. Requires the administrator
               to set google_client_id / google_client_secret once in Settings.
  microsoft  — user signs in with their Microsoft account (OAuth 2.0, Graph);
               works for Outlook / Office 365 calendars. Requires ms_client_id.
  apple      — Apple iCloud calendar via CalDAV: the user enters their Apple ID
               and an app-specific password (appleid.apple.com → App-Specific
               Passwords). Phones synchronized with iCloud pick changes up.
  caldav     — any other CalDAV server (Nextcloud, Fastmail, Synology…):
               URL + username + password/API key.
  monday     — monday.com board: API key; events are created as items.

Events created/changed/removed here are pushed to every connected account,
so the user's smartphone and other platforms stay in sync.

Developed by Sin Chi Chi · MAP Studio
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import urllib.request
import uuid

from sqlalchemy.orm import Session

from .db import CalendarAccount, CalendarEvent
from .security import decrypt_secret, encrypt_secret

UA = {"User-Agent": "NexaCrew-Calendar/1.0"}


def _http(url: str, method: str = "GET", data: bytes | None = None,
          headers: dict | None = None, timeout: int = 30) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={**UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:  # noqa: PERF203
        return e.code, e.read()
    except Exception as e:  # noqa: BLE001
        return 0, str(e).encode()


def _secret(acc: CalendarAccount) -> dict:
    try:
        return json.loads(decrypt_secret(acc.encrypted_secret) or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _save_secret(acc: CalendarAccount, data: dict) -> None:
    acc.encrypted_secret = encrypt_secret(json.dumps(data))


# ------------------------------------------------------------- OAuth ----
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPE = "https://www.googleapis.com/auth/calendar"
MS_AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_SCOPE = "offline_access Calendars.ReadWrite"


def oauth_start_url(provider: str, cfg: dict, redirect_uri: str, state: str) -> str:
    """Build the browser URL where the user signs in with their own account."""
    if provider == "google":
        cid = cfg.get("google_client_id", "")
        if not cid:
            raise ValueError("Google OAuth is not configured — the administrator must set "
                             "the Google client ID/secret in Settings → Calendar.")
        return GOOGLE_AUTH + "?" + urllib.parse.urlencode({
            "client_id": cid, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": GOOGLE_SCOPE, "access_type": "offline", "prompt": "consent",
            "state": state})
    if provider == "microsoft":
        cid = cfg.get("ms_client_id", "")
        if not cid:
            raise ValueError("Microsoft OAuth is not configured — the administrator must set "
                             "the Microsoft application (client) ID in Settings → Calendar.")
        return MS_AUTH + "?" + urllib.parse.urlencode({
            "client_id": cid, "redirect_uri": redirect_uri, "response_type": "code",
            "scope": MS_SCOPE, "state": state})
    raise ValueError(f"OAuth not supported for provider {provider}")


def oauth_exchange(provider: str, cfg: dict, redirect_uri: str, code: str) -> dict:
    """Exchange the authorization code for tokens."""
    if provider == "google":
        body = urllib.parse.urlencode({
            "client_id": cfg.get("google_client_id", ""),
            "client_secret": cfg.get("google_client_secret", ""),
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
            "code": code}).encode()
        st, resp = _http(GOOGLE_TOKEN, "POST", body,
                         {"Content-Type": "application/x-www-form-urlencoded"})
    elif provider == "microsoft":
        body = urllib.parse.urlencode({
            "client_id": cfg.get("ms_client_id", ""),
            "client_secret": cfg.get("ms_client_secret", ""),
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
            "scope": MS_SCOPE, "code": code}).encode()
        st, resp = _http(MS_TOKEN, "POST", body,
                         {"Content-Type": "application/x-www-form-urlencoded"})
    else:
        raise ValueError("unsupported provider")
    data = json.loads(resp.decode() or "{}")
    if st != 200 or "access_token" not in data:
        raise ValueError(f"Token exchange failed: {data.get('error_description') or data.get('error') or st}")
    return data


def _refresh_token(acc: CalendarAccount, cfg: dict) -> str:
    """Return a valid access token, refreshing when expired."""
    sec = _secret(acc)
    exp = sec.get("expires_at", 0)
    if sec.get("access_token") and dt.datetime.utcnow().timestamp() < exp - 60:
        return sec["access_token"]
    rt = sec.get("refresh_token")
    if not rt:
        return sec.get("access_token", "")
    if acc.provider == "google":
        body = urllib.parse.urlencode({
            "client_id": cfg.get("google_client_id", ""),
            "client_secret": cfg.get("google_client_secret", ""),
            "grant_type": "refresh_token", "refresh_token": rt}).encode()
        st, resp = _http(GOOGLE_TOKEN, "POST", body,
                         {"Content-Type": "application/x-www-form-urlencoded"})
    else:
        body = urllib.parse.urlencode({
            "client_id": cfg.get("ms_client_id", ""),
            "client_secret": cfg.get("ms_client_secret", ""),
            "grant_type": "refresh_token", "refresh_token": rt,
            "scope": MS_SCOPE}).encode()
        st, resp = _http(MS_TOKEN, "POST", body,
                         {"Content-Type": "application/x-www-form-urlencoded"})
    data = json.loads(resp.decode() or "{}")
    if st == 200 and data.get("access_token"):
        sec["access_token"] = data["access_token"]
        sec["expires_at"] = dt.datetime.utcnow().timestamp() + int(data.get("expires_in", 3600))
        if data.get("refresh_token"):
            sec["refresh_token"] = data["refresh_token"]
        _save_secret(acc, sec)
        return sec["access_token"]
    return sec.get("access_token", "")


# --------------------------------------------------------- push / sync ----
def _iso(d: dt.datetime) -> str:
    if d.tzinfo is None:  # stored naive local time — convert to real UTC
        d = d.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return d.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _push_google(acc: CalendarAccount, cfg: dict, ev: CalendarEvent,
                 remote_id: str | None, action: str) -> str | None:
    tok = _refresh_token(acc, cfg)
    cal = json.loads(acc.config or "{}").get("calendar_id", "primary")
    base = f"https://www.googleapis.com/calendar/v3/calendars/{urllib.parse.quote(cal)}/events"
    hdrs = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    if action == "delete":
        if remote_id:
            _http(f"{base}/{urllib.parse.quote(remote_id)}", "DELETE", headers=hdrs)
        return None
    body = json.dumps({
        "summary": ev.title, "description": ev.description, "location": ev.location,
        "start": {"date": ev.start_at.strftime("%Y-%m-%d")} if ev.all_day
                 else {"dateTime": _iso(ev.start_at), "timeZone": "UTC"},
        "end": {"date": ev.end_at.strftime("%Y-%m-%d")} if ev.all_day
               else {"dateTime": _iso(ev.end_at), "timeZone": "UTC"},
    }).encode()
    if remote_id:
        st, resp = _http(f"{base}/{urllib.parse.quote(remote_id)}", "PUT", body, hdrs)
    else:
        st, resp = _http(base, "POST", body, hdrs)
    if st in (200, 201):
        return json.loads(resp.decode()).get("id")
    raise RuntimeError(f"Google sync failed ({st}): {resp.decode()[:200]}")


def _push_microsoft(acc: CalendarAccount, cfg: dict, ev: CalendarEvent,
                    remote_id: str | None, action: str) -> str | None:
    tok = _refresh_token(acc, cfg)
    base = "https://graph.microsoft.com/v1.0/me/events"
    hdrs = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
    if action == "delete":
        if remote_id:
            _http(f"{base}/{urllib.parse.quote(remote_id)}", "DELETE", headers=hdrs)
        return None
    body = json.dumps({
        "subject": ev.title,
        "body": {"contentType": "text", "content": ev.description or ""},
        "location": {"displayName": ev.location or ""},
        "isAllDay": bool(ev.all_day),
        "start": {"dateTime": _iso(ev.start_at), "timeZone": "UTC"},
        "end": {"dateTime": _iso(ev.end_at), "timeZone": "UTC"},
    }).encode()
    if remote_id:
        st, resp = _http(f"{base}/{urllib.parse.quote(remote_id)}", "PATCH", body, hdrs)
    else:
        st, resp = _http(base, "POST", body, hdrs)
    if st in (200, 201):
        return json.loads(resp.decode()).get("id")
    raise RuntimeError(f"Microsoft sync failed ({st}): {resp.decode()[:200]}")


def _ics(ev: CalendarEvent, uid: str) -> bytes:
    # floating local time (no 'Z') — events display at the wall-clock time the
    # user asked for, regardless of the device's timezone
    fmt = "%Y%m%d" if ev.all_day else "%Y%m%dT%H%M%S"
    val = ";VALUE=DATE:" if ev.all_day else ":"
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//MAP Studio//NexaCrew//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTAMP:{dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}\r\n"
        f"DTSTART{val}{ev.start_at.strftime(fmt)}\r\n"
        f"DTEND{val}{ev.end_at.strftime(fmt)}\r\n"
        f"SUMMARY:{ev.title}\r\n"
        f"DESCRIPTION:{(ev.description or '').replace(chr(10), ' ')}\r\n"
        f"LOCATION:{ev.location or ''}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n").encode()


def _push_caldav(acc: CalendarAccount, ev: CalendarEvent,
                 remote_id: str | None, action: str) -> str | None:
    """Apple iCloud + generic CalDAV: HTTP basic auth, PUT/DELETE .ics."""
    import base64
    conf = json.loads(acc.config or "{}")
    sec = _secret(acc)
    url = conf.get("url", "").rstrip("/")
    if acc.provider == "apple" and not url:
        url = "https://caldav.icloud.com"   # discovery simplified: home calendar
    user = conf.get("username", "")
    pw = sec.get("password", "")
    auth = base64.b64encode(f"{user}:{pw}".encode()).decode()
    hdrs = {"Authorization": f"Basic {auth}", "Content-Type": "text/calendar; charset=utf-8"}
    uid = remote_id or f"nexacrew-{uuid.uuid4().hex}"
    href = conf.get("calendar_url", url)  # full collection URL preferred
    target = f"{href.rstrip('/')}/{uid}.ics"
    if action == "delete":
        if remote_id:
            _http(target, "DELETE", headers=hdrs)
        return None
    st, resp = _http(target, "PUT", _ics(ev, uid), hdrs)
    if st in (200, 201, 204):
        return uid
    raise RuntimeError(f"CalDAV sync failed ({st}): {resp.decode(errors='replace')[:200]}")


def _push_monday(acc: CalendarAccount, ev: CalendarEvent,
                 remote_id: str | None, action: str) -> str | None:
    sec = _secret(acc)
    conf = json.loads(acc.config or "{}")
    key = sec.get("api_key", "")
    board = conf.get("board_id", "")
    hdrs = {"Authorization": key, "Content-Type": "application/json"}
    if action == "delete":
        if remote_id:
            q = {"query": f'mutation {{ delete_item (item_id: {remote_id}) {{ id }} }}'}
            _http("https://api.monday.com/v2", "POST", json.dumps(q).encode(), hdrs)
        return None
    date_str = ev.start_at.strftime("%Y-%m-%d")
    col = json.dumps(json.dumps({"date4": {"date": date_str}}))
    if remote_id:
        q = {"query": f'mutation {{ change_multiple_column_values (item_id: {remote_id}, '
                      f'board_id: {board}, column_values: {col}) {{ id }} }}'}
    else:
        name = json.dumps(ev.title)
        q = {"query": f'mutation {{ create_item (board_id: {board}, item_name: {name}, '
                      f'column_values: {col}) {{ id }} }}'}
    st, resp = _http("https://api.monday.com/v2", "POST", json.dumps(q).encode(), hdrs)
    data = json.loads(resp.decode() or "{}")
    if st == 200 and not data.get("errors"):
        d = data.get("data", {})
        item = d.get("create_item") or d.get("change_multiple_column_values") or {}
        return str(item.get("id") or remote_id or "")
    raise RuntimeError(f"monday.com sync failed: {json.dumps(data)[:200]}")


# -------------------------------------------- natural-language prompts ----
import re as _re

CALENDAR_INTENT = _re.compile(
    r"\b(calendar|event|appointment|meeting)\b", _re.I)
_CREATE_RE = _re.compile(r"\b(add|create|new|book|put|make|set up)\b", _re.I)
_DELETE_RE = _re.compile(r"\b(remove|delete|cancel|drop)\b", _re.I)
_UPDATE_RE = _re.compile(r"\b(move|reschedule|revise|change|update|postpone|shift)\b", _re.I)
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def _parse_when(text: str) -> tuple[dt.datetime | None, dt.datetime | None, bool]:
    """Extract (start, end, all_day) from free text. Returns (None,…) if no date."""
    t = text.lower()
    now = dt.datetime.now()
    day: dt.date | None = None
    m = _re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if day is None:
        m = _re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
        if m:
            mo, d = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else now.year
            if y < 100:
                y += 2000
            try:
                day = dt.date(y, mo, d)
            except ValueError:
                try:
                    day = dt.date(y, d, mo)
                except ValueError:
                    day = None
            if day and day < now.date() and not m.group(3):
                day = dt.date(y + 1, day.month, day.day)
    if day is None:
        if "tomorrow" in t:
            day = now.date() + dt.timedelta(days=1)
        elif "today" in t:
            day = now.date()
        else:
            for i, wd in enumerate(_WEEKDAYS):
                if _re.search(rf"\b{wd}\b", t):
                    delta = (i - now.weekday()) % 7
                    if delta == 0:
                        delta = 7
                    day = now.date() + dt.timedelta(days=delta)
                    break
    if day is None:
        return None, None, False
    # time — "at 3pm", "15:30", "3:00 pm", ranges "from 2pm to 4pm"
    times = _re.findall(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b(?!\s*/)", t)
    parsed: list[dt.time] = []
    for h, mi, ap in times:
        hh, mm = int(h), int(mi or 0)
        if ap == "pm" and hh < 12:
            hh += 12
        elif ap == "am" and hh == 12:
            hh = 0
        if 0 <= hh <= 23 and 0 <= mm <= 59 and (ap or mi):
            parsed.append(dt.time(hh, mm))
    if parsed:
        start = dt.datetime.combine(day, parsed[0])
        end = dt.datetime.combine(day, parsed[1]) if len(parsed) > 1 else start + dt.timedelta(hours=1)
        if end <= start:
            end = start + dt.timedelta(hours=1)
        return start, end, False
    start = dt.datetime.combine(day, dt.time(0, 0))
    return start, start + dt.timedelta(days=1), True


def _extract_title(text: str) -> str:
    m = _re.search(r"[\"“'‘]([^\"”'’]{2,80})[\"”'’]", text)
    if m:
        return m.group(1).strip()
    m = _re.search(r"\b(?:event|appointment|meeting)\b[:,]?\s*(?:for|about|with|called|named)?\s*(.+)", text, _re.I)
    if m:
        tail = m.group(1)
        tail = _re.split(r"\b(?:on|at|from|to|tomorrow|today|next)\b", tail, 1, _re.I)[0]
        tail = tail.strip(" .,:;-")
        if tail:
            return tail[:120]
    return "Untitled event"


# ---- multi-event prompt parsing (numbered lists, per-event fields) --------
_DATE_TOKEN = _re.compile(
    r"\b(?:(\d{4})-(\d{1,2})-(\d{1,2})|(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?)\b")
# "1pm", "4:15PM", "11:AM" (typo-tolerant), "15:30"
_TIME_TOKEN = _re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*:?\s*([ap]\.?m\.?)|\b(\d{1,2}):(\d{2})\b(?!\s*[ap]m)", _re.I)
_FIELD_RE = _re.compile(
    r"(drop\s*off\s+address|pick\s*up\s+address|pickup\s+address|address|location|doctor|with)"
    r"\s*[:：]\s*", _re.I)


def _split_events(text: str) -> list[str]:
    """Split a prompt into one segment per event (numbered lists / lines)."""
    parts = _re.split(r"(?:^|\n)\s*\d{1,2}\s*[.)]\s+", text)
    segs = [p.strip() for p in parts if p.strip() and _DATE_TOKEN.search(p)]
    return segs if len(segs) >= 2 else [text]


def _seg_datetimes(seg: str, now: dt.datetime) -> tuple[dt.datetime | None, dt.datetime | None, bool]:
    """(start, end, all_day) from the date/time tokens of ONE segment.
    Supports cross-day ranges like '9/19/2026 11:30AM to 9/20/2026 11AM'."""
    dates: list[tuple[int, dt.date]] = []
    for m in _DATE_TOKEN.finditer(seg):
        if m.group(1):
            try:
                d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                continue
        else:
            mo, dd = int(m.group(4)), int(m.group(5))
            y = int(m.group(6)) if m.group(6) else now.year
            if y < 100:
                y += 2000
            try:
                d = dt.date(y, mo, dd)
            except ValueError:
                try:
                    d = dt.date(y, dd, mo)
                except ValueError:
                    continue
            if d < now.date() and not m.group(6):
                d = dt.date(y + 1, d.month, d.day)
        dates.append((m.start(), d))
    times: list[tuple[int, dt.time]] = []
    for m in _TIME_TOKEN.finditer(seg):
        if m.group(3):
            hh, mm = int(m.group(1)), int(m.group(2) or 0)
            ap = m.group(3).lower()
            if ap.startswith("p") and hh < 12:
                hh += 12
            elif ap.startswith("a") and hh == 12:
                hh = 0
        else:
            hh, mm = int(m.group(4)), int(m.group(5))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            times.append((m.start(), dt.time(hh, mm)))
    if not dates:
        return None, None, False
    # attach each date to the first time that appears after it (before next date)
    stamps: list[tuple[dt.date, dt.time | None]] = []
    for i, (pos, d) in enumerate(dates):
        nxt = dates[i + 1][0] if i + 1 < len(dates) else len(seg) + 1
        tt = next((t for p, t in times if pos <= p < nxt), None)
        stamps.append((d, tt))
    d0, t0 = stamps[0]
    if t0 is None:
        start = dt.datetime.combine(d0, dt.time(0, 0))
        return start, start + dt.timedelta(days=1), True
    start = dt.datetime.combine(d0, t0)
    if len(stamps) > 1:                       # explicit end date (multi-day)
        d1, t1 = stamps[1]
        end = dt.datetime.combine(d1, t1 or t0)
    else:                                     # second time on the same day?
        later = [t for _, t in times if dt.datetime.combine(d0, t) > start]
        end = dt.datetime.combine(d0, later[0]) if later else start + dt.timedelta(hours=1)
    if end <= start:
        end = start + dt.timedelta(hours=1)
    return start, end, False


def _seg_fields(seg: str) -> tuple[str, str, str]:
    """(head_text, location, description) — pulls 'address:', 'doctor:' … fields."""
    fields = list(_FIELD_RE.finditer(seg))
    head = seg[:fields[0].start()] if fields else seg
    location, desc = "", []
    for i, m in enumerate(fields):
        end = fields[i + 1].start() if i + 1 < len(fields) else len(seg)
        val = seg[m.end():end].strip(" .,;，。")
        key = _re.sub(r"\s+", " ", m.group(1).strip().lower())
        if not val:
            continue
        if key in ("address", "location", "drop off address") and not location:
            location = val
            if key == "drop off address":
                desc.append(f"Drop off address: {val}")
        else:
            desc.append(f"{key.capitalize()}: {val}")
    return head, location, "\n".join(desc)


def _seg_title(head: str) -> str:
    """Event title = the descriptive text left after removing date/time tokens."""
    t = _DATE_TOKEN.sub("\x00", head)
    t = _TIME_TOKEN.sub("\x00", t)
    # strip connector words orphaned next to removed tokens ("to", "from", …)
    t = _re.sub(r"\s*(?:\b(?:from|to|at|on|until|till)\b\s*)?\x00[\x00\s]*"
                r"(?:\b(?:from|to|at|on|until|till)\b\s*)?", " ", t)
    t = _re.sub(r"^\s*\d{1,2}\s*[.)]\s*", "", t)
    t = _re.sub(r"^\s*(?:please\s+)?(?:add|create|new|book|put|make|set\s+up)\b"
                r"(?:\s+(?:an?|the))?\s*(?:events?|appointments?|meetings?)?"
                r"(?:\s+(?:in|on|to)\s+(?:the\s+)?calendar)?\s*[:：]?\s*", "", t, flags=_re.I)
    t = _re.sub(r"[\"“”'‘’]", "", t)
    t = _re.sub(r"\s{2,}", " ", t).strip(" .,:;，。-–—")
    return t[:120]


def _find_event(db: Session, user_id: str, text: str) -> CalendarEvent | None:
    events = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id).all()
    tl = text.lower()
    best, score = None, 0
    for ev in events:
        words = [w for w in _re.findall(r"\w{3,}", ev.title.lower())]
        hit = sum(1 for w in words if w in tl)
        if words and hit > score:
            best, score = ev, hit
    return best if score else None


def handle_calendar_prompt(db: Session, user_text: str, user_id: str, cfg: dict) -> str | None:
    """Create / revise / remove calendar events from a natural-language prompt.

    Returns the reply message, or None when the prompt is not a calendar command.
    """
    if not CALENDAR_INTENT.search(user_text):
        return None
    n_acc = db.query(CalendarAccount).filter(CalendarAccount.user_id == user_id).count()
    sync_note = (f"\n🔄 Synchronized with your {n_acc} connected calendar account(s)."
                 if n_acc else "\n📶 Tip: open the 📅 Calendar page to sync your calendar "
                 "to your smartphone over Bluetooth.")

    if _DELETE_RE.search(user_text) and not _CREATE_RE.search(user_text):
        ev = _find_event(db, user_id, user_text)
        if not ev:
            return "❌ I couldn't find a matching event in your calendar to remove."
        title, when = ev.title, ev.start_at.strftime("%Y-%m-%d %H:%M")
        sync_event(db, ev, "delete", cfg)
        db.delete(ev)
        db.commit()
        return f"🗑️ Removed the event “{title}” ({when}) from your calendar.{sync_note}"

    if _UPDATE_RE.search(user_text):
        ev = _find_event(db, user_id, user_text)
        if ev:
            start, end, all_day = _parse_when(user_text)
            if start is None:
                return (f"❓ I found the event “{ev.title}” but couldn't understand the new "
                        "date/time. Try e.g. “move the meeting to 2026-08-15 at 3pm”.")
            ev.start_at, ev.end_at, ev.all_day = start, end, all_day
            db.commit()
            sync_event(db, ev, "update", cfg)
            return (f"✏️ Moved “{ev.title}” to "
                    f"{start.strftime('%Y-%m-%d') if all_day else start.strftime('%Y-%m-%d %H:%M')}."
                    f"{sync_note}")
        # fall through to create if nothing matched and creation verbs exist

    if _CREATE_RE.search(user_text) or _UPDATE_RE.search(user_text):
        now = dt.datetime.now()
        segs = _split_events(user_text)
        created, skipped = [], []
        for seg in segs:
            start, end, all_day = _seg_datetimes(seg, now)
            if start is None:
                skipped.append(seg.strip()[:60])
                continue
            head, loc, desc = _seg_fields(seg)
            title = _seg_title(head)
            if not title:
                title = _extract_title(seg)
            if not loc:
                m = _re.search(r"\b(?:at|in)\s+([A-Z][\w .'-]{2,40})", seg)
                if m and not _re.match(r"\d", m.group(1)):
                    loc = m.group(1).strip()
            ev = CalendarEvent(user_id=user_id, title=title, description=desc,
                               location=loc, start_at=start, end_at=end, all_day=all_day)
            db.add(ev)
            db.commit()
            sync_event(db, ev, "create", cfg)
            if all_day:
                when = start.strftime("%Y-%m-%d")
            elif end.date() != start.date():
                when = f"{start.strftime('%Y-%m-%d %H:%M')} → {end.strftime('%Y-%m-%d %H:%M')}"
            else:
                when = f"{start.strftime('%Y-%m-%d %H:%M')}–{end.strftime('%H:%M')}"
            created.append(f"“{title}” — {when}" + (f" @ {loc}" if loc else ""))
        if not created:
            return ("❓ I understood you want a calendar event but couldn't find the date. "
                    "Try e.g. “add event \u201cDentist\u201d on 2026-08-20 at 10am”.")
        if len(created) == 1 and not skipped:
            return f"📅 Created the event {created[0]}.{sync_note}"
        msg = f"📅 Created {len(created)} event(s):\n" + "\n".join(f"• {c}" for c in created)
        if skipped:
            msg += "\n⚠️ Couldn't parse a date in: " + "; ".join(skipped)
        return msg + sync_note
    return None


def sync_event(db: Session, ev: CalendarEvent, action: str, cfg: dict) -> None:
    """Push a create/update/delete of one event to all the user's accounts."""
    # dedicated iCloud CalDAV push (registered by main.py) — covers prompt-created
    # events too, since every code path funnels through sync_event
    hook = globals().get("icloud_push_hook")
    if hook:
        try:
            hook(db, ev, action)
        except Exception:  # noqa: BLE001
            pass
    accounts = db.query(CalendarAccount).filter(
        CalendarAccount.user_id == ev.user_id).all()
    remote = json.loads(ev.remote_ids or "{}")
    ok = err = 0
    for acc in accounts:
        if acc.provider == "apple":
            continue  # handled by the dedicated iCloud CalDAV push (main._icloud_push_event)
        rid = remote.get(acc.id)
        try:
            if acc.provider == "google":
                new_id = _push_google(acc, cfg, ev, rid, action)
            elif acc.provider == "microsoft":
                new_id = _push_microsoft(acc, cfg, ev, rid, action)
            elif acc.provider in ("apple", "caldav"):
                new_id = _push_caldav(acc, ev, rid, action)
            elif acc.provider == "monday":
                new_id = _push_monday(acc, ev, rid, action)
            else:
                continue
            if action == "delete":
                remote.pop(acc.id, None)
            elif new_id:
                remote[acc.id] = new_id
            acc.status, acc.last_error = "connected", ""
            acc.last_sync_at = dt.datetime.utcnow()
            ok += 1
        except Exception as e:  # noqa: BLE001
            acc.status, acc.last_error = "error", str(e)[:500]
            err += 1
    ev.remote_ids = json.dumps(remote)
    ev.sync_status = ("synced" if err == 0 else "partial" if ok else "error") if accounts else ""
    db.commit()
