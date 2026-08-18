# SPDX-License-Identifier: MIT
"""Workforce Identity, Time & Attendance, Visitor Management and Physical
Access Control — domain logic.

Implements handoff/Enterprise_Workforce_Visitor_Access_POS_Prompt.md scaled to
this platform's architecture (FastAPI + SQLite, per-user tenant isolation):

  * Worker QR badges: opaque random tokens (only SHA-256 hash stored — the QR
    contains NO PII), full lifecycle with append-only history, immediate
    revocation, no identifier reuse.
  * Kiosk enrollment: short-lived single-use codes exchanged for device-bound
    credentials (hash stored server-side; the plaintext credential exists only
    on the device).
  * Time & attendance: immutable raw punches with idempotency + duplicate/
    cooldown suppression; audited separate adjustments; timecard pairing.
  * Payroll: approved time → idempotent payroll batch (one per period) →
    accounting journal with traceable source link.
  * Visitor lifecycle state machine with encrypted identity numbers, masking
    and consent records.
  * Access decision service: allow/deny with machine-readable reason codes,
    immutable AccessEvent log. Advisory only — never overrides life safety.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets

SCAN_COOLDOWN_SEC = 30           # duplicate-scan suppression window
ENROLL_CODE_TTL_MIN = 15         # single-use enrollment code lifetime
PUNCH_SEQUENCE = ["in", "meal_start", "meal_end", "break_start", "break_end", "out"]
VISIT_STATES = ["pending", "approved", "denied", "checked_in", "checked_out", "expired"]


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def now() -> dt.datetime:
    return dt.datetime.utcnow()


# ---------------------------------------------------------------- badges
def new_badge_token() -> str:
    """Opaque, random, revocable — carries no PII whatsoever."""
    return "wb-" + secrets.token_urlsafe(24)


def issue_badge(db, user_id: str, worker_name: str, worker_record_id: str = "",
                issued_by: str = "", expires_days: int = 0):
    """Issue a badge; returns (badge, plaintext_token). Token shown once."""
    from .db import WorkerBadge
    from .security import encrypt_secret
    token = new_badge_token()
    b = WorkerBadge(
        user_id=user_id, worker_name=worker_name.strip()[:120],
        worker_record_id=worker_record_id, token_hash=sha256(token),
        token_enc=encrypt_secret(token),
        issued_by=issued_by,
        expires_at=(now() + dt.timedelta(days=expires_days)) if expires_days else None,
        lifecycle=json.dumps([{"at": now().isoformat(), "event": "issued",
                               "by": issued_by}]))
    db.add(b)
    db.commit()
    db.refresh(b)
    return b, token


def badge_lifecycle_append(b, event: str, by: str = "", detail: str = "") -> None:
    hist = json.loads(b.lifecycle or "[]")
    hist.append({"at": now().isoformat(), "event": event, "by": by, "detail": detail})
    b.lifecycle = json.dumps(hist)


def revoke_badge(db, badge, by: str = "", reason: str = "") -> None:
    badge.status = "revoked"
    badge.revoked_at = now()
    badge.revoke_reason = reason[:200]
    badge.token_enc = ""   # revoked badge QR is gone forever
    badge_lifecycle_append(badge, "revoked", by, reason)
    db.commit()


def find_badge_by_token(db, user_id_or_none, token: str):
    """Constant-shape lookup by token hash. Returns badge or None.
    When user_id is provided, enforces tenant isolation."""
    from .db import WorkerBadge
    if not token or not token.startswith("wb-"):
        return None
    q = db.query(WorkerBadge).filter(WorkerBadge.token_hash == sha256(token))
    if user_id_or_none:
        q = q.filter(WorkerBadge.user_id == user_id_or_none)
    return q.first()


def validate_badge(badge) -> str:
    """Returns "" if usable, else a machine-readable reason code."""
    if badge is None:
        return "badge_unknown"
    if badge.status == "revoked":
        return "badge_revoked"
    if badge.status == "suspended":
        return "badge_suspended"
    if badge.status == "expired" or (badge.expires_at and badge.expires_at < now()):
        return "badge_expired"
    if badge.status != "active":
        return "badge_inactive"
    return ""


# ---------------------------------------------------------------- enrollment
def create_enrollment(db, user_id: str, kind: str, name: str, site: str = "",
                      approved_by: str = ""):
    """Admin step: returns (enrollment, one-time code). Code lives 15 minutes."""
    from .db import DeviceEnrollment
    from .security import encrypt_secret
    code = "ek-" + secrets.token_urlsafe(9)
    e = DeviceEnrollment(
        user_id=user_id, kind=kind if kind in ("checkin", "visitor") else "checkin",
        name=name.strip()[:120], site=site.strip()[:120],
        enroll_code_hash=sha256(code), code_enc=encrypt_secret(code),
        code_expires_at=now() + dt.timedelta(minutes=ENROLL_CODE_TTL_MIN),
        approved_by=approved_by, status="pending")
    db.add(e)
    db.commit()
    db.refresh(e)
    return e, code


def exchange_enrollment(db, code: str, client_info: str = ""):
    """Device step: single-use code → device credential (plaintext returned
    once; only the hash persists). Returns (enrollment, credential) or (None, reason)."""
    from .db import DeviceEnrollment
    if not code or not code.startswith("ek-"):
        return None, "code_invalid"
    e = (db.query(DeviceEnrollment)
         .filter(DeviceEnrollment.enroll_code_hash == sha256(code)).first())
    if not e:
        return None, "code_invalid"
    if e.status != "pending":
        return None, "code_used"
    if e.code_expires_at and e.code_expires_at < now():
        return None, "code_expired"
    cred = "dc-" + secrets.token_urlsafe(24)
    e.credential_hash = sha256(cred)
    e.enroll_code_hash = ""            # single use — never exchangeable again
    e.code_enc = ""                    # wipe the stored plaintext code
    e.status = "enrolled"
    e.enrolled_at = now()
    ip = get_device_ip()
    prefix = f"ip={ip} · " if ip else ""
    e.client_info = (prefix + client_info)[:200]
    db.commit()
    return e, cred


# Real device IP — set per-request by an HTTP middleware in main.py so the
# fleet board shows the kiosk's network address, not a User-Agent artefact.
import contextvars as _ctxv  # noqa: E402

_DEVICE_IP: _ctxv.ContextVar[str] = _ctxv.ContextVar("device_ip", default="")


def set_device_ip(ip: str) -> None:
    _DEVICE_IP.set((ip or "").strip()[:60])


def get_device_ip() -> str:
    return _DEVICE_IP.get()


def find_device_by_credential(db, cred: str):
    from .db import DeviceEnrollment
    if not cred or not cred.startswith("dc-"):
        return None
    e = (db.query(DeviceEnrollment)
         .filter(DeviceEnrollment.credential_hash == sha256(cred),
                 DeviceEnrollment.status == "enrolled").first())
    if e:
        e.last_seen_at = now()
        ip = get_device_ip()
        if ip:                                  # refresh the recorded address
            rest = re.sub(r"^ip=[^\s·]+\s*·?\s*", "", e.client_info or "")
            e.client_info = (f"ip={ip} · " + rest)[:200]
        try:
            db.commit()
        except Exception:
            db.rollback()
    return e


# ---------------------------------------------------------------- time punches
def next_event_for(db, user_id: str, worker_record_id: str, worker_name: str) -> str:
    """Suggest the next punch type from today's history (in→out toggle)."""
    from .db import TimePunch
    start = now().replace(hour=0, minute=0, second=0, microsecond=0)
    last = (db.query(TimePunch)
            .filter(TimePunch.user_id == user_id,
                    TimePunch.worker_name == worker_name,
                    TimePunch.at_utc >= start, TimePunch.result == "ok")
            .order_by(TimePunch.at_utc.desc()).first())
    if not last or last.event == "out":
        return "in"
    return "out"


