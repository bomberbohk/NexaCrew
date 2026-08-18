"""NexaCrew — Virtual Company AI Agent Platform — FastAPI application.

Run:  python -m uvicorn app.main:app --port 8600  (from platform/ dir)
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import socket
import threading
import time as _time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .db import (
    AgentRun, ApprovalRequest, AuditEvent, Chat, Department, EmailDraft,
    EmailIdentity, LicenseKey, Message, Project, SOP, Shift, Task, Team, User,
    VirtualCompany, VirtualEmployee, Workflow, Workspace, get_db, init_db,
)
from . import tz
from .providers import CodexProvider
from .security import (
    PERMISSIONS, audit, check_company_scope, create_session, current_user,
    destroy_session, effective_company_owner_id, encrypt_secret,
    hash_password, optional_user, revoke_other_sessions,
    require_company, verify_password,
)
from .services import execute_approved_email, run_agent_message

app = FastAPI(title="NexaCrew — Virtual Company AI Agent Platform",
              description="Developed by Sin Chi Chi · MAP Studio",
              contact={"name": "Sin Chi Chi — MAP Studio"})
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
ROOT_DIR = Path(__file__).resolve().parent.parent.parent   # AGENT_AI program root


def _app_version() -> str:
    try:
        return (ROOT_DIR / "VERSION").read_text(encoding="utf-8-sig").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


APP_VERSION = _app_version()

from . import sysmon  # noqa: E402

sysmon.start_monitor()


# ---------------------------------------------------------------------------
# Freeze failsafe — crash & frozen prevention inside the server process.
# A watchdog thread asks the asyncio event loop to bump a heartbeat counter.
# If the loop stops responding for FREEZE_LIMIT_S (deadlocked / hung), the
# process force-exits with code 3 so the start.py watchdog (or the OS service
# manager) restarts it immediately. This protects even against kernel-level
# deadlocks that a normal exception handler could never catch.
# ---------------------------------------------------------------------------
FREEZE_LIMIT_S = 60
_hb = {"t": _time.time(), "loop": None}


@app.on_event("startup")
async def _capture_loop() -> None:
    _hb["loop"] = asyncio.get_running_loop()
    _hb["t"] = _time.time()

    def _beat() -> None:
        _hb["t"] = _time.time()

    def _failsafe() -> None:
        while True:
            _time.sleep(10)
            loop = _hb["loop"]
            if loop is None or loop.is_closed():
                return
            try:
                loop.call_soon_threadsafe(_beat)
            except RuntimeError:
                return
            if _time.time() - _hb["t"] > FREEZE_LIMIT_S:
                print(f"🐶 FREEZE FAILSAFE: event loop unresponsive for >{FREEZE_LIMIT_S}s "
                      "— force-exiting so the watchdog restarts the server", flush=True)
                os._exit(3)

    threading.Thread(target=_failsafe, daemon=True, name="freeze-failsafe").start()

    # server-installation license — periodic validation against the
    # mapstudiousa.com licensing authority (72 h offline grace)
    from .license_authority import start_background_validation
    from .config import get_config as _lic_cfg
    start_background_validation(_lic_cfg)

    # developer account — config is authoritative: grant the flag to the
    # configured username, revoke it from everyone else (least privilege)
    try:
        from .db import SessionLocal as _SL
        dev_name = (_lic_cfg().get("developer_username") or "").strip()
        with _SL() as _db:
            changed = False
            for u in _db.query(User).filter(User.is_developer == True).all():  # noqa: E712
                if u.username != dev_name:
                    u.is_developer = False
                    changed = True
            if dev_name:
                u = _db.query(User).filter(User.username == dev_name).first()
                if u and not u.is_developer:
                    u.is_developer = True
                    changed = True
            if changed:
                _db.commit()
    except Exception as e:  # noqa: BLE001 — startup must not die on this
        print(f"⚠ developer flag sync failed: {e}", flush=True)

    # automatic server updates from mapstudiousa.com (clients then update
    # themselves from this server via the existing heartbeat updater)
    threading.Thread(target=_portal_auto_updater, daemon=True,
                     name="portal-auto-update").start()
    # clustering: when a cluster peer runs a newer version, converge right away
    _cluster.on_update_available = _UPDATE_CHECK_NOW.set


# NOTE: security response headers are applied by the single _security_headers
# middleware further below (X-Frame-Options DENY, camera=(self) for the
# check-in kiosks, no-cache for UI code). A duplicate middleware here once
# overrode those hardened values with weaker ones — do not re-add it.


@app.middleware("http")
async def _traffic_meter(request: Request, call_next):
    """Meters the network traffic served by this application."""
    try:
        bytes_in = int(request.headers.get("content-length") or 0)
    except ValueError:
        bytes_in = 0
    response = await call_next(request)
    try:
        bytes_out = int(response.headers.get("content-length") or 0)
    except ValueError:
        bytes_out = 0
    sysmon.track_request(bytes_in, bytes_out)
    return response

from . import ops_console
ops_console.install(port=int(os.environ.get("NEXACREW_PORT", "8600")))

init_db()


def _d(obj, extra: dict | None = None) -> dict:
    """Serialize an ORM object, excluding secrets."""
    out = {}
    for c in obj.__table__.columns:
        if c.name in ("password_hash", "encrypted_credentials", "encrypted_secret"):
            continue
        v = getattr(obj, c.name)
        out[c.name] = v.isoformat() if isinstance(v, dt.datetime) else v
    if extra:
        out.update(extra)
    return out


# ==================== Auth ====================
class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=4, max_length=200)
    display_name: str = ""
    face: str = ""          # optional webcam frame (data URI) for the ops log


@app.post("/api/auth/setup")
def setup(creds: Credentials, db: Session = Depends(get_db)):
    if db.query(User).count():
        raise HTTPException(400, "Already initialized — sign in instead")
    user = User(username=creds.username, display_name=creds.display_name or creds.username,
                password_hash=hash_password(creds.password), is_admin=True)
    db.add(user)
    db.commit()
    ws = Workspace(name="Default Workspace", owner_id=user.id)
    db.add(ws)
    db.commit()
    audit(db, "auth.setup", f"user={creds.username}", user_id=user.id)
    return {"ok": True}


@app.post("/api/auth/login")
def login(creds: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    # brute-force protection: max 10 failed attempts per IP per 5 minutes
    ip = request.client.host if request.client else "?"
    now = _time.time()
    attempts = [t for t in _login_fails.get(ip, []) if now - t < 300]
    if len(attempts) >= 10:
        raise HTTPException(429, "Too many failed attempts — try again in a few minutes")
    user = db.query(User).filter(User.username == creds.username).first()
    if not user or not verify_password(creds.password, user.password_hash):
        # Fall back to mapstudiousa.com NexaCrew portal credentials: any
        # customer account created in the portal (or by the site admin) can
        # sign in to this licensed installation with the same e-mail+password.
        portal_ok = False
        if "@" in creds.username:
            try:
                from .config import get_config
                from .license_authority import portal_auth
                res = portal_auth(get_config(), creds.username, creds.password)
                portal_ok = bool(res.get("ok"))
            except Exception as e:  # noqa: BLE001 — auth fallback must not 500
                logging.getLogger("auth").warning("portal auth unavailable: %s", e)
                res = {}
            if portal_ok:
                if not user:
                    # auto-provision: local row exists only to hold sessions;
                    # the password stays remote (random local hash, unusable)
                    import secrets as _sec
                    user = User(username=creds.username,
                                display_name=res.get("display_name") or creds.username,
                                password_hash=hash_password(_sec.token_hex(24)),
                                is_admin=True)  # portal account = licence owner
                    db.add(user)
                    db.commit()
                    audit(db, "auth.portal_provision",
                          f"user={creds.username} auto-created from mapstudiousa.com portal",
                          user_id=user.id)
        if not portal_ok:
            attempts.append(now)
            _login_fails[ip] = attempts
            raise HTTPException(401, "Invalid username or password")
    _login_fails.pop(ip, None)
    ua = request.headers.get("user-agent", "")
    token = create_session(user.id, ip=ip, ua=ua)
    # Every worker must use their OWN account: a non-admin account allows
    # exactly one active sign-in. A second login (another PC / another
    # person) revokes the previous session — shared credentials become
    # immediately visible in the audit log instead of silently working.
    if not user.is_admin:
        kicked = revoke_other_sessions(user.id, token)
        if kicked:
            audit(db, "auth.session_replaced",
                  f"user={user.username} previous_sessions={kicked} new_ip={ip} "
                  "— possible account sharing; each worker must use their own account",
                  user_id=user.id)
    response.set_cookie("session", token, httponly=True, samesite="strict")
    audit(db, "auth.login", f"ip={ip} face={_store_login_face(db, user, creds.face)}",
          user_id=user.id)
    return {"ok": True, "user": _d(user)}


def _store_login_face(db: Session, user: User, data_uri: str) -> str:
    """Best-effort login face capture for the operations log. Verifies a
    human face and stores the JPEG in op_faces; returns the face id or
    'NONE'. Never blocks login — attribution failures are audited instead."""
    if not data_uri or not data_uri.startswith("data:image/") \
            or len(data_uri) > 8 * 1024 * 1024:
        return "NONE"
    try:
        from . import face_recog as _fm
        if not _fm.has_face(data_uri):
            return "NONE"
        import base64 as _b64
        import uuid as _uuid
        raw = _b64.b64decode(data_uri.split(",", 1)[1])
        face_id = f"{_dt_now_stamp()}_{user.username}_{_uuid.uuid4().hex[:6]}.jpg"
        (OP_FACE_DIR / face_id).write_bytes(raw)
        return face_id
    except Exception:                                    # noqa: BLE001
        logging.getLogger("auth").warning("login face store failed", exc_info=True)
        return "NONE"


@app.post("/api/auth/badge-login")
def badge_login(body: dict, request: Request, response: Response,
                db: Session = Depends(get_db)):
    """Sign in by scanning a worker-badge QR (opaque wb-… token). The badge
    resolves to the worker's HR record and its provisioned login account.
    An optional webcam frame is stored for the operations log."""
    ip = request.client.host if request.client else "?"
    now = _time.time()
    attempts = [t for t in _login_fails.get("bdg:" + ip, []) if now - t < 300]
    if len(attempts) >= 10:
        raise HTTPException(429, "Too many failed attempts — try again in a few minutes")
    token = str(body.get("badge") or "").strip()
    badge = wf_mod.find_badge_by_token(db, None, token)
    reason = wf_mod.validate_badge(badge)
    if reason:
        attempts.append(now)
        _login_fails["bdg:" + ip] = attempts
        audit(db, "auth.badge_login.fail", f"ip={ip} reason={reason}")
        raise HTTPException(403, {"badge_unknown": "Badge not recognized",
                                  "badge_revoked": "This badge has been revoked",
                                  "badge_suspended": "This badge is suspended",
                                  "badge_expired": "This badge has expired",
                                  }.get(reason, "Badge is not usable"))
    # badge → HR worker record → provisioned login account
    user = None
    if badge.worker_record_id:
        rec = db.query(BusinessRecord).filter(
            BusinessRecord.id == badge.worker_record_id).first()
        if rec is not None:
            try:
                uname = str(json.loads(rec.data or "{}").get("login_username") or "").strip()
            except Exception:
                uname = ""
            if uname:
                user = db.query(User).filter(User.username == uname,
                                             User.deleted_at.is_(None)).first()
    if user is None:
        attempts.append(now)
        _login_fails["bdg:" + ip] = attempts
        audit(db, "auth.badge_login.fail",
              f"ip={ip} badge of '{badge.worker_name}' has no login account")
        raise HTTPException(403, "This badge has no login account — ask your "
                                 "administrator to set a login on your HR record")
    _login_fails.pop("bdg:" + ip, None)
    ua = request.headers.get("user-agent", "")
    stoken = create_session(user.id, ip=ip, ua=ua)
    if not user.is_admin:
        kicked = revoke_other_sessions(user.id, stoken)
        if kicked:
            audit(db, "auth.session_replaced",
                  f"user={user.username} previous_sessions={kicked} new_ip={ip} "
                  "— badge login replaced an existing session", user_id=user.id)
    response.set_cookie("session", stoken, httponly=True, samesite="strict")
    face_id = _store_login_face(db, user, str(body.get("face") or ""))
    audit(db, "auth.badge_login",
          f"ip={ip} badge={badge.worker_name} face={face_id}", user_id=user.id)
    return {"ok": True, "user": _d(user)}


_login_fails: dict[str, list] = {}


@app.post("/api/auth/verify-admin")
def verify_admin(creds: Credentials, request: Request, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Re-authenticate with ADMINISTRATOR credentials (client-side Setup gate).
    The signed-in normal user must present a valid admin username+password."""
    ip = request.client.host if request.client else "?"
    now = _time.time()
    attempts = [t for t in _login_fails.get("adm:" + ip, []) if now - t < 300]
    if len(attempts) >= 10:
        raise HTTPException(429, "Too many failed attempts — try again in a few minutes")
    admin = db.query(User).filter(User.username == creds.username).first()
    if not admin or not admin.is_admin or not verify_password(creds.password, admin.password_hash):
        attempts.append(now)
        _login_fails["adm:" + ip] = attempts
        audit(db, "auth.verify_admin.fail", f"by={user.username}", user_id=user.id)
        raise HTTPException(401, "Administrator username or password is incorrect")
    _login_fails.pop("adm:" + ip, None)
    audit(db, "auth.verify_admin.ok", f"admin={admin.username} by={user.username}", user_id=user.id)
    return {"ok": True}


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    """Hardening headers on every response (clickjacking, MIME sniffing,
    referrer leakage, legacy XSS filter)."""
    # record the real network address of kiosk devices so the operations
    # console / fleet board shows genuine IPs (not User-Agent artefacts)
    if request.url.path.startswith("/api/workforce/"):
        try:
            from . import workforce as _wf
            _wf.set_device_ip(request.client.host if request.client else "")
        except Exception:
            pass
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-XSS-Protection", "1; mode=block")
    # camera=(self): the check-in / visitor kiosks scan badge QR codes with
    # the device camera; microphone & geolocation stay fully blocked.
    resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    # never let browsers cache stale UI code — a cached old app.js against a
    # new index.html made menu clicks render nothing
    p = request.url.path
    if p == "/" or p.endswith((".js", ".css", ".html")):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    destroy_session(request.cookies.get("session", ""))
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request, db: Session = Depends(get_db)):
    needs_setup = db.query(User).count() == 0
    _touch_client_ip(db, request)
    try:
        user = current_user(request, db)
        return {"user": _d(user), "needs_setup": needs_setup}
    except HTTPException:
        return {"user": None, "needs_setup": needs_setup}


_touch_cache: dict[str, float] = {}


def _touch_client_ip(db: Session, request: Request) -> None:
    """Any activity from an IP bound to a license counts as liveness, so
    clients show online even if the local beacon isn't running."""
    try:
        ip = request.client.host if request.client else ""
        if not ip or ip in ("127.0.0.1", "::1"):
            return
        now = _time.time()
        if now - _touch_cache.get(ip, 0) < 20:  # throttle DB writes
            return
        _touch_cache[ip] = now
        lic = db.query(LicenseKey).filter(
            LicenseKey.used_by_ip == ip, LicenseKey.revoked.is_(False)).first()
        if lic:
            lic.last_seen_at = dt.datetime.utcnow()
            db.commit()
    except Exception:  # noqa: BLE001 — liveness must never break requests
        pass


# ==================== User management (administrator) ====================
def require_admin(user: User) -> None:
    if not user.is_admin:
        raise HTTPException(403, "Administrator privileges required")


def require_developer(user: User) -> None:
    """Developer mode — the highest permission tier, above administrator.
    Granted exclusively through the server's `developer_username` config
    (synchronized at startup); it can never be self-assigned via the API."""
    if not getattr(user, "is_developer", False):
        raise HTTPException(403, "Developer privileges required")


class UserIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str | None = Field(default=None, max_length=200)
    display_name: str = ""
    is_admin: bool = False
    company_owner_id: str = Field(default="", max_length=64)


def _validate_company_binding(db: Session, owner_id: str) -> str:
    """Validate a company-tenant binding target. Returns the cleaned id.
    '' unbinds (user falls back to own/legacy tenant resolution)."""
    oid = (owner_id or "").strip()
    if not oid:
        return ""
    ok = (db.query(BusinessProfile)
          .filter(BusinessProfile.user_id == oid,
                  BusinessProfile.usage_mode == "commercial").first())
    if not ok:
        raise HTTPException(400, "Unknown company — pick one of the companies deployed on this server")
    return oid


@app.get("/api/users")
def list_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    return [_d(u) for u in db.query(User).filter(User.deleted_at.is_(None)).all()]


