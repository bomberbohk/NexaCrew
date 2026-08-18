"""Backup & restore — export/import settings, chats, skills, companies…

Both the server (administrator) and every client user can export a full JSON
backup and re-import it after a reinstall, so no data is ever lost.
- Administrator: everything (users, licenses, config, all business data).
- Standard user: everything he owns (chats, messages, skills, companies,
  employees, tasks, projects, schedules).
Backups can also be produced from a chat prompt ("/backup") and therefore via
cron schedules ("every day at 2am /backup").
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from sqlalchemy.orm import Session

from .db import (Chat, LicenseKey, Message, Project, ScheduledJob, Skill,
                 Task, User, VirtualCompany, VirtualEmployee)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BACKUP_DIR = DATA_DIR / "backups"
CONFIG_FILE = DATA_DIR / "config.json"

# tables in dependency order (parents before children) for import
_MODELS = {
    "users": User,
    "licenses": LicenseKey,
    "companies": VirtualCompany,
    "employees": VirtualEmployee,
    "projects": Project,
    "tasks": Task,
    "chats": Chat,
    "messages": Message,
    "skills": Skill,
    "schedules": ScheduledJob,
}
_ADMIN_ONLY = {"users", "licenses"}


def _row(obj) -> dict:
    out = {}
    for c in obj.__table__.columns:
        v = getattr(obj, c.name)
        out[c.name] = v.isoformat() if isinstance(v, dt.datetime) else v
    return out


def export_data(db: Session, user: User) -> dict:
    """Build a complete, scoped backup document."""
    is_admin = bool(user.is_admin)
    data: dict = {}
    if is_admin:
        for name, model in _MODELS.items():
            data[name] = [_row(r) for r in db.query(model).all()]
    else:
        own_companies = db.query(VirtualCompany).filter(
            VirtualCompany.owner_user_id == user.id).all()
        cids = [c.id for c in own_companies]
        own_chats = db.query(Chat).filter(Chat.owner_user_id == user.id).all()
        chat_ids = [c.id for c in own_chats]
        data["companies"] = [_row(r) for r in own_companies]
        data["employees"] = [_row(r) for r in db.query(VirtualEmployee)
                             .filter(VirtualEmployee.company_id.in_(cids)).all()] if cids else []
        data["projects"] = [_row(r) for r in db.query(Project)
                            .filter(Project.company_id.in_(cids)).all()] if cids else []
        data["tasks"] = [_row(r) for r in db.query(Task)
                         .filter(Task.company_id.in_(cids)).all()] if cids else []
        data["chats"] = [_row(r) for r in own_chats]
        data["messages"] = [_row(r) for r in db.query(Message)
                            .filter(Message.chat_id.in_(chat_ids)).all()] if chat_ids else []
        data["skills"] = [_row(r) for r in db.query(Skill)
                          .filter(Skill.owner_user_id == user.id).all()]
        data["schedules"] = [_row(r) for r in db.query(ScheduledJob)
                             .filter(ScheduledJob.user_id == user.id).all()]
    doc = {
        "kind": "agentai-backup",
        "format": 1,
        "scope": "admin" if is_admin else "user",
        "exported_at": dt.datetime.utcnow().isoformat(),
        "exported_by": user.username,
        "data": data,
    }
    if is_admin and CONFIG_FILE.is_file():
        try:
            doc["config"] = json.loads(CONFIG_FILE.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            pass
    return doc


def _apply_row(db: Session, model, row: dict) -> bool:
    """Upsert one row; returns True when inserted/updated."""
    cols = {c.name: c for c in model.__table__.columns}
    clean = {}
    for k, v in row.items():
        if k not in cols:
            continue
        if v is not None and str(cols[k].type) in ("DATETIME", "TIMESTAMP"):
            try:
                v = dt.datetime.fromisoformat(str(v))
            except ValueError:
                v = None
        clean[k] = v
    rid = clean.get("id")
    if not rid:
        return False
    existing = db.get(model, rid)
    if existing:
        for k, v in clean.items():
            setattr(existing, k, v)
    else:
        db.add(model(**clean))
    return True


def import_data(db: Session, doc: dict, user: User) -> dict:
    """Restore a backup document. Standard users may only restore their own
    data (ownership is forced onto the importing user); the administrator can
    restore everything including users, licenses and the platform config."""
    if not isinstance(doc, dict) or doc.get("kind") != "agentai-backup":
        raise ValueError("Not a valid AGENT_AI backup file")
    is_admin = bool(user.is_admin)
    data = doc.get("data") or {}
    counts: dict[str, int] = {}
    own_company_ids = {r.get("id") for r in data.get("companies", [])}
    own_chat_ids = {r.get("id") for r in data.get("chats", [])}
    for name, model in _MODELS.items():
        rows = data.get(name) or []
        if not rows:
            continue
        if name in _ADMIN_ONLY and not is_admin:
            continue
        n = 0
        for row in rows:
            if not is_admin:
                # force ownership onto the importing user; skip foreign rows
                if name in ("companies", "chats"):
                    row["owner_user_id"] = user.id
                elif name == "skills":
                    row["owner_user_id"] = user.id
                elif name == "schedules":
                    row["user_id"] = user.id
                elif name in ("employees", "projects", "tasks"):
                    if row.get("company_id") not in own_company_ids:
                        continue
                elif name == "messages":
                    if row.get("chat_id") not in own_chat_ids:
                        continue
            if _apply_row(db, model, row):
                n += 1
        db.commit()
        counts[name] = n
    if is_admin and isinstance(doc.get("config"), dict):
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(doc["config"], indent=2), encoding="utf-8")
        counts["config"] = 1
    return counts


def save_snapshot(db: Session, user: User) -> Path:
    """Write a backup file to platform/data/backups/ (used by the /backup
    chat command and cron-scheduled backups)."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BACKUP_DIR / f"backup_{user.username}_{stamp}.json"
    out.write_text(json.dumps(export_data(db, user), indent=1, default=str),
                   encoding="utf-8")
    # keep the 30 most recent snapshots
    snaps = sorted(BACKUP_DIR.glob("backup_*.json"))
    for old in snaps[:-30]:
        try:
            old.unlink()
        except OSError:
            pass
    return out