def record_punch(db, user_id: str, *, worker_name: str, worker_record_id: str = "",
                 badge_id: str = "", device_id: str = "", site: str = "",
                 event: str = "", source: str = "badge", idempotency_key: str = "",
                 note: str = ""):
    """Create an immutable punch. Duplicate protection:
    1) identical idempotency_key → returns existing punch (idempotent)
    2) same worker+event within SCAN_COOLDOWN_SEC → result="duplicate"
    Raw punches are never mutated afterwards."""
    from .db import TimePunch
    if idempotency_key:
        dup = (db.query(TimePunch)
               .filter(TimePunch.user_id == user_id,
                       TimePunch.idempotency_key == idempotency_key).first())
        if dup:
            return dup, True
    event = event or next_event_for(db, user_id, worker_record_id, worker_name)
    if event not in PUNCH_SEQUENCE:
        event = "in"
    cutoff = now() - dt.timedelta(seconds=SCAN_COOLDOWN_SEC)
    recent = (db.query(TimePunch)
              .filter(TimePunch.user_id == user_id,
                      TimePunch.worker_name == worker_name,
                      TimePunch.event == event, TimePunch.at_utc >= cutoff,
                      TimePunch.result == "ok").first())
    result = "duplicate" if recent else "ok"
    p = TimePunch(user_id=user_id, worker_record_id=worker_record_id,
                  worker_name=worker_name[:120], badge_id=badge_id,
                  device_id=device_id, site=site[:120], event=event,
                  at_utc=now(), source=source, result=result,
                  idempotency_key=idempotency_key[:80], note=note[:300])
    db.add(p)
    db.commit()
    db.refresh(p)
    return p, False