@app.post("/api/users")
def create_user(body: UserIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    if not body.password or len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if db.query(User).filter(User.username == body.username, User.deleted_at.is_(None)).first():
        raise HTTPException(400, "Username already exists")
    u = User(username=body.username, display_name=body.display_name or body.username,
             password_hash=hash_password(body.password), is_admin=body.is_admin,
             company_owner_id=_validate_company_binding(db, body.company_owner_id))
    db.add(u)
    db.commit()
    audit(db, "user.create",
          f"username={u.username} admin={u.is_admin} company={u.company_owner_id or 'none'}",
          user_id=user.id)
    return _d(u)


@app.put("/api/users/{uid}")
def update_user(uid: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    u = db.get(User, uid)
    if not u or u.deleted_at:
        raise HTTPException(404, "User not found")
    changes = []
    if body.get("username") and body["username"] != u.username:
        if db.query(User).filter(User.username == body["username"], User.deleted_at.is_(None)).first():
            raise HTTPException(400, "Username already exists")
        changes.append(f"username: '{u.username}' → '{body['username']}'")
        u.username = str(body["username"])[:80]
    if "display_name" in body:
        if str(body["display_name"])[:120] != (u.display_name or ""):
            changes.append(f"display_name: '{u.display_name or ''}' → '{str(body['display_name'])[:120]}'")
        u.display_name = str(body["display_name"])[:120]
    if body.get("password"):
        if len(str(body["password"])) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        u.password_hash = hash_password(str(body["password"]))
        revoke_other_sessions(u.id, "")  # force re-login everywhere with new password
        changes.append("password: ******** (changed, sessions revoked)")
    if "is_admin" in body:
        if u.id == user.id and not body["is_admin"]:
            raise HTTPException(400, "You cannot remove your own administrator role")
        if bool(body["is_admin"]) != bool(u.is_admin):
            changes.append(f"is_admin: {u.is_admin} → {bool(body['is_admin'])}")
        u.is_admin = bool(body["is_admin"])
    if "company_owner_id" in body:
        new_oid = _validate_company_binding(db, str(body["company_owner_id"] or ""))
        if new_oid != (u.company_owner_id or ""):
            changes.append(f"company: '{u.company_owner_id or 'none'}' → '{new_oid or 'none'}'")
        u.company_owner_id = new_oid
    db.commit()
    audit(db, "user.update", f"user={u.username} changes[{'; '.join(changes) or 'none'}]", user_id=user.id)
    return _d(u)


@app.delete("/api/users/{uid}")
def delete_user(uid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    if uid == user.id:
        raise HTTPException(400, "You cannot delete your own account")
    u = db.get(User, uid)
    if not u or u.deleted_at:
        raise HTTPException(404, "User not found")
    u.deleted_at = dt.datetime.utcnow()
    db.commit()
    revoke_other_sessions(u.id, "")  # sign the removed worker out everywhere
    audit(db, "user.delete", f"username={u.username}", user_id=user.id)
    return {"ok": True}


# ==================== Companies ====================
class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    logo: str = "🏢"
    description: str = ""
    industry: str = ""
    website: str = ""
    address: str = ""
    timezone: str = "UTC"
    mission: str = ""
    operating_principles: str = ""
    brand_voice: str = ""
    ai_instructions: str = ""


@app.get("/api/companies")
def list_companies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Per-tenant isolation: a bound worker (users.company_owner_id, set at HR
    # enrollment) sees their employer's companies; everyone else sees their
    # own. Legacy companies without an owner stay visible to admins.
    tenant_id = effective_company_owner_id(user)
    rows = (db.query(VirtualCompany)
            .filter(VirtualCompany.deleted_at.is_(None),
                    (VirtualCompany.owner_user_id == tenant_id) |
                    (VirtualCompany.owner_user_id.is_(None) if user.is_admin else False))
            .all())
    return [_d(c) for c in rows]


def _owned_company_ids(db: Session, user: User) -> list:
    """IDs of companies this user may access (own tenant; admins also legacy unowned)."""
    tenant_id = effective_company_owner_id(user)
    q = db.query(VirtualCompany.id).filter(VirtualCompany.deleted_at.is_(None))
    if user.is_admin:
        q = q.filter((VirtualCompany.owner_user_id == tenant_id) |
                     (VirtualCompany.owner_user_id.is_(None)))
    else:
        q = q.filter(VirtualCompany.owner_user_id == tenant_id)
    return [r[0] for r in q.all()]


@app.post("/api/companies")
def create_company(body: CompanyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ws = db.query(Workspace).first()
    if ws is None:  # fresh database where the seed never ran
        ws = Workspace(name="Default Workspace", owner_id=user.id)
        db.add(ws)
        db.commit()
    tenant_id = effective_company_owner_id(user)
    c = VirtualCompany(workspace_id=ws.id, owner_user_id=tenant_id, **body.model_dump())
    db.add(c)
    db.commit()
    audit(db, "company.create", c.name, company_id=c.id, user_id=user.id)
    return _d(c)


@app.put("/api/companies/{cid}")
def update_company(cid: str, body: CompanyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = require_company(db, cid, user)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    audit(db, "company.update", c.name, company_id=cid, user_id=user.id)
    return _d(c)


@app.delete("/api/companies/{cid}")
def delete_company(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = require_company(db, cid, user)
    c.deleted_at = dt.datetime.utcnow()
    db.commit()
    audit(db, "company.delete", c.name, company_id=cid, user_id=user.id)
    return {"ok": True}


# ==================== Departments ====================
class DeptIn(BaseModel):
    name: str
    parent_id: Optional[str] = None


@app.get("/api/companies/{cid}/departments")
def list_departments(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    rows = db.query(Department).filter(Department.company_id == cid, Department.deleted_at.is_(None)).all()
    return [_d(x) for x in rows]


@app.post("/api/companies/{cid}/departments")
def create_department(cid: str, body: DeptIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    d = Department(company_id=cid, name=body.name, parent_id=body.parent_id)
    db.add(d)
    db.commit()
    audit(db, "department.create", d.name, company_id=cid, user_id=user.id)
    return _d(d)


# ==================== Employees ====================
class EmployeeIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    avatar: str = "🧑‍💼"
    department_id: Optional[str] = None
    manager_id: Optional[str] = None
    job_title: str = ""
    biography: str = ""
    responsibilities: str = ""
    skills: str = ""
    goals: str = ""
    working_style: str = ""
    system_instructions: str = ""
    status: str = "Active"
    permissions: list[str] = ["view", "create", "edit", "draft_external"]


EMPLOYEE_TEMPLATES = {
    "CEO": {"job_title": "Chief Executive Officer", "responsibilities": "Set vision and strategy; final decision authority; represent the company externally.", "permissions": PERMISSIONS},
    "Operations Manager": {"job_title": "Operations Manager", "responsibilities": "Run daily operations, processes, and vendor coordination.", "permissions": ["view", "create", "edit", "archive", "draft_external", "use_integrations"]},
    "Project Manager": {"job_title": "Project Manager", "responsibilities": "Plan projects, manage tasks, deadlines, and status reporting.", "permissions": ["view", "create", "edit", "draft_external"]},
    "Software Engineer": {"job_title": "Software Engineer", "responsibilities": "Design, implement, review, and debug software.", "permissions": ["view", "create", "edit", "execute_code", "access_files"]},
    "Accountant": {"job_title": "Accountant", "responsibilities": "Bookkeeping, invoicing, reporting, and compliance.", "permissions": ["view", "create", "edit"]},
    "Customer Support Representative": {"job_title": "Customer Support Representative", "responsibilities": "Answer customer inquiries and resolve issues empathetically.", "permissions": ["view", "create", "draft_external", "send_external"]},
    "Sales Representative": {"job_title": "Sales Representative", "responsibilities": "Prospect, qualify leads, and close deals.", "permissions": ["view", "create", "draft_external"]},
    "Marketing Manager": {"job_title": "Marketing Manager", "responsibilities": "Plan campaigns, content, and brand communication.", "permissions": ["view", "create", "edit", "draft_external"]},
    "Executive Assistant": {"job_title": "Executive Assistant", "responsibilities": "Scheduling, correspondence, and administrative support.", "permissions": ["view", "create", "draft_external"]},
}


@app.get("/api/employee-templates")
def employee_templates(user: User = Depends(current_user)):
    return EMPLOYEE_TEMPLATES


@app.get("/api/companies/{cid}/employees")
def list_employees(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    rows = db.query(VirtualEmployee).filter(VirtualEmployee.company_id == cid,
                                            VirtualEmployee.deleted_at.is_(None)).all()
    return [_d(e) for e in rows]


@app.post("/api/companies/{cid}/employees")
def create_employee(cid: str, body: EmployeeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    data = body.model_dump()
    data["permissions"] = json.dumps([p for p in data["permissions"] if p in PERMISSIONS])
    e = VirtualEmployee(company_id=cid, **data)
    db.add(e)
    db.commit()
    audit(db, "employee.create", e.full_name, company_id=cid, user_id=user.id, employee_id=e.id)
    return _d(e)


@app.put("/api/employees/{eid}")
def update_employee(eid: str, body: EmployeeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    e = db.get(VirtualEmployee, eid)
    if not e:
        raise HTTPException(404, "Employee not found")
    require_company(db, e.company_id, user)  # per-user isolation
    data = body.model_dump()
    data["permissions"] = json.dumps([p for p in data["permissions"] if p in PERMISSIONS])
    for k, v in data.items():
        setattr(e, k, v)
    db.commit()
    audit(db, "employee.update", e.full_name, company_id=e.company_id, user_id=user.id, employee_id=eid)
    return _d(e)


# ==================== Email identities ====================
class IdentityIn(BaseModel):
    employee_id: str
    email_address: str
    display_name: str = ""
    signature: str = ""
    provider: str = "local-dev"
    credentials: str = ""  # stored encrypted, never returned


@app.get("/api/companies/{cid}/identities")
def list_identities(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    rows = db.query(EmailIdentity).filter(EmailIdentity.company_id == cid,
                                          EmailIdentity.deleted_at.is_(None)).all()
    return [_d(i) for i in rows]


@app.post("/api/companies/{cid}/identities")
def create_identity(cid: str, body: IdentityIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    emp = db.get(VirtualEmployee, body.employee_id)
    if not emp:
        raise HTTPException(404, "Employee not found")
    check_company_scope(emp, cid)
    ident = db.query(EmailIdentity).filter(
        EmailIdentity.company_id == cid,
        EmailIdentity.employee_id == body.employee_id,
        EmailIdentity.deleted_at.is_(None),
    ).first()
    if ident:  # update existing identity instead of creating a duplicate
        ident.provider = body.provider
        ident.email_address = body.email_address
        ident.display_name = body.display_name or emp.full_name
        ident.signature = body.signature
        if body.credentials:
            ident.encrypted_credentials = encrypt_secret(body.credentials)
        ident.verified = True
        ident.connection_status = "connected"
        ident.last_check_at = dt.datetime.utcnow()
    else:
        ident = EmailIdentity(
            company_id=cid, employee_id=body.employee_id, provider=body.provider,
            email_address=body.email_address, display_name=body.display_name or emp.full_name,
            signature=body.signature,
            encrypted_credentials=encrypt_secret(body.credentials) if body.credentials else "",
            verified=True, connection_status="connected",  # local-dev adapter auto-verifies
            last_check_at=dt.datetime.utcnow(),
        )
        db.add(ident)
    db.commit()
    audit(db, "identity.connect", f"{body.email_address} → {emp.full_name}",
          company_id=cid, user_id=user.id, employee_id=emp.id)
    return _d(ident)


# ==================== Projects & tasks ====================
class ProjectIn(BaseModel):
    name: str
    description: str = ""
    status: str = "Active"
    priority: str = "Medium"
    start_date: str = ""
    due_date: str = ""
    tags: str = ""
    instructions: str = ""
    goals: str = ""


TASK_STATUSES = ["Backlog", "Ready", "In Progress", "Waiting for Approval",
                 "Blocked", "Completed", "Failed", "Cancelled"]


class TaskIn(BaseModel):
    title: str
    description: str = ""
    status: str = "Backlog"
    priority: str = "Medium"
    project_id: Optional[str] = None
    assignee_id: Optional[str] = None


@app.get("/api/companies/{cid}/projects")
def list_projects(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    rows = db.query(Project).filter(Project.company_id == cid, Project.deleted_at.is_(None)).all()
    return [_d(p) for p in rows]


@app.post("/api/companies/{cid}/projects")
def create_project(cid: str, body: ProjectIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    p = Project(company_id=cid, **body.model_dump())
    db.add(p)
    db.commit()
    audit(db, "project.create", p.name, company_id=cid, user_id=user.id)
    return _d(p)


def _own_project(db: Session, pid: str, user: User) -> Project:
    p = db.get(Project, pid)
    if not p or p.deleted_at:
        raise HTTPException(404, "Project not found")
    require_company(db, p.company_id, user)
    return p


def _project_chats(db: Session, pid: str, user: User):
    """The user's own conversations linked to this project."""
    q = db.query(Chat).filter(Chat.project_id == pid, Chat.deleted_at.is_(None))
    if user.is_admin:
        q = q.filter((Chat.owner_user_id == user.id) | (Chat.owner_user_id.is_(None)))
    else:
        q = q.filter(Chat.owner_user_id == user.id)
    return q.order_by(Chat.updated_at.desc()).all()


@app.put("/api/projects/{pid}")
def update_project(pid: str, body: ProjectIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    p = _own_project(db, pid, user)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    db.commit()
    audit(db, "project.update", p.name, company_id=p.company_id, user_id=user.id)
    return _d(p)


@app.get("/api/projects/{pid}/overview")
def project_overview(pid: str, user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Project workspace: all linked conversations (cross-referenced with
    message counts, participants and last activity) plus the project's tasks."""
    p = _own_project(db, pid, user)
    chats_out = []
    for c in _project_chats(db, pid, user):
        msgs = db.query(Message).filter(Message.chat_id == c.id)
        n = msgs.count()
        last = msgs.order_by(Message.created_at.desc()).first()
        emp_ids = {m.employee_id for m in msgs.filter(Message.employee_id.isnot(None)).all()}
        participants = []
        for eid in emp_ids:
            e = db.get(VirtualEmployee, eid)
            if e:
                participants.append({"id": e.id, "name": e.full_name, "avatar": e.avatar})
        chats_out.append(_d(c, {
            "message_count": n,
            "participants": participants,
            "last_message": ((last.content or "")[:160] if last else ""),
            "last_message_at": (last.created_at.isoformat() if last and last.created_at else None),
        }))
    tasks = db.query(Task).filter(Task.project_id == pid, Task.deleted_at.is_(None)).all()
    return {"project": _d(p), "chats": chats_out, "tasks": [_d(t) for t in tasks],
            "total_messages": sum(c["message_count"] for c in chats_out),
            "governance": _gov_load(p), "compliance": _iso21500_compliance(p)}


# ---------------- ISO 21500 project governance ----------------
# Process groups and subject groups per ISO 21500:2021 (Project, programme and
# portfolio management — Context and concepts / Guidance on project management).
ISO21500_PHASES = ["Initiating", "Planning", "Implementing", "Controlling", "Closing"]

_GOV_DEFAULT = {
    "phase": "Initiating",          # ISO 21500 process group the project is in
    "sponsor": "",                   # accountable sponsor
    "manager": "",                   # project manager
    "charter": "",                   # business case / project charter (Integration)
    "scope_statement": "",           # Scope subject group
    "stakeholders": [],              # [{name, role, interest, influence, engagement}]
    "risks": [],                     # [{title, probability, impact, response, owner, status}]
    "milestones": [],                # [{name, date, status}]  (Time / Schedule)
    "budget": {"currency": "USD", "planned": "", "actual": ""},   # Cost
    "quality_criteria": "",          # Quality
    "procurement": "",               # Procurement
    "comms_plan": "",                # Communication
    "lessons": [],                   # [{note, at}]  (Closing / lessons learned)
}


def _gov_load(p: Project) -> dict:
    try:
        g = json.loads(p.governance or "{}")
    except Exception:
        g = {}
    out = dict(_GOV_DEFAULT)
    out.update({k: v for k, v in g.items() if k in _GOV_DEFAULT})
    return out


def _iso21500_compliance(p: Project) -> dict:
    """Score the project against the ten ISO 21500 subject groups."""
    g = _gov_load(p)
    checks = [
        ("Integration",   bool(g["charter"].strip()),            "Project charter / business case recorded"),
        ("Stakeholder",   len(g["stakeholders"]) > 0,            "Stakeholder register maintained"),
        ("Scope",         bool(g["scope_statement"].strip() or (p.goals or "").strip()), "Scope statement / goals defined"),
        ("Resource",      bool(g["manager"].strip()),            "Project manager & resources assigned"),
        ("Time",          len(g["milestones"]) > 0 or bool(p.due_date), "Schedule / milestones planned"),
        ("Cost",          bool(str(g["budget"].get("planned", "")).strip()), "Budget planned and tracked"),
        ("Risk",          len(g["risks"]) > 0,                   "Risk register maintained"),
        ("Quality",       bool(g["quality_criteria"].strip()),   "Quality / acceptance criteria defined"),
        ("Procurement",   bool(g["procurement"].strip()),        "Procurement approach documented"),
        ("Communication", bool(g["comms_plan"].strip()),         "Communication plan defined"),
    ]
    done = sum(1 for _, ok, _ in checks if ok)
    return {"score": round(done / len(checks) * 100),
            "phase": g["phase"], "phases": ISO21500_PHASES,
            "subjects": [{"subject": s, "ok": ok, "requirement": req} for s, ok, req in checks]}


@app.put("/api/projects/{pid}/governance")
def update_governance(pid: str, body: dict, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    p = _own_project(db, pid, user)
    g = _gov_load(p)
    for k, v in (body or {}).items():
        if k in _GOV_DEFAULT:
            g[k] = v
    if g.get("phase") not in ISO21500_PHASES:
        g["phase"] = "Initiating"
    p.governance = json.dumps(g, ensure_ascii=False)
    db.commit()
    audit(db, "project.governance", p.name, company_id=p.company_id, user_id=user.id)
    return {"governance": g, "compliance": _iso21500_compliance(p)}


@app.get("/api/projects/{pid}/search")
def project_search(pid: str, q: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Cross-reference search across every conversation in the project."""
    _own_project(db, pid, user)
    needle = (q or "").strip().lower()
    if not needle:
        return []
    out = []
    for c in _project_chats(db, pid, user):
        hits = (db.query(Message)
                .filter(Message.chat_id == c.id, Message.content.ilike(f"%{needle}%"))
                .order_by(Message.created_at.desc()).limit(20).all())
        for hit in hits:
            text = hit.content or ""
            idx = text.lower().find(needle)
            start = max(0, idx - 70)
            end = min(len(text), idx + len(needle) + 70)
            emp = db.get(VirtualEmployee, hit.employee_id) if hit.employee_id else None
            out.append({
                "chat_id": c.id, "chat_title": c.title, "message_id": hit.id,
                "role": hit.role, "speaker": (emp.full_name if emp else ("You" if hit.role == "user" else "System")),
                "snippet": ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else ""),
                "at": hit.created_at.isoformat() if hit.created_at else None,
            })
    out.sort(key=lambda r: r["at"] or "", reverse=True)
    return out[:100]


# ---------------- Token usage analytics ----------------
@app.get("/api/usage/tokens")
def usage_tokens(days: int = 30, scope: str = "me", user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Daily token usage per agent/model.

    scope=me  → current user's usage.
    scope=all → admin only: usage grouped per user (client) as well.
    """
    from .db import TokenUsage, User as _User
    days = max(1, min(days, 365))
    since = dt.datetime.utcnow() - dt.timedelta(days=days)
    q = db.query(TokenUsage).filter(TokenUsage.created_at >= since)
    if scope == "all":
        if not user.is_admin:
            raise HTTPException(403, "Administrator only")
    else:
        q = q.filter(TokenUsage.user_id == user.id)
    rows = q.all()
    day_list = [(tz.today_local() - dt.timedelta(days=i)).isoformat()
                for i in range(days - 1, -1, -1)]
    # per-agent daily series
    agents: dict = {}
    users_out: dict = {}
    uname: dict = {}
    for r in rows:
        d = tz.local_day_str(r.created_at) or day_list[-1]
        a = agents.setdefault(r.agent, {"total_in": 0, "total_out": 0, "calls": 0,
                                        "daily": {x: {"in": 0, "out": 0} for x in day_list}})
        a["total_in"] += r.input_tokens or 0
        a["total_out"] += r.output_tokens or 0
        a["calls"] += r.calls or 0
        if d in a["daily"]:
            a["daily"][d]["in"] += r.input_tokens or 0
            a["daily"][d]["out"] += r.output_tokens or 0
        if scope == "all":
            uid = r.user_id or "unknown"
            if uid not in uname:
                u = db.get(_User, uid) if uid != "unknown" else None
                uname[uid] = u.username if u else "unknown"
            uu = users_out.setdefault(uid, {"username": uname[uid], "total_in": 0, "total_out": 0,
                                            "daily": {x: {"in": 0, "out": 0} for x in day_list}})
            uu["total_in"] += r.input_tokens or 0
            uu["total_out"] += r.output_tokens or 0
            if d in uu["daily"]:
                uu["daily"][d]["in"] += r.input_tokens or 0
                uu["daily"][d]["out"] += r.output_tokens or 0
    return {"days": day_list, "agents": agents,
            "users": users_out if scope == "all" else None,
            "is_admin": bool(user.is_admin)}


@app.get("/api/usage/tokens/detail")
def usage_tokens_detail(user_id: str = "", days: int = 30, limit: int = 500,
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Itemized token-usage ledger (date, time, agent, tokens) for one user.
    Admin may inspect any user; others only themselves."""
    from .db import TokenUsage, User as _User, AgentRun
    target = user_id or user.id
    if target != user.id and not user.is_admin:
        raise HTTPException(403, "Administrator only")
    days = max(1, min(days, 365))
    since = dt.datetime.utcnow() - dt.timedelta(days=days)
    rows = (db.query(TokenUsage)
            .filter(TokenUsage.user_id == target, TokenUsage.created_at >= since)
            .order_by(TokenUsage.created_at.desc()).limit(max(1, min(limit, 2000))).all())
    tu = db.get(_User, target)
    out = []
    for r in rows:
        prompt = ""
        if r.run_id:
            run = db.get(AgentRun, r.run_id)
            if run and run.prompt:
                prompt = run.prompt[:120]
        out.append({"at": r.created_at.isoformat() if r.created_at else None,
                    "agent": r.agent, "input_tokens": r.input_tokens or 0,
                    "output_tokens": r.output_tokens or 0, "calls": r.calls or 1,
                    "run_id": r.run_id, "prompt": prompt})
    return {"username": tu.username if tu else "unknown", "user_id": target,
            "days": days, "records": out,
            "total_in": sum(x["input_tokens"] for x in out),
            "total_out": sum(x["output_tokens"] for x in out)}


@app.get("/api/companies/{cid}/tasks")
def list_tasks(cid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    rows = db.query(Task).filter(Task.company_id == cid, Task.deleted_at.is_(None)).all()
    return [_d(t) for t in rows]


@app.post("/api/companies/{cid}/tasks")
def create_task(cid: str, body: TaskIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_company(db, cid, user)
    if body.status not in TASK_STATUSES:
        raise HTTPException(422, f"Invalid status; must be one of {TASK_STATUSES}")
    if body.assignee_id:
        emp = db.get(VirtualEmployee, body.assignee_id)
        if emp:
            check_company_scope(emp, cid)
    t = Task(company_id=cid, **body.model_dump())
    db.add(t)
    db.commit()
    audit(db, "task.create", t.title, company_id=cid, user_id=user.id)
    return _d(t)


@app.put("/api/tasks/{tid}")
def update_task(tid: str, body: TaskIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    t = db.get(Task, tid)
    if not t:
        raise HTTPException(404, "Task not found")
    require_company(db, t.company_id, user)  # per-user isolation
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return _d(t)


# ==================== Operations: Teams / Workflows / SOPs / Shifts ====================
_OPS_MODELS = {"teams": Team, "workflows": Workflow, "sops": SOP, "shifts": Shift}


def _ops_model(kind: str):
    m = _OPS_MODELS.get(kind)
    if not m:
        raise HTTPException(404, "unknown collection")
    return m


@app.get("/api/companies/{cid}/ops/{kind}")
def ops_list(cid: str, kind: str, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    require_company(db, cid, user)
    m = _ops_model(kind)
    rows = db.query(m).filter(m.company_id == cid, m.deleted_at.is_(None)).all()
    return [_d(r) for r in rows]


_OPS_FIELDS = {
    "teams": {"name", "icon", "mission", "lead_id", "member_ids", "status"},
    "workflows": {"name", "icon", "description", "trigger", "stages", "diagram", "status"},
    "sops": {"code", "title", "category", "version", "status", "owner_id",
             "purpose", "scope", "procedure", "review_date"},
    "shifts": {"employee_id", "name", "days", "start_time", "end_time",
               "date", "role", "notes", "status"},
}


def _ops_clean(kind: str, body: dict) -> dict:
    allowed = _OPS_FIELDS[kind]
    out = {}
    for k, v in (body or {}).items():
        if k in allowed:
            out[k] = json.dumps(v) if isinstance(v, (list, dict)) else v
    return out


@app.post("/api/companies/{cid}/ops/{kind}")
def ops_create(cid: str, kind: str, body: dict, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    require_company(db, cid, user)
    m = _ops_model(kind)
    data = _ops_clean(kind, body)
    if kind == "sops" and not data.get("code"):
        n = db.query(m).filter(m.company_id == cid).count() + 1
        data["code"] = f"SOP-{n:03d}"
    row = m(company_id=cid, **data)
    db.add(row)
    db.commit()
    audit(db, f"{kind[:-1]}.create", getattr(row, "name", getattr(row, "title", "")),
          company_id=cid, user_id=user.id)
    return _d(row)


@app.put("/api/ops/{kind}/{oid}")
def ops_update(kind: str, oid: str, body: dict, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    row = db.get(_ops_model(kind), oid)
    if not row:
        raise HTTPException(404, "not found")
    require_company(db, row.company_id, user)
    if kind == "sops" and any(body.get(k) is not None and body.get(k) != getattr(row, k)
                              for k in ("purpose", "scope", "procedure")):
        row.version = (row.version or 1) + 1     # controlled-document revisioning
    for k, v in _ops_clean(kind, body).items():
        setattr(row, k, v)
    db.commit()
    return _d(row)


@app.delete("/api/ops/{kind}/{oid}")
def ops_delete(kind: str, oid: str, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    row = db.get(_ops_model(kind), oid)
    if not row:
        raise HTTPException(404, "not found")
    require_company(db, row.company_id, user)
    row.deleted_at = dt.datetime.utcnow()
    db.commit()
    audit(db, f"{kind[:-1]}.delete", getattr(row, "name", getattr(row, "title", "")),
          company_id=row.company_id, user_id=user.id)
    return {"ok": True}


# ==================== Chats ====================
class ChatIn(BaseModel):
    title: str = "New chat"
    company_id: Optional[str] = None
    project_id: Optional[str] = None
    active_employee_id: Optional[str] = None


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    image_ref: Optional[str] = None  # path of a referenced image (edit workflow)


def _own_chat(db: Session, chat_id: str, user: User) -> Chat:
    """Fetch a chat and enforce per-user isolation: users only access their
    own chats. Legacy chats without an owner are claimed by the first admin
    that touches them."""
    c = db.get(Chat, chat_id)
    if not c or c.deleted_at:
        raise HTTPException(404, "Chat not found")
    if c.owner_user_id is None:
        if not user.is_admin:
            raise HTTPException(404, "Chat not found")
        c.owner_user_id = user.id
        db.commit()
    elif c.owner_user_id != user.id:
        raise HTTPException(404, "Chat not found")
    return c


@app.get("/api/chats")
def list_chats(q: Optional[str] = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = db.query(Chat).filter(Chat.deleted_at.is_(None))
    # per-user isolation: everyone (admins included) sees only their own
    # chats; unowned legacy chats are shown to admins only.
    if user.is_admin:
        query = query.filter((Chat.owner_user_id == user.id) | (Chat.owner_user_id.is_(None)))
    else:
        query = query.filter(Chat.owner_user_id == user.id)
    rows = query.order_by(Chat.updated_at.desc()).all()
    if q:
        needle = q.strip().lower()
        out = []
        for c in rows:
            if needle in (c.title or "").lower():
                out.append(_d(c, {"match_kind": "title", "match_snippet": c.title,
                                  "match_message_id": None}))
            # every matching message becomes its own result (max 10 per chat)
            hits = (db.query(Message)
                    .filter(Message.chat_id == c.id, Message.content.ilike(f"%{needle}%"))
                    .order_by(Message.created_at.desc())
                    .limit(10).all())
            for hit in hits:
                text = hit.content or ""
                idx = text.lower().find(needle)
                start = max(0, idx - 60)
                end = min(len(text), idx + len(needle) + 60)
                snippet = ("…" if start > 0 else "") + text[start:end] + ("…" if end < len(text) else "")
                out.append(_d(c, {"match_kind": "message", "match_snippet": snippet,
                                  "match_message_id": hit.id,
                                  "match_time": hit.created_at.isoformat() if hit.created_at else None}))
        return out
    return [_d(c) for c in rows]


@app.post("/api/chats")
def create_chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.company_id:
        require_company(db, body.company_id, user)
    if body.active_employee_id:
        emp = db.get(VirtualEmployee, body.active_employee_id)
        if not emp:
            raise HTTPException(404, "Employee not found")
        if body.company_id:
            check_company_scope(emp, body.company_id)
    c = Chat(**body.model_dump())
    c.owner_user_id = user.id
    db.add(c)
    db.commit()
    return _d(c)


@app.put("/api/chats/{chat_id}")
def update_chat(chat_id: str, body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _own_chat(db, chat_id, user)
    if body.active_employee_id:
        emp = db.get(VirtualEmployee, body.active_employee_id)
        if not emp:
            raise HTTPException(404, "Employee not found")
        if c.company_id:
            check_company_scope(emp, c.company_id)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    return _d(c)


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _own_chat(db, chat_id, user)
    c.deleted_at = dt.datetime.utcnow()
    db.commit()
    return {"ok": True}


@app.get("/api/chats/{chat_id}/messages")
def list_messages(chat_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _own_chat(db, chat_id, user)
    rows = db.query(Message).filter(Message.chat_id == chat_id).order_by(Message.created_at).all()
    return [_d(m) for m in rows]


# -------- client file delivery: generated files reach the requesting PC --------
# Agents run ON the server, so files they create land on the server's disk.
# When the prompt came from a remote CLIENT computer we queue every produced
# file here; the client's next heartbeat announces them and the client program
# downloads each one to the SAME path on its own disk.
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\"'`|<>*?\r\n]+?\.[A-Za-z0-9]{1,6}(?![A-Za-z0-9.])")
_pending_files_lock = threading.Lock()
_pending_client_files: dict = {}   # license_id → [{id, src, dest, name}]


def queue_client_file_delivery(db: Session, ip: str, text: str) -> int:
    """Scan an agent reply for file paths that exist on the server's disk and
    queue them for delivery to the client machine bound to `ip`."""
    if not ip or ip in ("127.0.0.1", "::1", "localhost", "testclient"):
        return 0
    row = (db.query(LicenseKey)
           .filter(LicenseKey.used_by_ip == ip, LicenseKey.revoked.is_(False))
           .first())
    if not row:
        return 0
    queued = 0
    for raw in dict.fromkeys(_WIN_PATH_RE.findall(text or "")):
        try:
            p = Path(raw).resolve()
            p.relative_to(Path.home())          # only files under the home dir
        except (OSError, ValueError):
            continue
        if not p.is_file() or p.stat().st_size > 200 * 1024 * 1024:
            continue
        with _pending_files_lock:
            pend = _pending_client_files.setdefault(row.id, [])
            if any(f["src"] == str(p) for f in pend):
                continue
            pend.append({"id": uuid.uuid4().hex[:12], "src": str(p),
                         "dest": raw, "name": p.name})
            queued += 1
    if queued:
        audit(db, "client.file_delivery",
              f"{queued} file(s) queued for {row.used_by_host or ip}")
    return queued


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, body: MessageIn, request: Request,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    chat = _own_chat(db, chat_id, user)
    image_ref = body.image_ref
    if image_ref and not _safe_image_path(image_ref):
        raise HTTPException(400, "Invalid reference image path")
    res = run_agent_message(db, chat, body.content, user.id, image_ref=image_ref)
    try:
        queue_client_file_delivery(db, _client_ip(request),
                                   (res or {}).get("message", ""))
    except Exception:  # noqa: BLE001 — delivery must never break the chat
        pass
    return res


# -------- prompt queue: send prompts without waiting for the previous one --------
from . import prompt_queue  # noqa: E402

prompt_queue.start_workers()
prompt_queue.file_delivery_hook = queue_client_file_delivery


class QueueItemIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    image_ref: str | None = None


@app.post("/api/chats/{chat_id}/queue")
def queue_prompt(chat_id: str, body: QueueItemIn, request: Request,
                 user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    """Enqueue a prompt. Returns immediately; prompts of this chat run
    sequentially in the background, other chats run in parallel."""
    _own_chat(db, chat_id, user)
    if body.image_ref and not _safe_image_path(body.image_ref):
        raise HTTPException(400, "Invalid reference image path")
    try:
        item = prompt_queue.enqueue(chat_id, user.id, body.content, body.image_ref,
                                    client_ip=_client_ip(request))
    except ValueError as e:
        raise HTTPException(429, str(e))
    return {"ok": True, "item": item}


@app.get("/api/chats/{chat_id}/queue")
def get_queue(chat_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _own_chat(db, chat_id, user)
    return {"items": prompt_queue.list_queue(chat_id)}


@app.put("/api/chats/{chat_id}/queue/{item_id}")
def revise_queued(chat_id: str, item_id: str, body: QueueItemIn,
                  user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Revise a prompt that has not started processing yet."""
    _own_chat(db, chat_id, user)
    item = prompt_queue.revise(chat_id, item_id, user.id, body.content)
    if not item:
        raise HTTPException(409, "Prompt already started — it can no longer be revised")
    return {"ok": True, "item": item}


@app.delete("/api/chats/{chat_id}/queue/{item_id}")
def cancel_queued(chat_id: str, item_id: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    _own_chat(db, chat_id, user)
    if not prompt_queue.cancel(chat_id, item_id, user.id):
        raise HTTPException(409, "Prompt already started — it can no longer be cancelled")
    return {"ok": True}


def _safe_image_path(path_str: str) -> Optional[Path]:
    """Only serve image files under the user's home directory or the uploads folder."""
    try:
        p = Path(path_str).resolve()
    except (OSError, ValueError):
        return None
    if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
        return None
    allowed = False
    for root in (Path.home(), Path(__file__).resolve().parent.parent / "data" / "uploads"):
        try:
            p.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        return None
    return p if p.is_file() else None


@app.get("/api/image")
def serve_image(path: str, user: User = Depends(current_user)):
    p = _safe_image_path(path)
    if not p:
        raise HTTPException(404, "Image not found or not allowed")
    return FileResponse(str(p))


# ---------------- environment setup (multi-machine deployment) ----------------
from . import setup_tools  # noqa: E402


@app.get("/api/setup/status")
def get_setup_status(user: User = Depends(current_user)):
    require_admin(user)
    return setup_tools.setup_status()


@app.post("/api/setup/install")
def setup_install(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    tool = str(body.get("tool", ""))
    r = setup_tools.start_install(tool)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "install failed"))
    audit(db, "setup.install", f"tool={tool}", user_id=user.id)
    return r


@app.post("/api/setup/login")
def setup_login(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    tool = str(body.get("tool", ""))
    r = setup_tools.start_login(tool)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "login failed"))
    audit(db, "setup.login", f"tool={tool}", user_id=user.id)
    return r


# ---------------- agent configuration ----------------
from .config import FIELD_META, get_config, save_config  # noqa: E402


@app.get("/api/config")
def read_config(user: User = Depends(current_user)):
    require_admin(user)
    return {"config": get_config(), "meta": FIELD_META}


@app.put("/api/config")
def update_config(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    cfg = save_config(body or {})
    audit(db, "config.update", json.dumps(body)[:400], user_id=user.id)
    return {"config": cfg, "meta": FIELD_META}


@app.post("/api/config/test-smtp")
def test_smtp(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Test the SMTP settings: verify connection + login, then send a test email."""
    from .providers import SmtpEmailProvider, get_email_provider
    import uuid as _uuid
    to_addr = str(body.get("to", "")).strip()
    if not to_addr or "@" not in to_addr:
        raise HTTPException(400, "A valid recipient address is required")
    provider = get_email_provider("auto")
    if not isinstance(provider, SmtpEmailProvider):
        raise HTTPException(400, "SMTP is not configured — fill in SMTP host, username and password first, then Save.")
    # Step 1: connection + authentication
    import smtplib
    try:
        with smtplib.SMTP(provider.host, provider.port, timeout=30) as s:
            s.starttls()
            s.login(provider.username, provider.password)
    except smtplib.SMTPAuthenticationError as e:
        raise HTTPException(400, f"Connection OK but LOGIN FAILED: {str(e)[:300]} — "
                            "for Gmail you must use an App Password, not your normal password.")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not connect to {provider.host}:{provider.port} — {str(e)[:300]}")
    # Step 2: actual test email
    result = provider.send(
        sender=provider.from_addr, to=[to_addr], cc=[], bcc=[],
        subject="✅ Test email — NexaCrew",
        body=("This is a test email from your AI Agent Platform.\n\n"
              f"SMTP host: {provider.host}:{provider.port}\n"
              f"From: {provider.from_addr}\n\n"
              "If you can read this, real email delivery is working correctly."),
        idempotency_key=_uuid.uuid4().hex)
    audit(db, "config.test_smtp", f"to={to_addr} ok={result.ok}", user_id=user.id)
    if not result.ok:
        raise HTTPException(400, f"Login OK but sending failed: {result.error}")
    return {"ok": True, "message_id": result.provider_message_id,
            "detail": f"Connection ✓ Login ✓ Test email sent to {to_addr} — check the inbox (and spam folder)."}


@app.post("/api/employees/{eid}/test-email")
def test_employee_email(eid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Send a test email to the employee's connected identity address."""
    from .providers import SmtpEmailProvider, get_email_provider
    import uuid as _uuid
    emp = db.get(VirtualEmployee, eid)
    if not emp or emp.deleted_at:
        raise HTTPException(404, "Employee not found")
    require_company(db, emp.company_id, user)
    ident = (db.query(EmailIdentity)
             .filter(EmailIdentity.employee_id == eid,
                     EmailIdentity.deleted_at.is_(None)).first())
    if not ident:
        raise HTTPException(400, f"{emp.full_name} has no email identity connected.")
    provider = get_email_provider("auto")
    simulated = not isinstance(provider, SmtpEmailProvider)
    sender = provider.from_addr if isinstance(provider, SmtpEmailProvider) else "test@local-dev"
    result = provider.send(
        sender=sender, to=[ident.email_address], cc=[], bcc=[],
        subject=f"✅ Test email — identity check for {emp.full_name}",
        body=(f"Hello {emp.full_name},\n\n"
              "This is a test email from your AI Agent Platform to verify that "
              f"your connected identity ({ident.email_address}) can receive mail.\n\n"
              "If you can read this, delivery to this employee is working correctly."),
        idempotency_key=_uuid.uuid4().hex)
    audit(db, "identity.test_email", f"to={ident.email_address} ok={result.ok} simulated={result.simulated}",
          company_id=emp.company_id, user_id=user.id, employee_id=emp.id)
    if not result.ok:
        raise HTTPException(400, f"Sending failed: {result.error}")
    return {"ok": True, "simulated": result.simulated or simulated,
            "detail": (f"Test email sent to {ident.email_address}"
                       + (" (SIMULATED — no SMTP configured, written to the outbox folder)"
                          if (result.simulated or simulated) else " via SMTP — check the inbox (and spam folder)."))}


# ---------------- cron schedules ----------------
from .db import ScheduledJob  # noqa: E402
from .scheduler import describe_cron, start_scheduler, validate_cron  # noqa: E402

start_scheduler()


# ---------------- enterprise cluster ----------------
from . import cluster as _cluster  # noqa: E402

_cluster.start_cluster()


def _cluster_auth(request: Request) -> None:
    """Node-to-node authentication with the shared cluster secret."""
    secret = get_config().get("cluster_secret", "")
    if not secret or request.headers.get("X-Cluster-Secret") != secret:
        raise HTTPException(403, "Invalid or missing cluster secret")


@app.post("/api/cluster/heartbeat")
async def cluster_heartbeat(request: Request):
    _cluster_auth(request)
    info = await request.json()
    if not isinstance(info, dict) or "node_id" not in info:
        raise HTTPException(400, "Invalid heartbeat payload")
    info["host"] = info.get("host") or (request.client.host if request.client else "")
    _cluster.register_heartbeat(info)
    # a worker running a newer version means the portal has one — update now
    if _ver_tuple(str(info.get("version") or "0")) > _ver_tuple(APP_VERSION):
        _UPDATE_CHECK_NOW.set()
    return {"ok": True, "controller": _cluster.NODE_ID, "version": APP_VERSION}


@app.post("/api/cluster/execute")
async def cluster_execute(request: Request):
    """Executed on a worker: run an agent workload with the local CLIs."""
    _cluster_auth(request)
    body = await request.json()
    kind = body.get("kind", "codex")
    prompt, system = str(body.get("prompt", "")), str(body.get("system", ""))
    from .providers import ClaudeCodeProvider, CodexProvider
    try:
        if kind == "claude":
            out = ClaudeCodeProvider().run(prompt, system=system)
        else:
            out = CodexProvider().run(prompt, system=system,
                                      allow_write=bool(body.get("allow_write")))
        return {"ok": True, "output": out, "node": _cluster.node_info()["name"]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:2000]}


@app.get("/api/cluster/status")
def cluster_status_ep(user: User = Depends(current_user)):
    require_admin(user)
    return _cluster.cluster_status()


@app.get("/api/gpu")
def gpu_status(user: User = Depends(current_user)):
    """GPUs on this server and the (forced) GPU acceleration policy."""
    from .gpu import gpu_summary
    return gpu_summary()


@app.get("/api/system-status")
def system_status(user: User = Depends(current_user)):
    """Real-time CPU / GPU / RAM / network telemetry with rolling history."""
    return sysmon.status_snapshot()


@app.get("/api/health")
def health():
    """Unauthenticated liveness probe used by clients to detect server-down."""
    return {"ok": True, "product": "NexaCrew",
            "version": APP_VERSION, "node": _cluster.node_info()["name"]}


@app.get("/api/version")
def version():
    """Unauthenticated — clients compare this with their local VERSION on
    every start and auto-update when the server is newer."""
    return {"version": APP_VERSION}


@app.get("/api/license-authority")
def license_authority_status(user: User = Depends(current_user)):
    """Admin — status of this server installation's license as validated
    against the mapstudiousa.com licensing authority."""
    require_admin(user)
    from .license_authority import authority_status
    return authority_status()


@app.post("/api/license-authority/check")
def license_authority_check(user: User = Depends(current_user)):
    """Admin — force an immediate re-validation round-trip."""
    require_admin(user)
    from .config import get_config
    from .license_authority import check_once
    return check_once(get_config())


# ---------------- client license keys ----------------
def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


@app.get("/api/licenses")
def list_licenses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    rows = db.query(LicenseKey).order_by(LicenseKey.created_at.desc()).all()
    from .license_authority import authority_status, seats_in_use
    auth = authority_status()
    seats = int(auth.get("seats") or 0)
    usage = seats_in_use(db)   # server + desktop clients + mobile/kiosk devices
    return {"licenses": [_d(r) for r in rows],
            "seats": {"limit": seats,                     # 0 = evaluation / unlimited
                      "used": int(usage.get("used") or 0),
                      "by_type": usage.get("by_type") or {},
                      "plan": str(auth.get("plan") or ""),
                      "company": str(auth.get("company") or ""),
                      "server": socket.gethostname()}}


@app.post("/api/licenses")
def create_licenses(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Register purchased license keys. Keys are NO LONGER generated locally:
    every key must have been issued by mapstudiousa.com (the licensing
    authority) and is verified online before it is accepted.
    body: {keys: "XXXXX-XXXXX-XXXXX-XXXXX\n..." | [..], note: ""}"""
    require_admin(user)
    from .config import get_config
    from .license_authority import verify_key
    raw = body.get("keys") or body.get("key") or ""
    if isinstance(raw, str):
        candidates = [k.strip() for k in re.split(r"[\s,;]+", raw) if k.strip()]
    elif isinstance(raw, list):
        candidates = [str(k).strip() for k in raw if str(k).strip()]
    else:
        raise HTTPException(400, "keys must be a string or a list of strings")
    if not candidates:
        raise HTTPException(400, "Enter at least one license key purchased on mapstudiousa.com")
    if len(candidates) > 50:
        raise HTTPException(400, "Maximum 50 keys per request")
    key_re = re.compile(r"^[A-F0-9]{5}(-[A-F0-9]{5}){3}$")
    note = str(body.get("note") or "")[:200]
    cfg = get_config()
    # ONE LICENSE = ONE SERVER: the server's own authority key must not be
    # re-registered as a client seat key — that would let a single purchase
    # drive multiple machines.
    server_key = (cfg.get("authority_license_key") or "").strip().upper()
    made, errors = [], []
    for cand in candidates:
        norm = cand.upper().replace(" ", "")
        if not key_re.match(norm):
            errors.append(f"{cand}: invalid format (expected XXXXX-XXXXX-XXXXX-XXXXX)")
            continue
        if server_key and norm == server_key:
            errors.append(f"{norm}: this is the SERVER license key — it activates this "
                          f"server only and cannot be used as a client key. Purchase "
                          f"client seats within this license's seat allowance instead.")
            continue
        if db.query(LicenseKey).filter_by(key=norm).first():
            errors.append(f"{norm}: already registered on this server")
            continue
        res = verify_key(cfg, norm)
        if not res.get("ok"):
            errors.append(f"{norm}: {res.get('error', 'rejected by mapstudiousa.com')}")
            continue
        lic_note = note or f"{res.get('company', '')} · {res.get('plan', '')} · " \
                           f"{res.get('seats', 0)} seats (verified by mapstudiousa.com)"
        row = LicenseKey(key=norm, note=lic_note[:300])
        db.add(row)
        made.append(row)
    db.commit()
    if made:
        audit(db, "license.register",
              f"{len(made)} key(s) verified with mapstudiousa.com and registered",
              user_id=user.id)
    if not made and errors:
        raise HTTPException(400, "; ".join(errors[:5]))
    return {"licenses": [_d(r) for r in made], "errors": errors}


@app.delete("/api/licenses/{lid}")
def delete_license(lid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    row = db.query(LicenseKey).filter_by(id=lid).first()
    if not row:
        raise HTTPException(404, "license key not found")
    db.delete(row)
    db.commit()
    audit(db, "license.delete", row.key, user_id=user.id)
    return {"ok": True}


def _check_license(db: Session, key: str, ip: str, hostname: str = "",
                   claim: bool = True, enforce_ip: bool = True) -> LicenseKey:
    """Validate a license key for the calling IP; optionally claim it.
    Rules: key must exist and not be revoked. An unused key is bound to the
    first IP that claims it. A used key stays valid only for its bound IP.
    enforce_ip=False (program-package downloads): a valid, unrevoked key is
    accepted from any IP — multi-NIC clients often download through a
    different interface than the one their heartbeat binds; the package only
    contains program code the client already has."""
    norm = key.strip().upper().replace(" ", "")
    # The server's own authority key may download program packages (tray
    # updater on the server machine / same-license nodes). It is NEVER
    # accepted as a client seat claim — one license = one server.
    if not enforce_ip:
        from .config import get_config as _gc
        srv_key = (_gc().get("authority_license_key") or "").strip().upper()
        if srv_key and norm == srv_key:
            return LicenseKey(key=norm, note="server authority key (transient)")
    row = db.query(LicenseKey).filter_by(key=norm).first()
    if not row:
        # Key not registered locally — verify it against mapstudiousa.com and
        # auto-register on success, so a client seat purchased in the portal
        # works immediately without the admin pre-entering it. The server's
        # own authority key is still rejected as a client seat.
        import re as _re5
        from .config import get_config as _gc2
        cfg2 = _gc2()
        srv_key2 = (cfg2.get("authority_license_key") or "").strip().upper()
        if (norm != srv_key2
                and _re5.fullmatch(r"[A-F0-9]{5}(-[A-F0-9]{5}){3}", norm)):
            try:
                from .license_authority import verify_key
                res = verify_key(cfg2, norm)
            except Exception as e:                       # noqa: BLE001
                logging.getLogger("license").warning(
                    "portal verification unavailable for auto-register: %s", e)
                res = {}
            if res.get("ok"):
                row = LicenseKey(
                    key=norm,
                    note=(f"{res.get('company', '')} · {res.get('plan', '')} · "
                          f"{res.get('seats', 0)} seats (auto-registered via "
                          f"mapstudiousa.com at first use)")[:300])
                db.add(row)
                db.commit()
                db.refresh(row)
                audit(db, "license.autoregister",
                      f"{norm} verified with mapstudiousa.com and registered "
                      f"on first use from {ip}")
    if not row:
        raise HTTPException(403, "Invalid license key — ask your administrator for a key")
    if row.revoked:
        raise HTTPException(403, "This license key has been revoked")
    if row.used and row.used_by_ip and row.used_by_ip != ip:
        # DHCP-friendly re-binding: the same computer may come back with a new
        # IP (hotspot/router reassignment). Re-bind when the hostname matches,
        # or when the previously bound IP has stopped heartbeating (stale).
        same_host = bool(hostname and row.used_by_host and
                         hostname.strip().lower() == row.used_by_host.strip().lower())
        stale = not row.last_seen_at or (
            (dt.datetime.utcnow() - row.last_seen_at).total_seconds() > 300)
        if claim and (same_host or stale):
            row.used_by_ip = ip
        elif not enforce_ip:
            # accept without re-binding — the bound computer keeps its claim
            return row
        else:
            raise HTTPException(403, f"This license key is already in use by another computer ({row.used_by_ip})")
    if claim:
        newly_claimed = not row.used
        if not row.used:
            # SEAT ENFORCEMENT: a new device may only claim a key while the
            # TOTAL number of devices (server + desktop clients + mobile /
            # tablet / kiosk terminals) stays within the seats authorized by
            # the mapstudiousa.com license (e.g. Enterprise = 100 devices).
            from .license_authority import seat_limit, seats_in_use
            seats = seat_limit()
            if seats > 0:
                in_use = int(seats_in_use(db).get("used") or 0)
                if in_use >= seats:
                    audit(db, "license.seat_limit",
                          f"claim rejected for {hostname or ip}: {in_use}/{seats} seats in use")
                    raise HTTPException(
                        403, f"Seat limit reached — this server's license allows {seats} "
                             f"device(s) (server, desktop, mobile and kiosk all count) "
                             f"and all are in use. Upgrade the plan at mapstudiousa.com "
                             f"or remove an unused device.")
            row.used = True
            row.used_by_ip = ip
            row.used_at = dt.datetime.utcnow()
        if hostname:
            row.used_by_host = hostname
        row.last_seen_at = dt.datetime.utcnow()
        db.commit()
        if newly_claimed:
            # a new desktop client consumed a seat — sync the device snapshot
            # to mapstudiousa.com promptly (debounced) so the portal updates.
            from .license_authority import request_sync
            request_sync()
    return row


# ==================== Automatic server update from mapstudiousa.com ====================
_UPDATE_CHECK_NOW = threading.Event()   # set to force an immediate portal check


def _portal_auto_updater() -> None:
    """Daemon thread: the server checks mapstudiousa.com periodically; when
    the portal publishes a newer version it downloads the release package,
    verifies its SHA-256, applies it (platform/data is never touched) and
    restarts. Clients then auto-update from this server via the existing
    heartbeat mechanism — the whole fleet follows the portal automatically."""
    import hashlib
    import random
    import sys
    import tarfile
    import tempfile
    import urllib.request

    first = True
    while True:
        _UPDATE_CHECK_NOW.wait(timeout=120 if first else 6 * 3600 + random.randint(0, 900))
        _UPDATE_CHECK_NOW.clear()
        first = False
        try:
            from .config import get_config as _cfg
            cfg = _cfg()
            if str(cfg.get("auto_update_from_portal", "on")).strip().lower() == "off":
                continue
            base = (cfg.get("portal_package_url") or "").strip()
            if not base.startswith("https://"):
                continue
            req = urllib.request.Request(
                base + "?action=manifest",
                headers={"User-Agent": f"NexaCrew/{APP_VERSION}"})
            with urllib.request.urlopen(req, timeout=30) as r:
                man = json.loads(r.read(1 << 20).decode("utf-8"))
            remote = str(man.get("version") or "").strip()
            sha_want = str(man.get("sha256") or "").strip().lower()
            if (not man.get("ok") or not remote or not sha_want
                    or _ver_tuple(remote) <= _ver_tuple(APP_VERSION)):
                continue
            url = str(man.get("url") or (base + "?action=download"))
            print(f"⬆ portal update: v{APP_VERSION} → v{remote} — downloading", flush=True)
            tmp = Path(tempfile.gettempdir()) / f"nexacrew_update_{remote}.tar.gz"
            h = hashlib.sha256()
            dreq = urllib.request.Request(
                url, headers={"User-Agent": f"NexaCrew/{APP_VERSION}"})
            with urllib.request.urlopen(dreq, timeout=120) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    h.update(chunk)
                    f.write(chunk)
            if h.hexdigest().lower() != sha_want:
                print(f"❌ portal update v{remote}: SHA-256 mismatch — aborted "
                      "(will retry next cycle)", flush=True)
                tmp.unlink(missing_ok=True)
                continue
            with tarfile.open(tmp, "r:gz") as tf:
                members = []
                for m in tf.getmembers():
                    parts = Path(m.name).parts
                    if len(parts) < 2 or m.issym() or m.islnk() or ".." in parts:
                        continue  # top-level dir, links, traversal
                    rel = Path(*parts[1:]).as_posix()
                    if rel.startswith("platform/data"):
                        continue  # never overwrite the customer database/config
                    m.name = rel
                    members.append(m)
                tf.extractall(ROOT_DIR, members=members)
            tmp.unlink(missing_ok=True)
            try:
                from .db import SessionLocal as _SL
                with _SL() as _db:
                    audit(_db, "server.auto_update",
                          f"updated from mapstudiousa.com: v{APP_VERSION} → v{remote}")
                    _db.commit()
            except Exception:  # noqa: BLE001 — audit failure must not block restart
                pass
            print(f"✅ updated to v{remote} — restarting server", flush=True)
            _time.sleep(2)
            try:
                os.execv(sys.executable, [sys.executable] + sys.argv)
            except OSError:
                os._exit(3)  # supervisor (start.py watchdog / systemd) restarts us
        except Exception as e:  # noqa: BLE001 — updater must never crash the server
            print(f"⚠ portal update check failed: {e} — retrying next cycle", flush=True)


@app.post("/api/license/claim")
def license_claim(body: dict, request: Request, db: Session = Depends(get_db)):
    """Unauthenticated — a client computer claims (or re-validates) a license
    key before installing. Binds the key to the caller's IP address."""
    row = _check_license(db, str(body.get("key") or ""), _client_ip(request),
                         hostname=str(body.get("hostname") or ""), claim=True)
    audit(db, "license.claim", f"{row.key} claimed by {row.used_by_ip} ({row.used_by_host})")
    return {"ok": True, "key": row.key, "bound_ip": row.used_by_ip,
            "version": APP_VERSION}


def _ver_tuple(v: str) -> tuple:
    parts = []
    for p in str(v or "0").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts + [0] * (3 - len(parts)))


@app.post("/api/client/heartbeat")
def client_heartbeat(body: dict, request: Request, db: Session = Depends(get_db)):
    """Unauthenticated — installed clients ping this every 30 s so the server
    can show a live client connection list. Validated by license key + IP.
    The client reports its program version; when it is older than the server
    version the reply carries update_required=True and the client force-updates
    itself immediately (download package → replace files → restart).
    The reply also carries any pending remote configuration pushed by an
    administrator (config + config_rev) — the client applies it when its
    locally applied revision is older."""
    row = _check_license(db, str(body.get("key") or ""), _client_ip(request),
                         hostname=str(body.get("hostname") or ""), claim=True)
    cv = str(body.get("version") or "").strip()
    cos = str(body.get("os") or "").strip()[:120]
    dirty = False
    if cv and cv != (row.client_version or ""):
        row.client_version = cv
        dirty = True
    if cos and cos != (row.client_os or ""):
        row.client_os = cos
        dirty = True
    # hardware identity — MAC of the NIC that reaches this server, OS, CPU
    # serial, disk serial, local IP. Recorded against the license.
    hw = body.get("hw")
    if isinstance(hw, dict) and hw:
        clean = {k: str(hw.get(k) or "")[:120] for k in
                 ("mac", "ip", "os", "cpu_serial", "disk_serial", "nic", "device_type")}
        blob = json.dumps(clean, sort_keys=True)
        if blob != (row.client_hw or "{}"):
            row.client_hw = blob
            dirty = True
    if dirty:
        db.commit()
    # live telemetry (kept in memory only — sliding NOC metrics)
    m = body.get("metrics") or {}
    if isinstance(m, dict):
        _client_metrics[row.id] = {
            "cpu": m.get("cpu"), "ram": m.get("ram"),
            "ts": dt.datetime.utcnow().timestamp()}
    update_required = bool(cv) and _ver_tuple(cv) < _ver_tuple(APP_VERSION)
    if update_required:
        audit(db, "client.update_forced",
              f"{row.used_by_host or row.used_by_ip}: v{cv} → v{APP_VERSION}")
    out = {"ok": True, "server_version": APP_VERSION,
           "bound_ip": row.used_by_ip,
           "update_required": update_required}
    # remote configuration push — only when the client's applied rev is older
    try:
        client_rev = int(body.get("config_rev") or 0)
    except (TypeError, ValueError):
        client_rev = 0
    if (row.config_rev or 0) > client_rev:
        try:
            cfg = json.loads(row.client_config or "{}")
        except ValueError:
            cfg = {}
        if cfg:
            out["config"] = cfg
            out["config_rev"] = row.config_rev
    # generated-file delivery — files the agents produced for THIS client
    with _pending_files_lock:
        pend = list(_pending_client_files.get(row.id) or [])
    if pend:
        out["files"] = [{"id": f["id"], "name": f["name"], "dest": f["dest"]}
                        for f in pend]
    return out


@app.get("/api/client/file")
def client_fetch_file(key: str, id: str, request: Request,  # noqa: A002
                      db: Session = Depends(get_db)):
    """Client program downloads a generated file announced in its heartbeat.
    License-key + bound-IP validated; the entry is removed once served."""
    row = _check_license(db, key, _client_ip(request))
    with _pending_files_lock:
        pend = _pending_client_files.get(row.id) or []
        entry = next((f for f in pend if f["id"] == id), None)
        if entry:
            pend.remove(entry)
    if not entry or not Path(entry["src"]).is_file():
        raise HTTPException(404, "File no longer available")
    return FileResponse(entry["src"], filename=entry["name"],
                        media_type="application/octet-stream")


_ACTION_PLAN_SYSTEM = """You are NexaCrew Action-by-Prompt, an automation \
planner that controls a user's computer with keyboard and mouse like a human.
You receive: the application that was in the foreground when the user asked \
(e.g. Photoshop, WINWORD, chrome), the window title, the operating system, \
the screen size, the user's task prompt and optional attachments (file paths, \
sometimes with text content).

Reply with ONLY a JSON object, no markdown, in this exact shape:
{"note": "<one-line summary of what you will do>",
 "plan": [ {"action": "...", ...}, ... ]}

Allowed actions (execute in order, human-like pacing is added automatically):
 {"action":"open_app",  "name":"<app name>", "seconds":4, "note":"..."}
 {"action":"open_url",  "url":"https://…",   "seconds":4, "note":"..."}
 {"action":"open_file", "path":"<abs path>", "seconds":4, "note":"..."}
 {"action":"wait",      "seconds":2,                       "note":"..."}
 {"action":"type",      "text":"…",                        "note":"..."}
 {"action":"paste",     "text":"long text via clipboard",  "note":"..."}
 {"action":"hotkey",    "keys":["ctrl","s"],               "note":"..."}
 {"action":"press",     "key":"enter", "times":1,          "note":"..."}
 {"action":"click",     "x":100, "y":200, "button":"left", "times":1, "note":"..."}

Rules:
- Prefer the application the user triggered from; open it with open_app if it
  may not be focused. Use open_file for attachments the target app should load.
- Use keyboard-driven flows (menus via hotkeys, typing full content with
  paste) — avoid blind pixel clicks unless coordinates are certain from the
  screen size (e.g. centre of screen).
- For document/text creation (Word, editors): open the app, then paste the
  complete, professional, ready-to-use content you author yourself.
- For a browser task (e.g. an eBay listing): open_url the right page, then
  guide with waits, typing and tab/enter key presses; author the full
  professional listing text (title, description, specifics) yourself.
- For creative apps (e.g. Photoshop) prefer scriptable/menu hotkeys and
  realistic, conservative steps; describe each step in "note".
- Keep the plan under 40 steps. If the task is impossible to automate safely,
  return an empty plan and explain in "note"."""


@app.post("/api/action/plan")
def action_plan(body: dict, request: Request, db: Session = Depends(get_db)):
    """Unauthenticated (license-key validated) — plan an "Action by prompt"
    task for a client machine. Returns a JSON keyboard/mouse step plan."""
    ip = _client_ip(request)
    if ip not in ("127.0.0.1", "::1", "localhost"):   # server machine needs no key
        _check_license(db, str(body.get("key") or ""), ip,
                       hostname="", claim=True)
    task = str(body.get("prompt") or "").strip()
    if not task:
        raise HTTPException(400, "Empty prompt")
    atts = body.get("attachments") or []
    att_txt = ""
    for a in atts[:20]:          # generous cap — all attached files reach the model
        att_txt += f"\n- {a.get('name')} (path: {a.get('path')})"
        if a.get("note"):
            att_txt += f" — {a['note']}"
        if a.get("text"):
            att_txt += f"\n  content:\n{str(a['text'])[:8000]}"
    user_prompt = (
        f"Foreground application: {body.get('app') or 'unknown'}\n"
        f"Window title: {body.get('title') or ''}\n"
        f"Operating system: {body.get('os') or ''}\n"
        f"Screen size: {json.dumps(body.get('screen') or {})}\n"
        f"Attachments:{att_txt or ' none'}\n\n"
        f"User task:\n{task}\n\n"
        "Produce the JSON plan now.")
    from .providers import ClaudeCodeProvider, CodexProvider
    out = ""
    for prov in (CodexProvider(), ClaudeCodeProvider()):
        try:
            if prov.available:
                out = prov.run(user_prompt, system=_ACTION_PLAN_SYSTEM)
                if out:
                    break
        except Exception:  # noqa: BLE001
            continue
    if not out:
        raise HTTPException(503, "No AI provider is available on the server "
                                 "to plan this task")
    # extract the JSON object from the model output
    try:
        s, e = out.find("{"), out.rfind("}")
        data = json.loads(out[s:e + 1]) if s >= 0 <= e else {}
    except ValueError:
        data = {}
    plan = data.get("plan") if isinstance(data, dict) else None
    if not isinstance(plan, list):
        return {"ok": False, "plan": [],
                "note": (data.get("note") if isinstance(data, dict) else "")
                or "The AI reply could not be parsed into steps."}
    audit(db, "action.plan",
          f"{body.get('app') or '?'} — {task[:120]} → {len(plan)} step(s)")
    return {"ok": True, "note": str(data.get("note") or ""), "plan": plan}


CLIENT_ONLINE_WINDOW_S = 90  # heartbeat every 30 s → offline after 3 misses
_client_metrics: dict = {}   # license_id → {cpu, ram, ts} (memory only)


MAX_CLIENT_DEVICES = 500     # bound on self-registered kiosk/browser devices


@app.post("/api/client/device-register")
def device_register(body: dict, request: Request, user=Depends(optional_user),
                    db: Session = Depends(get_db)):
    """Browser-based devices (phones / tablets / Chromebooks on the station or
    kiosk pages) self-register here — no installed client program needed.
    Works BEFORE sign-in (kiosk login screen) so the device is visible to
    administrators immediately; the operator name is attached after sign-in.
    Records device type, OS/model (from the user agent), IP and usage.
    NOTE: web browsers cannot read the WiFi MAC address (privacy sandbox);
    the field exists for admin entry / managed devices."""
    from .db import ClientDevice
    uid = str(body.get("device_uid") or "").strip()[:80]
    if not uid or not re.fullmatch(r"dev-[A-Za-z0-9]{6,40}", uid):
        raise HTTPException(422, "device_uid required (format dev-<token>)")
    row = db.query(ClientDevice).filter_by(device_uid=uid).first()
    is_new = row is None
    if not row:
        # bound table growth — anonymous beacons must not fill the disk
        if db.query(ClientDevice).count() >= MAX_CLIENT_DEVICES:
            raise HTTPException(429, "device registry full — remove stale devices")
        # SEAT ENFORCEMENT: a brand-new mobile/tablet/kiosk device consumes a
        # seat like any desktop client — reject when the license is full.
        from .license_authority import seat_limit, seats_in_use
        seats = seat_limit()
        if seats > 0:
            in_use = int(seats_in_use(db).get("used") or 0)
            if in_use >= seats:
                audit(db, "license.seat_limit",
                      f"device-register rejected for {_client_ip(request)}: "
                      f"{in_use}/{seats} seats in use")
                raise HTTPException(
                    403, f"Seat limit reached — this server's license allows "
                         f"{seats} device(s). Upgrade the plan at mapstudiousa.com "
                         f"or remove an unused device.")
        row = ClientDevice(device_uid=uid)
        db.add(row)
    row.kind = str(body.get("kind") or "mobile")[:30]
    row.usage = str(body.get("usage") or "")[:120]
    row.os = str(body.get("os") or "")[:80]
    row.model = str(body.get("model") or "")[:120]
    row.ua = str(body.get("ua") or "")[:500]
    row.ip = _client_ip(request)
    if body.get("mac"):
        row.mac = str(body.get("mac"))[:40]
    if user is not None:                      # keep last known operator otherwise
        row.user_name = user.display_name or user.username
    row.last_seen_at = dt.datetime.utcnow()
    db.commit()
    if is_new:
        # push the updated device snapshot to mapstudiousa.com promptly
        # (debounced 30 s) so the portal shows the new device without
        # waiting for the next periodic validation.
        from .license_authority import request_sync
        request_sync()
    return {"ok": True}


@app.get("/api/clients")
def list_clients(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Admin — live client connection list with license + online status."""
    require_admin(user)
    now = dt.datetime.utcnow()
    out = []
    for r in db.query(LicenseKey).order_by(LicenseKey.created_at.desc()).all():
        online = bool(r.last_seen_at and not r.revoked and
                      (now - r.last_seen_at).total_seconds() < CLIENT_ONLINE_WINDOW_S)
        cv = (r.client_version or "")
        met = _client_metrics.get(r.id) or {}
        fresh = met and (now.timestamp() - (met.get("ts") or 0)) < CLIENT_ONLINE_WINDOW_S
        try:
            hw = json.loads(r.client_hw or "{}")
        except ValueError:
            hw = {}
        out.append({
            "license_id": r.id, "license_key": r.key, "note": r.note,
            "revoked": r.revoked, "claimed": r.used,
            "version": cv,
            "outdated": bool(cv) and _ver_tuple(cv) < _ver_tuple(APP_VERSION),
            "ip": r.used_by_ip or "", "hostname": r.used_by_host or "",
            "os": r.client_os or "",
            "device_type": hw.get("device_type") or "desktop",
            "mac": hw.get("mac") or "",
            "cpu_serial": hw.get("cpu_serial") or "",
            "disk_serial": hw.get("disk_serial") or "",
            "usage": "operation",
            "config_rev": r.config_rev or 0,
            "cpu": met.get("cpu") if fresh else None,
            "ram": met.get("ram") if fresh else None,
            "claimed_at": r.used_at.isoformat() if r.used_at else None,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
            "online": online,
            "status": ("revoked" if r.revoked else
                       "online" if online else
                       "offline" if r.used else "never connected"),
        })
    # browser-based devices (mobile / tablet / Chromebook kiosk terminals)
    from .db import ClientDevice
    devices = []
    for d in db.query(ClientDevice).order_by(ClientDevice.created_at.desc()).all():
        online = bool(d.last_seen_at and
                      (now - d.last_seen_at).total_seconds() < 180)   # 3 min beacon window
        devices.append({
            "id": d.id, "device_uid": d.device_uid, "kind": d.kind or "mobile",
            "usage": d.usage or "", "os": d.os or "", "model": d.model or "",
            "ip": d.ip or "", "mac": d.mac or "", "user": d.user_name or "",
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "online": online,
        })
    import socket as _socket
    from .cluster import cluster_status as _cstat
    cl = _cstat()
    return {"clients": out, "devices": devices,
            "online_window_s": CLIENT_ONLINE_WINDOW_S,
            "server_version": APP_VERSION,
            "server_hostname": _socket.gethostname(),
            "cluster": {"role": cl.get("role", "standalone"),
                        "controller_ip": cl.get("controller_ip", ""),
                        "controller_port": cl.get("controller_port", 8600),
                        "nodes": cl.get("nodes", [])}}


@app.get("/api/clients/{lid}/config")
def get_client_config(lid: str, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Admin — the remote configuration currently pushed to a client."""
    require_admin(user)
    row = db.query(LicenseKey).filter_by(id=lid).first()
    if not row:
        raise HTTPException(404, "license key not found")
    try:
        cfg = json.loads(row.client_config or "{}")
    except ValueError:
        cfg = {}
    return {"config": cfg, "config_rev": row.config_rev or 0,
            "note": row.note or ""}


@app.put("/api/clients/{lid}/config")
def put_client_config(lid: str, body: dict, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Admin — push configuration to a client program. Delivered on the next
    heartbeat (≤30 s); the client merges it into its config.json and restarts
    itself so every setting takes effect immediately."""
    require_admin(user)
    row = db.query(LicenseKey).filter_by(id=lid).first()
    if not row:
        raise HTTPException(404, "license key not found")
    cfg = body.get("config")
    if not isinstance(cfg, dict):
        raise HTTPException(400, "config must be a JSON object")
    for k in ("license_key", "deploy_mode"):   # never remotely overridable
        cfg.pop(k, None)
    if "note" in body:
        row.note = str(body.get("note") or "")[:200]
    row.client_config = json.dumps(cfg)
    row.config_rev = (row.config_rev or 0) + 1
    db.commit()
    audit(db, "client.config_push",
          f"{row.used_by_host or row.used_by_ip or row.key}: rev {row.config_rev} "
          f"({', '.join(sorted(cfg.keys())) or 'cleared'})", user_id=user.id)
    return {"ok": True, "config_rev": row.config_rev}


# ---------------- client package (install / auto-update) ----------------
_PKG_EXCLUDE_DIRS = {".venv", ".venv-linux", ".venv-mac", ".git", "__pycache__",
                     "node_modules", "data", ".pytest_cache"}
_pkg_cache: dict = {"version": None, "path": None}
_pkg_lock = threading.Lock()
_pkg_progress: dict = {"state": "idle", "done": 0, "total": 0}


def _build_client_package() -> Path:
    """Zip the program folder (source only — no data, venv or caches).
    Rebuilt automatically whenever any source file is newer than the zip.
    Built atomically (temp file + rename) under a lock so a client can never
    download a half-written archive."""
    import zipfile
    out = ROOT_DIR / "platform" / "data" / f"client_package_{APP_VERSION}.zip"
    files = []
    newest = 0.0
    for p in ROOT_DIR.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT_DIR)
        if any(part in _PKG_EXCLUDE_DIRS for part in rel.parts):
            continue
        if rel.suffix in (".zip", ".pyc", ".db"):
            continue
        files.append((p, rel))
        newest = max(newest, p.stat().st_mtime)
    with _pkg_lock:
        if out.is_file() and out.stat().st_mtime >= newest:
            _pkg_progress.update(state="ready", done=len(files), total=len(files))
            return out  # cache is current
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".zip.tmp")
        _pkg_progress.update(state="building", done=0, total=len(files))
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for i, (p, rel) in enumerate(files, 1):
                z.write(p, str(rel))
                _pkg_progress["done"] = i
        # verify before publishing — a client must never see a bad archive
        _pkg_progress["state"] = "verifying"
        with zipfile.ZipFile(tmp) as z:
            if z.testzip() is not None:
                tmp.unlink(missing_ok=True)
                _pkg_progress["state"] = "error"
                raise HTTPException(500, "package build failed verification")
        tmp.replace(out)      # atomic on the same filesystem
        # clean up stale packages from previous versions
        for old in out.parent.glob("client_package_*.zip"):
            if old != out:
                try:
                    old.unlink()
                except OSError:
                    pass
        _pkg_cache.update(version=APP_VERSION, path=out)
        _pkg_progress["state"] = "ready"
    return out


@app.get("/api/client-package-progress")
def client_package_progress():
    """Live packaging progress for the download page's progress bar.
    No secrets — just counters."""
    return dict(_pkg_progress)


@app.get("/api/cameras")
def camera_defaults():
    """Server-wide camera role defaults (Settings → Cameras). Public read —
    device-name substrings only, needed before some operator flows."""
    cfg = get_config()
    return {"camera_internal": str(cfg.get("camera_internal") or ""),
            "camera_external": str(cfg.get("camera_external") or "")}


@app.get("/api/client-package")
def client_package(key: str, request: Request, host: str = "",
                   db: Session = Depends(get_db)):
    """Program package download — requires a valid license key bound to the
    caller's IP (used by the installer and by the auto-updater). The optional
    `host` parameter carries the client's hostname so the SAME computer is
    recognized even when the request leaves through a different network
    interface / DHCP address than the one the key is bound to."""
    _check_license(db, key, _client_ip(request), hostname=host,
                   claim=True, enforce_ip=False)
    pkg = _build_client_package()
    return FileResponse(pkg, media_type="application/zip",
                        filename=f"agent_ai_client_{APP_VERSION}.zip")


@app.get("/api/installer")
def installer_script(key: str, request: Request, db: Session = Depends(get_db)):
    """Generates a one-click Windows installer (.bat) with the server address
    and the client's license key baked in. It downloads the program package,
    extracts it, writes client-mode config and starts the platform."""
    _check_license(db, key, _client_ip(request), claim=True)
    host = request.headers.get("host") or "127.0.0.1:8600"
    server_ip, _, server_port = host.partition(":")
    server_port = server_port or "8600"
    norm = key.strip().upper().replace(" ", "")
    script = f"""@echo off\r
title Virtual Company AI Agent - Client installer\r
echo ==============================================================\r
echo   NexaCrew - client installation\r
echo   Developed by Sin Chi Chi . MAP Studio\r
echo ==============================================================\r
set "SERVER={server_ip}"\r
set "PORT={server_port}"\r
set "KEY={norm}"\r
set "DEST=%USERPROFILE%\\AGENT_AI"\r
set "PKG=%TEMP%\\agent_ai_pkg.zip"\r
echo Installing to %DEST% ...\r
if not exist "%DEST%" mkdir "%DEST%"\r
echo [1/4] Downloading program package from http://%SERVER%:%PORT% ...\r
powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing 'http://%SERVER%:%PORT%/api/client-package?key=%KEY%' -OutFile '%PKG%'" || goto :fail\r
if not exist "%PKG%" goto :fail\r
echo [2/4] Extracting ...\r
powershell -NoProfile -Command "Expand-Archive -Force '%PKG%' '%DEST%'" || goto :fail\r
del /q "%PKG%" >nul 2>&1\r
echo [3/4] Writing client configuration ...\r
if not exist "%DEST%\\platform\\data" mkdir "%DEST%\\platform\\data"\r
powershell -NoProfile -Command "$f='%DEST%\\platform\\data\\config.json'; $c=@{{}}; if(Test-Path $f){{ (Get-Content $f -Raw | ConvertFrom-Json).PSObject.Properties | ForEach-Object {{ $c[$_.Name]=$_.Value }} }}; $c['deploy_mode']='client'; $c['client_server_ip']='%SERVER%'; $c['client_server_port']=[int]'%PORT%'; $c['license_key']='%KEY%'; $c | ConvertTo-Json | Set-Content $f -Encoding UTF8" || goto :fail\r
echo [4/4] Starting the platform (this installs Python + libraries automatically) ...\r
cd /d "%DEST%"\r
rem start DETACHED so the program (and its system-tray icon) keeps running\r
rem after this installer window is closed\r
where pythonw >nul 2>&1 && (start "" pythonw start.py & goto :started)\r
where python  >nul 2>&1 && (start "NexaCrew" python start.py & goto :started)\r
where py      >nul 2>&1 && (start "NexaCrew" py start.py & goto :started)\r
goto :nopython\r
:started\r
echo.\r
echo Installation complete - NexaCrew is starting in the background.\r
echo Look for the NexaCrew icon in the system tray (near the clock).\r
timeout /t 8 >nul\r
goto :eof\r
:nopython\r
echo.\r
echo Python was not found. Install Python 3.9+ from https://python.org, then run:\r
echo   %DEST%\\start.py\r
pause\r
goto :eof\r
:fail\r
echo.\r
echo Installation failed - check that the server is reachable and the license key is valid.\r
pause\r
"""
    return Response(content=script, media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="install_agent_ai.bat"'})


@app.get("/api/installer-sh")
def installer_script_sh(key: str, request: Request, db: Session = Depends(get_db)):
    """One-click macOS / Linux client installer (.sh) with the server address
    and license key baked in: downloads the package, extracts it, writes the
    client config and starts the platform DETACHED (tray icon appears)."""
    _check_license(db, key, _client_ip(request), claim=True)
    host = request.headers.get("host") or "127.0.0.1:8600"
    server_ip, _, server_port = host.partition(":")
    server_port = server_port or "8600"
    norm = key.strip().upper().replace(" ", "")
    script = f"""#!/bin/bash
# NexaCrew - client installation (macOS / Linux)
# Developed by Sin Chi Chiu . MAP Studio
set -u
SERVER="{server_ip}"; PORT="{server_port}"; KEY="{norm}"
DEST="$HOME/AGENT_AI"; PKG="/tmp/agent_ai_pkg.zip"
echo "=============================================================="
echo "  NexaCrew - client installation -> $DEST"
echo "=============================================================="
mkdir -p "$DEST"
echo "[1/4] Downloading program package from http://$SERVER:$PORT ..."
curl -fsSL "http://$SERVER:$PORT/api/client-package?key=$KEY" -o "$PKG" || {{ echo "Download failed."; exit 1; }}
echo "[2/4] Extracting ..."
if command -v unzip >/dev/null 2>&1; then unzip -oq "$PKG" -d "$DEST"
else python3 -c "import zipfile;zipfile.ZipFile('$PKG').extractall('$DEST')"; fi
rm -f "$PKG"
echo "[3/4] Writing client configuration ..."
mkdir -p "$DEST/platform/data"
python3 - "$DEST" "$SERVER" "$PORT" "$KEY" <<'PYEOF'
import json, sys, pathlib
dest, server, port, key = sys.argv[1:5]
f = pathlib.Path(dest) / "platform" / "data" / "config.json"
cfg = {{}}
try: cfg = json.loads(f.read_text(encoding="utf-8-sig"))
except Exception: pass
cfg.update(deploy_mode="client", client_server_ip=server,
           client_server_port=int(port), license_key=key)
f.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
PYEOF
echo "[4/4] Starting the platform (installs Python libraries automatically) ..."
cd "$DEST"
chmod +x start.py client_start.py 2>/dev/null
# detached: the program and its menu-bar / tray icon keep running after
# this terminal window is closed
nohup python3 start.py >/dev/null 2>&1 &
echo
echo "Installation complete - NexaCrew is starting in the background."
echo "Look for the NexaCrew icon in the menu bar / system tray."
"""
    return Response(content=script, media_type="application/octet-stream",
                    headers={"Content-Disposition": 'attachment; filename="install_agent_ai.sh"'})


@app.get("/api/client-backup")
def client_backup():
    """Settings backup for client installs (fetched at setup and on every
    login). Clients store it locally so they can keep running standalone
    with the same configuration when the server is down. Secrets that only
    make sense on the server (SMTP/Twilio passwords) are excluded."""
    cfg = get_config()
    safe = {k: v for k, v in cfg.items()
            if k not in ("smtp_password", "twilio_auth_token", "cluster_secret")}
    # ai_api_* (including the key) IS shared so clients connect to the same
    # AI model through the server-managed API configuration.
    safe["deploy_mode"] = "server"        # fallback runs locally
    safe["server_bind"] = "127.0.0.1"     # local-only when in fallback
    return {"config": safe, "backed_up_at": dt.datetime.utcnow().isoformat()}


@app.post("/api/cluster/discover")
def cluster_discover(user: User = Depends(current_user)):
    """LAN auto-discovery: broadcast the MAPSTUDIO-DISCOVER-V1 probe and
    return every platform server that answered."""
    require_admin(user)
    return {"servers": _cluster.discover_servers()}


@app.get("/api/schedules")
def list_schedules(user: User = Depends(current_user), db: Session = Depends(get_db)):
    jobs = (db.query(ScheduledJob).filter(ScheduledJob.deleted_at.is_(None),
                                          ScheduledJob.user_id == user.id)
            .order_by(ScheduledJob.created_at.desc()).all())
    out = []
    for j in jobs:
        chat = db.get(Chat, j.chat_id)
        out.append(_d(j, {"cron_human": describe_cron(j.cron),
                          "chat_title": chat.title if chat else "(deleted chat)"}))
    return out


@app.post("/api/schedules")
def create_schedule(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    cron = str(body.get("cron", "")).strip()
    if not validate_cron(cron):
        raise HTTPException(400, "Invalid cron expression — use 5 fields: min hour dom month dow")
    _own_chat(db, str(body.get("chat_id", "")), user)  # must be the user's own chat
    job = ScheduledJob(name=str(body.get("name", "Scheduled task"))[:120], cron=cron,
                       prompt=str(body.get("prompt", "")), chat_id=body["chat_id"],
                       user_id=user.id, enabled=bool(body.get("enabled", True)))
    if not job.prompt.strip():
        raise HTTPException(400, "prompt is required")
    db.add(job)
    db.commit()
    audit(db, "schedule.create", f"job={job.id} cron={cron}", user_id=user.id)
    return _d(job, {"cron_human": describe_cron(job.cron)})


@app.put("/api/schedules/{job_id}")
def update_schedule(job_id: str, body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(ScheduledJob, job_id)
    if not job or job.deleted_at or job.user_id != user.id:
        raise HTTPException(404, "Schedule not found")
    if "cron" in body:
        if not validate_cron(str(body["cron"])):
            raise HTTPException(400, "Invalid cron expression")
        if str(body["cron"]) != job.cron:
            job.last_status = None  # re-armed with a new time
        job.cron = str(body["cron"])
    for f in ("name", "prompt", "chat_id"):
        if f in body:
            setattr(job, f, str(body[f]))
    if "enabled" in body:
        job.enabled = bool(body["enabled"])
    db.commit()
    audit(db, "schedule.update", f"job={job.id}", user_id=user.id)
    return _d(job, {"cron_human": describe_cron(job.cron)})


@app.delete("/api/schedules/{job_id}")
def delete_schedule(job_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    job = db.get(ScheduledJob, job_id)
    if not job or job.user_id != user.id:
        raise HTTPException(404, "Schedule not found")
    job.deleted_at = dt.datetime.utcnow()
    db.commit()
    audit(db, "schedule.delete", f"job={job.id}", user_id=user.id)
    return {"ok": True}


# ---------------- mobile messaging bridge (WhatsApp / WeChat) ----------------
from .messaging import (  # noqa: E402
    email_attachments, extract_file_paths, get_messaging_provider, sender_allowed,
)


def _mobile_chat(db: Session, channel: str) -> Chat:
    """Find or create the dedicated chat used for mobile-originated requests."""
    title = f"📱 Mobile — {channel.capitalize()}"
    chat = (db.query(Chat).filter(Chat.title == title, Chat.deleted_at.is_(None)).first())
    if chat:
        return chat
    emp = (db.query(VirtualEmployee)
           .filter(VirtualEmployee.status == "Active", VirtualEmployee.deleted_at.is_(None)).first())
    if not emp:
        raise HTTPException(500, "No active employee available to handle mobile requests")
    chat = Chat(title=title, company_id=emp.company_id, active_employee_id=emp.id)
    db.add(chat)
    db.commit()
    return chat


@app.post("/api/webhook/{channel}")
def mobile_webhook(channel: str, body: dict, db: Session = Depends(get_db)):
    """Inbound prompt from WhatsApp/WeChat.

    Body: {"token": secret, "from": sender number/id, "text": the prompt}
    Auth: shared webhook_token from Settings + sender allow-list (no session).
    """
    from .config import get_config
    if channel not in ("whatsapp", "wechat"):
        raise HTTPException(404, "Unknown channel")
    cfg = get_config()
    if not cfg["webhook_token"] or str(body.get("token", "")) != cfg["webhook_token"]:
        raise HTTPException(403, "Invalid webhook token")
    sender = str(body.get("from", "")).strip()
    text = str(body.get("text", "")).strip()
    if not sender or not text:
        raise HTTPException(400, "'from' and 'text' are required")
    if not sender_allowed(sender):
        audit(db, "mobile.rejected", f"channel={channel} from={sender}")
        raise HTTPException(403, "Sender is not on the allow-list (Settings → Allowed mobile senders)")

    chat = _mobile_chat(db, channel)
    owner = db.query(User).first()
    audit(db, "mobile.request", f"channel={channel} from={sender} text={text[:200]}",
          company_id=chat.company_id)
    result = run_agent_message(db, chat, f"[via {channel} from {sender}] {text}",
                               owner.id if owner else "mobile")
    answer = result["message"]

    # Collect generated files: explicit attachments + any file paths in the answer
    files = list(result.get("attachments") or [])
    for p in extract_file_paths(answer):
        if p not in files:
            files.append(p)

    # 1) Reply on the same channel (with attachment references)
    provider = get_messaging_provider(channel)
    send_res = provider.send(sender, answer[:3000], attachments=files)

    # 2) Email the attachments too
    email_res = None
    if files and cfg["notify_email"]:
        email_res = email_attachments(cfg["notify_email"],
                                      f"Generated files — {channel} request",
                                      f"Your request: {text}\n\n{answer[:1500]}", files)
    audit(db, "mobile.reply", f"channel={channel} to={sender} files={len(files)} "
          f"msg={send_res.get('message_id', '')}", company_id=chat.company_id)
    return {"ok": True, "run_id": result.get("run_id"), "answer": answer,
            "attachments": files, "message_send": send_res, "email_send": email_res}


@app.post("/api/open-file")
def open_file_locally(body: dict, user: User = Depends(current_user)):
    """Open a generated file with its default Windows application (local-dev convenience)."""
    try:
        p = Path(str(body.get("path", ""))).resolve()
    except (OSError, ValueError):
        raise HTTPException(400, "Invalid path")
    try:
        p.relative_to(Path.home())
    except ValueError:
        raise HTTPException(403, "Only files under your home directory can be opened")
    _deny_sensitive_path(p, user)
    if not p.is_file():
        raise HTTPException(404, "File not found")
    import os
    import platform as _pf
    import subprocess as _sp
    sysname = _pf.system()
    if sysname == "Windows":
        os.startfile(str(p))  # noqa: S606 — local desktop app by design
    elif sysname == "Darwin":
        _sp.Popen(["open", str(p)])
    else:
        _sp.Popen(["xdg-open", str(p)])
    return {"ok": True, "opened": str(p)}


_TEXT_EXTS = {".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".html", ".css",
              ".xml", ".yaml", ".yml", ".log", ".ini", ".toml", ".bat", ".ps1", ".sql"}
_IMG_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


def _deny_sensitive_path(p: Path, user: User) -> None:
    """Defence-in-depth for the file-serving endpoints: even inside the home
    directory, never serve dot-files/dirs (.ssh, .aws, .gitconfig, browser
    profiles…) and keep the platform's own data directory (SQLite DB, Fernet
    key, backups) admin-only. Prevents credential exfiltration by a
    compromised low-privilege account."""
    if any(part.startswith(".") for part in p.parts[1:]):
        raise HTTPException(403, "Hidden/system files are not served")
    if not user.is_admin:
        data_dir = (Path(__file__).resolve().parent.parent / "data")
        try:
            p.relative_to(data_dir)
            raise HTTPException(403, "Platform data files are admin-only")
        except ValueError:
            pass


@app.get("/api/download")
def download_file(path: str, user: User = Depends(current_user)):
    """Stream a generated file to the browser — lets remote CLIENT computers
    save files that the agents created on the server's disk."""
    try:
        p = Path(path).resolve()
        p.relative_to(Path.home())
    except (OSError, ValueError):
        raise HTTPException(403, "Not allowed")
    _deny_sensitive_path(p, user)
    if not p.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(str(p), filename=p.name,
                        media_type="application/octet-stream")


@app.get("/api/preview")
def preview_file(path: str, user: User = Depends(current_user)):
    """Lightweight file preview for hover tooltips: text snippet, image flag, or metadata."""
    try:
        p = Path(path).resolve()
        p.relative_to(Path.home())
    except (OSError, ValueError):
        raise HTTPException(403, "Not allowed")
    _deny_sensitive_path(p, user)
    if not p.is_file():
        raise HTTPException(404, "File not found")
    st = p.stat()
    meta = {"name": p.name, "size": st.st_size,
            "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")}
    ext = p.suffix.lower()
    if ext in _IMG_EXTS:
        return {**meta, "kind": "image"}
    if ext == ".pdf":
        pages = None
        try:
            head = p.read_bytes()[:2_000_000]
            pages = head.count(b"/Type /Page") - head.count(b"/Type /Pages") or None
        except OSError:
            pass
        return {**meta, "kind": "pdf", "pages": pages}
    if ext in _TEXT_EXTS:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:1200]
        except OSError:
            text = "(could not read file)"
        return {**meta, "kind": "text", "content": text}
    return {**meta, "kind": "binary"}


@app.get("/api/chats/{chat_id}/progress")
def chat_progress(chat_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Live status of the most recent agent run for this chat."""
    _own_chat(db, chat_id, user)
    from .db import ToolCall
    run = (db.query(AgentRun).filter(AgentRun.chat_id == chat_id)
           .order_by(AgentRun.created_at.desc()).first())
    if not run:
        return {"status": "none", "stages": [], "run_id": None}
    calls = db.query(ToolCall).filter(ToolCall.run_id == run.id).order_by(ToolCall.created_at).all()
    labels = {"codex.plan": "🧠 Codex — planning",
              "codex.image": "🎨 Codex — generating image",
              "codex.file": "📄 Codex — creating file",
              "codex.index": "📚 Codex — building index",
              "claude_code.verify": "✅ Claude Code — verifying index",
              "codex.schedule": "⏰ Codex — parsing schedule",
              "codex.configure": "⚙️ Codex — updating configuration",
              "codex.analyze": "🔍 Codex — analyzing attachment",
              "claude_code.implement": "⚙️ Claude Code — implementing",
              "vscode.open": "🚀 VS Code — handoff"}
    return {"status": run.status, "run_id": run.id,
            "stages": [{"tool": c.tool, "label": labels.get(c.tool, c.tool),
                        "status": c.status} for c in calls]}


@app.get("/api/runs/{run_id}/detail")
def run_detail(run_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Full live detail of an agent run: every stage with arguments, output and timing."""
    from .db import ToolCall
    run = db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    calls = db.query(ToolCall).filter(ToolCall.run_id == run.id).order_by(ToolCall.created_at).all()
    labels = {"codex.plan": "🧠 Codex — planning",
              "codex.image": "🎨 Codex — image generation",
              "codex.file": "📄 Codex — file creation",
              "codex.index": "📚 Codex — index building",
              "claude_code.verify": "✅ Claude Code — index verification",
              "codex.schedule": "⏰ Codex — schedule parsing",
              "codex.configure": "⚙️ Codex — configuration update",
              "codex.analyze": "🔍 Codex — attachment analysis",
              "claude_code.implement": "⚙️ Claude Code — implementation",
              "vscode.open": "🚀 VS Code — handoff (Claude Fable 5)"}
    emp = db.get(VirtualEmployee, run.employee_id) if run.employee_id else None
    return {
        "id": run.id, "status": run.status, "prompt": run.prompt,
        "result": run.result, "error": run.error,
        "employee": emp.full_name if emp else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "stages": [{
            "tool": c.tool,
            "label": labels.get(c.tool, c.tool),
            "status": c.status,
            "arguments": c.arguments,
            "result": c.result,
            "started_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        } for c in calls],
    }


# ==================== Approvals ====================
@app.get("/api/approvals")
def list_approvals(user: User = Depends(current_user), db: Session = Depends(get_db)):
    own = _owned_company_ids(db, user)
    rows = (db.query(ApprovalRequest)
            .filter((ApprovalRequest.company_id.in_(own)) |
                    (ApprovalRequest.company_id.is_(None) if user.is_admin else False))
            .order_by(ApprovalRequest.created_at.desc()).limit(200).all())
    out = []
    for a in rows:
        extra = {}
        if a.kind == "send_email" and a.payload_ref:
            draft = db.get(EmailDraft, a.payload_ref)
            if draft:
                ident = db.get(EmailIdentity, draft.identity_id)
                extra["draft"] = _d(draft, {"from_address": ident.email_address if ident else "?"})
        out.append(_d(a, extra))
    return out


@app.post("/api/approvals/{aid}/approve")
def approve(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(ApprovalRequest, aid)
    if not a or a.status != "pending":
        raise HTTPException(400, "Approval not pending")
    if a.company_id:
        require_company(db, a.company_id, user)  # per-user isolation
    elif not user.is_admin:
        raise HTTPException(404, "Approval not found")
    a.status = "approved"
    a.decided_by = user.id
    a.decided_at = dt.datetime.utcnow()
    db.commit()
    audit(db, "approval.approved", a.summary, company_id=a.company_id, user_id=user.id)
    if a.kind == "send_email":
        return execute_approved_email(db, a, user.id)
    a.status = "executed"
    db.commit()
    return {"ok": True}


@app.post("/api/approvals/{aid}/reject")
def reject(aid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(ApprovalRequest, aid)
    if not a or a.status != "pending":
        raise HTTPException(400, "Approval not pending")
    if a.company_id:
        require_company(db, a.company_id, user)  # per-user isolation
    elif not user.is_admin:
        raise HTTPException(404, "Approval not found")
    a.status = "rejected"
    a.decided_by = user.id
    a.decided_at = dt.datetime.utcnow()
    if a.kind == "send_email" and a.payload_ref:
        draft = db.get(EmailDraft, a.payload_ref)
        if draft:
            draft.status = "cancelled"
    db.commit()
    audit(db, "approval.rejected", a.summary, company_id=a.company_id, user_id=user.id)
    return {"ok": True}


# ==================== Dashboard / audit / misc ====================
@app.get("/api/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Per-user dashboard — every number is scoped to the user's own data."""
    own = _owned_company_ids(db, user)
    own_chats = [r[0] for r in db.query(Chat.id)
                 .filter(Chat.deleted_at.is_(None), Chat.owner_user_id == user.id).all()]
    runs_q = db.query(AgentRun).filter(
        (AgentRun.company_id.in_(own)) | (AgentRun.chat_id.in_(own_chats)))
    return {
        "companies": len(own),
        "employees": db.query(VirtualEmployee).filter(
            VirtualEmployee.deleted_at.is_(None), VirtualEmployee.company_id.in_(own)).count(),
        "projects": db.query(Project).filter(
            Project.deleted_at.is_(None), Project.company_id.in_(own)).count(),
        "open_tasks": db.query(Task).filter(
            Task.deleted_at.is_(None), Task.company_id.in_(own),
            Task.status.notin_(["Completed", "Cancelled"])).count(),
        "pending_approvals": db.query(ApprovalRequest).filter(
            ApprovalRequest.status == "pending", ApprovalRequest.company_id.in_(own)).count(),
        "recent_runs": [_d(r) for r in runs_q.order_by(AgentRun.created_at.desc()).limit(8)],
        "failed_runs": runs_q.filter(AgentRun.status == "error").count(),
        "codex_available": CodexProvider().available,
    }


@app.get("/api/audit")
def audit_log(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    rows = db.query(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(300).all()
    return [_d(a) for a in rows]


@app.get("/api/runs")
def runs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(100).all()
    return [_d(r) for r in rows]


@app.get("/api/permissions")
def permissions(user: User = Depends(current_user)):
    return PERMISSIONS


# ==================== Skills ====================
from .db import Skill  # noqa: E402


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    instructions: str = Field(min_length=1)  # unlimited length
    target: str = "both"  # codex | claude | both
    enabled: bool = True


def _own_skill(db: Session, sid: str, user: User) -> Skill:
    s = db.get(Skill, sid)
    if not s or s.deleted_at:
        raise HTTPException(404, "Skill not found")
    if not user.is_admin and s.owner_user_id != user.id:
        raise HTTPException(404, "Skill not found")  # don't reveal others' skills
    return s


@app.get("/api/skills")
def list_skills(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(Skill).filter(Skill.deleted_at.is_(None))
    if not user.is_admin:
        q = q.filter(Skill.owner_user_id == user.id)  # users see only their own
    return [_d(s) for s in q.order_by(Skill.created_at).all()]


@app.post("/api/skills")
def create_skill(body: SkillIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.target not in ("codex", "claude", "both"):
        raise HTTPException(422, "target must be codex, claude or both")
    s = Skill(**body.model_dump(), owner_user_id=user.id)
    db.add(s)
    db.commit()
    audit(db, "skill.create", s.name, user_id=user.id)
    return _d(s)


@app.put("/api/skills/{sid}")
def update_skill(sid: str, body: SkillIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _own_skill(db, sid, user)
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    db.commit()
    audit(db, "skill.update", s.name, user_id=user.id)
    return _d(s)


@app.delete("/api/skills/{sid}")
def delete_skill(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        s = _own_skill(db, sid, user)
    except HTTPException:
        return {"ok": True}
    s.deleted_at = dt.datetime.utcnow()
    db.commit()
    audit(db, "skill.delete", s.name, user_id=user.id)
    return {"ok": True}


# -------- SkillScript BASIC (plugin/scripting framework) --------
from . import skillscript  # noqa: E402


class ScriptIn(BaseModel):
    code: str = Field(min_length=1, max_length=20000)
    context: dict = {}


@app.get("/api/skillscript/reference")
def skillscript_reference(user: User = Depends(current_user)):
    return {"reference": skillscript.language_reference()}


@app.post("/api/skillscript/validate")
def skillscript_validate(body: ScriptIn, user: User = Depends(current_user)):
    return skillscript.validate(body.code)


@app.post("/api/skillscript/run")
def skillscript_run(body: ScriptIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Test-run a SkillScript program in the sandbox (AI/email effects
    enabled; limits: 20k steps / 120 s / 5 AI calls)."""
    ctx = dict(body.context or {})
    ctx.setdefault("user_input", ctx.get("USER_INPUT", ""))
    result = skillscript.run_script(body.code, context=ctx, allow_effects=True)
    audit(db, "skillscript.run", result.get("name", "?"), user_id=user.id)
    return result


# ==================== Uploads ====================
from fastapi import UploadFile, File  # noqa: E402

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_UPLOAD_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
                       ".txt", ".md", ".pdf", ".csv", ".json", ".docx", ".xlsx"}
MAX_UPLOAD = 25 * 1024 * 1024  # 25 MB


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...), user: User = Depends(current_user)):
    import uuid as _uuid
    ext = Path(file.filename or "file").suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTS:
        raise HTTPException(422, f"File type {ext or '(none)'} not allowed")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 25 MB)")
    safe_name = f"{_uuid.uuid4().hex[:8]}_{Path(file.filename).stem[:60]}{ext}"
    dest = UPLOAD_DIR / safe_name
    dest.write_bytes(data)
    is_image = ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    return {"path": str(dest), "name": file.filename, "is_image": is_image, "size": len(data)}


# ==================== Serial-number OCR (server-side) ====================
_rapidocr_engine = None

# ==================== HTTPS listener (mobile kiosk camera access) ==========
# iPhone / Android browsers BLOCK camera access (navigator.mediaDevices is
# removed) on insecure HTTP origins. A parallel HTTPS listener on port 8443
# with an auto-generated self-signed certificate makes the station/kiosk page
# camera-capable on phones: https://<server>:8443/?station=…
HTTPS_PORT = 8443
try:
    from .config import get_config as _https_cfg
    HTTPS_PORT = int((_https_cfg() or {}).get("https_port", 8443))
except Exception:  # pragma: no cover
    pass
_CERT_DIR = Path(__file__).resolve().parent.parent / "data" / "certs"


def _ensure_self_signed_cert() -> tuple[str, str] | None:
    """Create (once) and return (certfile, keyfile) for the LAN HTTPS listener."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import datetime as _dt
        import ipaddress as _ipa
        _CERT_DIR.mkdir(parents=True, exist_ok=True)
        crt, key = _CERT_DIR / "nexacrew.crt", _CERT_DIR / "nexacrew.key"
        if crt.is_file() and key.is_file():
            return str(crt), str(key)
        pk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "NexaCrew Server")])
        sans: list[x509.GeneralName] = [x509.DNSName("localhost")]
        try:
            import socket as _sk
            sans.append(x509.DNSName(_sk.gethostname()))
            for info in _sk.getaddrinfo(_sk.gethostname(), None, _sk.AF_INET):
                try: sans.append(x509.IPAddress(_ipa.ip_address(info[4][0])))
                except ValueError: pass
        except OSError:
            pass
        sans.append(x509.IPAddress(_ipa.ip_address("127.0.0.1")))
        cert = (x509.CertificateBuilder()
                .subject_name(name).issuer_name(name)
                .public_key(pk.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(_dt.datetime.utcnow() - _dt.timedelta(days=1))
                .not_valid_after(_dt.datetime.utcnow() + _dt.timedelta(days=3650))
                .add_extension(x509.SubjectAlternativeName(sans), critical=False)
                .sign(pk, hashes.SHA256()))
        key.write_bytes(pk.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return str(crt), str(key)
    except Exception:  # pragma: no cover — cryptography missing/locked dir
        return None


def _start_https_listener() -> None:
    """Serve the SAME app over HTTPS on HTTPS_PORT in a background thread."""
    pair = _ensure_self_signed_cert()
    if not pair:
        return
    try:
        import uvicorn as _uv

        def _run() -> None:
            import time as _t
            _t.sleep(3)   # let the module finish loading all routes first
            try:
                cfg = _uv.Config(app, host="0.0.0.0", port=HTTPS_PORT,
                                 ssl_certfile=pair[0], ssl_keyfile=pair[1],
                                 log_level="warning")
                srv = _uv.Server(cfg)
                # uvicorn installs POSIX signal handlers, which raises
                # "signal only works in main thread" inside a thread — skip them
                srv.install_signal_handlers = lambda: None  # type: ignore[method-assign]
                import asyncio as _aio
                _log = logging.getLogger("https_listener")

                def _quiet_handler(loop, context) -> None:
                    """Benign TLS/TCP disconnects (phones dropping the socket,
                    self-signed-cert handshake aborts) are ROUTINE on a LAN
                    kiosk listener — log at DEBUG, never dump tracebacks to
                    the operations console. Everything else is logged with
                    context at ERROR."""
                    exc = context.get("exception")
                    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                                        BrokenPipeError, TimeoutError)) or (
                            exc is not None and "ssl" in type(exc).__module__):
                        _log.debug("client connection dropped (normal): %s", exc)
                        return
                    _log.error("https listener loop error: %s (%s)",
                               context.get("message"), exc)

                loop = _aio.new_event_loop()
                _aio.set_event_loop(loop)
                loop.set_exception_handler(_quiet_handler)
                try:
                    loop.run_until_complete(srv.serve())
                finally:
                    loop.close()
            except Exception as e:  # pragma: no cover
                logging.getLogger("https_listener").error(
                    "listener on :%s failed: %s — phones cannot use the camera "
                    "until the port is free and cryptography is installed",
                    HTTPS_PORT, e)

        threading.Thread(target=_run, daemon=True, name="https-8443").start()
    except Exception:  # pragma: no cover
        pass


_start_https_listener()

# ---- browser OCR engine (Tesseract.js) — self-hosted so clients load it
# from THIS server / their own install instead of the internet CDN. The files
# are fetched once at startup, live inside platform/static (therefore they are
# ALSO packed into every client program package and every update), and the
# browser caches them after the first use.
_OCR_VENDOR = STATIC_DIR / "vendor" / "tesseract"
_OCR_ASSETS = {
    "tesseract.min.js": "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js",
    "worker.min.js": "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/worker.min.js",
    # ALL FOUR core variants — the worker picks one at runtime depending on
    # browser capabilities (SIMD support) and requested engine (lstm/full)
    "tesseract-core.wasm.js": "https://cdn.jsdelivr.net/npm/tesseract.js-core@5/tesseract-core.wasm.js",
    "tesseract-core-simd.wasm.js": "https://cdn.jsdelivr.net/npm/tesseract.js-core@5/tesseract-core-simd.wasm.js",
    "tesseract-core-lstm.wasm.js": "https://cdn.jsdelivr.net/npm/tesseract.js-core@5/tesseract-core-lstm.wasm.js",
    "tesseract-core-simd-lstm.wasm.js": "https://cdn.jsdelivr.net/npm/tesseract.js-core@5/tesseract-core-simd-lstm.wasm.js",
    "eng.traineddata.gz": "https://tessdata.projectnaptha.com/4.0.0/eng.traineddata.gz",
}


def _ensure_ocr_assets() -> None:
    """Download the browser OCR engine once so every client gets it from the
    LAN (fast) and offline installs still work. Silent no-op when offline —
    the frontend falls back to the CDN in that case."""
    import urllib.request
    _OCR_VENDOR.mkdir(parents=True, exist_ok=True)
    for name, url in _OCR_ASSETS.items():
        dest = _OCR_VENDOR / name
        if dest.is_file() and dest.stat().st_size > 10000:
            continue
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
            if len(data) > 10000:
                dest.write_bytes(data)
        except Exception:  # noqa: BLE001 — offline; frontend uses CDN fallback
            pass


threading.Thread(target=_ensure_ocr_assets, daemon=True).start()


@app.get("/api/ocr-assets-status")
def ocr_assets_status():
    """Which OCR engine files are hosted locally (frontend prefers these)."""
    return {n: (_OCR_VENDOR / n).is_file() and (_OCR_VENDOR / n).stat().st_size > 10000
            for n in _OCR_ASSETS}


def _get_rapidocr():
    """Lazy-load the RapidOCR engine (onnxruntime based, no external binary)."""
    global _rapidocr_engine
    if _rapidocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR
        _rapidocr_engine = RapidOCR()
    return _rapidocr_engine


_SN_RE = __import__("re").compile(
    r"\b[S5]N\s*[:.;,\-]?\s*([A-Z0-9][A-Z0-9\-. ]{5,32})", __import__("re").I)


def _extract_serial_py(text: str) -> str:
    """Pull the serial out of OCR text — 'SN:XXXX' from the ALT+V screen."""
    raw = text.replace("|", "I")
    m = _SN_RE.search(raw)
    if m:
        sn = __import__("re").sub(r"[\s\-.]+", "", m.group(1)).upper()
        if 8 <= len(sn) <= 22 and any(c.isalpha() for c in sn) \
                and sum(c.isdigit() for c in sn) >= 2:
            return sn
    # fallback: best letters+digits token
    best = ""
    for tk in __import__("re").findall(r"\b[A-Z0-9\-]{8,22}\b", raw.upper()):
        tk = tk.replace("-", "")
        if any(c.isalpha() for c in tk) and sum(c.isdigit() for c in tk) >= 2 \
                and len(tk) > len(best):
            best = tk
    return best


@app.post("/api/business/ocr-serial")
async def ocr_serial(file: UploadFile = File(...), user: User = Depends(current_user),
                     db: Session = Depends(get_db)):
    """Receive a webcam frame, OCR it server-side and return the serial after 'SN:'."""
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Image too large")
    import io as _io
    import numpy as _np
    from PIL import Image as _Image
    try:
        img = _Image.open(_io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(422, "Not a readable image")
    # upscale small frames — OCR quality improves markedly
    if img.width < 1600:
        r = 1600 / img.width
        img = img.resize((1600, int(img.height * r)), _Image.LANCZOS)
    try:
        engine = _get_rapidocr()
        result, _ = engine(_np.array(img))
    except Exception as e:                                    # pragma: no cover
        raise HTTPException(503, f"OCR engine unavailable: {e}")
    text = "\n".join(seg[1] for seg in (result or []))
    serial = _extract_serial_py(text)
    audit(db, "business.ocr.serial", serial or "(none)", user_id=user.id)
    return {"serial": serial, "text": text[:500]}


# ==================== Operator face capture (action attribution) ====================
# Every operations action starts with a webcam face capture. The server
# verifies a real human face is present (OpenCV/dlib pipeline in face_recog),
# stores the image, and the face id is chained into the tamper-evident audit
# log for that action — so every record is traceable to the person who was
# physically at the workstation, not just the logged-in account.
from . import face_recog as face_mod  # noqa: E402

OP_FACE_DIR = UPLOAD_DIR / "op_faces"
OP_FACE_DIR.mkdir(parents=True, exist_ok=True)


@app.post("/api/auth/face-presence")
def face_presence(body: dict, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Post-login camera watchdog: verify the signed-in worker's face is
    visible. Stores nothing; audits only on a blocked→visible transition
    signalled by the client (alert=true) to keep the log noise-free."""
    data_uri = str(body.get("image") or "")
    if not data_uri.startswith("data:image/") or len(data_uri) > 8 * 1024 * 1024:
        raise HTTPException(422, "image must be a data URI")
    try:
        ok = face_mod.has_face(data_uri)
    except Exception:                                    # noqa: BLE001
        ok = True          # vision stack unavailable → do not nag the worker
    if not ok and bool(body.get("alert")):
        audit(db, "auth.camera_blocked",
              "no face visible at the signed-in workstation", user_id=user.id)
    return {"face": bool(ok)}


@app.post("/api/business/face-capture")
async def business_face_capture(body: dict, user: User = Depends(current_user),
                                db: Session = Depends(get_db)):
    """Verify a webcam frame contains a real human face and store it.
    Returns {ok, face_id} or {ok: False, reason}."""
    data_uri = body.get("image") or ""
    if not data_uri.startswith("data:image/"):
        raise HTTPException(422, "image must be a data URI")
    if len(data_uri) > 8 * 1024 * 1024:
        raise HTTPException(413, "Image too large")
    # human-face presence check (Haar + dlib ladder). If the vision libraries
    # are missing we fail CLOSED — attribution is a security control.
    try:
        ok = face_mod.has_face(data_uri)
    except Exception:
        ok = False
    if not ok:
        audit(db, "business.face.rejected", "no human face in frame", user_id=user.id)
        return {"ok": False, "reason": "no_face"}
    import base64 as _b64
    import uuid as _uuid
    raw = _b64.b64decode(data_uri.split(",", 1)[1])
    face_id = f"{_dt_now_stamp()}_{user.username}_{_uuid.uuid4().hex[:6]}.jpg"
    (OP_FACE_DIR / face_id).write_bytes(raw)
    audit(db, "business.face.capture", face_id, user_id=user.id)
    return {"ok": True, "face_id": face_id}


def _dt_now_stamp() -> str:
    import datetime as _dt
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S")


@app.get("/api/business/face-image/{face_id}")
def business_face_image(face_id: str, user: User = Depends(current_user)):
    import re as _re2
    if not _re2.fullmatch(r"[A-Za-z0-9_.\-]+\.jpg", face_id):
        raise HTTPException(422, "bad id")
    # admins can inspect any capture; workers can view their own only
    if not user.is_admin and f"_{user.username}_" not in face_id:
        raise HTTPException(403, "Not permitted")
    p = OP_FACE_DIR / face_id
    if not p.exists():
        raise HTTPException(404, "not found")
    from fastapi.responses import Response
    return Response(p.read_bytes(), media_type="image/jpeg")


_FACE_IN_DETAIL = __import__("re").compile(r"face=([A-Za-z0-9_.\-]+\.jpg|NONE)")


def _oplog_row(ev, users_by_id: dict) -> dict:
    detail = ev.detail or ""
    m = _FACE_IN_DETAIL.search(detail)
    face = m.group(1) if m and m.group(1) != "NONE" else ""
    module = detail.split(" face=")[0].strip() if "face=" in detail else detail.strip()
    # value payload — what the operator actually entered / changed / removed
    values = ""
    vm = __import__("re").search(r"\b(values=|changes=\[|deleted_values=)", detail)
    if vm:
        values = detail[vm.start():].strip()
        module = detail[:vm.start()].split(" face=")[0].strip()
    # chat-driven events carry the register in the action name: business.<mod>.<op>
    am = __import__("re").match(r"business\.([a-z_]+)\.(create|update|delete|status)$", ev.action or "")
    if am and am.group(1) not in ("record", "face", "ocr", "doc", "prompt"):
        module = am.group(1)
    u = users_by_id.get(ev.user_id)
    from .tz import to_local as _to_local
    _ca = ""
    if ev.created_at:
        _lt = _to_local(ev.created_at)
        _ca = _lt.strftime("%Y-%m-%d %H:%M:%S ") + (_lt.tzname() or "PT")
    return {
        "id": ev.id, "action": ev.action, "module": module, "face": face,
        "detail": detail, "values": values[:2000],
        "user": (u.display_name or u.username) if u else "—",
        "username": u.username if u else "", "created_at": _ca,
        "entry_hash": (ev.entry_hash or "")[:12],
    }


@app.get("/api/business/oplog")
def business_oplog(module: str = "", limit: int = 0,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Operations audit log — every business.* action with the operator's
    captured face image id. Admins see all users; workers see their own.
    limit=0 (default) returns the complete log — ISO 9001 §7.5.3 requires the
    full retained record to be retrievable, not a truncated window."""
    q = db.query(AuditEvent).filter(AuditEvent.action.like("business.%"))
    if not user.is_admin:
        q = q.filter(AuditEvent.user_id == user.id)
    q = q.order_by(AuditEvent.created_at.desc())
    if limit > 0:
        q = q.limit(min(limit, 100000))
    rows = q.all()
    users_by_id = {u.id: u for u in db.query(User).all()}
    out = [_oplog_row(ev, users_by_id) for ev in rows]
    if module:
        out = [r for r in out if r["module"].split(" ")[0] == module]
    return out


# ==================== Inventory / facility map (WMS-grade) ====================
from .db import WarehouseMap  # noqa: E402


@app.get("/api/business/maps")
def maps_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(WarehouseMap).filter(WarehouseMap.user_id == user.id,
                                          WarehouseMap.status == "active")
            .order_by(WarehouseMap.warehouse, WarehouseMap.zone).all())
    return [{"id": m.id, "warehouse": m.warehouse, "zone": m.zone,
             "updated_at": str(m.updated_at or m.created_at or "")} for m in rows]


@app.get("/api/business/maps/{map_id}")
def maps_get(map_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.query(WarehouseMap).filter(WarehouseMap.id == map_id,
                                      WarehouseMap.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    return {"id": m.id, "warehouse": m.warehouse, "zone": m.zone, "data": m.data or "{}"}


@app.post("/api/business/maps")
def maps_create(payload: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    wh = (payload.get("warehouse") or "Warehouse 1").strip()[:80]
    zn = (payload.get("zone") or "Zone A").strip()[:80]
    m = WarehouseMap(user_id=user.id, warehouse=wh, zone=zn,
                     data=payload.get("data") or "{}")
    db.add(m)
    db.commit()
    audit(db, "business.invmap.create",
          f"values={{\"warehouse\": \"{wh}\", \"zone\": \"{zn}\"}}", user_id=user.id)
    return {"id": m.id, "warehouse": m.warehouse, "zone": m.zone}


@app.put("/api/business/maps/{map_id}")
def maps_update(map_id: str, payload: dict,
                user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.query(WarehouseMap).filter(WarehouseMap.id == map_id,
                                      WarehouseMap.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    changed = []
    if "warehouse" in payload and payload["warehouse"].strip():
        if m.warehouse != payload["warehouse"].strip()[:80]:
            changed.append(f"warehouse: '{m.warehouse}' → '{payload['warehouse'].strip()[:80]}'")
        m.warehouse = payload["warehouse"].strip()[:80]
    if "zone" in payload and payload["zone"].strip():
        if m.zone != payload["zone"].strip()[:80]:
            changed.append(f"zone: '{m.zone}' → '{payload['zone'].strip()[:80]}'")
        m.zone = payload["zone"].strip()[:80]
    if "data" in payload:
        import json as _json
        try:
            n_el = len((_json.loads(payload["data"]) or {}).get("elements") or [])
            changed.append(f"layout: {n_el} element(s)")
        except Exception:
            changed.append("layout updated")
        m.data = payload["data"]
    db.commit()
    audit(db, "business.invmap.update",
          f"map='{m.warehouse}/{m.zone}' changes[{'; '.join(changed) or 'none'}]",
          user_id=user.id)
    return {"ok": True}


@app.delete("/api/business/maps/{map_id}")
def maps_delete(map_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    m = db.query(WarehouseMap).filter(WarehouseMap.id == map_id,
                                      WarehouseMap.user_id == user.id).first()
    if not m:
        raise HTTPException(404, "Map not found")
    audit(db, "business.invmap.delete",
          f"deleted_values={{\"warehouse\": \"{m.warehouse}\", \"zone\": \"{m.zone}\"}}",
          user_id=user.id)
    db.delete(m)
    db.commit()
    return {"ok": True}


# ==================== Business profile (personal vs commercial) ====================
from . import business as business_mod  # noqa: E402
from .db import BusinessProfile, BusinessRecord  # noqa: E402


def _get_bp(db: Session, user: User) -> BusinessProfile:
    bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == user.id).first()
    if not bp:
        bp = BusinessProfile(user_id=user.id)
        db.add(bp)
        db.commit()
        db.refresh(bp)
    return bp


def _biz_uid(db: Session, user: User) -> str:
    """Shared-tenant id: workers (non-admin, no own commercial profile)
    operate on the company owner's workspace and records."""
    return business_mod.biz_owner_id(db, user.id)


def _get_owner_bp(db: Session, user: User) -> BusinessProfile:
    """BusinessProfile of the shared tenant (falls back to the user's own)."""
    oid = _biz_uid(db, user)
    if oid != user.id:
        bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == oid).first()
        if bp:
            return bp
    return _get_bp(db, user)


def _commercial_company_count(db: Session) -> int:
    return (db.query(BusinessProfile)
            .filter(BusinessProfile.usage_mode == "commercial").count())


def _license_valid(db: Session, bp: BusinessProfile) -> bool:
    """A company's license is valid when a non-revoked LicenseKey is bound."""
    key = (getattr(bp, "license_key", "") or "").strip()
    if not key:
        return False
    row = db.query(LicenseKey).filter(LicenseKey.key == key,
                                      LicenseKey.revoked.is_(False)).first()
    return row is not None


def _license_required(db: Session, bp: BusinessProfile) -> bool:
    """Per-company licensing is ENFORCED when the server hosts more than one
    commercial company — each company must then hold its own license key.
    Single-company servers are grandfathered (no key required)."""
    if bp.usage_mode != "commercial":
        return False
    return _commercial_company_count(db) > 1 and not _license_valid(db, bp)


def _bp_d(bp: BusinessProfile) -> dict:
    try:
        docs = json.loads(bp.docs or "[]")
    except Exception:
        docs = []
    return {"usage_mode": bp.usage_mode or "personal",
            "company_type": bp.company_type or "", "custom_type": bp.custom_type or "",
            "company_name": bp.company_name or "", "company_desc": bp.company_desc or "",
            "generated_prompt": bp.generated_prompt or "",
            "prompt_status": bp.prompt_status or "", "docs": docs,
            "docs_chars": len(bp.docs_text or "")}


@app.get("/api/business/types")
def business_types(user: User = Depends(current_user)):
    return [{"key": k, "label": v["label"], "icon": v["icon"],
             "modules": [{"key": m["key"], "name": m["name"], "iso": m["iso"]}
                         for m in v["modules"]]}
            for k, v in business_mod.INDUSTRY_TEMPLATES.items()]


@app.get("/api/business/profile")
def business_profile(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _bp_d(_get_bp(db, user))


@app.put("/api/business/profile")
def business_profile_update(body: dict, user: User = Depends(current_user),
                            db: Session = Depends(get_db)):
    bp = _get_bp(db, user)
    mode = (body.get("usage_mode") or bp.usage_mode or "personal").strip()
    if mode not in ("personal", "commercial"):
        raise HTTPException(422, "usage_mode must be personal or commercial")
    ctype = (body.get("company_type") or "").strip()
    if mode == "commercial" and ctype and ctype != "custom" \
            and ctype not in business_mod.INDUSTRY_TEMPLATES:
        raise HTTPException(422, "Unknown company type")
    bp.usage_mode = mode
    bp.company_type = ctype
    bp.custom_type = (body.get("custom_type") or "")[:120]
    bp.company_name = (body.get("company_name") or "")[:200]
    bp.company_desc = (body.get("company_desc") or "")[:4000]
    audit(db, "business.profile.update", f"mode={mode} type={ctype or bp.custom_type}",
          user_id=user.id)
    db.commit()
    return _bp_d(bp)


@app.post("/api/business/generate")
async def business_generate(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Generate the professional company instruction prompt with AI (Codex CLI);
    falls back to a deterministic ISO-aligned template if no CLI is available."""
    bp = _get_bp(db, user)
    if bp.usage_mode != "commercial":
        raise HTTPException(422, "Set usage mode to commercial first")
    if not bp.company_type and not bp.custom_type:
        raise HTTPException(422, "Choose a company type first")
    bp.prompt_status = "generating"
    db.commit()
    from . import services as _svc
    prompt = business_mod.generation_prompt(bp, bp.docs_text or "")

    def _gen() -> str:
        prov = getattr(_svc, "_agent_provider", None)
        if prov is not None and getattr(prov, "available", False):
            out = (prov.run(prompt) or "").strip()
            if len(out) > 100:
                return out
        return business_mod.fallback_prompt(bp)

    try:
        from starlette.concurrency import run_in_threadpool
        text = await run_in_threadpool(_gen)
        bp.generated_prompt = text[:20000]
        bp.prompt_status = "ready"
    except Exception as e:  # noqa: BLE001
        bp.prompt_status = "error"
        db.commit()
        raise HTTPException(502, f"Prompt generation failed: {e}")
    audit(db, "business.prompt.generate",
          f"type={bp.company_type or bp.custom_type} chars={len(bp.generated_prompt)}",
          user_id=user.id)
    db.commit()
    return _bp_d(bp)


@app.put("/api/business/prompt")
def business_prompt_edit(body: dict, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Manual review/edit of the generated instruction prompt."""
    bp = _get_bp(db, user)
    bp.generated_prompt = (body.get("prompt") or "")[:20000]
    bp.prompt_status = "ready" if bp.generated_prompt.strip() else ""
    db.commit()
    return _bp_d(bp)


def _extract_doc_text(name: str, data: bytes) -> str:
    ext = Path(name or "doc").suffix.lower()
    if ext in (".txt", ".md", ".csv", ".json"):
        return data.decode("utf-8", errors="replace")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
            import io
            r = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in r.pages)
        except Exception:
            return ""
    if ext == ".docx":
        try:
            import io
            import zipfile
            import re as _re
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            xml = _re.sub(r"</w:p>", "\n", xml)
            return _re.sub(r"<[^>]+>", "", xml)
        except Exception:
            return ""
    return ""


@app.post("/api/business/docs")
async def business_doc_upload(file: UploadFile = File(...),
                              user: User = Depends(current_user),
                              db: Session = Depends(get_db)):
    """Upload an SOP handbook / ISO document; its text is learned into the
    company corpus and used when (re)generating the instruction prompt."""
    ext = Path(file.filename or "doc").suffix.lower()
    if ext not in (".txt", ".md", ".pdf", ".docx", ".csv", ".json"):
        raise HTTPException(422, f"Unsupported document type {ext or '(none)'}")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 25 MB)")
    from starlette.concurrency import run_in_threadpool
    text = await run_in_threadpool(_extract_doc_text, file.filename or "doc", data)
    text = (text or "").strip()
    if not text:
        raise HTTPException(422, "Could not extract any text from this document")
    bp = _get_bp(db, user)
    try:
        docs = json.loads(bp.docs or "[]")
    except Exception:
        docs = []
    docs.append({"name": file.filename, "size": len(data), "chars": len(text),
                 "at": dt.datetime.utcnow().isoformat() + "Z"})
    bp.docs = json.dumps(docs)
    corpus = (bp.docs_text or "")
    corpus += f"\n\n===== DOCUMENT: {file.filename} =====\n{text}"
    bp.docs_text = corpus[-200000:]  # keep the newest 200k chars
    audit(db, "business.doc.upload", f"{file.filename} ({len(text)} chars)", user_id=user.id)
    db.commit()
    return _bp_d(bp)


@app.delete("/api/business/docs/{idx}")
def business_doc_delete(idx: int, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    bp = _get_bp(db, user)
    try:
        docs = json.loads(bp.docs or "[]")
    except Exception:
        docs = []
    if not 0 <= idx < len(docs):
        raise HTTPException(404, "Document not found")
    name = docs[idx].get("name", "")
    docs.pop(idx)
    bp.docs = json.dumps(docs)
    if name:
        # remove that document's section from the corpus
        marker = f"===== DOCUMENT: {name} ====="
        parts = (bp.docs_text or "").split("\n\n===== DOCUMENT: ")
        kept = [p for p in parts if not ("DOCUMENT: " + p).startswith("DOCUMENT: " + name + " =====")
                and not p.startswith(name + " =====")]
        bp.docs_text = "\n\n===== DOCUMENT: ".join(kept) if kept else ""
        _ = marker
    audit(db, "business.doc.delete", name, user_id=user.id)
    db.commit()
    return _bp_d(bp)


@app.get("/api/business/workspace")
def business_workspace(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Industry workspace descriptor: label + module schemas + record counts."""
    bp = _get_owner_bp(db, user)
    if bp.usage_mode != "commercial":
        return {"active": False}
    if _license_required(db, bp):
        return {"active": False, "license_required": True,
                "company_name": bp.company_name or "",
                "is_owner": bp.user_id == user.id}
    oid = bp.user_id
    mods = business_mod.modules_for(bp.company_type, oid)
    counts: dict[str, int] = {}
    open_counts: dict[str, int] = {}
    for r in db.query(BusinessRecord.module, BusinessRecord.status) \
               .filter(BusinessRecord.user_id == oid).all():
        counts[r[0]] = counts.get(r[0], 0) + 1
        if r[1] == "open":
            open_counts[r[0]] = open_counts.get(r[0], 0) + 1
    t = business_mod.INDUSTRY_TEMPLATES.get(bp.company_type)
    from . import ops_package as opk_mod
    pkg = opk_mod.load_package(oid)
    return {"active": True,
            "label": business_mod.template_label(bp.company_type, bp.custom_type),
            "icon": (t or {}).get("icon", "🏢"),
            "company_name": bp.company_name or "",
            "prompt_ready": bp.prompt_status == "ready",
            "license": {"bound": bool((getattr(bp, "license_key", "") or "").strip()),
                        "valid": _license_valid(db, bp),
                        "enforced": _commercial_company_count(db) > 1},
            "ops_package": ({"name": pkg["name"], "version": pkg["version"],
                             "modules": len(pkg["modules"])} if pkg else None),
            "modules": [dict(m, count=counts.get(m["key"], 0),
                             open=open_counts.get(m["key"], 0)) for m in mods]}


@app.get("/api/business/companies")
def business_companies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Admin — all commercial companies hosted on this server (multi-tenant).
    Used by HR Employee Enrollment to bind a worker to their company."""
    require_admin(user)
    rows = (db.query(BusinessProfile)
            .filter(BusinessProfile.usage_mode == "commercial")
            .order_by(BusinessProfile.created_at).all())
    return [{"owner_id": b.user_id,
             "company_name": b.company_name or "(unnamed company)",
             "licensed": _license_valid(db, b),
             "mine": b.user_id == _biz_uid(db, user)} for b in rows]


@app.post("/api/business/act-as")
def business_act_as(body: dict, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Admin — switch the acting company workspace. Every company deployed on
    this server can be inspected/operated by an administrator; the binding is
    stored on the admin's own account ('' returns to the admin's own tenant).
    Non-admin workers cannot switch — their binding is set in User Management
    or at HR enrollment."""
    require_admin(user)
    oid = _validate_company_binding(db, str(body.get("owner_id") or ""))
    me = db.get(User, user.id)
    prev = me.company_owner_id or ""
    me.company_owner_id = oid
    db.commit()
    audit(db, "business.act_as", f"company: '{prev or 'own'}' → '{oid or 'own'}'", user_id=user.id)
    return {"ok": True, "acting_company_owner_id": oid}


@app.post("/api/business/license")
def business_license_bind(body: dict, user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Admin — bind a license key to THIS company. Keys are generated in
    Administration ▸ Licenses; one key licenses exactly one company."""
    require_admin(user)
    key = str(body.get("key") or "").strip()
    if not key or len(key) > 200:
        raise HTTPException(422, "License key is required")
    row = db.query(LicenseKey).filter(LicenseKey.key == key).first()
    if not row or row.revoked:
        raise HTTPException(400, "Unknown or revoked license key — generate one "
                                 "under Administration ▸ Licenses")
    other = (db.query(BusinessProfile)
             .filter(BusinessProfile.license_key == key,
                     BusinessProfile.user_id != _biz_uid(db, user)).first())
    if other:
        raise HTTPException(409, "This key already licenses another company — "
                                 "each company needs its own key")
    bp = _get_owner_bp(db, user)
    bp.license_key = key
    audit(db, "business.license.bind",
          f"company='{bp.company_name}' key=…{key[-6:]}", user_id=user.id)
    db.commit()
    return {"ok": True, "valid": True}


@app.get("/api/business/ops-package")
def ops_package_get(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Operations Studio — the installed package (or the built-in template
    exported as an editable starter). Operations are distributable JSON
    packages so this platform fits ANY company, not one hard-coded firm."""
    require_admin(user)
    from . import ops_package as opk_mod
    bp = _get_bp(db, user)
    pkg = opk_mod.load_package(user.id)
    company = (bp.company_name or bp.custom_type or "Company").strip()
    starter = opk_mod.builtin_as_package(bp.company_type, company,
                                         bp.generated_prompt or "")
    return {"installed": pkg is not None,
            "package": pkg or starter or {"schema": opk_mod.SCHEMA_VERSION,
                                          "name": company.upper() + " BUILD",
                                          "version": "1.0.0",
                                          "chat_prompt": bp.generated_prompt or "",
                                          "modules": []},
            "builtin_label": business_mod.template_label(bp.company_type,
                                                         bp.custom_type),
            "limits": {"max_modules": opk_mod.MAX_MODULES,
                       "max_fields": opk_mod.MAX_FIELDS,
                       "max_kb": opk_mod.MAX_PACKAGE_BYTES // 1024}}


@app.post("/api/business/ops-package")
def ops_package_install(body: dict, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Install / replace this company's Operations Package (validated,
    audited, atomic). Historical records of removed modules are RETAINED —
    they reappear if the module key returns."""
    require_admin(user)
    from . import ops_package as opk_mod
    pkg = body.get("package")
    if not isinstance(pkg, dict):
        raise HTTPException(422, "body.package (JSON object) is required")
    try:
        clean = opk_mod.save_package(user.id, pkg)
    except ValueError as e:
        raise HTTPException(422, f"Package rejected: {e}") from e
    except OSError as e:
        raise HTTPException(500, "Package could not be persisted — check disk "
                                 "space and data/ permissions") from e
    audit(db, "business.ops_package.install",
          f"'{clean['name']}' v{clean['version']} modules={len(clean['modules'])}",
          user_id=user.id)
    db.commit()
    return {"ok": True, "package": clean}


@app.delete("/api/business/ops-package")
def ops_package_remove(user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Revert to the built-in industry template (records are retained)."""
    require_admin(user)
    from . import ops_package as opk_mod
    try:
        existed = opk_mod.delete_package(user.id)
    except OSError as e:
        raise HTTPException(500, "Package file could not be removed") from e
    audit(db, "business.ops_package.remove",
          "reverted to built-in template" if existed else "no package installed",
          user_id=user.id)
    db.commit()
    return {"ok": True, "removed": existed}


# ==================== Developer mode — company export / import ====================
COMPANY_BUNDLE_SCHEMA = "nexacrew-company/1"


@app.get("/api/dev/companies")
def dev_companies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Developer only — every commercial company hosted on this server."""
    require_developer(user)
    rows = (db.query(BusinessProfile)
            .filter(BusinessProfile.usage_mode == "commercial")
            .order_by(BusinessProfile.company_name).limit(500).all())
    return {"companies": [{"owner_id": r.user_id,
                           "company_name": r.company_name or r.custom_type or "(unnamed)",
                           "company_type": r.company_type} for r in rows]}


@app.get("/api/dev/company-export")
def dev_company_export(owner_id: str = "", user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Developer only — export a chosen company as a portable bundle
    (profile + Operations Package) that any server can import."""
    require_developer(user)
    from . import ops_package as opk_mod
    oid = (owner_id or "").strip() or _biz_uid(db, user)
    bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == oid).first()
    if not bp:
        raise HTTPException(404, "Unknown company — pick one from /api/dev/companies")
    pkg = opk_mod.load_package(oid)
    if pkg is None:
        company = (bp.company_name or bp.custom_type or "Company").strip()
        pkg = opk_mod.builtin_as_package(bp.company_type, company,
                                         bp.generated_prompt or "")
    bundle = {"schema": COMPANY_BUNDLE_SCHEMA,
              "exported_at": dt.datetime.utcnow().isoformat() + "Z",
              "exported_by": user.username,
              "app_version": APP_VERSION,
              "company": {"usage_mode": "commercial",
                          "company_type": bp.company_type,
                          "custom_type": bp.custom_type,
                          "company_name": bp.company_name,
                          "company_desc": bp.company_desc,
                          "generated_prompt": bp.generated_prompt,
                          "docs": bp.docs or "[]",
                          "docs_text": bp.docs_text or ""},
              "ops_package": pkg}
    audit(db, "dev.company.export",
          f"company='{bp.company_name}' owner={oid}", user_id=user.id)
    db.commit()
    return bundle


@app.post("/api/dev/company-import")
def dev_company_import(body: dict, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    """Import a company bundle into the caller's own company (developer or
    administrator). Sets the business profile and installs the Operations
    Package atomically; the action is audited."""
    if not (getattr(user, "is_developer", False) or user.is_admin):
        raise HTTPException(403, "Administrator or developer privileges required")
    from . import ops_package as opk_mod
    if not isinstance(body, dict) or body.get("schema") != COMPANY_BUNDLE_SCHEMA:
        raise HTTPException(422, f"body must be a company bundle (schema={COMPANY_BUNDLE_SCHEMA})")
    co = body.get("company")
    pkg = body.get("ops_package")
    if not isinstance(co, dict) or not isinstance(pkg, dict):
        raise HTTPException(422, "bundle must contain 'company' and 'ops_package' objects")
    bp = _get_owner_bp(db, user)
    try:
        clean = opk_mod.save_package(bp.user_id, pkg)
    except ValueError as e:
        raise HTTPException(422, f"Operations Package rejected: {e}") from e
    except OSError as e:
        raise HTTPException(500, "Package could not be persisted — check disk "
                                 "space and data/ permissions") from e
    bp.usage_mode = "commercial"
    bp.company_type = str(co.get("company_type") or "")[:80]
    bp.custom_type = str(co.get("custom_type") or "")[:200]
    bp.company_name = str(co.get("company_name") or "")[:200]
    bp.company_desc = str(co.get("company_desc") or "")[:20000]
    bp.generated_prompt = str(co.get("generated_prompt") or "")
    bp.docs = co.get("docs") if isinstance(co.get("docs"), str) else "[]"
    bp.docs_text = str(co.get("docs_text") or "")
    bp.prompt_status = "ready" if bp.generated_prompt else ""
    audit(db, "dev.company.import",
          f"company='{bp.company_name}' pkg='{clean['name']}' v{clean['version']} "
          f"modules={len(clean['modules'])}", user_id=user.id)
    db.commit()
    return {"ok": True, "company_name": bp.company_name, "package": clean}


@app.get("/api/business/records")
def business_records(module: str, status: str = "", limit: int = 500,
                     user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(BusinessRecord).filter(BusinessRecord.user_id == _biz_uid(db, user),
                                        BusinessRecord.module == module)
    if status:
        q = q.filter(BusinessRecord.status == status)
    rows = q.order_by(BusinessRecord.created_at.desc()).limit(max(1, min(limit, 2000))).all()
    out = []
    for r in rows:
        try:
            d = json.loads(r.data or "{}")
        except Exception:
            d = {}
        out.append({"id": r.id, "module": r.module, "status": r.status,
                    "data": d, "created_at": str(r.created_at or "")})
    return out


@app.post("/api/business/records")
def business_record_create(body: dict, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    module = (body.get("module") or "").strip()
    bp = _get_owner_bp(db, user)
    oid = bp.user_id
    data = body.get("data") or {}
    if module == "workers" and user.is_admin:
        # multi-company servers: HR enrollment asks WHICH company the
        # employee joins — the record and the worker login are bound to it
        chosen = str(data.pop("company_owner", "") or "").strip()
        if chosen and chosen != oid:
            cbp = db.query(BusinessProfile).filter(
                BusinessProfile.user_id == chosen,
                BusinessProfile.usage_mode == "commercial").first()
            if not cbp:
                raise HTTPException(422, "Selected company does not exist on this server")
            bp, oid = cbp, chosen
    else:
        data.pop("company_owner", None)
    if _license_required(db, bp):
        raise HTTPException(403, f"Company '{bp.company_name}' has no valid license "
                                 "key — bind one under Operations ▸ License")
    valid = {m["key"] for m in business_mod.modules_for(bp.company_type, oid)}
    if module not in valid:
        raise HTTPException(422, "Unknown module for this business type")
    provisioned = None
    if module == "workers":
        # HR enrollment doubles as account provisioning: every worker gets
        # their own login (Administration → Users). The plaintext password
        # is hashed immediately and NEVER stored in the business record.
        uname = str(data.get("login_username") or "").strip()[:80]
        pw = str(data.pop("login_password", "") or "")
        if not uname or not pw:
            raise HTTPException(400, "Login username and password are required — "
                                     "every worker must have their own account")
        if len(pw) < 8:
            raise HTTPException(400, "Password must be at least 8 characters")
        if db.query(User).filter(User.username == uname,
                                 User.deleted_at.is_(None)).first():
            raise HTTPException(400, f"Username '{uname}' already exists — choose another")
        import re as _re4
        wf_face = str(data.get("face_photo") or "").strip()
        if not wf_face or not _re4.fullmatch(r"[A-Za-z0-9_.\-]+\.jpg", wf_face):
            raise HTTPException(400, "Worker face photo is required — let the camera "
                                     "capture the worker's face before committing the record")
        data["login_username"] = uname
        provisioned = User(username=uname,
                           display_name=str(data.get("name") or uname)[:120],
                           password_hash=hash_password(pw), is_admin=False,
                           company_owner_id=oid)
        db.add(provisioned)
    rec = BusinessRecord(user_id=oid, module=module,
                         data=json.dumps(data),
                         status=(body.get("status") or "open"))
    db.add(rec)
    face = (body.get("face") or "").strip()[:80]
    audit(db, "business.record.create",
          f"{module}" + (f" face={face}" if face else " face=NONE")
          + f" values={json.dumps(data, ensure_ascii=False)[:1500]}",
          user_id=user.id)
    # CROSS-FORM CASCADE — auto-create related records (e.g. receiving flags
    # data-bearing media → Data Security log) so workers never re-key data.
    cascades = []
    for c in business_mod.cascade_for(module, data, valid):
        crec = BusinessRecord(user_id=oid, module=c["module"],
                              data=json.dumps(c["data"]), status="open")
        db.add(crec)
        audit(db, "business.record.cascade",
              f"{module} → {c['module']}: {c['reason']} "
              f"values={json.dumps(c['data'], ensure_ascii=False)[:800]}",
              user_id=user.id)
        cascades.append({"module": c["module"], "rec": crec, "reason": c["reason"]})
    if provisioned is not None:
        audit(db, "user.create",
              f"username={provisioned.username} admin=False "
              f"(auto-provisioned from HR Employee Enrollment)", user_id=user.id)
    db.commit()
    db.refresh(rec)
    return {"id": rec.id,
            "user_created": provisioned.username if provisioned is not None else None,
            "cascades": [{"module": c["module"], "id": c["rec"].id,
                          "reason": c["reason"]} for c in cascades]}


@app.put("/api/business/records/{rid}")
def business_record_update(rid: str, body: dict, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    rec = db.query(BusinessRecord).filter(BusinessRecord.id == rid,
                                          BusinessRecord.user_id == _biz_uid(db, user)).first()
    if not rec:
        raise HTTPException(404, "Record not found")
    change_bits = []
    if "data" in body:
        try:
            old_d = json.loads(rec.data or "{}")
        except Exception:
            old_d = {}
        new_d = body.get("data") or {}
        if rec.module == "workers":
            # never persist plaintext; a filled password field on edit means
            # "reset this worker's login password" — or, for records enrolled
            # before account provisioning existed, CREATE the account now.
            pw = str(new_d.pop("login_password", "") or "")
            if pw:
                if len(pw) < 8:
                    raise HTTPException(400, "Password must be at least 8 characters")
                uname = str(new_d.get("login_username") or "").strip()[:80]
                if not uname:
                    raise HTTPException(400, "Login username is required to set a password")
                acct = db.query(User).filter(User.username == uname,
                                             User.deleted_at.is_(None)).first()
                if acct:
                    acct.password_hash = hash_password(pw)
                    revoke_other_sessions(acct.id, "")
                    change_bits.append("login_password: ******** (reset, sessions revoked)")
                else:
                    acct = User(username=uname,
                                display_name=str(new_d.get("name") or uname)[:120],
                                password_hash=hash_password(pw), is_admin=False)
                    db.add(acct)
                    audit(db, "user.create",
                          f"username={uname} admin=False "
                          "(auto-provisioned from HR Employee Enrollment amend)",
                          user_id=user.id)
                    change_bits.append(f"login account created: {uname}")
        for k in sorted(set(old_d) | set(new_d)):
            ov, nv = str(old_d.get(k, "") or ""), str(new_d.get(k, "") or "")
            if ov != nv:
                change_bits.append(f"{k}: '{ov[:120]}' → '{nv[:120]}'")
        rec.data = json.dumps(new_d)
    if body.get("status") in ("open", "done", "archived") and body["status"] != rec.status:
        change_bits.append(f"status: '{rec.status}' → '{body['status']}'")
        rec.status = body["status"]
    elif body.get("status") in ("open", "done", "archived"):
        rec.status = body["status"]
    # ISO 9001/14001/45001 §7.5.3 — amendments to controlled records are
    # attributable and auditable, INCLUDING the amended values (old → new)
    face = (body.get("face") or "").strip()[:80]
    audit(db, "business.record.update",
          f"{rec.module}" + (f" face={face}" if face else " face=NONE")
          + f" changes=[{'; '.join(change_bits)[:1500]}]",
          user_id=user.id)
    db.commit()
    return {"ok": True}


@app.post("/api/business/workers/{rid}/badge")
def worker_badge_generate(rid: str, user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Issue (or re-issue) the printable ID badge for an HR worker record.
    One active badge per worker: any previous badge for this record is
    revoked first. The QR token opens the check-in kiosk punch flow; the
    badge number is written back onto the worker record."""
    oid = _biz_uid(db, user)
    rec = db.query(BusinessRecord).filter(BusinessRecord.id == rid,
                                          BusinessRecord.user_id == oid,
                                          BusinessRecord.module == "workers").first()
    if not rec:
        raise HTTPException(404, "Worker record not found")
    try:
        data = json.loads(rec.data or "{}")
    except Exception:
        data = {}
    name = str(data.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Worker record has no name — complete the record first")
    face_id = str(data.get("face_photo") or "").strip()
    import re as _re3
    if not face_id or not _re3.fullmatch(r"[A-Za-z0-9_.\-]+\.jpg", face_id):
        raise HTTPException(400, "No worker face photo on file — amend the record and "
                                 "let the camera capture the worker's face first")
    photo_path = OP_FACE_DIR / face_id
    if not photo_path.exists():
        raise HTTPException(400, "Stored face photo is missing — amend the record to "
                                 "capture a new photo, then generate the badge again")
    # one active badge per worker — revoke any previous one (audited lifecycle)
    for old in db.query(WorkerBadge).filter(WorkerBadge.user_id == oid,
                                            WorkerBadge.worker_record_id == rid,
                                            WorkerBadge.status == "active").all():
        wf_mod.revoke_badge(db, old, by=user.username, reason="badge re-issued")
    b, token = wf_mod.issue_badge(db, oid, name, worker_record_id=rid,
                                  issued_by=user.username)
    badge_no = "WB-" + b.id.replace("-", "")[:8].upper()
    data["badge_no"] = badge_no
    rec.data = json.dumps(data)
    audit(db, "workforce.badge.issue",
          f"{name} badge={badge_no} record={rid[:8]} (HR Employee Enrollment)",
          user_id=user.id)
    db.commit()
    import base64 as _b64
    photo_uri = "data:image/jpeg;base64," + _b64.b64encode(photo_path.read_bytes()).decode()
    parts = name.split()
    return {"ok": True, "badge_id": b.id, "badge_no": badge_no,
            "first_name": parts[0] if parts else "",
            "last_name": " ".join(parts[1:]),
            "name": name, "role": str(data.get("role") or ""),
            "management": str(data.get("management") or "").strip().lower() == "yes",
            "qr_png": _qr_data_uri(token), "photo": photo_uri}


@app.delete("/api/business/records/{rid}")
def business_record_delete(rid: str, face: str = "", user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    rec = db.query(BusinessRecord).filter(BusinessRecord.id == rid,
                                          BusinessRecord.user_id == _biz_uid(db, user)).first()
    if not rec:
        raise HTTPException(404, "Record not found")
    deleted_values = rec.data or "{}"
    rec_module = rec.module
    db.delete(rec)
    face = face.strip()[:80]
    audit(db, "business.record.delete",
          f"{rec_module}" + (f" face={face}" if face else " face=NONE")
          + f" deleted_values={deleted_values[:1500]}",
          user_id=user.id)
    db.commit()
    return {"ok": True}


# ==================== POS / Purchasing / Accounting (restaurant & supermarket ERP) ====================
from . import pos as pos_mod  # noqa: E402
from . import purchasing as purch_mod  # noqa: E402
from . import accounting as acct_mod  # noqa: E402
from .db import Account as GLAccount, JournalEntry, PosObject, PurchaseOrder as PO_ERP, Vendor, VendorInvoice  # noqa: E402
from .security import decrypt_secret as _dec, encrypt_secret as _enc  # noqa: E402


def _require_pos(db: Session, user: User) -> BusinessProfile:
    """Server-side business-type gate: POS/Purchasing/Accounting APIs are
    reachable only for restaurant / supermarket commercial deployments."""
    bp = _get_owner_bp(db, user)
    if bp.usage_mode != "commercial" or not pos_mod.pos_enabled(bp.company_type):
        raise HTTPException(403, "POS modules are available only for Restaurant or Supermarket businesses")
    return bp


@app.get("/api/pos/nav")
def pos_nav(user: User = Depends(current_user), db: Session = Depends(get_db)):
    bp = _get_owner_bp(db, user)
    if bp.usage_mode != "commercial":
        return {"pos": False, "sections": []}
    return pos_mod.navigation_for(bp.company_type)


@app.get("/api/pos/schema/{kind}")
def pos_schema(kind: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bp = _require_pos(db, user)
    if kind not in pos_mod.kinds_for(bp.company_type):
        raise HTTPException(403, f"'{kind}' is not enabled for a {bp.company_type} business")
    return pos_mod.kind_schema(kind)


@app.get("/api/pos/objects/{kind}")
def pos_list(kind: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    bp = _require_pos(db, user)
    if kind not in pos_mod.kinds_for(bp.company_type):
        raise HTTPException(403, f"'{kind}' is not enabled for a {bp.company_type} business")
    rows = (db.query(PosObject).filter(PosObject.user_id == user.id, PosObject.kind == kind)
            .order_by(PosObject.sort, PosObject.created_at).all())
    out = [pos_mod.object_dict(o) for o in rows]
    if kind == "kiosk":
        # By owner request the device token is visible to the authenticated
        # POS admin (session-guarded; still encrypted at rest & audited).
        for o, d in zip(rows, out):
            try:
                d["device_token"] = _dec(o.secret or "") or ""
            except Exception:
                d["device_token"] = ""
    return out


@app.post("/api/pos/objects/{kind}")
def pos_create(kind: str, body: dict, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    bp = _require_pos(db, user)
    if kind not in pos_mod.kinds_for(bp.company_type):
        raise HTTPException(403, f"'{kind}' is not enabled for a {bp.company_type} business")
    data = body.get("data") or {}
    if kind == "drawer_event":
        err = pos_mod.validate_drawer_event(data)
        if err:
            raise HTTPException(422, err)
    o = PosObject(user_id=user.id, kind=kind, name=(body.get("name") or data.get("name") or "")[:200],
                  data=json.dumps(data), parent_id=body.get("parent_id") or "",
                  sort=int(body.get("sort") or 0))
    # encrypted secrets (delivery credentials, POS PINs); never returned
    secrets_in = body.get("secrets") or {}
    if secrets_in:
        o.secret = _enc(json.dumps(secrets_in))
    if kind == "kiosk":
        # unique device authentication token — returned ONCE at creation
        token = pos_mod.new_kiosk_token()
        o.secret = _enc(token)
    db.add(o)
    audit(db, "pos.create", f"{kind}: {o.name}", user_id=user.id)
    db.commit()
    db.refresh(o)
    out = pos_mod.object_dict(o)
    if kind == "kiosk":
        out["device_token"] = token  # shown once; store it on the kiosk device
    return out


@app.put("/api/pos/objects/{oid}")
def pos_update(oid: str, body: dict, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    _require_pos(db, user)
    o = db.query(PosObject).filter(PosObject.id == oid, PosObject.user_id == user.id).first()
    if not o:
        raise HTTPException(404, "Object not found")
    if "data" in body:
        data = body.get("data") or {}
        if o.kind == "drawer_event":
            err = pos_mod.validate_drawer_event(data)
            if err:
                raise HTTPException(422, err)
        o.data = json.dumps(data)
        o.name = (body.get("name") or data.get("name") or o.name or "")[:200]
    if "active" in body:
        o.active = bool(body["active"])
    if "sort" in body:
        o.sort = int(body["sort"] or 0)
    if body.get("secrets"):
        o.secret = _enc(json.dumps(body["secrets"]))
    if body.get("revoke_token") and o.kind == "kiosk":
        o.secret = _enc(pos_mod.new_kiosk_token())
        audit(db, "pos.kiosk.token_revoked", o.name, user_id=user.id)
    audit(db, "pos.update", f"{o.kind}: {o.name}", user_id=user.id)
    db.commit()
    return pos_mod.object_dict(o)


@app.delete("/api/pos/objects/{oid}")
def pos_delete(oid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    o = db.query(PosObject).filter(PosObject.id == oid, PosObject.user_id == user.id).first()
    if not o:
        raise HTTPException(404, "Object not found")
    db.delete(o)
    audit(db, "pos.delete", f"{o.kind}: {o.name}", user_id=user.id)
    db.commit()
    return {"ok": True}


# ---------- POS Kiosk Client API (spec §3.2 / §7) ----------
# Kiosks authenticate with their device token — never a user session.
# A kiosk can read ONLY its own assigned configuration and submit orders.
def _require_kiosk(db: Session, token: str):
    k = pos_mod.find_kiosk_by_token(db, (token or "").strip())
    if not k:
        raise HTTPException(401, "Invalid, revoked or deactivated kiosk device token")
    return k


@app.post("/api/kiosk/handshake")
def kiosk_handshake(body: dict, db: Session = Depends(get_db)):
    """Device-token authentication → the kiosk's full runtime configuration:
    business info, active categories/items (+options or variants), its
    assigned printer and drawer. Records last-online time."""
    k = _require_kiosk(db, body.get("token") or "")
    bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == k.user_id).first()
    if not bp or not pos_mod.pos_enabled(bp.company_type):
        raise HTTPException(403, "POS is not enabled for this business")
    kd = json.loads(k.data or "{}")
    kd["last_online"] = dt.datetime.utcnow().isoformat()
    k.data = json.dumps(kd)

    def _objs(kind: str) -> list[dict]:
        rows = (db.query(PosObject)
                .filter(PosObject.user_id == k.user_id, PosObject.kind == kind,
                        PosObject.active.is_(True))
                .order_by(PosObject.sort, PosObject.created_at).all())
        return [pos_mod.object_dict(o) for o in rows]

    cfg = {"kiosk": pos_mod.object_dict(k), "business": {
               "name": bp.company_name or "", "type": bp.company_type},
           "categories": _objs("category"), "items": _objs("item"),
           "togo": _objs("togo")}
    if bp.company_type == "restaurant":
        cfg["option_groups"] = _objs("option_group")
        cfg["zones"] = _objs("zone")
        cfg["structures"] = _objs("structure")
        cfg["tables"] = _objs("table")
    else:
        cfg["sub_items"] = _objs("sub_item")
        cfg["departments"] = _objs("department")
    # only the devices assigned to THIS kiosk
    for kind in ("printer", "drawer"):
        assigned = [o for o in _objs(kind)
                    if (o["data"].get("kiosk") or "").strip().lower()
                    in ((k.name or "").strip().lower(), k.id)]
        cfg[kind] = assigned[0] if assigned else None
    audit(db, "pos.kiosk.handshake", k.name, user_id=k.user_id)
    db.commit()
    return cfg


@app.post("/api/kiosk/orders")
def kiosk_order(body: dict, db: Session = Depends(get_db)):
    """Order submission from an authenticated kiosk. Idempotent via the
    client-supplied idempotency_key — resubmitting after a network failure
    can never create a duplicate order (spec §24)."""
    k = _require_kiosk(db, body.get("token") or "")
    idem = (body.get("idempotency_key") or "").strip()
    if not idem:
        raise HTTPException(422, "idempotency_key is required")
    lines = body.get("lines") or []
    if not isinstance(lines, list) or not lines:
        raise HTTPException(422, "Order needs at least one line")
    # idempotency: same kiosk + same key → return the existing order
    for o in db.query(PosObject).filter(PosObject.user_id == k.user_id,
                                        PosObject.kind == "order").all():
        try:
            d = json.loads(o.data or "{}")
        except Exception:
            continue
        if d.get("idempotency_key") == idem and d.get("kiosk_id") == k.id:
            return {"ok": True, "order_id": o.id, "idempotent": True}
    try:
        total = round(sum(float(x.get("qty") or 0) * float(x.get("price") or 0)
                          for x in lines), 2)
    except (TypeError, ValueError):
        raise HTTPException(422, "Order lines contain unreadable qty/price")
    data = {"idempotency_key": idem, "kiosk_id": k.id, "kiosk": k.name,
            "order_type": body.get("order_type") or "dine-in",
            "table": body.get("table") or "", "worker": body.get("worker") or "",
            "payment_method": body.get("payment_method") or "",
            "lines": lines, "total": total, "status": "open"}
    o = PosObject(user_id=k.user_id, kind="order",
                  name=f"Order {dt.datetime.utcnow().strftime('%Y%m%d-%H%M%S')} · {k.name}",
                  data=json.dumps(data))
    db.add(o)
    audit(db, "pos.kiosk.order", f"{k.name} total=${total:,.2f} type={data['order_type']}",
          user_id=k.user_id)
    db.commit()
    db.refresh(o)
    return {"ok": True, "order_id": o.id, "total": total, "idempotent": False}


@app.post("/api/kiosk/worker-login")
def kiosk_worker_login(body: dict, db: Session = Depends(get_db)):
    import secrets as _secrets
    """Individual worker sign-in at a POS kiosk (spec: never shared cashier
    identities). Verifies the POS Account username + PIN/password (stored
    encrypted). Returns role + display name; every order records the worker."""
    k = _require_kiosk(db, body.get("token") or "")
    username = str(body.get("username") or "").strip().lower()
    pin = str(body.get("pin") or "")
    if not username or not pin:
        raise HTTPException(422, "username and pin are required")
    accounts = (db.query(PosObject)
                .filter(PosObject.user_id == k.user_id,
                        PosObject.kind == "pos_account",
                        PosObject.active.is_(True)).all())
    for a in accounts:
        try:
            ad = json.loads(a.data or "{}")
        except Exception:
            continue
        if str(ad.get("username") or a.name or "").strip().lower() != username:
            continue
        if ad.get("status") and ad["status"] != "active":
            raise HTTPException(403, f"Account is {ad['status']}")
        # account may be scoped to a specific POS system (restaurant / supermarket)
        scope = str(ad.get("pos_scope") or "both").strip().lower()
        if scope in ("restaurant", "supermarket"):
            bp = (db.query(BusinessProfile)
                  .filter(BusinessProfile.user_id == k.user_id).first())
            if bp and (bp.company_type or "").lower() != scope:
                raise HTTPException(403, f"Account is authorized for {scope} POS only")
        # account may be locked to one kiosk
        assigned = str(ad.get("kiosk") or "").strip().lower()
        if assigned and assigned not in ((k.name or "").strip().lower(), k.id):
            raise HTTPException(403, "Account is not authorized on this kiosk")
        if not a.secret:
            raise HTTPException(403, "Account has no PIN set — configure it on the POS Server")
        try:
            stored = json.loads(_dec(a.secret) or "{}")
            stored_pin = str(stored.get("pin") or "")
        except Exception:
            stored_pin = ""
        if not stored_pin or not _secrets.compare_digest(stored_pin, pin):
            raise HTTPException(401, "Invalid PIN")
        audit(db, "pos.worker.login", f"{ad.get('worker') or username} @ {k.name}",
              user_id=k.user_id)
        db.commit()
        return {"ok": True, "worker": ad.get("worker") or username,
                "username": username, "role": ad.get("role") or "Cashier"}
    raise HTTPException(401, "Unknown POS account")


@app.post("/api/kiosk/heartbeat")
def kiosk_heartbeat(body: dict, request: Request, db: Session = Depends(get_db)):
    """Lightweight liveness ping from the kiosk client (every ~20 s).
    Updates last-online; powers the data-center-grade status board."""
    k = _require_kiosk(db, body.get("token") or "")
    kd = json.loads(k.data or "{}")
    now = dt.datetime.utcnow()
    kd["last_online"] = now.isoformat()
    kd["client_version"] = str(body.get("version") or kd.get("client_version") or "")[:40]
    # real network address of the device — never trust the self-reported one
    real_ip = request.client.host if request.client else ""
    kd["client_ip"] = (real_ip or str(body.get("ip") or kd.get("client_ip") or ""))[:60]
    k.data = json.dumps(kd)
    db.commit()
    return {"ok": True, "server_time": now.isoformat() + "Z", "kiosk": k.name}


@app.get("/api/pos/kiosks/status")
def kiosks_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Connection status board for every kiosk (POS Server side).
    ONLINE   — heartbeat within 60 s
    DEGRADED — heartbeat within 5 min (missed pings)
    OFFLINE  — older than 5 min
    NEVER    — no successful handshake yet"""
    _require_pos(db, user)
    now = dt.datetime.utcnow()
    out = []
    rows = (db.query(PosObject)
            .filter(PosObject.user_id == user.id, PosObject.kind == "kiosk")
            .order_by(PosObject.sort, PosObject.created_at).all())
    for k in rows:
        try:
            kd = json.loads(k.data or "{}")
        except Exception:
            kd = {}
        last = kd.get("last_online") or ""
        age = None
        if last:
            try:
                age = (now - dt.datetime.fromisoformat(last.replace("Z", ""))).total_seconds()
            except Exception:
                age = None
        if not k.active:
            status = "disabled"
        elif age is None:
            status = "never"
        elif age <= 60:
            status = "online"
        elif age <= 300:
            status = "degraded"
        else:
            status = "offline"
        # today's order volume through this kiosk
        orders_today = 0
        for o in db.query(PosObject).filter(PosObject.user_id == user.id,
                                            PosObject.kind == "order").all():
            try:
                od = json.loads(o.data or "{}")
            except Exception:
                continue
            if od.get("kiosk_id") == k.id and o.created_at and tz.local_day_str(o.created_at) == tz.today_local().isoformat():
                orders_today += 1
        out.append({"id": k.id, "name": k.name, "location": kd.get("location") or "",
                    "status": status, "last_online": last,
                    "age_seconds": round(age) if age is not None else None,
                    "client_version": kd.get("client_version") or "",
                    "client_ip": kd.get("client_ip") or "",
                    "printer": kd.get("printer") or "", "drawer": kd.get("drawer") or "",
                    "orders_today": orders_today, "active": bool(k.active)})
    return {"server_time": now.isoformat() + "Z", "kiosks": out,
            "online": sum(1 for x in out if x["status"] == "online"),
            "total": len(out)}


# ---------- Purchasing: vendors ----------
@app.get("/api/purchasing/vendors")
def vendors_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    rows = db.query(Vendor).filter(Vendor.user_id == user.id).order_by(Vendor.name).all()
    return [{"id": v.id, "name": v.name, "contact": v.contact, "phone": v.phone,
             "email": v.email, "terms": v.terms, "status": v.status,
             "default_account": v.default_account} for v in rows]


@app.post("/api/purchasing/vendors")
def vendor_create(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    if not (body.get("name") or "").strip():
        raise HTTPException(422, "Vendor name required")
    v = Vendor(user_id=user.id, name=body["name"][:200], contact=body.get("contact") or "",
               phone=body.get("phone") or "", email=body.get("email") or "",
               address=body.get("address") or "", terms=body.get("terms") or "Net 30",
               tax_id=body.get("tax_id") or "", default_account=body.get("default_account") or "")
    db.add(v)
    audit(db, "purchasing.vendor.create", v.name, user_id=user.id)
    db.commit()
    return {"id": v.id}


@app.put("/api/purchasing/vendors/{vid}")
def vendor_update(vid: str, body: dict, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    _require_pos(db, user)
    v = db.query(Vendor).filter(Vendor.id == vid, Vendor.user_id == user.id).first()
    if not v:
        raise HTTPException(404, "Vendor not found")
    for f in ("name", "contact", "phone", "email", "address", "terms", "tax_id",
              "default_account", "status", "notes"):
        if f in body:
            setattr(v, f, body[f] or "")
    audit(db, "purchasing.vendor.update", v.name, user_id=user.id)
    db.commit()
    return {"ok": True}


# ---------- Purchasing: purchase orders + receiving ----------
def _po_d(p: PO_ERP) -> dict:
    try:
        lines = json.loads(p.lines or "[]")
    except Exception:
        lines = []
    return {"id": p.id, "po_number": p.po_number, "vendor_id": p.vendor_id or "",
            "lines": lines, "tax": p.tax, "shipping": p.shipping, "discount": p.discount,
            "total": p.total, "status": p.status, "notes": p.notes,
            "expected": str(p.expected or "")[:10], "created_at": str(p.created_at or "")}


@app.get("/api/purchasing/pos")
def pos_orders_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    rows = (db.query(PO_ERP).filter(PO_ERP.user_id == user.id)
            .order_by(PO_ERP.created_at.desc()).limit(500).all())
    return [_po_d(p) for p in rows]


@app.post("/api/purchasing/pos")
def po_create(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    n = db.query(PO_ERP).filter(PO_ERP.user_id == user.id).count() + 1
    lines = body.get("lines") or []
    total = sum(float(x.get("qty") or 0) * float(x.get("unit_cost") or 0) for x in lines)
    total += float(body.get("tax") or 0) + float(body.get("shipping") or 0) - float(body.get("discount") or 0)
    p = PO_ERP(user_id=user.id, po_number=f"PO-{dt.date.today().year}-{n:04d}",
               vendor_id=body.get("vendor_id") or None, lines=json.dumps(lines),
               tax=float(body.get("tax") or 0), shipping=float(body.get("shipping") or 0),
               discount=float(body.get("discount") or 0), total=round(total, 2),
               status=body.get("status") or "draft", notes=body.get("notes") or "")
    db.add(p)
    audit(db, "purchasing.po.create", p.po_number, user_id=user.id)
    db.commit()
    return _po_d(p)


@app.put("/api/purchasing/pos/{pid}")
def po_update(pid: str, body: dict, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    _require_pos(db, user)
    p = db.query(PO_ERP).filter(PO_ERP.id == pid, PO_ERP.user_id == user.id).first()
    if not p:
        raise HTTPException(404, "PO not found")
    valid = ("draft", "pending approval", "approved", "sent", "partially received",
             "received", "closed", "cancelled")
    if body.get("status") and body["status"] in valid:
        p.status = body["status"]
    if "lines" in body:
        p.lines = json.dumps(body["lines"] or [])
    if "notes" in body:
        p.notes = body["notes"] or ""
    audit(db, "purchasing.po.update", f"{p.po_number} → {p.status}", user_id=user.id)
    db.commit()
    return _po_d(p)


@app.post("/api/purchasing/pos/{pid}/receive")
def po_receive(pid: str, body: dict, user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    """Record complete/partial receiving; updates line received/damaged/missing
    quantities and derives PO status. Inventory increases only here (spec §19)."""
    _require_pos(db, user)
    p = db.query(PO_ERP).filter(PO_ERP.id == pid, PO_ERP.user_id == user.id).first()
    if not p:
        raise HTTPException(404, "PO not found")
    lines = json.loads(p.lines or "[]")
    recs = {str(r.get("idx")): r for r in (body.get("receipts") or [])}
    all_full = True
    any_recv = False
    for i, ln in enumerate(lines):
        r = recs.get(str(i))
        if r:
            ln["received"] = float(ln.get("received") or 0) + float(r.get("received") or 0)
            ln["damaged"] = float(ln.get("damaged") or 0) + float(r.get("damaged") or 0)
            ln["missing"] = float(r.get("missing") or ln.get("missing") or 0)
            ln["lot"] = r.get("lot") or ln.get("lot") or ""
            ln["expiry"] = r.get("expiry") or ln.get("expiry") or ""
        if float(ln.get("received") or 0) > 0:
            any_recv = True
        if float(ln.get("received") or 0) < float(ln.get("qty") or 0):
            all_full = False
    p.lines = json.dumps(lines)
    p.status = "received" if all_full and any_recv else ("partially received" if any_recv else p.status)
    # inventory increase in the ERP inventory register
    for i, ln in enumerate(lines):
        r = recs.get(str(i))
        if r and float(r.get("received") or 0) > 0 and ln.get("sku"):
            for rec in db.query(BusinessRecord).filter(
                    BusinessRecord.user_id == user.id, BusinessRecord.module == "inventory").all():
                try:
                    d = json.loads(rec.data or "{}")
                    if (d.get("sku") or "").strip().lower() == str(ln["sku"]).strip().lower():
                        d["qty"] = float(d.get("qty") or 0) + float(r["received"])
                        rec.data = json.dumps(d)
                        break
                except Exception:
                    continue
    audit(db, "purchasing.po.receive", f"{p.po_number} → {p.status}", user_id=user.id)
    db.commit()
    return _po_d(p)


# ---------- AI invoice upload + mandatory human verification ----------
def _inv_d(i: VendorInvoice) -> dict:
    try:
        ext = json.loads(i.extracted or "{}")
    except Exception:
        ext = {}
    try:
        cor = json.loads(i.corrected or "{}")
    except Exception:
        cor = {}
    try:
        conf = json.loads(i.fields_confirmed or "[]")
    except Exception:
        conf = []
    return {"id": i.id, "file_name": i.file_name, "checksum": i.checksum[:16],
            "doc_type": i.doc_type, "status": i.status, "vendor_id": i.vendor_id or "",
            "po_id": i.po_id or "", "extracted": ext, "corrected": cor,
            "fields_confirmed": conf, "required_fields": purch_mod.REQUIRED_FIELDS,
            "statement": purch_mod.REQUIRED_STATEMENT,
            "confirmed_by": i.confirmed_by or "", "journal_id": i.journal_id or "",
            "created_at": str(i.created_at or "")}


@app.get("/api/purchasing/invoices")
def invoices_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    rows = (db.query(VendorInvoice).filter(VendorInvoice.user_id == user.id)
            .order_by(VendorInvoice.created_at.desc()).limit(300).all())
    return [_inv_d(i) for i in rows]


@app.post("/api/purchasing/invoices")
async def invoice_upload(file: UploadFile = File(...), user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Upload → store original untouched → AI extraction with field-level
    confidence → status 'ai review required'. Posting is impossible until a
    human confirms every required field (spec §16)."""
    _require_pos(db, user)
    import uuid as _uuid
    ext = Path(file.filename or "doc").suffix.lower()
    if ext not in (".pdf", ".jpg", ".jpeg", ".png", ".tiff", ".heic", ".txt", ".csv"):
        raise HTTPException(422, f"Unsupported invoice file type {ext or '(none)'}")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 25 MB)")
    inv_dir = UPLOAD_DIR / "invoices"
    inv_dir.mkdir(parents=True, exist_ok=True)
    dest = inv_dir / f"{_uuid.uuid4().hex[:10]}_{Path(file.filename).stem[:50]}{ext}"
    dest.write_bytes(data)  # original preserved unchanged, forever
    inv = VendorInvoice(user_id=user.id, file_path=str(dest), file_name=file.filename or dest.name,
                        checksum=pos_mod.file_checksum(data), status="processing")
    db.add(inv)
    db.commit()
    from starlette.concurrency import run_in_threadpool
    doc = await run_in_threadpool(purch_mod.extract_invoice, str(dest), inv.file_name)
    inv.extracted = json.dumps(doc)
    inv.doc_type = doc.get("doc_type") or "invoice"
    inv.status = "ai review required"
    problems = purch_mod.validate_invoice(db, user.id, inv)
    if problems:
        inv.status = "exception"
        inv.notes = "\n".join(problems)
    audit(db, "purchasing.invoice.upload",
          f"{inv.file_name} checksum={inv.checksum[:12]} status={inv.status}", user_id=user.id)
    db.commit()
    return _inv_d(inv)


@app.put("/api/purchasing/invoices/{iid}")
def invoice_review(iid: str, body: dict, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Human review: corrections + per-field confirmation + signed statement.
    AI never bypasses this step."""
    _require_pos(db, user)
    inv = db.query(VendorInvoice).filter(VendorInvoice.id == iid,
                                         VendorInvoice.user_id == user.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    if inv.status == "posted":
        raise HTTPException(422, "Posted invoices are corrected via credit memo / reversal, not edits")
    if "corrected" in body:
        inv.corrected = json.dumps(body["corrected"] or {})
    if "fields_confirmed" in body:
        allowed = set(purch_mod.REQUIRED_FIELDS) | {"po_number", "terms", "currency", "freight"}
        inv.fields_confirmed = json.dumps([f for f in body["fields_confirmed"] if f in allowed])
    if "vendor_id" in body:
        inv.vendor_id = body["vendor_id"] or None
    if "po_id" in body:
        inv.po_id = body["po_id"] or ""
    if body.get("statement_accepted"):
        inv.confirm_statement = purch_mod.REQUIRED_STATEMENT
        inv.confirmed_by = user.username
        inv.confirmed_at = dt.datetime.utcnow()
    if body.get("status") in ("rejected", "on hold", "pending approval", "ai review required"):
        inv.status = body["status"]
    audit(db, "purchasing.invoice.review", f"{inv.file_name} status={inv.status}", user_id=user.id)
    db.commit()
    return _inv_d(inv)


@app.get("/api/purchasing/invoices/{iid}/match")
def invoice_match(iid: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Three-way match (spec §18): PO ↔ receiving ↔ invoice with tolerances.
    Read-only — results guide the human reviewer, never auto-post."""
    _require_pos(db, user)
    inv = db.query(VendorInvoice).filter(VendorInvoice.id == iid,
                                         VendorInvoice.user_id == user.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    r = purch_mod.match_invoice(db, user.id, inv)
    if r["matched"] and inv.status == "ai review required":
        inv.status = "matched"
        db.commit()
    audit(db, "purchasing.invoice.match",
          f"{inv.file_name} matched={r['matched']} issues={len(r['issues'])}", user_id=user.id)
    return r


@app.post("/api/purchasing/invoices/{iid}/post")
def invoice_post(iid: str, body: dict, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    _require_pos(db, user)
    inv = db.query(VendorInvoice).filter(VendorInvoice.id == iid,
                                         VendorInvoice.user_id == user.id).first()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    try:
        acct_mod.seed_coa(db, user.id)
        r = purch_mod.post_invoice(db, user.id, inv, account=body.get("account") or "")
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, "purchasing.invoice.post",
          f"{inv.file_name} → JE {r['journal_id']} (confirmed by {inv.confirmed_by})",
          user_id=user.id)
    return {"ok": True, **r}


# ---------- Accounting ----------
@app.get("/api/accounting/accounts")
def gl_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    acct_mod.seed_coa(db, user.id)
    rows = (db.query(GLAccount).filter(GLAccount.user_id == user.id)
            .order_by(GLAccount.number).all())
    return [{"id": a.id, "number": a.number, "name": a.name, "type": a.type,
             "active": bool(a.active)} for a in rows]


@app.get("/api/accounting/journals")
def journals_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    rows = (db.query(JournalEntry).filter(JournalEntry.user_id == user.id)
            .order_by(JournalEntry.number.desc()).limit(300).all())
    out = []
    for j in rows:
        try:
            lines = json.loads(j.lines or "[]")
        except Exception:
            lines = []
        out.append({"id": j.id, "number": j.number, "at": str(j.at or "")[:10],
                    "memo": j.memo, "lines": lines, "source": j.source,
                    "source_ref": j.source_ref or "", "status": j.status,
                    "total": round(sum(float(x.get("debit") or 0) for x in lines), 2)})
    return out


@app.post("/api/accounting/journals")
def journal_create(body: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    acct_mod.seed_coa(db, user.id)
    try:
        je = acct_mod.create_journal(db, user.id, body.get("lines") or [],
                                     memo=body.get("memo") or "",
                                     post=bool(body.get("post")))
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, "accounting.journal.create", f"JE #{je.number} {je.status}", user_id=user.id)
    return {"id": je.id, "number": je.number, "status": je.status}


@app.post("/api/accounting/journals/{jid}/post")
def journal_post(jid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    j = db.query(JournalEntry).filter(JournalEntry.id == jid,
                                      JournalEntry.user_id == user.id).first()
    if not j:
        raise HTTPException(404, "Entry not found")
    if j.status != "draft":
        raise HTTPException(422, "Only draft entries can be posted")
    try:
        acct_mod._validate_lines(json.loads(j.lines or "[]"))
    except ValueError as e:
        raise HTTPException(422, str(e))
    j.status = "posted"
    audit(db, "accounting.journal.post", f"JE #{j.number}", user_id=user.id)
    db.commit()
    return {"ok": True}


@app.post("/api/accounting/journals/{jid}/reverse")
def journal_reverse(jid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _require_pos(db, user)
    j = db.query(JournalEntry).filter(JournalEntry.id == jid,
                                      JournalEntry.user_id == user.id).first()
    if not j:
        raise HTTPException(404, "Entry not found")
    try:
        r = acct_mod.reverse_journal(db, user.id, j)
    except ValueError as e:
        raise HTTPException(422, str(e))
    audit(db, "accounting.journal.reverse", f"JE #{j.number} → reversal #{r.number}", user_id=user.id)
    return {"ok": True, "reversal": r.number}


@app.get("/api/accounting/reports/{kind}")
def accounting_report(kind: str, year: int = 0, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    _require_pos(db, user)
    acct_mod.seed_coa(db, user.id)
    y = year or dt.date.today().year
    d1, d2 = dt.datetime(y, 1, 1), dt.datetime(y, 12, 31, 23, 59, 59)
    if kind == "pl":
        return acct_mod.profit_and_loss(db, user.id, d1, d2)
    if kind == "balance":
        return acct_mod.balance_sheet(db, user.id, d2)
    if kind == "trial":
        return acct_mod.trial_balance(db, user.id, d1, d2)
    if kind == "gl":
        return acct_mod.general_ledger(db, user.id, d1, d2)
    if kind == "cashflow":
        return acct_mod.cash_flow(db, user.id, d1, d2)
    raise HTTPException(404, "Unknown report — use pl | balance | trial | gl | cashflow")


@app.get("/api/accounting/export/xlsx")
def accounting_export(year: int = 0, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    """Accountant-ready tax-season XLSX package (spec §11); export is audited
    with filters and file checksum, and never modifies accounting records."""
    bp = _require_pos(db, user)
    acct_mod.seed_coa(db, user.id)
    y = year or dt.date.today().year
    out_dir = UPLOAD_DIR / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"tax_package_{y}_{stamp}.xlsx"
    r = acct_mod.export_xlsx(db, user.id, bp.company_name or "Business", y, str(out_path))
    audit(db, "accounting.export.xlsx",
          f"year={y} sheets={r['sheets']} checksum={r['checksum'][:16]}", user_id=user.id)
    from fastapi.responses import FileResponse
    return FileResponse(str(out_path),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        filename=f"Tax_Package_{y}.xlsx")


# ==================== Backup & restore ====================
from . import backup as backup_mod  # noqa: E402


@app.get("/api/backup/export")
def backup_export(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Download a full JSON backup (admin: everything; user: own data)."""
    doc = backup_mod.export_data(db, user)
    audit(db, "backup.export", f"scope={doc['scope']}", user_id=user.id)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    from fastapi.responses import JSONResponse
    return JSONResponse(doc, headers={
        "Content-Disposition": f'attachment; filename="agentai_backup_{stamp}.json"'})


@app.post("/api/backup/import")
async def backup_import(file: UploadFile = File(...), user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    """Restore a previously exported backup (after reinstall etc.)."""
    raw = await file.read()
    if len(raw) > 200 * 1024 * 1024:
        raise HTTPException(413, "Backup file too large")
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
        counts = backup_mod.import_data(db, doc, user)
    except (ValueError, KeyError) as e:
        raise HTTPException(422, f"Invalid backup file: {e}")
    audit(db, "backup.import", json.dumps(counts), user_id=user.id)
    return {"ok": True, "restored": counts}


@app.post("/api/backup/snapshot")
def backup_snapshot(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Write a server-side snapshot file (also used by /backup chat prompts)."""
    out = backup_mod.save_snapshot(db, user)
    audit(db, "backup.snapshot", str(out), user_id=user.id)
    return {"ok": True, "path": str(out)}


# ==================== Migration set (administrator) ====================
from . import migration  # noqa: E402


@app.get("/api/migration/usb")
def migration_usb(user: User = Depends(current_user)):
    """Auto-detect plugged-in USB flash drives (Windows / macOS / Linux)."""
    require_admin(user)
    return {"drives": migration.detect_usb_drives()}


@app.post("/api/migration/start")
def migration_start(body: dict, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    """Build the migration ZIP (program + full backup + OS installers) and
    copy it onto the selected USB drive, with live progress."""
    require_admin(user)
    usb_path = str(body.get("usb_path") or "").strip()
    drives = {d["path"] for d in migration.detect_usb_drives()}
    if usb_path not in drives:
        raise HTTPException(422, "USB drive not detected — plug it in and try again")
    doc = backup_mod.export_data(db, user)  # full admin backup travels along
    if not migration.start_migration(usb_path, doc):
        raise HTTPException(409, "A migration is already running")
    audit(db, "migration.start", usb_path, user_id=user.id)
    return {"ok": True}


@app.get("/api/migration/status")
def migration_status(user: User = Depends(current_user)):
    require_admin(user)
    return migration.get_state()


# ==================== Calendar (events + external sync) ====================
from . import calendar_sync  # noqa: E402
from .config import get_config as _get_cfg  # noqa: E402
from .db import CalendarAccount, CalendarEvent  # noqa: E402

_oauth_states: dict[str, dict] = {}  # state → {user_id, provider, redirect}


def _ev_d(ev: CalendarEvent) -> dict:
    d = _d(ev)
    d["start_at"] = ev.start_at.isoformat() if ev.start_at else None
    d["end_at"] = ev.end_at.isoformat() if ev.end_at else None
    return d


@app.get("/api/calendar/events")
def calendar_events(user: User = Depends(current_user), db: Session = Depends(get_db)):
    evs = db.query(CalendarEvent).filter(CalendarEvent.user_id == user.id) \
        .order_by(CalendarEvent.start_at).all()
    return {"events": [_ev_d(e) for e in evs]}


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    location: str = ""
    start_at: str
    end_at: str = ""
    all_day: bool = False


def _parse_dt(s: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(s.replace("Z", ""))
    except ValueError:
        raise HTTPException(422, f"Invalid date/time: {s}")


@app.post("/api/calendar/events")
def calendar_create(body: EventIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    start = _parse_dt(body.start_at)
    end = _parse_dt(body.end_at) if body.end_at else start + dt.timedelta(hours=1)
    ev = CalendarEvent(user_id=user.id, title=body.title, description=body.description,
                       location=body.location, start_at=start, end_at=end,
                       all_day=body.all_day)
    db.add(ev)
    db.commit()
    calendar_sync.sync_event(db, ev, "create", _get_cfg())
    audit(db, "calendar.create", ev.title, user_id=user.id)
    return _ev_d(ev)


@app.put("/api/calendar/events/{event_id}")
def calendar_update(event_id: str, body: EventIn, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    ev = db.get(CalendarEvent, event_id)
    if not ev or ev.user_id != user.id:
        raise HTTPException(404, "Event not found")
    ev.title, ev.description, ev.location = body.title, body.description, body.location
    ev.start_at = _parse_dt(body.start_at)
    ev.end_at = _parse_dt(body.end_at) if body.end_at else ev.start_at + dt.timedelta(hours=1)
    ev.all_day = body.all_day
    db.commit()
    calendar_sync.sync_event(db, ev, "update", _get_cfg())
    return _ev_d(ev)


@app.delete("/api/calendar/events/{event_id}")
def calendar_delete(event_id: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    ev = db.get(CalendarEvent, event_id)
    if not ev or ev.user_id != user.id:
        raise HTTPException(404, "Event not found")
    calendar_sync.sync_event(db, ev, "delete", _get_cfg())
    db.delete(ev)
    db.commit()
    return {"ok": True}


@app.get("/api/calendar/accounts")
def calendar_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    accs = db.query(CalendarAccount).filter(CalendarAccount.user_id == user.id).all()
    out = []
    for a in accs:
        d = _d(a)
        d.pop("encrypted_secret", None)  # never expose secrets
        d["last_sync_at"] = a.last_sync_at.isoformat() if a.last_sync_at else None
        out.append(d)
    cfg = _get_cfg()
    return {"accounts": out,
            "oauth_ready": {"google": bool(cfg.get("google_client_id")),
                            "microsoft": bool(cfg.get("ms_client_id"))}}


class AccountIn(BaseModel):
    provider: str = Field(pattern="^(google|microsoft|apple|caldav|monday)$")
    label: str = ""
    # apple / caldav
    username: str = ""
    password: str = ""
    url: str = ""
    calendar_url: str = ""
    # monday
    api_key: str = ""
    board_id: str = ""


@app.post("/api/calendar/accounts")
def calendar_account_add(body: AccountIn, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Connect an API-key / password based calendar (apple, caldav, monday).
    Google/Microsoft use the OAuth sign-in endpoints instead."""
    if body.provider in ("google", "microsoft"):
        raise HTTPException(422, "Use the sign-in button for Google/Microsoft")
    if body.provider in ("apple", "caldav") and not (body.username and body.password):
        raise HTTPException(422, "Username and password/app-specific password required")
    if body.provider == "monday" and not (body.api_key and body.board_id):
        raise HTTPException(422, "monday.com API key and board ID required")
    conf = {"username": body.username, "url": body.url,
            "calendar_url": body.calendar_url, "board_id": body.board_id}
    secret = {"password": body.password, "api_key": body.api_key}
    acc = CalendarAccount(user_id=user.id, provider=body.provider,
                          label=body.label or body.provider,
                          config=json.dumps(conf),
                          encrypted_secret=encrypt_secret(json.dumps(secret)),
                          status="connected")
    db.add(acc)
    db.commit()
    audit(db, "calendar.connect", body.provider, user_id=user.id)
    return {"ok": True, "id": acc.id}


@app.delete("/api/calendar/accounts/{account_id}")
def calendar_account_remove(account_id: str, user: User = Depends(current_user),
                            db: Session = Depends(get_db)):
    acc = db.get(CalendarAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(404, "Account not found")
    db.delete(acc)
    db.commit()
    return {"ok": True}


@app.post("/api/calendar/accounts/{account_id}/sync")
def calendar_account_sync(account_id: str, user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Push every local event of this user to the given account now."""
    acc = db.get(CalendarAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(404, "Account not found")
    cfg = _get_cfg()
    evs = db.query(CalendarEvent).filter(CalendarEvent.user_id == user.id).all()
    for ev in evs:
        calendar_sync.sync_event(db, ev, "update" if json.loads(ev.remote_ids or "{}").get(acc.id) else "create", cfg)
    db.refresh(acc)
    return {"ok": True, "status": acc.status, "error": acc.last_error, "events": len(evs)}


@app.get("/api/calendar/oauth/{provider}/start")
def calendar_oauth_start(provider: str, request: Request,
                         user: User = Depends(current_user)):
    """Return the URL where the user signs in with their own Google/Microsoft
    account; the consent screen requests calendar permission."""
    import secrets as _secrets
    if provider not in ("google", "microsoft"):
        raise HTTPException(422, "Unsupported OAuth provider")
    redirect = str(request.base_url).rstrip("/") + f"/api/calendar/oauth/{provider}/callback"
    state = _secrets.token_urlsafe(24)
    _oauth_states[state] = {"user_id": user.id, "provider": provider,
                            "redirect": redirect, "ts": _time.time()}
    try:
        url = calendar_sync.oauth_start_url(provider, _get_cfg(), redirect, state)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"url": url}


@app.get("/api/calendar/oauth/{provider}/callback")
def calendar_oauth_callback(provider: str, code: str = "", state: str = "",
                            error: str = "", db: Session = Depends(get_db)):
    from fastapi.responses import HTMLResponse
    ctx = _oauth_states.pop(state, None)
    done = "<script>setTimeout(function(){window.close()},2500)</script>"
    if error or not ctx or ctx["provider"] != provider or not code:
        return HTMLResponse(f"<h3>❌ Calendar connection failed: {error or 'invalid state'}</h3>{done}")
    try:
        tok = calendar_sync.oauth_exchange(provider, _get_cfg(), ctx["redirect"], code)
    except ValueError as e:
        return HTMLResponse(f"<h3>❌ {e}</h3>{done}")
    secret = {"access_token": tok.get("access_token", ""),
              "refresh_token": tok.get("refresh_token", ""),
              "expires_at": _time.time() + int(tok.get("expires_in", 3600))}
    acc = CalendarAccount(user_id=ctx["user_id"], provider=provider,
                          label="Google Calendar" if provider == "google" else "Outlook Calendar",
                          config="{}",
                          encrypted_secret=encrypt_secret(json.dumps(secret)),
                          status="connected")
    db.add(acc)
    db.commit()
    return HTMLResponse("<h3>✅ Calendar connected! You can close this window.</h3>" + done)


# ==================== Bluetooth calendar sync ====================
from . import bluetooth_sync  # noqa: E402


@app.get("/api/bluetooth/status")
def bluetooth_status(user: User = Depends(current_user)):
    """Bluetooth radio availability on this computer (shown in System Status)."""
    return bluetooth_sync.adapter_status()


@app.post("/api/bluetooth/scan")
def bluetooth_scan(user: User = Depends(current_user)):
    """Discover nearby phones so the user can choose which one to sync to."""
    st = bluetooth_sync.adapter_status()
    if not st["available"]:
        raise HTTPException(422, "No Bluetooth adapter found on this computer")
    if not st["enabled"]:
        raise HTTPException(422, "Bluetooth is turned OFF — enable it in the OS settings")
    return {"devices": bluetooth_sync.scan(15)}


class BtSyncIn(BaseModel):
    address: str = Field(min_length=11, max_length=23)
    name: str = ""


@app.post("/api/bluetooth/pair")
def bluetooth_pair(body: BtSyncIn, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    """Pair with the chosen phone — returns paired successfully / failed."""
    res = bluetooth_sync.pair(body.address)
    audit(db, "bluetooth.pair", f"{body.name} {body.address} → {res['paired']}",
          user_id=user.id)
    return res


@app.post("/api/bluetooth/sync")
def bluetooth_sync_start(body: BtSyncIn, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Pair (if needed) and push the user's full calendar to the phone,
    with live stage/progress reporting via /api/bluetooth/sync/status."""
    evs = db.query(CalendarEvent).filter(CalendarEvent.user_id == user.id) \
        .order_by(CalendarEvent.start_at).all()
    if not evs:
        raise HTTPException(422, "Your calendar has no events to synchronize yet")
    if not bluetooth_sync.start_sync(body.address, body.name or body.address, evs):
        raise HTTPException(409, "A Bluetooth sync is already running")
    audit(db, "bluetooth.sync", f"{body.name} {body.address} ({len(evs)} events)",
          user_id=user.id)
    return {"ok": True, "events": len(evs)}


@app.get("/api/bluetooth/sync/status")
def bluetooth_sync_status(user: User = Depends(current_user)):
    return bluetooth_sync.get_state()


# -------- iPhone / iPad calendar subscription (iOS blocks Bluetooth OBEX) ----
import hashlib as _hashlib  # noqa: E402


def _feed_token(user_id: str) -> str:
    from .security import _load_key
    secret = _load_key()
    return _hashlib.sha256(user_id.encode() + b"|calfeed|" + secret).hexdigest()[:32]


def _lan_ip() -> str:
    """The LAN IP of the interface holding the default route (gateway/DNS) —
    the address phones on the same network must use to reach this server."""
    import socket as _socket
    try:
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))  # no packet is sent — just selects the route
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    try:
        ip = _socket.gethostbyname(_socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass
    return "127.0.0.1"


@app.get("/api/calendar/feed-url")
def calendar_feed_url(request: Request, user: User = Depends(current_user)):
    """Subscription URL for iPhone/iPad: iOS Calendar subscribes natively and
    auto-refreshes — the reliable sync path since iOS blocks Bluetooth push.
    Always uses the server's LAN IP (default-gateway interface), never
    127.0.0.1, so the phone can reach it over Wi-Fi."""
    host_hdr = request.headers.get("host", "")
    port = host_hdr.rsplit(":", 1)[1] if ":" in host_hdr else "8600"
    hostname = host_hdr.rsplit(":", 1)[0] if host_hdr else ""
    if hostname in ("127.0.0.1", "localhost", "", "0.0.0.0", "::1"):
        host = f"{_lan_ip()}:{port}"
    else:
        host = host_hdr  # already reached via a routable address
    token = _feed_token(user.id)
    return {"http_url": f"http://{host}/api/calendar/feed/{token}.ics",
            "webcal_url": f"webcal://{host}/api/calendar/feed/{token}.ics",
            "import_url": f"http://{host}/calendar/import/{token}",
            "lan_ip": _lan_ip()}


@app.get("/api/calendar/feed/{token}.ics")
def calendar_feed(token: str, db: Session = Depends(get_db)):
    """Public tokenized ICS feed (no session cookie — the phone's Calendar
    app fetches it). Token = HMAC of the user id, unguessable."""
    for u in db.query(User).all():
        if _feed_token(u.id) == token:
            evs = db.query(CalendarEvent).filter(CalendarEvent.user_id == u.id) \
                .order_by(CalendarEvent.start_at).all()
            payload = bluetooth_sync.build_ics(evs)
            return Response(content=payload, media_type="text/calendar",
                            headers={"Content-Disposition": 'inline; filename="nexacrew.ics"'})
    raise HTTPException(404, "Unknown calendar feed")


def _parse_ics(data: str) -> list:
    """Minimal RFC-5545 parser: returns list of event dicts from VEVENT blocks.
    Handles folded lines, DATE and DATE-TIME (incl. trailing Z / TZID params)."""
    import re as _re
    from datetime import datetime as _dt
    # unfold: CRLF followed by space/tab is a continuation
    text = data.replace("\r\n", "\n").replace("\r", "\n")
    text = _re.sub(r"\n[ \t]", "", text)
    events = []
    for block in _re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, _re.S):
        props = {}
        for line in block.strip().split("\n"):
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            name = key.split(";", 1)[0].upper()
            props.setdefault(name, (key, val.strip()))
        def _unesc(s):
            return s.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")
        def _when(prop):
            if prop not in props:
                return None, False
            key, val = props[prop]
            val = val.strip()
            if _re.fullmatch(r"\d{8}", val):  # all-day DATE
                return _dt.strptime(val, "%Y%m%d"), True
            m = _re.fullmatch(r"(\d{8})T(\d{6})Z?", val)
            if m:
                return _dt.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S"), False
            return None, False
        start, all_day = _when("DTSTART")
        if not start:
            continue
        end, _ = _when("DTEND")
        if not end:
            end = start
        events.append({
            "uid": props.get("UID", ("", ""))[1],
            "title": _unesc(props.get("SUMMARY", ("", "Untitled"))[1]) or "Untitled",
            "description": _unesc(props.get("DESCRIPTION", ("", ""))[1]),
            "location": _unesc(props.get("LOCATION", ("", ""))[1]),
            "start_at": start, "end_at": end, "all_day": all_day,
        })
    return events


def _import_ics_for_user(db: Session, user_id: str, raw: bytes,
                         mark_account_id: str = "") -> dict:
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if "BEGIN:VCALENDAR" not in text.upper():
        raise HTTPException(400, "Not a valid ICS calendar file")
    parsed = _parse_ics(text)
    existing = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id).all()
    seen = {(e.title, e.start_at) for e in existing}
    added = skipped = 0
    for ev in parsed:
        if (ev["title"], ev["start_at"]) in seen:
            skipped += 1
            continue
        row = CalendarEvent(user_id=user_id, title=ev["title"],
                            description=ev["description"], location=ev["location"],
                            start_at=ev["start_at"], end_at=ev["end_at"],
                            all_day=ev["all_day"])
        if mark_account_id:
            # came FROM this account — remember so two-way sync never echoes it back
            row.remote_ids = json.dumps({mark_account_id: ev.get("uid") or "imported"})
            row.sync_status = "synced"
        db.add(row)
        seen.add((ev["title"], ev["start_at"]))
        added += 1
    db.commit()
    return {"found": len(parsed), "imported": added, "skipped": skipped}


@app.post("/api/calendar/import")
async def calendar_import(file: UploadFile = File(...),
                          user: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Import an .ics file into the signed-in user's calendar (desktop upload)."""
    return _import_ics_for_user(db, user.id, await file.read())


def _feed_user(db: Session, token: str):
    for u in db.query(User).all():
        if _feed_token(u.id) == token:
            return u
    return None


@app.get("/calendar/import/{token}")
def calendar_import_page(token: str, db: Session = Depends(get_db)):
    """Mobile upload page (opened by scanning the QR code on the phone).
    Tokenized like the feed — no login needed on the phone; imports into the
    account the token belongs to. Offers two paths: iCloud public-calendar
    link (server fetches the ICS directly) or manual .ics file upload."""
    u = _feed_user(db, token)
    if not u:
        raise HTTPException(404, "Unknown import link")
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NexaCrew — Import calendar</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0f1420;color:#e8ecf4;
margin:0;padding:28px 16px;display:flex;flex-direction:column;align-items:center}}
.card{{background:#1a2233;border-radius:16px;padding:22px;max-width:440px;width:100%;margin-bottom:16px}}
h2{{margin:0 0 6px}} h3{{margin:0 0 8px;font-size:16px}}
p,li{{color:#9aa7bd;font-size:14px;line-height:1.65}}
ol{{margin:8px 0 12px 20px;padding:0}}
input[type=file]{{margin:12px 0;width:100%;color:#e8ecf4}}
input[type=url]{{width:100%;box-sizing:border-box;background:#0f1420;color:#e8ecf4;border:1px solid #2c3852;
border-radius:10px;padding:11px 12px;font-size:14px;margin:10px 0}}
button{{background:#4f7cff;color:#fff;border:0;border-radius:10px;padding:12px 22px;
font-size:15px;font-weight:600;width:100%}}
button.alt{{background:#2c3852}}
.res{{margin-top:12px;font-size:14px}}
b.acct{{color:#e8ecf4}}</style></head><body>
<div class="card"><h2>📥 Import calendar</h2>
<p>Importing into account <b class="acct">{u.username}</b>.</p></div>

<div class="card"><h3>🍎 iPhone — via iCloud (recommended)</h3>
<ol>
<li>Open the <b>Calendar</b> app on this iPhone.</li>
<li>Tap <b>Calendars</b> (bottom) → tap <b>ⓘ</b> next to the calendar you want.</li>
<li>Turn on <b>Public Calendar</b> → tap <b>Share Link…</b> → <b>Copy</b>.</li>
<li>Paste the link below — this server signs into nothing; it simply fetches
the public <b>webcal://</b> feed iCloud provides and imports the events.</li>
</ol>
<input type="url" id="iclink" placeholder="webcal://p12-caldav.icloud.com/published/2/…" autocomplete="off">
<button onclick="fromUrl()">🍎 Fetch from iCloud &amp; import</button>
<div class="res" id="res-url"></div></div>

<div class="card"><h3>📄 Or upload an .ics file</h3>
<p>Android / ChromeOS: Calendar app → <b>Export</b> saves an .ics file.
iPhone: any app or shortcut that saves the calendar as .ics also works.</p>
<input type="file" id="f" accept=".ics,text/calendar">
<button class="alt" onclick="up()">Upload &amp; import</button>
<div class="res" id="res-file"></div></div>
<script>
function show(id,ok,msg){{document.getElementById(id).innerHTML=(ok?'✅ ':'❌ ')+msg;}}
async function fromUrl(){{
  const url=document.getElementById('iclink').value.trim();
  if(!url){{show('res-url',false,'Paste the iCloud public-calendar link first.');return;}}
  document.getElementById('res-url').textContent='⏳ Fetching from iCloud…';
  try{{
    const resp=await fetch('/api/calendar/feed/{token}/import-url',{{method:'POST',
      headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{url:url}})}});
    const j=await resp.json();
    if(resp.ok)show('res-url',true,'Imported <b>'+j.imported+'</b> event(s), skipped '+j.skipped+' duplicate(s).');
    else show('res-url',false,j.detail||'Import failed');
  }}catch(e){{show('res-url',false,e);}}
}}
async function up(){{
  const f=document.getElementById('f').files[0];
  if(!f){{show('res-file',false,'Please choose an .ics file first.');return;}}
  document.getElementById('res-file').textContent='⏳ Uploading…';
  const fd=new FormData(); fd.append('file',f);
  try{{
    const resp=await fetch('/api/calendar/feed/{token}/import',{{method:'POST',body:fd}});
    const j=await resp.json();
    if(resp.ok)show('res-file',true,'Imported <b>'+j.imported+'</b> event(s), skipped '+j.skipped+' duplicate(s).');
    else show('res-file',false,j.detail||'Import failed');
  }}catch(e){{show('res-file',false,e);}}
}}
</script></body></html>"""
    return Response(content=html, media_type="text/html")


def _fetch_ics_from_url(url: str) -> bytes:
    """Fetch an ICS feed from a webcal:// or https:// URL (e.g. an iCloud
    public-calendar share link). webcal:// is just https:// underneath."""
    import urllib.request as _rq
    u = url.strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[9:]
    if not (u.lower().startswith("https://") or u.lower().startswith("http://")):
        raise HTTPException(400, "Link must start with webcal://, https:// or http://")
    try:
        req = _rq.Request(u, headers={"User-Agent": "NexaCrew-Calendar/1.0"})
        with _rq.urlopen(req, timeout=20) as resp:
            data = resp.read(5 * 1024 * 1024)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Could not fetch the calendar link: {e}")
    if b"BEGIN:VCALENDAR" not in data[:2000].upper():
        raise HTTPException(400, "The link did not return a valid calendar (ICS) feed")
    return data


# -------- iCloud CalDAV sign-in import (Apple's supported third-party path:
# Apple ID + app-specific password from appleid.apple.com; Apple offers no
# OAuth for iCloud Calendar) ----------------------------------------------
def _caldav_request(url: str, method: str, auth_header: str, body: str = "",
                    depth: str = "0", extra: dict = None) -> tuple:
    """One CalDAV/WebDAV request; returns (status, body_text)."""
    import urllib.request as _rq
    import urllib.error as _er
    headers = {"Authorization": auth_header,
               "User-Agent": "NexaCrew-Calendar/1.0",
               "Depth": depth,
               "Content-Type": 'application/xml; charset="utf-8"'}
    if extra:
        headers.update(extra)
    req = _rq.Request(url, data=body.encode("utf-8") if body else None,
                      headers=headers, method=method)
    try:
        with _rq.urlopen(req, timeout=25) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except _er.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _icloud_auth_header(apple_id: str, app_password: str) -> str:
    import base64 as _b64
    return "Basic " + _b64.b64encode(f"{apple_id}:{app_password}".encode()).decode()


# CalDAV cloud providers reachable with username + app password.
# apple: app-specific password from appleid.apple.com
# (Google removed: Google no longer allows App-Password Basic auth on CalDAV — OAuth only)
_CALDAV_PROVIDERS = {
    "apple": {
        "label": "iCloud",
        "base": "https://caldav.icloud.com",
        "start": lambda base, username: base + "/",
        "auth_help": "iCloud rejected the sign-in. Use an app-specific password "
                     "from appleid.apple.com → Sign-In and Security → App-Specific "
                     "Passwords (your normal iCloud password will NOT work here).",
        "skip_calendars": ("birthdays", "holidays", "siri suggestions"),
    },
}


def _icloud_discover_calendars(auth: str, provider: str = "apple",
                               username: str = "") -> list:
    """Sign in and return [(absolute_calendar_url, display_name), ...].
    Raises HTTPException with a friendly message on auth/discovery failure."""
    from xml.etree import ElementTree as _ET
    prov = _CALDAV_PROVIDERS[provider]
    base = prov["base"]

    def _hrefs_from(xml_text: str, prop_tag: str) -> list:
        out = []
        try:
            root = _ET.fromstring(xml_text)
        except _ET.ParseError:
            return out
        for el in root.iter():
            if el.tag.endswith("}" + prop_tag):
                for h in el.iter("{DAV:}href"):
                    if h.text:
                        out.append(h.text.strip())
        return out

    def _abs(href: str) -> str:
        if href.startswith("http"):
            return href
        # Google hrefs are absolute paths on apidata.googleusercontent.com
        root = base.split("/", 3)
        origin = root[0] + "//" + root[2]
        return origin + href

    st, body = _caldav_request(prov["start"](base, username), "PROPFIND", auth,
        '<?xml version="1.0"?><d:propfind xmlns:d="DAV:">'
        '<d:prop><d:current-user-principal/></d:prop></d:propfind>')
    if st in (401, 403):
        raise HTTPException(401, prov["auth_help"])
    if st not in (207, 200):
        raise HTTPException(502, f"{prov['label']} CalDAV discovery failed (HTTP {st})")
    principals = _hrefs_from(body, "current-user-principal")
    if not principals:
        raise HTTPException(502, f"Could not locate the {prov['label']} account principal")
    principal_url = _abs(principals[0])

    st, body = _caldav_request(principal_url, "PROPFIND", auth,
        '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" '
        'xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><c:calendar-home-set/></d:prop></d:propfind>')
    if st in (401, 403):
        raise HTTPException(401, prov["auth_help"])
    homes = _hrefs_from(body, "calendar-home-set")
    if not homes:
        raise HTTPException(502, f"Could not locate the {prov['label']} calendar home")
    home = _abs(homes[0])

    st, body = _caldav_request(home, "PROPFIND", auth,
        '<?xml version="1.0"?><d:propfind xmlns:d="DAV:" '
        'xmlns:c="urn:ietf:params:xml:ns:caldav">'
        '<d:prop><d:resourcetype/><d:displayname/></d:prop></d:propfind>',
        depth="1")
    cal_urls = []
    try:
        root = _ET.fromstring(body)
        for resp in root.iter("{DAV:}response"):
            href_el = resp.find("{DAV:}href")
            if href_el is None or not href_el.text:
                continue
            is_cal = any(True for el in resp.iter()
                         if el.tag == "{urn:ietf:params:xml:ns:caldav}calendar")
            if is_cal:
                name_el = resp.find(".//{DAV:}displayname")
                name = (name_el.text or "").strip() if name_el is not None else ""
                cal_urls.append((_abs(href_el.text.strip()), name or "Calendar"))
    except _ET.ParseError:
        pass
    if not cal_urls:
        raise HTTPException(502, f"No calendars found in this {prov['label']} account")
    return cal_urls


def _icloud_fetch_ics(apple_id: str, app_password: str, progress=None,
                      provider: str = "apple") -> bytes:
    """Sign into the cloud CalDAV server and return every event as one merged VCALENDAR."""
    import re as _re
    prov = _CALDAV_PROVIDERS[provider]
    auth = _icloud_auth_header(apple_id, app_password)
    cal_urls = _icloud_discover_calendars(auth, provider, apple_id)

    merged = ["BEGIN:VCALENDAR", "VERSION:2.0",
              f"PRODID:-//NexaCrew//{prov['label']} import//EN"]
    total = 0
    for cal_url, name in cal_urls:
        st, body = _caldav_request(cal_url, "REPORT", auth,
            '<?xml version="1.0"?><c:calendar-query xmlns:d="DAV:" '
            'xmlns:c="urn:ietf:params:xml:ns:caldav">'
            '<d:prop><c:calendar-data/></d:prop>'
            '<c:filter><c:comp-filter name="VCALENDAR">'
            '<c:comp-filter name="VEVENT"/></c:comp-filter></c:filter>'
            '</c:calendar-query>', depth="1")
        if st not in (207, 200):
            continue
        for blob in _re.findall(r"BEGIN:VEVENT.*?END:VEVENT",
                                body.replace("&#13;", ""), _re.S):
            merged.append(blob.strip())
            total += 1
        if progress:
            progress(f"{name}: fetched")
    merged.append("END:VCALENDAR")
    if total == 0:
        raise HTTPException(404, "Signed in successfully, but no events were found "
                                 f"in any {prov['label']} calendar")
    return "\r\n".join(merged).encode("utf-8")


async def _cloud_import(provider: str, request: Request, user: User, db: Session):
    body = await request.json()
    username = str(body.get("apple_id") or body.get("username") or "").strip()
    app_password = str(body.get("app_password", "")).strip()
    save = bool(body.get("save", True))
    if not username or not app_password:
        raise HTTPException(400, "Account email and app password are required")
    from starlette.concurrency import run_in_threadpool
    data = await run_in_threadpool(_icloud_fetch_ics, username, app_password,
                                   None, provider)
    acct = None
    if save:
        acct = _icloud_save_account(db, user.id, username, app_password, provider)
    result = _import_ics_for_user(db, user.id, data,
                                  mark_account_id=acct.id if acct else "")
    if acct:
        result["account_saved"] = True
        result["account_label"] = acct.label
    return result


@app.post("/api/calendar/icloud/import")
async def calendar_icloud_import(request: Request, user: User = Depends(current_user),
                                 db: Session = Depends(get_db)):
    """Sign into iCloud via CalDAV (Apple ID + app-specific password) and import
    all events; credentials stored encrypted for continuous two-way sync."""
    return await _cloud_import("apple", request, user, db)


# -------- connected cloud accounts (apple / google_app): save + two-way sync ----
def _icloud_save_account(db: Session, user_id: str, username: str,
                         app_password: str, provider: str = "apple") -> "CalendarAccount":
    """Store/refresh the cloud connection with the app-password encrypted at rest."""
    from .security import encrypt_secret
    acct = db.query(CalendarAccount).filter(
        CalendarAccount.user_id == user_id,
        CalendarAccount.provider == provider).first()
    if not acct:
        acct = CalendarAccount(user_id=user_id, provider=provider)
        db.add(acct)
    acct.label = username
    acct.encrypted_secret = encrypt_secret(json.dumps(
        {"apple_id": username, "app_password": app_password}))
    acct.status = "connected"
    acct.last_error = ""
    acct.last_sync_at = dt.datetime.utcnow()
    db.commit()
    return acct


def _icloud_creds(acct) -> tuple:
    from .security import decrypt_secret
    d = json.loads(decrypt_secret(acct.encrypted_secret))
    return d.get("apple_id") or d.get("username"), d["app_password"]


def _icloud_target_calendar(auth: str, provider: str = "apple", username: str = "") -> str:
    """URL of the calendar NexaCrew events are written to — the account's
    first personal calendar (usually the default)."""
    cals = _icloud_discover_calendars(auth, provider, username)
    skip = _CALDAV_PROVIDERS[provider]["skip_calendars"]
    for url, name in cals:
        if not any(s in name.lower() for s in skip):
            return url
    return cals[0][0]


def _icloud_event_ics(ev) -> str:
    """A single-event VCALENDAR for CalDAV PUT, uid = nexacrew-<event id>."""
    from .bluetooth_sync import build_ics
    return build_ics([ev]).decode("utf-8")


def _icloud_push_event(db: Session, ev, action: str) -> None:
    """Push a create/update/delete of one event to every connected cloud
    account (iCloud and/or Google). Silent no-op when none is connected."""
    accts = db.query(CalendarAccount).filter(
        CalendarAccount.user_id == ev.user_id,
        CalendarAccount.provider.in_(list(_CALDAV_PROVIDERS)),
        CalendarAccount.status == "connected").all()
    for acct in accts:
        if acct.encrypted_secret:
            _cloud_push_one(db, acct, ev, action)


def _cloud_push_one(db: Session, acct, ev, action: str) -> None:
    provider = acct.provider
    label = _CALDAV_PROVIDERS[provider]["label"]
    try:
        username, app_password = _icloud_creds(acct)
        auth = _icloud_auth_header(username, app_password)
        cfg = json.loads(acct.config or "{}")
        cal_url = cfg.get("target_calendar")
        if not cal_url:
            cal_url = _icloud_target_calendar(auth, provider, username)
            cfg["target_calendar"] = cal_url
            acct.config = json.dumps(cfg)
        if not cal_url.endswith("/"):
            cal_url += "/"
        remote = json.loads(ev.remote_ids or "{}")
        href = remote.get(acct.id) or (cal_url + f"nexacrew-{ev.id}.ics")
        if action == "delete":
            _caldav_request(href, "DELETE", auth)
        else:
            ics = _icloud_event_ics(ev)
            st, body = _caldav_request(href, "PUT", auth, ics,
                                       extra={"Content-Type": "text/calendar; charset=utf-8"})
            if st in (401, 403):
                raise RuntimeError(f"{label} sign-in expired — reconnect the account")
            if st >= 400 and st != 412:
                raise RuntimeError(f"{label} rejected the event (HTTP {st})")
            remote[acct.id] = href
            ev.remote_ids = json.dumps(remote)
            ev.sync_status = "synced"
        acct.last_sync_at = dt.datetime.utcnow()
        acct.last_error = ""
        db.commit()
    except HTTPException as e:
        acct.status = "error"
        acct.last_error = str(e.detail)
        if action != "delete":
            ev.sync_status = "error"
        db.commit()
    except Exception as e:  # noqa: BLE001
        acct.last_error = str(e)
        if action != "delete":
            ev.sync_status = "error"
        db.commit()


# every event create/update/delete (UI, prompt, import) funnels through
# calendar_sync.sync_event — register the iCloud push there
calendar_sync.icloud_push_hook = _icloud_push_event


def _cloud_account_info(provider: str, user: User, db: Session):
    acct = db.query(CalendarAccount).filter(
        CalendarAccount.user_id == user.id,
        CalendarAccount.provider == provider).first()
    if not acct:
        return {"connected": False}
    return {"connected": acct.status == "connected", "label": acct.label,
            "status": acct.status, "last_error": acct.last_error,
            "last_sync_at": acct.last_sync_at.isoformat() if acct.last_sync_at else None}


def _cloud_disconnect(provider: str, user: User, db: Session):
    acct = db.query(CalendarAccount).filter(
        CalendarAccount.user_id == user.id,
        CalendarAccount.provider == provider).first()
    if acct:
        db.delete(acct)
        db.commit()
    return {"ok": True}


async def _cloud_sync(provider: str, user: User, db: Session):
    """Two-way sync with the saved cloud account:
    1. pull — import every remote event not yet in NexaCrew
    2. push — upload every NexaCrew event not yet in the cloud"""
    label = _CALDAV_PROVIDERS[provider]["label"]
    acct = db.query(CalendarAccount).filter(
        CalendarAccount.user_id == user.id,
        CalendarAccount.provider == provider).first()
    if not acct or not acct.encrypted_secret:
        raise HTTPException(404, f"No saved {label} account — sign in first")
    username, app_password = _icloud_creds(acct)
    from starlette.concurrency import run_in_threadpool

    try:
        data = await run_in_threadpool(_icloud_fetch_ics, username, app_password,
                                       None, provider)
        pulled = _import_ics_for_user(db, user.id, data, mark_account_id=acct.id)
    except HTTPException as e:
        if e.status_code == 404:  # empty remote calendars is fine
            pulled = {"found": 0, "imported": 0, "skipped": 0}
        else:
            acct.status = "error"
            acct.last_error = str(e.detail)
            db.commit()
            raise

    evs = db.query(CalendarEvent).filter(CalendarEvent.user_id == user.id).all()
    pushed = 0
    for ev in evs:
        remote = json.loads(ev.remote_ids or "{}")
        if acct.id not in remote or ev.sync_status == "error":
            await run_in_threadpool(_cloud_push_one, db, acct, ev, "update")
            db.refresh(ev)
            if json.loads(ev.remote_ids or "{}").get(acct.id):
                pushed += 1
    acct.status = "connected" if not acct.last_error else acct.status
    acct.last_sync_at = dt.datetime.utcnow()
    db.commit()
    return {"pulled": pulled, "pushed": pushed,
            "last_error": acct.last_error or None}


@app.get("/api/calendar/icloud/account")
def calendar_icloud_account(user: User = Depends(current_user),
                            db: Session = Depends(get_db)):
    return _cloud_account_info("apple", user, db)


@app.delete("/api/calendar/icloud/account")
def calendar_icloud_disconnect(user: User = Depends(current_user),
                               db: Session = Depends(get_db)):
    return _cloud_disconnect("apple", user, db)


@app.post("/api/calendar/icloud/sync")
async def calendar_icloud_sync(user: User = Depends(current_user),
                               db: Session = Depends(get_db)):
    return await _cloud_sync("apple", user, db)


@app.post("/api/calendar/feed/{token}/import-url")
async def calendar_import_url_by_token(token: str, request: Request,
                                       db: Session = Depends(get_db)):
    """Import from an iCloud public-calendar (webcal://) or any ICS URL —
    used by the QR-opened mobile page."""
    u = _feed_user(db, token)
    if not u:
        raise HTTPException(404, "Unknown import link")
    body = await request.json()
    from starlette.concurrency import run_in_threadpool
    data = await run_in_threadpool(_fetch_ics_from_url, str(body.get("url", "")))
    return _import_ics_for_user(db, u.id, data)


@app.post("/api/calendar/import-url")
async def calendar_import_url(request: Request, user: User = Depends(current_user),
                              db: Session = Depends(get_db)):
    """Import from an iCloud public-calendar / ICS URL for the signed-in user."""
    body = await request.json()
    from starlette.concurrency import run_in_threadpool
    data = await run_in_threadpool(_fetch_ics_from_url, str(body.get("url", "")))
    return _import_ics_for_user(db, user.id, data)


@app.post("/api/calendar/feed/{token}/import")
async def calendar_import_by_token(token: str, file: UploadFile = File(...),
                                   db: Session = Depends(get_db)):
    """Tokenized import used by the mobile page — same token as the feed URL."""
    u = _feed_user(db, token)
    if not u:
        raise HTTPException(404, "Unknown import link")
    return _import_ics_for_user(db, u.id, await file.read())


# ==================== Email (personal IMAP accounts) ====================
from . import mailbox as mailbox_mod  # noqa: E402
from .db import MailAccount  # noqa: E402


def _mail_acct(db: Session, user: User, account_id: str) -> MailAccount:
    acct = db.get(MailAccount, account_id)
    if not acct or acct.user_id != user.id:
        raise HTTPException(404, "Mail account not found")
    return acct


def _mail_acct_d(a: MailAccount) -> dict:
    return {"id": a.id, "label": a.label, "imap_host": a.imap_host,
            "imap_port": a.imap_port, "use_ssl": bool(a.use_ssl),
            "auth_method": a.auth_method, "username": a.username,
            "smtp_host": a.smtp_host or "", "smtp_port": a.smtp_port or 465,
            "is_gmail": "gmail" in (a.imap_host or "").lower(),
            "status": a.status, "last_error": a.last_error,
            "last_checked_at": a.last_checked_at.isoformat() if a.last_checked_at else None}


@app.get("/api/mail/accounts")
def mail_accounts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    accts = db.query(MailAccount).filter(MailAccount.user_id == user.id) \
        .order_by(MailAccount.created_at).all()
    return [_mail_acct_d(a) for a in accts]


class MailAccountIn(BaseModel):
    label: str = ""
    imap_host: str
    imap_port: int = 993
    use_ssl: bool = True
    auth_method: str = "password"     # password | oauth2
    username: str
    password: str = ""                # password OR oauth2 access token
    smtp_host: str = ""               # blank = auto (imap.x → smtp.x)
    smtp_port: int = 465


@app.post("/api/mail/accounts")
async def mail_account_add(body: MailAccountIn, user: User = Depends(current_user),
                           db: Session = Depends(get_db)):
    if not body.password:
        raise HTTPException(400, "Password / token is required")
    acct = mailbox_mod.save_account(db, user.id, body.dict())
    from starlette.concurrency import run_in_threadpool
    r = await run_in_threadpool(mailbox_mod.test_account, acct)
    db.commit()
    audit(db, "mail.connect", acct.username, user_id=user.id)
    return {**_mail_acct_d(acct), "test": r}


@app.put("/api/mail/accounts/{account_id}")
async def mail_account_update(account_id: str, body: MailAccountIn,
                              user: User = Depends(current_user),
                              db: Session = Depends(get_db)):
    acct = _mail_acct(db, user, account_id)
    mailbox_mod.save_account(db, user.id, body.dict(), acct)
    from starlette.concurrency import run_in_threadpool
    r = await run_in_threadpool(mailbox_mod.test_account, acct)
    db.commit()
    return {**_mail_acct_d(acct), "test": r}


@app.delete("/api/mail/accounts/{account_id}")
def mail_account_remove(account_id: str, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    acct = _mail_acct(db, user, account_id)
    db.delete(acct)
    db.commit()
    audit(db, "mail.disconnect", acct.username, user_id=user.id)
    return {"ok": True}


@app.post("/api/mail/accounts/{account_id}/test")
async def mail_account_test(account_id: str, user: User = Depends(current_user),
                            db: Session = Depends(get_db)):
    acct = _mail_acct(db, user, account_id)
    from starlette.concurrency import run_in_threadpool
    r = await run_in_threadpool(mailbox_mod.test_account, acct)
    db.commit()
    return r


@app.get("/api/mail/accounts/{account_id}/folders")
async def mail_folders(account_id: str, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    acct = _mail_acct(db, user, account_id)
    from starlette.concurrency import run_in_threadpool
    try:
        folders = await run_in_threadpool(mailbox_mod.list_folders, acct)
        acct.status, acct.last_error = "connected", ""
        acct.last_checked_at = dt.datetime.utcnow()
        db.commit()
        return folders
    except Exception as e:  # noqa: BLE001
        acct.status, acct.last_error = "error", str(e)[:300]
        db.commit()
        raise HTTPException(502, f"IMAP error: {str(e)[:200]}")


@app.get("/api/mail/accounts/{account_id}/messages")
async def mail_messages(account_id: str, folder: str = "INBOX", limit: int = 50,
                        page: int = 0, q: str = "", unseen: int = 0, category: str = "",
                        user: User = Depends(current_user), db: Session = Depends(get_db)):
    acct = _mail_acct(db, user, account_id)
    from starlette.concurrency import run_in_threadpool
    try:
        r = await run_in_threadpool(mailbox_mod.list_messages, acct, folder,
                                    min(limit, 100), page, q, bool(unseen), category)
        acct.status, acct.last_error = "connected", ""
        acct.last_checked_at = dt.datetime.utcnow()
        db.commit()
        return r
    except Exception as e:  # noqa: BLE001
        acct.status, acct.last_error = "error", str(e)[:300]
        db.commit()
        raise HTTPException(502, f"IMAP error: {str(e)[:200]}")


@app.get("/api/mail/accounts/{account_id}/messages/{uid}")
async def mail_message(account_id: str, uid: str, folder: str = "INBOX",
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    acct = _mail_acct(db, user, account_id)
    from starlette.concurrency import run_in_threadpool
    try:
        return await run_in_threadpool(mailbox_mod.fetch_message, acct, folder, uid, True)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"IMAP error: {str(e)[:200]}")


class MailActionIn(BaseModel):
    action: str                       # read | unread | flag | unflag | delete
    folder: str = "INBOX"


@app.post("/api/mail/accounts/{account_id}/messages/{uid}/action")
async def mail_message_action(account_id: str, uid: str, body: MailActionIn,
                              user: User = Depends(current_user),
                              db: Session = Depends(get_db)):
    acct = _mail_acct(db, user, account_id)
    from starlette.concurrency import run_in_threadpool
    try:
        r = await run_in_threadpool(mailbox_mod.message_action, acct,
                                    body.folder, uid, body.action)
        audit(db, f"mail.{body.action}", f"{acct.username} uid={uid}", user_id=user.id)
        return r
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"IMAP error: {str(e)[:200]}")


class MailSendIn(BaseModel):
    mode: str = "compose"             # compose | reply | replyall | forward
    folder: str = "INBOX"
    uid: str = ""                     # original message for reply / forward
    to: str = ""
    cc: str = ""
    subject: str = ""
    body: str = ""


@app.post("/api/mail/accounts/{account_id}/send")
async def mail_send(account_id: str, body: MailSendIn,
                    user: User = Depends(current_user), db: Session = Depends(get_db)):
    acct = _mail_acct(db, user, account_id)
    from starlette.concurrency import run_in_threadpool
    try:
        if body.mode in ("reply", "replyall"):
            if not body.uid:
                raise HTTPException(400, "uid of the original message is required")
            r = await run_in_threadpool(mailbox_mod.reply_message, acct, body.folder,
                                        body.uid, body.body, body.mode == "replyall")
        elif body.mode == "forward":
            if not body.uid or not body.to:
                raise HTTPException(400, "uid and to are required for forward")
            r = await run_in_threadpool(mailbox_mod.forward_message, acct, body.folder,
                                        body.uid, body.to, body.body)
        else:
            if not body.to or not body.subject:
                raise HTTPException(400, "to and subject are required")
            r = await run_in_threadpool(mailbox_mod.send_message, acct, body.to,
                                        body.subject, body.body, body.cc)
        audit(db, f"mail.{body.mode}", f"{acct.username} → {body.to or 'thread'}",
              user_id=user.id)
        return r
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Send failed: {str(e)[:250]}")


# ==================== Workforce, Visitor & Access Control ====================
# handoff/Enterprise_Workforce_Visitor_Access_POS_Prompt.md — badges, kiosk
# enrollment, time & attendance, payroll, visitor management, access decisions.
from . import workforce as wf_mod  # noqa: E402
from .db import (AccessEvent, DeviceEnrollment, DoorGate,  # noqa: E402
                 PayrollBatch, TimeAdjustment, TimePunch, Visit, WorkerBadge)


def _require_device(db: Session, cred: str, kind: str | None = None) -> DeviceEnrollment:
    d = wf_mod.find_device_by_credential(db, (cred or "").strip())
    if not d or (kind and d.kind != kind):
        raise HTTPException(401, "Invalid, revoked or wrong-type device credential")
    return d


# ---- admin: badges ----
@app.get("/api/workforce/badges")
def badges_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(WorkerBadge).filter(WorkerBadge.user_id == user.id)
            .order_by(WorkerBadge.created_at.desc()).all())
    out = []
    for b in rows:
        token = ""
        if b.status == "active" and (getattr(b, "token_enc", "") or ""):
            try:
                token = _dec(b.token_enc)
            except Exception:
                token = ""
        out.append({"id": b.id, "worker_name": b.worker_name, "status": b.status,
                    "issued_by": b.issued_by,
                    "token": token,
                    "qr_png": _qr_data_uri(token) if token else "",
                    "expires_at": b.expires_at.isoformat() if b.expires_at else None,
                    "last_used_at": b.last_used_at.isoformat() if b.last_used_at else None,
                    "last_used_site": b.last_used_site, "revoke_reason": b.revoke_reason,
                    "lifecycle": json.loads(b.lifecycle or "[]"),
                    "created_at": b.created_at.isoformat()})
    return out


def _qr_data_uri(payload: str) -> str:
    """PNG QR code as a data URI. Generated only at issuance time — the
    server stores just the token hash, so a QR can never be regenerated."""
    try:
        import base64
        import io

        import qrcode
        img = qrcode.make(payload, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:  # noqa: BLE001 — token text still works without an image
        logging.getLogger("workforce").error(
            "QR image generation failed (%s: %s) — install the 'qrcode' "
            "package (pip install qrcode) and restart", type(e).__name__, e)
        return ""


@app.post("/api/workforce/badges")
def badge_issue(body: dict, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    name = str(body.get("worker_name") or "").strip()
    if not name:
        raise HTTPException(422, "worker_name is required")
    b, token = wf_mod.issue_badge(db, user.id, name,
                                  worker_record_id=str(body.get("worker_record_id") or ""),
                                  issued_by=user.username,
                                  expires_days=int(body.get("expires_days") or 0))
    audit(db, "workforce.badge.issue", f"{name} badge={b.id[:8]}", user_id=user.id)
    # the token is shown exactly once; only its hash is stored
    return {"ok": True, "badge_id": b.id, "badge_token": token,
            "qr_png": _qr_data_uri(token)}


@app.get("/api/workforce/badges/{bid}/qr")
def badge_qr(bid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Re-view / save an ACTIVE badge's QR. The token is kept encrypted at
    rest (Fernet); revoked badges have it wiped permanently. Access is
    session-guarded and audited."""
    b = (db.query(WorkerBadge).filter(WorkerBadge.id == bid,
                                      WorkerBadge.user_id == user.id).first())
    if not b:
        raise HTTPException(404, "Badge not found")
    if b.status != "active" or not (b.token_enc or ""):
        raise HTTPException(409, "QR unavailable — badge is not active (re-issue to get a new QR)")
    try:
        token = _dec(b.token_enc)
    except Exception:
        raise HTTPException(409, "QR unavailable — stored credential cannot be decrypted")
    audit(db, "workforce.badge.qr_view", f"{b.worker_name} badge={b.id[:8]}", user_id=user.id)
    db.commit()
    return {"ok": True, "worker_name": b.worker_name, "qr_png": _qr_data_uri(token)}


@app.post("/api/workforce/badges/{bid}/revoke")
def badge_revoke(bid: str, body: dict, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    b = (db.query(WorkerBadge).filter(WorkerBadge.id == bid,
                                      WorkerBadge.user_id == user.id).first())
    if not b:
        raise HTTPException(404, "Badge not found")
    wf_mod.revoke_badge(db, b, by=user.username, reason=str(body.get("reason") or ""))
    audit(db, "workforce.badge.revoke", f"{b.worker_name} badge={b.id[:8]}", user_id=user.id)
    return {"ok": True}


# ---- admin: device enrollment / fleet ----
@app.get("/api/workforce/devices")
def devices_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(DeviceEnrollment).filter(DeviceEnrollment.user_id == user.id)
            .order_by(DeviceEnrollment.created_at.desc()).all())
    out = []
    for d in rows:
        code = ""
        if (d.status == "pending" and (getattr(d, "code_enc", "") or "")
                and (not d.code_expires_at or d.code_expires_at > dt.datetime.utcnow())):
            try:
                code = _dec(d.code_enc)
            except Exception:
                code = ""
        out.append({"id": d.id, "kind": d.kind, "name": d.name, "site": d.site,
                    "status": d.status, "approved_by": d.approved_by,
                    "enroll_code": code,
                    "code_qr_png": _qr_data_uri(code) if code else "",
                    "code_expires_at": d.code_expires_at.isoformat() if d.code_expires_at else None,
                    "enrolled_at": d.enrolled_at.isoformat() if d.enrolled_at else None,
                    "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
                    "client_info": d.client_info})
    return out


@app.post("/api/workforce/devices/enroll-code")
def device_enroll_code(body: dict, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    e, code = wf_mod.create_enrollment(db, user.id,
                                       kind=str(body.get("kind") or "checkin"),
                                       name=str(body.get("name") or "Kiosk"),
                                       site=str(body.get("site") or ""),
                                       approved_by=user.username)
    audit(db, "workforce.device.enroll_code", f"{e.name} ({e.kind})", user_id=user.id)
    return {"ok": True, "enrollment_id": e.id, "code": code,
            "expires_minutes": wf_mod.ENROLL_CODE_TTL_MIN,
            "qr_png": _qr_data_uri(code)}


@app.post("/api/workforce/devices/{did}/revoke")
def device_revoke(did: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    d = (db.query(DeviceEnrollment).filter(DeviceEnrollment.id == did,
                                           DeviceEnrollment.user_id == user.id).first())
    if not d:
        raise HTTPException(404, "Device not found")
    d.status = "revoked"
    d.credential_hash = ""
    db.commit()
    audit(db, "workforce.device.revoke", d.name, user_id=user.id)
    return {"ok": True}


# ---- device (kiosk) endpoints — credential-authenticated, no session ----
@app.post("/api/workforce/enroll")
def device_enroll(body: dict, db: Session = Depends(get_db)):
    """Exchange a single-use enrollment code for a device-bound credential.
    The credential is returned once; store it in the device's secure storage."""
    e, cred_or_reason = wf_mod.exchange_enrollment(
        db, str(body.get("code") or ""), client_info=str(body.get("client_info") or ""))
    if e is None:
        raise HTTPException(401, f"Enrollment failed: {cred_or_reason}")
    audit(db, "workforce.device.enrolled", e.name, user_id=e.user_id)
    return {"ok": True, "device_id": e.id, "kind": e.kind, "name": e.name,
            "site": e.site, "credential": cred_or_reason}


@app.post("/api/workforce/scan")
def worker_scan(body: dict, db: Session = Depends(get_db)):
    """Badge scan at a check-in kiosk.
    Worker badges (wb-…) → immutable punch. Visitor badges (vb-…) are also
    accepted: the scan validates the visitor badge and toggles the visit
    between checked-in and checked-out. The kiosk never learns PII beyond
    the display name."""
    d = _require_device(db, str(body.get("device") or ""), kind="checkin")
    code = str(body.get("badge") or "")
    if code.startswith("vb-"):
        v = (db.query(Visit)
             .filter(Visit.user_id == d.user_id,
                     Visit.badge_code_hash == wf_mod.sha256(code)).first())
        if not v:
            audit(db, "workforce.scan.denied", "visitor_badge_unknown", user_id=d.user_id)
            raise HTTPException(403, "Scan denied: visitor badge unknown or revoked")
        if v.badge_expires_at and v.badge_expires_at < dt.datetime.utcnow():
            audit(db, "workforce.scan.denied", "visitor_badge_expired", user_id=d.user_id)
            raise HTTPException(403, "Scan denied: visitor badge expired")
        if v.status == "checked_in":
            v.status = "checked_out"
            v.checked_out_at = dt.datetime.utcnow()
            v.badge_code_hash = ""      # badge invalid immediately
            wf_mod.visit_event(v, "checked_out", "checkin-kiosk")
            event = "out"
        elif v.status == "approved":
            v.status = "checked_in"
            v.checked_in_at = dt.datetime.utcnow()
            wf_mod.visit_event(v, "checked_in", "checkin-kiosk")
            event = "in"
        else:
            raise HTTPException(409, f"Visitor badge not usable in state '{v.status}'")
        db.commit()
        audit(db, "visitor.scan." + event, v.visitor_name, user_id=d.user_id)
        return {"ok": True, "worker": v.visitor_name + " (visitor)", "event": event,
                "result": "ok", "at": dt.datetime.utcnow().isoformat() + "Z",
                "idempotent": False}
    badge = wf_mod.find_badge_by_token(db, d.user_id, code)
    bad = wf_mod.validate_badge(badge)
    if bad:
        audit(db, "workforce.scan.denied", bad, user_id=d.user_id)
        raise HTTPException(403, f"Scan denied: {bad}")
    badge.last_used_at = dt.datetime.utcnow()
    badge.last_used_site = d.site
    p, idem = wf_mod.record_punch(
        db, d.user_id, worker_name=badge.worker_name,
        worker_record_id=badge.worker_record_id, badge_id=badge.id,
        device_id=d.id, site=d.site, event=str(body.get("event") or ""),
        source="badge", idempotency_key=str(body.get("idempotency_key") or ""))
    return {"ok": True, "worker": badge.worker_name, "event": p.event,
            "result": p.result, "at": p.at_utc.isoformat() + "Z",
            "idempotent": idem}


# ---- admin: time & attendance ----
@app.get("/api/workforce/punches")
def punches_list(worker: str = "", user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    q = db.query(TimePunch).filter(TimePunch.user_id == user.id)
    if worker:
        q = q.filter(TimePunch.worker_name == worker)
    rows = q.order_by(TimePunch.at_utc.desc()).limit(200).all()
    return [{"id": p.id, "worker": p.worker_name, "event": p.event,
             "at": p.at_utc.isoformat() + "Z", "site": p.site,
             "source": p.source, "result": p.result} for p in rows]


@app.get("/api/workforce/timecard")
def timecard_get(worker: str, day_from: str, day_to: str,
                 user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return wf_mod.timecard(db, user.id, worker, day_from, day_to)
    except ValueError:
        raise HTTPException(422, "Dates must be YYYY-MM-DD")


@app.post("/api/workforce/adjustments")
def adjustment_create(body: dict, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    a = TimeAdjustment(user_id=user.id,
                       worker_name=str(body.get("worker") or "")[:120],
                       day=str(body.get("day") or "")[:10],
                       minutes_delta=int(body.get("minutes_delta") or 0),
                       reason=str(body.get("reason") or "")[:500],
                       requested_by=user.username, status="pending")
    if not a.worker_name or not a.day or not a.reason.strip():
        raise HTTPException(422, "worker, day and reason are required")
    db.add(a)
    db.commit()
    audit(db, "workforce.adjustment.request",
          f"{a.worker_name} {a.day} {a.minutes_delta:+}m", user_id=user.id)
    return {"ok": True, "id": a.id}


@app.post("/api/workforce/adjustments/{aid}/decide")
def adjustment_decide(aid: str, body: dict, user: User = Depends(current_user),
                      db: Session = Depends(get_db)):
    a = (db.query(TimeAdjustment).filter(TimeAdjustment.id == aid,
                                         TimeAdjustment.user_id == user.id).first())
    if not a:
        raise HTTPException(404, "Adjustment not found")
    if a.status != "pending":
        raise HTTPException(409, "Adjustment already decided")
    approve = bool(body.get("approve"))
    a.status = "approved" if approve else "rejected"
    a.approved_by = user.username
    db.commit()
    audit(db, "workforce.adjustment." + a.status, f"{a.worker_name} {a.day}", user_id=user.id)
    return {"ok": True, "status": a.status}


@app.get("/api/workforce/adjustments")
def adjustments_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(TimeAdjustment).filter(TimeAdjustment.user_id == user.id)
            .order_by(TimeAdjustment.created_at.desc()).limit(100).all())
    return [{"id": a.id, "worker": a.worker_name, "day": a.day,
             "minutes_delta": a.minutes_delta, "reason": a.reason,
             "status": a.status, "requested_by": a.requested_by,
             "approved_by": a.approved_by} for a in rows]


# ---- admin: payroll ----
@app.post("/api/workforce/payroll/batch")
def payroll_build(body: dict, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    ps, pe = str(body.get("period_start") or ""), str(body.get("period_end") or "")
    if not ps or not pe:
        raise HTTPException(422, "period_start and period_end are required (YYYY-MM-DD)")
    wages = body.get("wages") or {}
    batch, existed = wf_mod.build_payroll_batch(db, user.id, ps, pe, wages,
                                                by=user.username)
    if not existed:
        audit(db, "workforce.payroll.batch", f"{ps}..{pe}", user_id=user.id)
    return {"ok": True, "batch_id": batch.id, "existed": existed,
            "status": batch.status, "total_gross": batch.total_gross / 100.0,
            "lines": json.loads(batch.lines or "[]")}


@app.post("/api/workforce/payroll/{bid}/post")
def payroll_post(bid: str, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    batch = (db.query(PayrollBatch).filter(PayrollBatch.id == bid,
                                           PayrollBatch.user_id == user.id).first())
    if not batch:
        raise HTTPException(404, "Batch not found")
    je = wf_mod.approve_and_post_payroll(db, batch, by=user.username)
    audit(db, "workforce.payroll.post", f"batch={bid[:8]}", user_id=user.id)
    return {"ok": True, "status": batch.status,
            "journal_id": batch.journal_id, "posted": je is not None}


@app.get("/api/workforce/payroll")
def payroll_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(PayrollBatch).filter(PayrollBatch.user_id == user.id)
            .order_by(PayrollBatch.created_at.desc()).all())
    return [{"id": b.id, "period_start": b.period_start, "period_end": b.period_end,
             "status": b.status, "total_gross": b.total_gross / 100.0,
             "approved_by": b.approved_by, "journal_id": b.journal_id,
             "lines": json.loads(b.lines or "[]")} for b in rows]


@app.get("/api/workforce/payroll/{bid}/export.csv")
def payroll_export(bid: str, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    batch = (db.query(PayrollBatch).filter(PayrollBatch.id == bid,
                                           PayrollBatch.user_id == user.id).first())
    if not batch:
        raise HTTPException(404, "Batch not found")
    audit(db, "workforce.payroll.export", f"batch={bid[:8]}", user_id=user.id)
    from fastapi.responses import Response
    return Response(wf_mod.payroll_csv(batch), media_type="text/csv",
                    headers={"Content-Disposition":
                             f"attachment; filename=payroll_{batch.period_start}.csv"})


# ---- visitor kiosk (device-authenticated) ----
@app.post("/api/visitor/candidates")
def visitor_candidates(body: dict, db: Session = Depends(get_db)):
    """Returning-visitor candidate list for ON-DEVICE face recognition.
    The kiosk browser runs a real face-embedding model (face-api.js) and
    compares the live face with these stored portraits locally. Returns up
    to 5 photos PER distinct visitor (appearance varies between visits) —
    no identity numbers."""
    d = _require_device(db, str(body.get("device") or ""), kind="visitor")
    rows = (db.query(Visit)
            .filter(Visit.user_id == d.user_id, Visit.face_photo != "")
            .order_by(Visit.created_at.desc()).limit(300).all())
    by_name: dict[str, dict] = {}
    for v in rows:
        key = (v.visitor_name or "").strip().lower()
        if not key:
            continue
        if key not in by_name:
            if len(by_name) >= 100:
                continue
            by_name[key] = {"visitor_name": v.visitor_name,
                            "company": getattr(v, "company", "") or "",
                            "category": v.category, "host": v.host,
                            "purpose": v.purpose, "destination": v.destination,
                            "id_doc_type": v.id_doc_type, "language": v.language,
                            "last_visit": v.created_at.isoformat(),
                            "face_photo": v.face_photo, "face_photos": []}
        if len(by_name[key]["face_photos"]) < 5:
            by_name[key]["face_photos"].append(v.face_photo)
    return {"candidates": list(by_name.values())}


@app.post("/api/visitor/recognize")
def visitor_recognize(body: dict, db: Session = Depends(get_db)):
    """Returning-visitor face recognition at the unattended kiosk.
    Real face recognition stack: face_recognition (dlib 128-d encodings),
    DeepFace (Facenet512 verification) and OpenCV (decode/CLAHE/Haar).
    Accept rule: dlib distance ≤ 0.58, ambiguity margin only against a
    plausible runner-up, DeepFace veto only on borderline matches. No
    identity numbers are returned — masked only, same as the console."""
    d = _require_device(db, str(body.get("device") or ""), kind="visitor")
    face = str(body.get("face_photo") or "")
    if not face.startswith("data:image/") or len(face) > 400_000:
        raise HTTPException(422, "A face photo is required")

    # roster: up to 5 stored photos per distinct visitor
    rows = (db.query(Visit)
            .filter(Visit.user_id == d.user_id, Visit.face_photo != "")
            .order_by(Visit.created_at.desc()).limit(300).all())
    by_name: dict[str, dict] = {}
    for v in rows:
        key = (v.visitor_name or "").strip().lower()
        if not key:
            continue
        if key not in by_name:
            by_name[key] = {"visit": v, "visitor_name": v.visitor_name,
                            "face_photos": []}
        if len(by_name[key]["face_photos"]) < 5:
            by_name[key]["face_photos"].append(v.face_photo)

    from . import face_recog
    if face_recog.available():
        winner, info = face_recog.match_visitor(face, list(by_name.values()))
        if winner is None:
            audit(db, "visitor.recognize.miss",
                  f"{info.get('reason')} d={info.get('distance')} m={info.get('margin')}",
                  user_id=d.user_id)
            return {"match": False, "reason": info.get("reason"),
                    "distance": info.get("distance"), "margin": info.get("margin")}
        v = winner["visit"]
        sim = max(0.0, min(1.0, 1.0 - float(info.get("distance") or 0) / 1.0))
        audit(db, "visitor.recognize.hit",
              f"{v.visitor_name} d={info.get('distance')} m={info.get('margin')} "
              f"deepface={info.get('verified')}", user_id=d.user_id)
        return {"match": True, "similarity": round(sim, 3),
                "distance": info.get("distance"), "margin": info.get("margin"),
                "deepface_verified": info.get("verified"),
                "visitor_name": v.visitor_name,
                "company": getattr(v, "company", "") or "",
                "category": v.category, "host": v.host, "purpose": v.purpose,
                "destination": v.destination, "id_doc_type": v.id_doc_type,
                "language": v.language, "last_visit": v.created_at.isoformat(),
                "face_photo": v.face_photo}

    # legacy fallback (libraries missing): conservative pixel matcher
    match, score = wf_mod.recognize_visitor(db, d.user_id, face)
    if not match:
        audit(db, "visitor.recognize.miss", f"fallback best={score:.2f}", user_id=d.user_id)
        return {"match": False, "similarity": round(max(score, 0.0), 3)}
    audit(db, "visitor.recognize.hit",
          f"fallback {match['visitor_name']} ({score:.2f})", user_id=d.user_id)
    return {"match": True, "similarity": round(score, 3),
            "visitor_name": match["visitor_name"], "company": match["company"],
            "category": match["category"], "host": match["host"],
            "purpose": match["purpose"], "destination": match["destination"],
            "id_doc_type": match["id_doc_type"], "language": match["language"],
            "last_visit": match["created_at"], "face_photo": match["face_photo"]}


@app.post("/api/visitor/register")
def visitor_register(body: dict, db: Session = Depends(get_db)):
    d = _require_device(db, str(body.get("device") or ""), kind="visitor")
    name = str(body.get("visitor_name") or "").strip()
    if not name:
        raise HTTPException(422, "visitor_name is required")
    if not body.get("consent"):
        raise HTTPException(422, "Privacy consent is required to register")
    v = wf_mod.register_visit(
        db, d.user_id, visitor_name=name,
        category=str(body.get("category") or "walk-in"),
        host=str(body.get("host") or ""), purpose=str(body.get("purpose") or ""),
        destination=str(body.get("destination") or ""),
        language=str(body.get("language") or "en"),
        id_doc_type=str(body.get("id_doc_type") or "none"),
        id_number=str(body.get("id_number") or ""), consent=True,
        face_photo=str(body.get("face_photo") or ""),
        doc_photos=body.get("doc_photos") or [],
        company=str(body.get("company") or ""))
    # Unattended kiosk: self-service check-in — no human approval step.
    # The visit is auto-approved, badge issued and checked in immediately.
    wf_mod.approve_visit(db, v, by="self-service-kiosk")
    v.status = "checked_in"
    v.checked_in_at = dt.datetime.utcnow()
    wf_mod.visit_event(v, "checked_in", "self-service-kiosk")
    db.commit()
    audit(db, "visitor.register", f"{v.visitor_name} → host {v.host} (self check-in)", user_id=d.user_id)
    return {"ok": True, "visit_id": v.id, "status": v.status,
            "visitor_name": v.visitor_name,
            "badge_expires_at": v.badge_expires_at.isoformat() if v.badge_expires_at else None}


@app.get("/api/visitor/status/{vid}")
def visitor_status(vid: str, device: str, db: Session = Depends(get_db)):
    d = _require_device(db, device, kind="visitor")
    v = db.query(Visit).filter(Visit.id == vid, Visit.user_id == d.user_id).first()
    if not v:
        raise HTTPException(404, "Visit not found")
    # kiosk gets only what it must display — no identity details
    return {"visit_id": v.id, "status": v.status, "visitor_name": v.visitor_name,
            "badge_expires_at": v.badge_expires_at.isoformat() if v.badge_expires_at else None}


@app.post("/api/visitor/checkout")
def visitor_checkout(body: dict, db: Session = Depends(get_db)):
    d = _require_device(db, str(body.get("device") or ""), kind="visitor")
    v = (db.query(Visit).filter(Visit.id == str(body.get("visit_id") or ""),
                                Visit.user_id == d.user_id).first())
    if not v:
        raise HTTPException(404, "Visit not found")
    if v.status not in ("approved", "checked_in"):
        raise HTTPException(409, f"Cannot check out a visit in state '{v.status}'")
    v.status = "checked_out"
    v.checked_out_at = dt.datetime.utcnow()
    v.badge_code_hash = ""          # badge invalid immediately
    wf_mod.visit_event(v, "checked_out", "kiosk")
    db.commit()
    audit(db, "visitor.checkout", v.visitor_name, user_id=d.user_id)
    return {"ok": True}


# ---- admin: visitor review console ----
@app.get("/api/visitor/visits")
def visits_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(Visit).filter(Visit.user_id == user.id)
            .order_by(Visit.created_at.desc()).limit(200).all())
    return [wf_mod.visit_dict(v) for v in rows]


@app.post("/api/visitor/visits/{vid}/decide")
def visit_decide(vid: str, body: dict, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    v = db.query(Visit).filter(Visit.id == vid, Visit.user_id == user.id).first()
    if not v:
        raise HTTPException(404, "Visit not found")
    if v.status != "pending":
        raise HTTPException(409, f"Visit already {v.status}")
    if bool(body.get("approve")):
        code = wf_mod.approve_visit(db, v, by=user.username,
                                    badge_hours=int(body.get("badge_hours") or 8))
        v.status = "checked_in"
        v.checked_in_at = dt.datetime.utcnow()
        wf_mod.visit_event(v, "checked_in", user.username)
        db.commit()
        audit(db, "visitor.approve", v.visitor_name, user_id=user.id)
        return {"ok": True, "status": v.status, "badge_code": code,
                "qr_png": _qr_data_uri(code) if code else "",
                "badge_expires_at": v.badge_expires_at.isoformat()}
    v.status = "denied"
    wf_mod.visit_event(v, "denied", user.username)
    db.commit()
    audit(db, "visitor.deny", v.visitor_name, user_id=user.id)
    return {"ok": True, "status": "denied"}


@app.post("/api/visitor/visits/{vid}/reprint")
def visit_reprint(vid: str, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    """Reprint a visitor badge — SAME-DAY visits only. Badge codes are
    stored hash-only, so a reprint securely ROTATES the code: a new opaque
    code is issued and the old QR stops working immediately."""
    v = db.query(Visit).filter(Visit.id == vid, Visit.user_id == user.id).first()
    if not v:
        raise HTTPException(404, "Visit not found")
    if v.status not in ("approved", "checked_in"):
        raise HTTPException(409, f"Cannot reprint a badge for a visit in state '{v.status}'")
    today = tz.today_local()
    visit_day = (v.checked_in_at or v.created_at)
    if not visit_day or tz.to_local(visit_day).date() != today:
        raise HTTPException(403, "Reprint allowed only on the day of the visit")
    if v.badge_expires_at and v.badge_expires_at < dt.datetime.utcnow():
        raise HTTPException(403, "Badge already expired — approve a new visit instead")
    import secrets as _secrets
    code = "vb-" + _secrets.token_urlsafe(12)
    v.badge_code_hash = wf_mod.sha256(code)   # rotate — old QR invalid now
    wf_mod.visit_event(v, "badge_reprinted", user.username)
    db.commit()
    audit(db, "visitor.badge.reprint", v.visitor_name, user_id=user.id)
    return {"ok": True, "badge_code": code, "qr_png": _qr_data_uri(code),
            "badge_expires_at": v.badge_expires_at.isoformat() if v.badge_expires_at else None}


# ---- doors / access control ----
@app.get("/api/access/doors")
def doors_list(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(DoorGate).filter(DoorGate.user_id == user.id)
            .order_by(DoorGate.created_at).all())
    return [{"id": d.id, "name": d.name, "site": d.site, "zone": d.zone,
             "mode": d.mode, "schedule": d.schedule,
             "allow_visitors": d.allow_visitors, "active": d.active,
             "health": d.health} for d in rows]


@app.post("/api/access/doors")
def door_create(body: dict, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    d = DoorGate(user_id=user.id, name=name[:120],
                 site=str(body.get("site") or "")[:120],
                 zone=str(body.get("zone") or "")[:120],
                 mode=str(body.get("mode") or "badge"),
                 schedule=str(body.get("schedule") or "")[:20],
                 allow_visitors=bool(body.get("allow_visitors")))
    db.add(d)
    db.commit()
    audit(db, "access.door.create", name, user_id=user.id)
    return {"ok": True, "id": d.id}


@app.post("/api/access/decision")
def access_check(body: dict, db: Session = Depends(get_db)):
    """Access decision for a door scan. Device-authenticated (either kiosk
    kind may host a door reader). Advisory only — life-safety hardware
    behavior is never overridden by this service."""
    d = _require_device(db, str(body.get("device") or ""))
    door = (db.query(DoorGate).filter(DoorGate.id == str(body.get("door_id") or ""),
                                      DoorGate.user_id == d.user_id).first())
    badge = visit = None
    code = str(body.get("code") or "")
    subject = ""
    if code.startswith("wb-"):
        badge = wf_mod.find_badge_by_token(db, d.user_id, code)
        subject = badge.worker_name if badge else ""
    elif code.startswith("vb-"):
        visit = (db.query(Visit)
                 .filter(Visit.user_id == d.user_id,
                         Visit.badge_code_hash == wf_mod.sha256(code)).first())
        subject = visit.visitor_name if visit else ""
        if visit is None:
            # unknown visitor badge → explicit deny via decision service
            allow, reason = wf_mod.access_decision(db, d.user_id, door,
                                                   subject_name="unknown")
            return {"allow": False, "reason": "visitor_badge_unknown"}
    allow, reason = wf_mod.access_decision(db, d.user_id, door, badge=badge,
                                           visit=visit, subject_name=subject)
    return {"allow": allow, "reason": reason}


@app.get("/api/access/events")
def access_events(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = (db.query(AccessEvent).filter(AccessEvent.user_id == user.id)
            .order_by(AccessEvent.at_utc.desc()).limit(200).all())
    return [{"id": e.id, "door_id": e.door_id, "subject_kind": e.subject_kind,
             "subject_name": e.subject_name, "decision": e.decision,
             "reason": e.reason, "at": e.at_utc.isoformat() + "Z"} for e in rows]


# ==================== Static frontend ====================
@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/station/{code}")
def station_page(code: str):
    """Friendly kiosk URL — /station/FRM-CHR-TEST-001 redirects to the
    canonical /?station=… form (easier to type/share on phones)."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=f"/?station={code}", status_code=307)


@app.get("/sw.js")
def service_worker():
    """PWA service worker — served at the root so its scope covers the whole
    site (station/kiosk pages installable on Android / iOS / ChromeOS)."""
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/",
                                 "Cache-Control": "no-cache, must-revalidate"})


@app.get("/kiosk")
def kiosk_client():
    """POS Kiosk Client — standalone touch UI; authenticates with the kiosk
    device token (never a user session)."""
    return FileResponse(STATIC_DIR / "kiosk.html")


@app.get("/checkin")
def checkin_kiosk():
    """Worker Check-In/Check-Out Kiosk — device-credential authenticated."""
    return FileResponse(STATIC_DIR / "checkin.html",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/visitor")
def visitor_kiosk():
    """Visitor Management Kiosk — device-credential authenticated."""
    return FileResponse(STATIC_DIR / "visitor.html",
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/{code}")
def station_fallback(code: str):
    """Phone keyboards / QR apps often mangle '?station=' into a bare path.
    If the path looks like a register/station code (e.g. FRM-CHR-TEST-001 or
    'station=FRM-…'), redirect to the kiosk; otherwise a normal 404.
    Declared LAST so it never shadows the named routes above."""
    from fastapi.responses import RedirectResponse
    c = code.strip()
    if c.lower().startswith("station="):
        return RedirectResponse(url=f"/?station={c[8:]}", status_code=307)
    if __import__("re").fullmatch(r"(?i)(FRM|OP)-[A-Z0-9][A-Z0-9\-]{2,40}", c):
        return RedirectResponse(url=f"/?station={c}", status_code=307)
    raise HTTPException(404, "Not Found")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
