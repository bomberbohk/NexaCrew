"""Security: password hashing, session tokens, credential encryption,
permission checks, company-boundary enforcement, tamper-evident audit log."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .db import AuditEvent, User, VirtualCompany, get_db

_SECRETS_DIR = Path(__file__).resolve().parent.parent / "data"
_SECRETS_DIR.mkdir(parents=True, exist_ok=True)
_KEY_FILE = _SECRETS_DIR / ".secret_key"


def _load_key() -> bytes:
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    return key


_FERNET = Fernet(_load_key())
_SESSION_KEY = _load_key()  # HMAC key for session tokens

SESSIONS: dict[str, str] = {}  # token -> user_id (in-memory sessions)

PERMISSIONS = [
    "view", "create", "edit", "archive", "delete",
    "draft_external", "send_external", "access_files",
    "execute_code", "use_integrations", "manage_credentials",
    "manage_org",
]

SENSITIVE_ACTIONS = {"send_email", "delete_data", "modify_credentials"}


# ---------------- passwords / sessions ----------------
def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return hmac.compare_digest(calc, digest)


def create_session(user_id: str, ip: str = "", ua: str = "") -> str:
    token = secrets.token_urlsafe(32)
    import time as _t
    SESSIONS[token] = {"uid": user_id, "seen": _t.time(),
                       "ip": ip[:64], "ua": ua[:200]}
    return token


def revoke_other_sessions(user_id: str, keep_token: str) -> int:
    """Kill every other session of this user (one person = one account =
    one active sign-in). Returns how many sessions were revoked so the
    caller can audit-log an account-sharing / stolen-password signal."""
    stale = [t for t, rec in list(SESSIONS.items())
             if t != keep_token
             and (rec.get("uid") if isinstance(rec, dict) else rec) == user_id]
    for t in stale:
        SESSIONS.pop(t, None)
    return len(stale)


def destroy_session(token: str) -> None:
    SESSIONS.pop(token, None)


_SESSION_IDLE_TTL = 24 * 3600      # 24 h inactivity
_SESSION_MAX_SESSIONS = 10000      # hard cap — drop oldest (DoS guard)


def _session_uid(token: str) -> "str | None":
    """Resolve a session token → user id with sliding idle expiry."""
    import time as _t
    rec = SESSIONS.get(token or "")
    if rec is None:
        return None
    if isinstance(rec, str):                      # legacy record — upgrade
        rec = {"uid": rec, "seen": _t.time()}
        SESSIONS[token] = rec
    if _t.time() - rec["seen"] > _SESSION_IDLE_TTL:
        SESSIONS.pop(token, None)
        return None
    rec["seen"] = _t.time()
    if len(SESSIONS) > _SESSION_MAX_SESSIONS:     # evict stalest
        for k in sorted(SESSIONS, key=lambda k: SESSIONS[k]["seen"])[:100]:
            SESSIONS.pop(k, None)
    return rec["uid"]


# ---------------- credential encryption ----------------
def encrypt_secret(plaintext: str) -> str:
    return _FERNET.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _FERNET.decrypt(ciphertext.encode()).decode()


# ---------------- auth dependency ----------------
def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("session")
    user_id = _session_uid(token or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not signed in")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Unknown user")
    return user


def optional_user(request: Request, db: Session = Depends(get_db)):
    """Best-effort auth — returns the signed-in User or None. Used by kiosk
    beacon endpoints that must work from the login screen (device shows up
    in the admin Clients panel before anyone signs in on it)."""
    try:
        return current_user(request, db)
    except HTTPException:
        return None


# ---------------- company boundary ----------------
def effective_company_owner_id(user: User) -> str:
    """Resolve the tenant whose Virtual Company registry (companies,
    employees, skills, schedules) this user should see. A worker bound at
    HR enrollment (users.company_owner_id) sees THEIR employer's registry,
    matching the same tenant-binding used for the Business/ERP workspace
    (see business.biz_owner_id); everyone else sees their own."""
    owner_id = (user.company_owner_id or "").strip()
    return owner_id or user.id


def require_company(db: Session, company_id: str, user=None) -> VirtualCompany:
    """Fetch a company; when a user is given, enforce per-tenant isolation:
    users only access companies owned by their resolved tenant (see
    effective_company_owner_id). Unowned legacy companies are admin-only
    and are claimed by the first admin that touches them."""
    company = db.get(VirtualCompany, company_id)
    if not company or company.deleted_at:
        raise HTTPException(status_code=404, detail="Company not found")
    if user is not None:
        tenant_id = effective_company_owner_id(user)
        if company.owner_user_id is None:
            if not user.is_admin:
                raise HTTPException(status_code=404, detail="Company not found")
            company.owner_user_id = user.id
            db.commit()
        elif company.owner_user_id != tenant_id:
            raise HTTPException(status_code=404, detail="Company not found")
    return company


def check_company_scope(obj, company_id: str) -> None:
    """Block insecure direct object references across companies."""
    if getattr(obj, "company_id", None) not in (None, company_id):
        raise HTTPException(status_code=403, detail="Cross-company access denied")


def employee_has_permission(employee, perm: str) -> bool:
    try:
        perms = json.loads(employee.permissions or "[]")
    except json.JSONDecodeError:
        perms = []
    return perm in perms


# ---------------- tamper-evident audit ----------------
_AUDIT_LOCK = threading.Lock()   # chain integrity: one writer at a time


def audit(db: Session, action: str, detail: str = "", company_id: Optional[str] = None,
          user_id: Optional[str] = None, employee_id: Optional[str] = None) -> AuditEvent:
    from sqlalchemy import text as _text
    # Without serialization two concurrent writers read the same tail and
    # emit entries with identical prev_hash — a permanently broken chain.
    with _AUDIT_LOCK:
        last = db.query(AuditEvent).order_by(_text("rowid DESC")).first()
        prev_hash = last.entry_hash if last else ""
        payload = f"{prev_hash}|{action}|{detail}|{company_id}|{user_id}|{dt.datetime.utcnow().isoformat()}"
        entry_hash = hashlib.sha256(payload.encode()).hexdigest()
        ev = AuditEvent(company_id=company_id, user_id=user_id, employee_id=employee_id,
                        action=action, detail=detail[:4000], prev_hash=prev_hash, entry_hash=entry_hash)
        db.add(ev)
        db.commit()
    return ev