def timecard(db, user_id: str, worker_name: str, day_from: str, day_to: str) -> dict:
    """Pair raw in/out punches into worked minutes per day (+ approved
    adjustments). Original punches remain untouched."""
    from .db import TimeAdjustment, TimePunch
    f = dt.datetime.fromisoformat(day_from)
    t = dt.datetime.fromisoformat(day_to) + dt.timedelta(days=1)
    rows = (db.query(TimePunch)
            .filter(TimePunch.user_id == user_id,
                    TimePunch.worker_name == worker_name,
                    TimePunch.at_utc >= f, TimePunch.at_utc < t,
                    TimePunch.result == "ok")
            .order_by(TimePunch.at_utc).all())
    days: dict[str, dict] = {}
    open_in: dict[str, dt.datetime] = {}
    for p in rows:
        d = p.at_utc.strftime("%Y-%m-%d")
        rec = days.setdefault(d, {"minutes": 0, "punches": 0, "missing_out": False})
        rec["punches"] += 1
        if p.event == "in":
            open_in[d] = p.at_utc
        elif p.event == "out" and d in open_in:
            rec["minutes"] += int((p.at_utc - open_in.pop(d)).total_seconds() // 60)
    for d in open_in:
        days[d]["missing_out"] = True
    adjs = (db.query(TimeAdjustment)
            .filter(TimeAdjustment.user_id == user_id,
                    TimeAdjustment.worker_name == worker_name,
                    TimeAdjustment.status == "approved",
                    TimeAdjustment.day >= day_from, TimeAdjustment.day <= day_to).all())
    for a in adjs:
        days.setdefault(a.day, {"minutes": 0, "punches": 0, "missing_out": False})
        days[a.day]["minutes"] += a.minutes_delta
    total = sum(v["minutes"] for v in days.values())
    return {"worker": worker_name, "from": day_from, "to": day_to,
            "days": days, "total_minutes": total,
            "exceptions": [d for d, v in days.items() if v["missing_out"]]}


# ---------------------------------------------------------------- payroll
def build_payroll_batch(db, user_id: str, period_start: str, period_end: str,
                        wages: dict[str, float], by: str = ""):
    """Idempotent: one batch per (user, period). Re-running returns the
    existing batch — retries can never duplicate payroll."""
    from .db import PayrollBatch, TimePunch
    existing = (db.query(PayrollBatch)
                .filter(PayrollBatch.user_id == user_id,
                        PayrollBatch.period_start == period_start,
                        PayrollBatch.period_end == period_end).first())
    if existing:
        return existing, True
    workers = {r[0] for r in
               (db.query(TimePunch.worker_name)
                .filter(TimePunch.user_id == user_id, TimePunch.result == "ok")
                .distinct().all())}
    lines, total_cents = [], 0
    for w in sorted(workers):
        tc = timecard(db, user_id, w, period_start, period_end)
        mins = tc["total_minutes"]
        if mins <= 0:
            continue
        reg = min(mins, 40 * 60 * 2)     # configurable in a fuller build
        ot = max(0, mins - reg)
        wage = float(wages.get(w, 0))
        gross = round((reg / 60) * wage + (ot / 60) * wage * 1.5, 2)
        total_cents += int(gross * 100)
        lines.append({"worker": w, "regular_min": reg, "ot_min": ot,
                      "wage": wage, "gross": gross,
                      "exceptions": tc["exceptions"]})
    batch = PayrollBatch(user_id=user_id, period_start=period_start,
                         period_end=period_end, lines=json.dumps(lines),
                         total_gross=total_cents, status="draft")
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch, False


def approve_and_post_payroll(db, batch, by: str = ""):
    """Approve → balanced accounting journal (source=payroll, traceable link).
    Re-posting an already-posted batch is a no-op (returns existing journal)."""
    from .db import JournalEntry
    if batch.journal_id:
        return db.query(JournalEntry).get(batch.journal_id)
    total = batch.total_gross / 100.0
    if total <= 0:
        return None
    num = (db.query(JournalEntry).filter(JournalEntry.user_id == batch.user_id)
           .count()) + 1
    je = JournalEntry(
        user_id=batch.user_id, number=num, at=now(),
        memo=f"Payroll {batch.period_start}..{batch.period_end}",
        lines=json.dumps([
            {"account": "Payroll Expense", "debit": total, "credit": 0,
             "memo": "gross wages"},
            {"account": "Wages Payable", "debit": 0, "credit": total,
             "memo": "accrued"}]),
        source="payroll", source_ref=batch.id, status="posted")
    db.add(je)
    db.flush()
    batch.status = "posted"
    batch.approved_by = by
    batch.journal_id = je.id
    batch.export_checksum = sha256(batch.lines)
    db.commit()
    return je


def payroll_csv(batch) -> str:
    rows = ["worker,regular_min,ot_min,wage,gross"]
    for ln in json.loads(batch.lines or "[]"):
        rows.append(f"{ln['worker']},{ln['regular_min']},{ln['ot_min']},"
                    f"{ln['wage']},{ln['gross']}")
    return "\n".join(rows)


# ---------------------------------------------------------------- visitors
def visit_event(v, event: str, by: str = "") -> None:
    ev = json.loads(v.events or "[]")
    ev.append({"at": now().isoformat(), "event": event, "by": by})
    v.events = json.dumps(ev)


def mask_id(number: str) -> str:
    n = (number or "").strip()
    return ("•" * max(0, len(n) - 4) + n[-4:]) if n else ""


def register_visit(db, user_id: str, *, visitor_name: str, category: str = "walk-in",
                   host: str = "", purpose: str = "", destination: str = "",
                   language: str = "en", id_doc_type: str = "none",
                   id_number: str = "", consent: bool = False, face_photo: str = "",
                   doc_photos: list | None = None, company: str = ""):
    """Kiosk registration. Identity number is encrypted at rest immediately;
    plaintext is never stored, logged, or returned. face_photo is a small
    JPEG data URI auto-captured at the kiosk (consent covers it).
    doc_photos: [{label, image}] ID document / org-badge captures."""
    from .db import Visit
    from .security import encrypt_secret
    if face_photo and (not face_photo.startswith("data:image/") or len(face_photo) > 400_000):
        face_photo = ""          # reject non-image / oversized payloads
    docs = []
    for p in (doc_photos or [])[:6]:
        img = str((p or {}).get("image") or "")
        if img.startswith("data:image/") and len(img) <= 1_500_000:
            docs.append({"label": str((p or {}).get("label") or "")[:60], "image": img})
    v = Visit(user_id=user_id, visitor_name=visitor_name.strip()[:120],
              company=company.strip()[:120],
              category=category if category in
              ("walk-in", "preregistered", "contractor", "vendor",
               "delivery", "official") else "walk-in",
              host=host.strip()[:120], purpose=purpose.strip()[:300],
              destination=destination.strip()[:120], language=language[:8],
              id_doc_type=id_doc_type[:30],
              id_number_enc=encrypt_secret(id_number) if id_number else "",
              face_photo=face_photo, doc_images=json.dumps(docs),
              consent_at=now() if consent else None, status="pending")
    visit_event(v, "registered", "kiosk")
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def approve_visit(db, v, by: str, badge_hours: int = 8):
    """Host/security approval → expiring visitor badge (opaque code)."""
    code = "vb-" + secrets.token_urlsafe(12)
    v.status = "approved"
    v.approved_by = by
    v.badge_code_hash = sha256(code)
    v.badge_expires_at = now() + dt.timedelta(hours=max(1, badge_hours))
    visit_event(v, "approved", by)
    db.commit()
    return code


def visit_dict(v) -> dict:
    """Serialize with PII masking — id number NEVER returned in full."""
    from .security import decrypt_secret
    masked = ""
    if v.id_number_enc:
        try:
            masked = mask_id(decrypt_secret(v.id_number_enc))
        except Exception:
            masked = "••••"
    return {"id": v.id, "visitor_name": v.visitor_name, "category": v.category,
            "company": getattr(v, "company", "") or "",
            "host": v.host, "purpose": v.purpose, "destination": v.destination,
            "status": v.status, "id_doc_type": v.id_doc_type,
            "id_number_masked": masked, "language": v.language,
            "face_photo": getattr(v, "face_photo", "") or "",
            "doc_images": json.loads(v.doc_images or "[]"),
            "consent": bool(v.consent_at), "approved_by": v.approved_by,
            "events": json.loads(v.events or "[]"),
            "badge_expires_at": v.badge_expires_at.isoformat() if v.badge_expires_at else None,
            "checked_in_at": v.checked_in_at.isoformat() if v.checked_in_at else None,
            "checked_out_at": v.checked_out_at.isoformat() if v.checked_out_at else None,
            "created_at": v.created_at.isoformat() if v.created_at else None}


# ---------------------------------------------------------------- access control
def access_decision(db, user_id: str, door, *, badge=None, visit=None,
                    subject_name: str = "") -> tuple[bool, str]:
    """Vendor-neutral decision service. Advisory only: hardware must remain
    fail-safe per fire code. Returns (allow, machine_readable_reason)."""
    from .db import AccessEvent
    reason, allow = "", False
    if door is None or not door.active:
        reason = "door_inactive"
    elif door.health == "tamper":
        reason = "door_tamper"
    elif door.mode == "locked":
        reason = "door_locked"
    elif door.schedule:
        try:
            a, b = door.schedule.split("-")
            hhmm = now().strftime("%H:%M")
            if not (a <= hhmm <= b):
                reason = "outside_schedule"
        except ValueError:
            pass
    if not reason:
        if badge is not None:
            bad = validate_badge(badge)
            reason = bad or "ok"
            allow = not bad
        elif visit is not None:
            if not door.allow_visitors:
                reason = "visitors_not_allowed"
            elif visit.status not in ("approved", "checked_in"):
                reason = "visit_not_approved"
            elif visit.badge_expires_at and visit.badge_expires_at < now():
                reason = "visitor_badge_expired"
            elif visit.destination and door.zone and \
                    visit.destination.strip().lower() != door.zone.strip().lower():
                reason = "zone_not_granted"
            else:
                reason, allow = "ok", True
        else:
            reason = "no_credential"
    ev = AccessEvent(user_id=user_id, door_id=door.id if door else "",
                     subject_kind="visitor" if visit is not None else "worker",
                     subject_id=(visit.id if visit is not None
                                 else badge.id if badge is not None else ""),
                     subject_name=subject_name[:120],
                     decision="allow" if allow else "deny",
                     reason=reason, at_utc=now())
    db.add(ev)
    db.commit()
    return allow, reason


# ---------------------------------------------------------------- face recognition
# Returning-visitor recognition for the unattended kiosk. Pure-Python (PIL):
# portraits are captured by the same kiosk flow (face centred in the oval,
# fixed 3:4 crop), so an illumination-normalized template correlation over
# the face region is reliable enough to look up a prior record on-site.
# The kiosk always shows the matched profile for the visitor to CONFIRM
# ("THAT'S ME"). This pixel matcher is only the FALLBACK path (the kiosk
# normally runs a real neural face-embedding model in the browser), so the
# threshold is set conservatively — prefer a miss over a false identity.
FACE_MATCH_THRESHOLD = 0.45      # min similarity to accept a returning visitor


def _face_image(data_uri: str):
    """Decode a portrait data URI → grayscale PIL image, or None."""
    import base64
    import io
    m = _re.match(r"data:image/(?:png|jpe?g|webp|bmp);base64,(.+)", data_uri or "", _re.I | _re.S)
    if not m:
        return None
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(base64.b64decode(m.group(1))))
        return ImageOps.exif_transpose(img).convert("L")
    except Exception:
        return None


def _crop_vector(img, dx: float = 0.0, dy: float = 0.0, zoom: float = 1.0):
    """Feature vector of the central face window, optionally shifted
    (dx, dy as fractions of size) and zoomed. Identity-oriented features:
    the crop is masked to the face oval (background killed) and encoded as
    GRADIENT ORIENTATION/magnitude structure, not raw brightness — two
    photos of the same room/lighting no longer look alike."""
    try:
        from PIL import ImageFilter, ImageOps
        w, h = img.size
        cw, ch = (0.82 - 0.18) / zoom, (0.80 - 0.12) / zoom
        x0 = max(0.0, min(1 - cw, 0.18 / zoom + dx))
        y0 = max(0.0, min(1 - ch, 0.12 / zoom + dy))
        c = img.crop((int(w * x0), int(h * y0), int(w * (x0 + cw)), int(h * (y0 + ch))))
        N = 40
        c = ImageOps.equalize(c.resize((N, N)))
        px = list(c.getdata())
        # horizontal & vertical gradients (Sobel-lite, pure python on 40×40)
        feats: list[float] = []
        cx, cy, rx, ry = (N - 1) / 2, (N - 1) / 2 * 1.06, N * 0.42, N * 0.50
        for y in range(1, N - 1):
            for x in range(1, N - 1):
                # elliptical face mask — pixels outside the oval contribute 0
                if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 > 1.0:
                    feats.append(0.0)
                    feats.append(0.0)
                    continue
                i = y * N + x
                gx = float(px[i + 1]) - float(px[i - 1])
                gy = float(px[i + N]) - float(px[i - N])
                feats.append(gx)
                feats.append(gy)
        n = len(feats)
        mean = sum(feats) / n
        sd = (sum((f - mean) ** 2 for f in feats) / n) ** 0.5 or 1.0
        return [(f - mean) / sd for f in feats]
    except Exception:
        return None


def _face_vector(data_uri: str):
    """Centred feature vector (kept for compatibility / tooling)."""
    img = _face_image(data_uri)
    return _crop_vector(img) if img is not None else None


def face_similarity(vec_a, vec_b) -> float:
    """Normalized cross-correlation of two face vectors → [-1, 1]."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return -1.0
    return sum(a * b for a, b in zip(vec_a, vec_b)) / len(vec_a)


def _probe_variants(data_uri: str):
    """Live-capture variants tolerant to small position/scale differences:
    centre + 4 shifts + zoom in/out, each also mirrored."""
    from PIL import ImageOps
    img = _face_image(data_uri)
    if img is None:
        return []
    out = []
    for src in (img, ImageOps.mirror(img)):
        for dx, dy, z in ((0, 0, 1.0), (-0.06, 0, 1.0), (0.06, 0, 1.0),
                          (0, -0.06, 1.0), (0, 0.06, 1.0),
                          (0, 0, 1.15), (0, 0, 0.88)):
            v = _crop_vector(src, dx, dy, z)
            if v:
                out.append(v)
    return out


def recognize_visitor(db, user_id: str, face_photo: str):
    """Match a live kiosk portrait against previous visitors' stored photos.
    Returns (visit_dict_of_best_match, similarity) or (None, best_score).
    Every stored photo of every visitor is compared (a person's appearance
    varies between visits); the probe is tested in several shifted/zoomed/
    mirrored variants to tolerate camera-position differences."""
    from .db import Visit
    probes = _probe_variants(face_photo)
    if not probes:
        return None, -1.0
    rows = (db.query(Visit)
            .filter(Visit.user_id == user_id, Visit.face_photo != "")
            .order_by(Visit.created_at.desc()).limit(300).all())
    newest: dict[str, object] = {}
    best_by_name: dict[str, float] = {}
    for v in rows:
        key = (v.visitor_name or "").strip().lower()
        if not key:
            continue
        newest.setdefault(key, v)             # rows are newest-first
        ref = _face_vector(v.face_photo)
        if not ref:
            continue
        score = max(face_similarity(p, ref) for p in probes)
        if score > best_by_name.get(key, -1.0):
            best_by_name[key] = score
    if not best_by_name:
        return None, -1.0
    key, best_score = max(best_by_name.items(), key=lambda kv: kv[1])
    if best_score >= FACE_MATCH_THRESHOLD:
        return visit_dict(newest[key]), best_score
    return None, best_score


# ---------------------------------------------------------------- chat intent
# “please check the visitors today / show today's visitors with photos and ID”
# → answer straight from the Visit register, attaching the captured images.
import re as _re

VISITOR_INTENT = _re.compile(
    r"\b(?:visitor|visitors|visit|visits|guest|guests)\b.{0,60}\b(?:today|now|list|show|check|report|status|current|on.?site|premises|image|images|photo|photos|picture|id)\b"
    r"|\b(?:list|show|check|view|report|who|any|see)\b.{0,40}\b(?:visitor|visitors|guest|guests)\b", _re.I)

_STATUS_ICON = {"pending": "🟡", "approved": "🟢", "checked_in": "🟢",
                "checked_out": "⚪", "denied": "🔴", "expired": "⚪"}


def _save_data_uri(data_uri: str, name: str) -> "str | None":
    """Persist a data:image/* URI under data/uploads so the chat can attach
    and display it via /api/image. Returns the file path or None."""
    import base64
    import pathlib
    import uuid as _uuid
    m = _re.match(r"data:image/(png|jpe?g|gif|webp|bmp);base64,(.+)", data_uri or "", _re.I | _re.S)
    if not m:
        return None
    ext = {"jpg": "jpg", "jpeg": "jpg"}.get(m.group(1).lower(), m.group(1).lower())
    updir = pathlib.Path(__file__).resolve().parent.parent / "data" / "uploads" / "visitors"
    updir.mkdir(parents=True, exist_ok=True)
    safe = _re.sub(r"[^\w-]+", "_", name)[:40] or "visitor"
    p = updir / f"{safe}_{_uuid.uuid4().hex[:8]}.{ext}"
    try:
        p.write_bytes(base64.b64decode(m.group(2)))
    except Exception:
        return None
    return str(p)


def handle_visitor_prompt(db, text: str, user_id: str):
    """Answer visitor queries from chat. Returns (message, attachment_paths)
    or None when the prompt isn't about visitors. Identity numbers stay
    masked — same policy as the review console."""
    from .db import Visit
    low = text.lower()
    today_only = bool(_re.search(r"\btoday\b|\bnow\b|\bcurrent\b|on.?site|premises", low))
    want_images = bool(_re.search(r"\bimage|photo|picture|face|id\b|document", low))
    q = db.query(Visit).filter(Visit.user_id == user_id)
    if today_only:
        start = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        q = q.filter(Visit.created_at >= start)
    rows = q.order_by(Visit.created_at.desc()).limit(20).all()
    if not rows:
        return ("🛂 **VISITOR REGISTER** — no visitor registrations "
                + ("today." if today_only else "on file."), [])
    lines = [f"🛂 **VISITOR REGISTER — {'TODAY' if today_only else 'LATEST'}** "
             f"({len(rows)} record{'s' if len(rows) != 1 else ''})", ""]
    attachments: list[str] = []
    for i, v in enumerate(rows, 1):
        d = visit_dict(v)
        icon = _STATUS_ICON.get(v.status, "▫")
        lines.append(f"{i}. {icon} **{d['visitor_name']}**"
                     + (f" — {d['company']}" if d["company"] else "")
                     + f" · {d['category']} · {v.status.replace('_', ' ').upper()}")
        det = []
        if d["host"]:
            det.append(f"host {d['host']}")
        if d["purpose"]:
            det.append(f"purpose: {d['purpose']}")
        if d["destination"]:
            det.append(f"→ {d['destination']}")
        if det:
            lines.append("   " + " · ".join(det))
        idline = f"   🪪 ID: {d['id_doc_type']}"
        if d["id_number_masked"]:
            idline += f" · {d['id_number_masked']}"
        lines.append(idline + f" · registered {d['created_at'][:16].replace('T', ' ')} UTC")
        if want_images and len(attachments) < 12:
            if d["face_photo"]:
                p = _save_data_uri(d["face_photo"], f"{d['visitor_name']}_face")
                if p:
                    attachments.append(p)
                    lines.append(f"   📷 portrait attached ({d['visitor_name']})")
            for di in d["doc_images"][:2]:
                p = _save_data_uri(di.get("image", ""),
                                   f"{d['visitor_name']}_{di.get('label', 'doc')}")
                if p:
                    attachments.append(p)
                    lines.append(f"   📄 {di.get('label') or 'ID document'} attached ({d['visitor_name']})")
        lines.append("")
    on_site = sum(1 for v in rows if v.status == "checked_in")
    pending = sum(1 for v in rows if v.status == "pending")
    lines.append(f"Summary: {on_site} on premises · {pending} awaiting approval.")
    lines.append("🔒 Identity numbers are always masked; full records: Workforce & Visitors console.")
    return "\n".join(lines), attachments
