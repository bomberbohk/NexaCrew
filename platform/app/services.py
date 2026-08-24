"""Orchestration services: agent runs and the email draft/approval workflow."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .db import (
    AgentRun,
    ApprovalRequest,
    Chat,
    EmailDraft,
    EmailIdentity,
    EmailMessage,
    InboxMessage,
    Message,
    Project,
    VirtualCompany,
    VirtualEmployee,
    Workspace,
)
from .providers import (AgentProvider, ClaudeCodeProvider, CodexProvider,
                        VSCodeLauncher, get_email_provider)
from .security import audit, check_company_scope, employee_has_permission

_agent_provider: AgentProvider = CodexProvider()
_claude_provider = ClaudeCodeProvider()
_vscode = VSCodeLauncher()

HANDOFF_DIR = Path(__file__).resolve().parent.parent / "data" / "handoff"

EMAIL_INTENT = re.compile(r"\b(send|write|draft|compose)\b.{0,40}\b(e-?mail|message to)\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
MAILBOX_INTENT = re.compile(
    r"\b(list|show|check|read|get|any|view|open|search|find|delete|remove|mark|reply|forward)\b"
    r".{0,50}\b(e-?mails?|inbox|mailbox|messages? received)\b"
    r"|\b(e-?mails?|inbox|mailbox)\b.{0,40}"
    r"\b(list|show|check|read|open|search|find|delete|remove|mark|reply|forward)\b"
    r"|\b(e-?mail list|inbox|mailbox)\b"
    r"|\b(reply|forward|read|open|delete|remove|mark)\b[^\n]{0,25}#\s?\d", re.I)
ORG_INTENT = re.compile(
    r"\b(create|add|hire|set ?up|remove|delete|fire|archive|update|revise|rename|modify|edit|change)\b"
    r".{0,80}\b(virtual\s+)?(employees?|empolyees?|companies|company|staff|team member)\b", re.I)
OPS_INTENT = re.compile(
    r"\b(create|add|set ?up|make|new|remove|delete|drop|retire|update|revise|rename|modify|edit|change|assign|pause|resume|disable|enable|approve)\b"
    r".{0,90}\b(teams?|work ?flows?|sops?|standard operating procedures?|"
    r"shifts?|rosters?|shift rosters?|duty schedules?|work schedules?)\b", re.I)
COLLAB_INTENT = re.compile(
    r"\b(work|collaborat\w*|co-?operat\w*|discuss\w*|brainstorm\w*|meet\w*)\b.{0,80}\b(together|jointly)\b"
    r"|\b(together|jointly)\b.{0,80}\b(work|collaborat\w*|co-?operat\w*)\b"
    r"|\b(cross.?arrange|joint (task|project|meeting)|team discussion)\b", re.I)
PROGRAMMING_HINTS = re.compile(
    r"\b(code|coding|program|script|game|function|class|bug|debug|api|app|website|"
    r"frontend|backend|python|javascript|typescript|java\b|c\+\+|c#|rust|go\b|"
    r"sql|html|css|refactor|implement|compile|library|framework|algorithm|build)\b",
    re.IGNORECASE,
)
IMAGE_INTENT = re.compile(
    r"\b(generate|create|make|draw|design|render|produce)\b.{0,60}"
    r"\b(image|picture|photo|logo|icon|illustration|artwork|drawing|banner|poster|wallpaper)\b"
    r"|\b(image|picture|logo|icon|illustration)\b.{0,30}\b(generat|creat|draw)",
    re.IGNORECASE | re.DOTALL,
)
EDIT_INTENT = re.compile(
    r"\b(edit|change|modify|correct|fix|adjust|update|remove|add|replace|recolor|resize|"
    r"crop|rotate|enhance|improve|redraw|regenerate|make it|turn it|convert)\b",
    re.IGNORECASE,
)
CONFIG_INTENT = re.compile(
    r"\b(set|change|update|config(ure)?|increase|decrease|raise|lower)\b.{0,50}"
    r"\b(timeout|time ?limit|output folder|images? (folder|director)|files? (folder|director)|"
    r"page threshold|big.?doc|context messages?|setting)\b",
    re.IGNORECASE | re.DOTALL,
)
FILE_INTENT = re.compile(
    r"\b(create|generate|make|write|produce|export|prepare|build)\b.{0,60}"
    r"\b(pdf|docx?|excel|xlsx|csv|spreadsheet|report|presentation|pptx?|text file|"
    r"markdown file|md file|word file|word document|\.pdf|\.docx|\.xlsx|\.csv|\.txt)\b",
    re.IGNORECASE | re.DOTALL,
)
PAGES_RE = re.compile(r"(\d{1,4})\s*(?:\+\s*)?(?:pages?|pgs?)\b", re.IGNORECASE)
BIG_DOC_HINTS = re.compile(r"\b(book|e-?book|manual|thesis|whitepaper|comprehensive|full-?length)\b", re.IGNORECASE)
# Short follow-ups like "in PDF file please" / "as docx" — format mention without a creation verb
FILE_FORMAT_MENTION = re.compile(
    r"\b(pdf|docx?|xlsx|pptx?|csv|spreadsheet|word (?:file|document)|excel (?:file|sheet)?)\b",
    re.IGNORECASE,
)


def _is_big_document(user_text: str) -> bool:
    """Huge document (configurable page threshold) → multi-agent pipeline."""
    from .config import get_config
    m = PAGES_RE.search(user_text)
    if m and int(m.group(1)) >= get_config()["big_doc_min_pages"]:
        return True
    return bool(BIG_DOC_HINTS.search(user_text))


def set_agent_provider(p: AgentProvider) -> None:
    global _agent_provider
    _agent_provider = p


def _employee_system_prompt(company: VirtualCompany, employee: VirtualEmployee,
                            project: Project | None) -> str:
    parts = [
        f"You are {employee.full_name}, {employee.job_title} at {company.name}.",
        f"Company mission: {company.mission}" if company.mission else "",
        f"Company AI instructions: {company.ai_instructions}" if company.ai_instructions else "",
        f"Your biography: {employee.biography}" if employee.biography else "",
        f"Your responsibilities: {employee.responsibilities}" if employee.responsibilities else "",
        f"Your working style: {employee.working_style}" if employee.working_style else "",
        f"Role instructions: {employee.system_instructions}" if employee.system_instructions else "",
        (f"ACTIVE PROJECT — '{project.name}': {project.description}".rstrip(": ")
         if project else ""),
        f"Project instructions: {project.instructions}" if project and project.instructions else "",
        f"Project goals: {project.goals}" if project and project.goals else "",
        "Act strictly within your role and authority. If information is missing or ambiguous, ask for clarification instead of guessing.",
    ]
    return "\n".join(p for p in parts if p)


def _business_block(db: Session, user_id: "str | None") -> str:
    """Company operating doctrine — injected into EVERY chat when the user
    configured commercial mode with a generated instruction prompt."""
    if not user_id:
        return ""
    try:
        from .db import BusinessProfile
        from .business import biz_owner_id, template_label
        user_id = biz_owner_id(db, user_id)   # workers inherit the company doctrine
        bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == user_id).first()
        if not bp or bp.usage_mode != "commercial":
            return ""
        # Operations Package chat directive takes precedence — operations
        # (registers AND their chat doctrine) are externalized per company,
        # so a vendor package fully defines how the AI talks about operations.
        directive = ""
        src = ""
        try:
            from . import ops_package as _opk
            pkg = _opk.load_package(user_id)
            if pkg and (pkg.get("chat_prompt") or "").strip():
                directive = pkg["chat_prompt"].strip()
                src = f" · Operations Package '{pkg['name']}' v{pkg['version']}"
        except Exception:  # noqa: BLE001 — package layer must never break chat
            pass
        if not directive:
            directive = (bp.generated_prompt or "").strip()
        if not directive:
            return ""
        label = template_label(bp.company_type, bp.custom_type)
        head = (f"\n\n## COMPANY OPERATING DOCTRINE — {bp.company_name or 'Company'} "
                f"({label}){src} — MANDATORY\nThis platform is deployed for COMMERCIAL use. "
                "The following company instruction prompt governs ALL your work, tone "
                "and compliance behavior (ISO 9001/14001/45001/25010 aligned):\n\n")
        return head + directive
    except Exception:
        return ""


def _skills_block(db: Session, target: str, user_id: "str | None" = None) -> str:
    """Collect enabled skills for a given agent (codex/claude), scoped to the
    requesting user (his own skills + legacy global skills). Plain skills
    are injected verbatim; SkillScript BASIC programs are executed in the
    sandbox and their OUTPUT becomes the injected instructions."""
    from .db import Skill
    from . import skillscript
    q = (db.query(Skill)
         .filter(Skill.deleted_at.is_(None), Skill.enabled.is_(True),
                 Skill.target.in_([target, "both"])))
    # per-user isolation: a user's chats use only HIS skills (+ global ones
    # created before ownership existed)
    q = q.filter((Skill.owner_user_id == user_id) | (Skill.owner_user_id.is_(None)))
    rows = q.all()
    if not rows:
        return ""
    parts = ["\n\n## CUSTOM SKILLS — HIGHEST-PRIORITY DIRECTIVES\n"
             "The following skills OVERRIDE your default behavior, style and any "
             "conflicting base instructions. When a user request matches a skill's "
             "domain, you MUST follow that skill's rules exactly and completely — "
             "they take precedence over everything above. Apply them with full "
             "professional depth; never abbreviate or partially apply a skill."]
    for s in rows:
        if skillscript.is_script(s.instructions):
            # dynamic skill: run the BASIC program (AI/email effects disabled
            # during prompt building to avoid recursion)
            r = skillscript.run_script(s.instructions,
                                       context={"skill_name": s.name, "target": target},
                                       allow_effects=False)
            if r.get("ok") and r.get("output", "").strip():
                parts.append(f"### Skill: {s.name} (dynamic)\n{r['output'].strip()}")
            else:
                parts.append(f"### Skill: {s.name} (dynamic — script error: "
                             f"{r.get('error', 'no output')})")
        else:
            parts.append(f"### Skill: {s.name}\n{s.instructions}")
    return "\n".join(parts)


def _chat_owner(db: Session, run) -> "str | None":
    """Owner user of the chat a run belongs to — for per-user skill scoping."""
    try:
        c = db.get(Chat, run.chat_id) if getattr(run, "chat_id", None) else None
        return getattr(c, "owner_user_id", None)
    except Exception:  # noqa: BLE001
        return None


def run_agent_message(db: Session, chat: Chat, user_text: str, user_id: str,
                      image_ref: str | None = None, face: str | None = None) -> dict:
    """Full pipeline for a chat message (spec §4)."""
    if not chat.active_employee_id:
        raise HTTPException(400, "No active employee selected for this chat — identity must be unambiguous")
    employee = db.get(VirtualEmployee, chat.active_employee_id)
    if not employee or employee.status != "Active":
        raise HTTPException(400, "Selected employee is not active")
    company = db.get(VirtualCompany, chat.company_id) if chat.company_id else None
    if company:
        check_company_scope(employee, company.id)
    project = db.get(Project, chat.project_id) if chat.project_id else None

    # TOKEN QUOTA ENFORCEMENT — when the license's included tokens (plan +
    # purchased extra tokens) are exhausted, AI runs stop until the customer
    # buys extra tokens on mapstudiousa.com. The quota refreshes on every
    # license validation (≤12 h, or immediately via “Validate now”).
    from .license_authority import token_quota
    tq = token_quota(db)
    if tq["exceeded"]:
        audit(db, "license.token_limit",
              f"AI run blocked: {tq['used']:,}/{tq['included']:,} tokens used",
              company_id=chat.company_id, user_id=user_id)
        raise HTTPException(
            402, f"Token allowance reached — {tq['used']:,} of {tq['included']:,} "
                 f"included tokens used. Purchase extra tokens in your NexaCrew "
                 f"portal at mapstudiousa.com (Purchase → Buy extra tokens), then "
                 f"run Settings → License keys → Validate now to apply the top-up.")

    db.add(Message(chat_id=chat.id, role="user", content=user_text,
                   attachments=json.dumps([image_ref] if image_ref else [])))
    db.commit()

    run = AgentRun(company_id=chat.company_id, chat_id=chat.id,
                   employee_id=employee.id, prompt=user_text, status="running")
    db.add(run)
    db.commit()

    from .providers import reset_usage
    reset_usage()

    # Multilingual operations — prompts in Traditional/Simplified Chinese,
    # Japanese, Korean, Spanish, French, German … are normalized to English
    # intent tokens (names/subjects/addresses stay untouched), so every
    # email / calendar / schedule / org operation works in any language.
    # The user's SELF-LEARNED personal vocabulary is applied first.
    from .i18n_intents import normalize_intent_text
    from .phrase_learning import (get_user_phrases, handle_phrase_prompt,
                                  learn_from_success)
    phrase_reply = handle_phrase_prompt(db, user_text, user_id)
    if phrase_reply is not None:
        run.status = "done"
        run.result = "phrase vocabulary updated"
        db.commit()
        db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                       content=phrase_reply))
        db.commit()
        return {"message": phrase_reply, "run_id": run.id}
    op_text = normalize_intent_text(user_text, get_user_phrases(db, user_id))

    # /backup command — from a direct prompt OR a cron-scheduled prompt:
    # writes a server-side snapshot of everything the user owns.
    if re.search(r"^(\[SCHEDULED TASK[^\]]*\]\s*)?/backup\b", user_text.strip(), re.I):
        from . import backup as backup_mod
        from .db import User as _User
        u = db.get(_User, user_id)
        out_path = backup_mod.save_snapshot(db, u) if u else None
        run.status = "done"
        db.commit()
        msg = (f"💾 Backup complete — snapshot saved on the server:\n`{out_path}`\n\n"
               "It contains all your chats, skills, companies, employees, tasks and "
               "schedules. You can also download a copy anytime from 💾 Backup, and "
               "restore it there after a reinstall. Tip: schedule this automatically, "
               "e.g. “every day at 2am /backup”.") if out_path else "❌ Backup failed — user not found."
        db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id, content=msg))
        db.commit()
        return {"message": msg, "run_id": run.id}

    # Calendar intent — “add event …”, “cancel the meeting …” → local calendar
    # CRUD + sync to every connected external calendar (Google/Outlook/Apple/…).
    from .calendar_sync import CALENDAR_INTENT, handle_calendar_prompt
    if (CALENDAR_INTENT.search(op_text) and not EMAIL_INTENT.search(op_text)
            and not user_text.startswith("[SCHEDULED TASK")):
        from .config import get_config
        try:
            cal_msg = handle_calendar_prompt(db, op_text, user_id, get_config())
        except Exception as e:  # noqa: BLE001
            cal_msg = ("❌ **CALENDAR SUBSYSTEM FAULT**\n\nThe request could not be completed. "
                       f"No data was modified.\n\n`DIAGNOSTIC: {e}`")
        if cal_msg is not None:
            run.status = "done"
            db.commit()
            from .security import audit as _audit
            _audit(db, "chat.calendar",
                   f"input: {user_text[:400]} | result: {cal_msg[:200]}", user_id=user_id)
            learn_from_success(db, user_id, user_text, op_text)
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=cal_msg))
            db.commit()
            return {"message": cal_msg, "run_id": run.id}

    # Visitor register intent — “check today's visitors with photos and ID”
    # → answers straight from the Visit table, attaching captured images.
    from .workforce import VISITOR_INTENT, handle_visitor_prompt
    if (not user_text.startswith("[SCHEDULED TASK") and VISITOR_INTENT.search(op_text)
            and not EMAIL_INTENT.search(op_text)):
        try:
            vis_res = handle_visitor_prompt(db, op_text, user_id)
        except Exception as e:  # noqa: BLE001
            vis_res = (f"❌ Visitor module error: {e}", [])
        if vis_res is not None:
            vis_msg, vis_atts = vis_res
            run.status = "done"
            run.result = "visitor register queried"
            db.commit()
            from .security import audit as _audit
            _audit(db, "chat.visitor", f"input: {user_text[:400]}", user_id=user_id)
            learn_from_success(db, user_id, user_text, op_text)
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=vis_msg, attachments=json.dumps(vis_atts)))
            db.commit()
            return {"message": vis_msg, "run_id": run.id, "attachments": vis_atts}

    # POS / Purchasing / Accounting intent — restaurant & supermarket ERP
    # (menu items, tables, kiosks, vendors, invoices, P&L…) via chat, any language.
    from .pos import POS_INTENT, handle_pos_prompt
    if (not user_text.startswith("[SCHEDULED TASK") and POS_INTENT.search(op_text)
            and not EMAIL_INTENT.search(op_text)):
        try:
            pos_msg = handle_pos_prompt(db, op_text, user_id)
        except Exception as e:  # noqa: BLE001
            pos_msg = ("❌ **POS SUBSYSTEM FAULT**\n\nThe transaction was not processed. "
                       f"No data was modified.\n\n`DIAGNOSTIC: {e}`")
        if pos_msg is not None:
            run.status = "done"
            run.result = "pos/purchasing/accounting operated"
            db.commit()
            from .security import audit as _audit
            _audit(db, "chat.pos",
                   f"input: {user_text[:400]} | result: {pos_msg[:200]}", user_id=user_id)
            learn_from_success(db, user_id, user_text, op_text)
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=pos_msg))
            db.commit()
            return {"message": pos_msg, "run_id": run.id}

    # Operation / audit log intent — “check the operation log”, “檢查操作日誌”,
    # “muéstrame el registro de operaciones” → enterprise audit-trail report,
    # answered natively in the requester's language. Must run BEFORE the
    # business handler so “audit log” isn't routed to the ISO audits register.
    from .audit_chat import AUDIT_INTENT, handle_audit_prompt
    if (not user_text.startswith("[SCHEDULED TASK") and AUDIT_INTENT.search(op_text)
            and not EMAIL_INTENT.search(op_text)):
        from .db import User as _User
        _u = db.query(_User).filter(_User.id == user_id).first()
        try:
            aud_res = handle_audit_prompt(db, user_text, op_text, _u)
        except Exception as e:  # noqa: BLE001
            aud_res = (f"❌ Audit log module error: {e}", [])
        if aud_res is not None:
            aud_msg, aud_atts = aud_res if isinstance(aud_res, tuple) else (aud_res, [])
            run.status = "done"
            run.result = "operation log reported"
            db.commit()
            from .security import audit as _audit
            _audit(db, "audit.viewed", f"input: {user_text[:400]}", user_id=user_id)
            learn_from_success(db, user_id, user_text, op_text)
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=aud_msg, attachments=json.dumps(aud_atts)))
            db.commit()
            return {"message": aud_msg, "run_id": run.id, "attachments": aud_atts}

    # Business / ERP intent — “add inventory…”, “list invoices”, “低庫存”,
    # “business report” → operates the commercial ERP registers directly.
    from .business import BUSINESS_INTENT, handle_business_prompt
    if (not user_text.startswith("[SCHEDULED TASK") and BUSINESS_INTENT.search(op_text)
            and not EMAIL_INTENT.search(op_text)):
        try:
            biz_msg = handle_business_prompt(db, op_text, user_id,
                                             face=face, raw_text=user_text)
        except Exception as e:  # noqa: BLE001
            biz_msg = ("❌ **BUSINESS SUBSYSTEM FAULT**\n\nThe operation was aborted before commit. "
                       f"No data was modified.\n\n`DIAGNOSTIC: {e}`")
        if biz_msg is not None:
            run.status = "done"
            run.result = "business ERP operated"
            db.commit()
            learn_from_success(db, user_id, user_text, op_text)
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=biz_msg))
            db.commit()
            return {"message": biz_msg, "run_id": run.id}

    # Schedule intent FIRST — “send an email at 7:55PM on 8/8” must become a
    # schedule, not an immediate email draft.
    from .scheduler import SCHEDULE_INTENT
    if not user_text.startswith("[SCHEDULED TASK") and SCHEDULE_INTENT.search(op_text):
        result = _handle_schedule_request(db, chat, op_text, run, user_id)
        if result is not None:
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=result["message"]))
            db.commit()
            return result

    # Mailbox intent — “list/check emails”, “show inbox” → real mail data,
    # checked BEFORE the send-email intent.
    if MAILBOX_INTENT.search(op_text) and not EMAIL_INTENT.search(op_text):
        # 1) the user's own connected IMAP accounts (real email) take priority
        from .mailbox import handle_mail_prompt
        try:
            real = handle_mail_prompt(db, op_text, user_id)
        except Exception as e:  # noqa: BLE001
            real = f"❌ Mail error: {e}"
        if real is not None:
            run.status = "done"
            run.result = "real mailbox operated"
            db.commit()
            learn_from_success(db, user_id, user_text, op_text)
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=real))
            db.commit()
            return {"message": real, "run_id": run.id}
        # 2) otherwise: internal virtual-employee mailboxes
        result = _handle_mailbox_request(db, company, employee, op_text, run)
        db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                       content=result["message"]))
        db.commit()
        return result

    # Operations intent — create/revise/remove teams, workflows, SOPs and
    # shift-roster entries by prompt (checked before org: "team" overlaps).
    if OPS_INTENT.search(op_text) and not EMAIL_INTENT.search(op_text) \
            and not COLLAB_INTENT.search(op_text) \
            and not user_text.startswith("[SCHEDULED TASK"):
        result = _handle_ops_request(db, chat, op_text, run, user_id)
        if result is not None:
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=result["message"]))
            db.commit()
            return result

    # Org-management intent — create/update/remove employees & companies by prompt
    if ORG_INTENT.search(op_text) and not EMAIL_INTENT.search(op_text) \
            and not COLLAB_INTENT.search(op_text):
        result = _handle_org_request(db, op_text, run, user_id)
        if result is not None:
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=result["message"]))
            db.commit()
            return result

    # Collaboration intent — several employees (possibly across companies) work
    # together; every turn of their conversation is shown in the chat.
    if COLLAB_INTENT.search(user_text):
        result = _handle_collab_request(db, chat, company, employee, user_text, run, user_id)
        if result is not None:
            return result

    # Email intent → draft + approval workflow instead of free execution
    if EMAIL_INTENT.search(user_text) or (
            user_text.startswith("[SCHEDULED TASK") and EMAIL_RE.search(user_text)
            and re.search(r"\b(email|mail|send)\b", user_text, re.I)):
        result = _handle_email_request(db, company, employee, user_text, run, user_id,
                                       attachment=image_ref)
        db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                       content=result["message"]))
        db.commit()
        return result

    # Config intent → Codex maps the request onto the platform settings
    if CONFIG_INTENT.search(user_text):
        result = _handle_config_request(db, user_text, run, user_id)
        if result is not None:
            db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id,
                           content=result["message"]))
            db.commit()
            return result

    if not employee_has_permission(employee, "execute_code") and not employee_has_permission(employee, "view"):
        run.status = "error"
        run.error = "Employee lacks permission to handle this request"
        db.commit()
        raise HTTPException(403, run.error)

    system = (_employee_system_prompt(company, employee, project) if company else "") + \
        _business_block(db, user_id) + _skills_block(db, "codex", user_id)
    wants_generation = bool(IMAGE_INTENT.search(user_text))
    wants_edit = bool(image_ref) and bool(EDIT_INTENT.search(user_text))
    # Attachment + no generation/edit verbs → the user wants ANALYSIS of the file
    is_analysis = bool(image_ref) and not wants_generation and not wants_edit
    is_image = (wants_generation or wants_edit) or (bool(image_ref) and not is_analysis)
    # Explicit "create a PDF…" OR a short follow-up that just names a file format
    # (e.g. "in PDF file please") — both mean the user wants a file produced.
    is_file = (not is_image and not is_analysis) and (
        bool(FILE_INTENT.search(user_text))
        or (len(user_text) <= 120 and bool(FILE_FORMAT_MENTION.search(user_text)))
    )
    is_programming = (not is_image and not is_analysis and not is_file) and bool(PROGRAMMING_HINTS.search(user_text)) and \
        employee_has_permission(employee, "execute_code") and _claude_provider.available

    # Short follow-ups need conversation context so Codex knows WHAT to put in the file
    context_text = user_text
    if is_file and len(user_text) <= 120:
        from .config import get_config
        n_ctx = get_config()["history_context_messages"]
        recent = (db.query(Message).filter(Message.chat_id == chat.id)
                  .order_by(Message.created_at.desc()).limit(n_ctx).all())
        history = "\n".join(
            f"[{m.role}] {m.content[:1500]}" for m in reversed(recent))
        context_text = (f"## Recent conversation (for context)\n{history}\n\n"
                        f"## Current request\n{user_text}")

    attachments: list[str] = []
    try:
        if is_analysis:
            answer = _run_file_analysis(db, run, user_text, system, image_ref)
        elif is_image:
            # Image generation/editing: Codex only — no Claude Code / VS Code handoff.
            answer, attachments = _run_image_request(db, run, user_text, system, image_ref)
        elif is_file:
            # Detect big documents from the FULL context (a short follow-up like
            # "in PDF please" may refer to a 500-page request earlier in the chat)
            if _is_big_document(context_text):
                answer = _run_big_document_pipeline(db, run, context_text, system)
            else:
                answer = _run_file_creation(db, run, context_text, system)
        elif is_programming:
            answer = _run_programming_pipeline(db, run, user_text, system)
        else:
            answer = _agent_provider.run(user_text, system=system)
        run.status = "done"
        run.result = answer
    except Exception as e:  # noqa: BLE001
        run.status = "error"
        run.error = str(e)
        answer = f"⚠ Agent execution failed: {e}"
    answer = answer.rstrip() + _usage_footer()
    run.result = answer if run.status == "done" else run.result
    # persist per-agent token usage for the usage analytics dashboards
    try:
        from .providers import get_usage
        from .db import TokenUsage
        for agent_name, u in get_usage().items():
            db.add(TokenUsage(user_id=user_id, company_id=chat.company_id, run_id=run.id,
                              agent=agent_name, input_tokens=u["input_tokens"],
                              output_tokens=u["output_tokens"], calls=u["calls"]))
    except Exception:  # noqa: BLE001
        pass
    db.add(Message(chat_id=chat.id, role="employee", employee_id=employee.id, content=answer,
                   attachments=json.dumps(attachments)))
    db.commit()
    audit(db, "agent.run", f"run={run.id} status={run.status}", company_id=chat.company_id,
          user_id=user_id, employee_id=employee.id)
    return {"message": answer, "run_id": run.id, "kind": "answer", "attachments": attachments}


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
WIN_PATH_RE = re.compile(r"[A-Za-z]:\\[^\s\"'`|<>]+?\.(?:png|jpe?g|gif|webp|bmp)", re.I)

AGENT_LABELS = {"codex": "🧠 Codex", "claude_code": "⚙️ Claude Code", "vscode": "🚀 VS Code"}


def _usage_footer() -> str:
    """Per-response token usage line (estimated — the CLIs don't expose exact counts)."""
    from .providers import get_usage
    usage = get_usage()
    parts = []
    for agent in ("codex", "claude_code"):
        u = usage.get(agent)
        if u:
            parts.append(f"{AGENT_LABELS[agent]}: ~{u['input_tokens']:,} in / ~{u['output_tokens']:,} out"
                         + (f" ({u['calls']} calls)" if u["calls"] > 1 else ""))
    if not parts:
        return ""
    parts.append("🚀 VS Code: n/a (handoff — tokens billed to Copilot)")
    return "\n\n📊 Token usage (estimated): " + " · ".join(parts)


def _run_file_analysis(db: Session, run, user_text: str, system: str, file_ref: str) -> str:
    """Analyze an attached image/file with Codex (read-only, no generation)."""
    from .db import ToolCall

    p = Path(file_ref)
    tc = ToolCall(run_id=run.id, tool="codex.analyze", status="running",
                  arguments=json.dumps({"file": file_ref, "prompt": user_text[:500]}))
    db.add(tc)
    db.commit()
    kind = "image" if p.suffix.lower() in IMAGE_EXTS else "file"
    prompt = (
        f"EXECUTE NOW — the user attached a {kind} and wants you to ANALYZE it "
        "(do NOT generate or edit any image).\n"
        f"Attached {kind}: {file_ref}\n"
        f"Open/read/view that {kind} and answer the user's question about it in detail. "
        "Describe concrete contents — never guess without looking at it.\n\n"
        f"User's question:\n{user_text}"
    )
    answer = _agent_provider.run(prompt, system=system, cwd=str(p.parent if p.parent.exists() else Path.home()))
    tc.status = "done"
    tc.result = answer[:4000]
    db.commit()
    return f"🔍 ANALYSIS ({p.name})\n" + answer.strip()


def _run_image_request(db: Session, run, user_text: str, system: str,
                       image_ref: str | None = None) -> tuple[str, list[str]]:
    """Image generation/editing: handled entirely by Codex (only Codex can
    generate images) — no Claude Code implementation or VS Code handoff.
    Returns (answer, list of image file paths)."""
    from .db import ToolCall
    from .config import get_config

    out_dir = Path(get_config()["images_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p: p.stat().st_mtime for p in out_dir.glob("*") if p.suffix.lower() in IMAGE_EXTS}

    tc = ToolCall(run_id=run.id, tool="codex.image", status="running",
                  arguments=json.dumps({"prompt": user_text[:500], "reference": image_ref}))
    db.add(tc)
    db.commit()

    if image_ref:
        prompt = (
            "EXECUTE NOW — do not reply conversationally, do not ask questions, do not just acknowledge.\n"
            "The user is EDITING an existing image. You MUST use this reference image as the basis: "
            f"{image_ref}\n"
            "Load/analyze the reference image and apply ONLY the requested corrections, keeping "
            "everything else consistent. Use your image-generation tool and SAVE the corrected image "
            f"as a NEW PNG file inside the current working directory ({out_dir}).\n"
            "Your final answer MUST contain the full absolute path of the saved file.\n\n"
            f"Correction request (apply relative to the reference image):\n{user_text}"
        )
    else:
        prompt = (
            "EXECUTE NOW — do not reply conversationally, do not ask questions, do not just acknowledge.\n"
            "Use your image-generation tool to create the requested image and SAVE it as a PNG file "
            f"inside the current working directory ({out_dir}).\n"
            "Your final answer MUST contain the full absolute path of the saved file. "
            "If you truly cannot generate images, state that clearly — never pretend.\n\n"
            f"Image request:\n{user_text}"
        )

    answer = _agent_provider.run(prompt, system="", cwd=str(out_dir), allow_write=True)

    # Collect produced images: new/changed files in out_dir + any paths Codex mentioned
    found: list[str] = []
    for p in out_dir.glob("*"):
        if p.suffix.lower() in IMAGE_EXTS and (p not in before or p.stat().st_mtime > before[p]):
            found.append(str(p))
    for m in WIN_PATH_RE.findall(answer):
        if Path(m).exists() and m not in found:
            found.append(m)

    tc.status = "done"
    tc.result = answer[:4000]
    db.commit()
    header = "🎨 CODEX IMAGE EDIT (referencing your image)\n" if image_ref else "🎨 CODEX IMAGE GENERATION\n"
    return header + answer.strip(), found


def _run_file_creation(db: Session, run, user_text: str, system: str) -> str:
    """Document/file creation (PDF, DOCX, XLSX, CSV, …): Codex with write access."""
    from .db import ToolCall
    from .config import get_config

    out_dir = Path(get_config()["files_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p: p.stat().st_mtime for p in out_dir.glob("*") if p.is_file()}

    tc = ToolCall(run_id=run.id, tool="codex.file", status="running",
                  arguments=json.dumps({"prompt": user_text[:500]}))
    db.add(tc)
    db.commit()

    prompt = (
        "EXECUTE NOW — do not reply conversationally, do not ask questions, do not just acknowledge.\n"
        "You have WRITE ACCESS to the current working directory. Create the requested file(s) "
        f"and SAVE them inside the current working directory ({out_dir}).\n"
        "If you need a Python library (e.g. reportlab/fpdf for PDF, openpyxl for Excel, python-docx for Word), "
        "install it with pip and run a script to produce the file.\n"
        "If the content requires up-to-date information you cannot access, use reasonable placeholder data "
        "and clearly note it in the document.\n"
        "Your final answer MUST contain the full absolute path of every saved file.\n\n"
        f"Request:\n{user_text}"
    )
    answer = _agent_provider.run(prompt, system=system, cwd=str(out_dir), allow_write=True)

    new_files = [str(p) for p in out_dir.glob("*")
                 if p.is_file() and (p not in before or p.stat().st_mtime > before[p])]
    tc.status = "done"
    tc.result = answer[:4000]
    db.commit()
    header = "📄 FILE CREATED\n" if new_files else "📄 FILE REQUEST\n"
    if new_files:
        header += "Saved: " + ", ".join(new_files) + "\n\n"
    return header + answer.strip()


def _run_big_document_pipeline(db: Session, run, user_text: str, system: str) -> str:
    """Huge (30+ page) PDF/DOCX generation — mandatory 3-stage pipeline:
    1. Codex: produce the index/table of contents ONLY.
    2. Claude Code: verify every index entry is correct/complete.
    3. VS Code: hand off a spec instructing Python-based generation of the
       files and file structure (Copilot / Claude Fable 5)."""
    from .db import ToolCall
    from .config import get_config

    out_dir = Path(get_config()["files_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- Stage 1: Codex builds the index only ----
    tc1 = ToolCall(run_id=run.id, tool="codex.index", status="running",
                   arguments=json.dumps({"prompt": user_text[:500]}))
    db.add(tc1)
    db.commit()
    index = _agent_provider.run(
        "You are the INDEXING agent for a large document (30+ pages). "
        "Do NOT write the document. Produce ONLY a complete, detailed index / table of contents: "
        "every chapter and section with a 1–2 sentence description of its content, plus an "
        "estimated page count per chapter so the total matches the requested length. "
        "Output as structured Markdown.\n\nDocument request:\n" + user_text,
        system=system)
    tc1.status = "done"
    tc1.result = index[:4000]
    db.commit()

    # ---- Stage 2: Claude Code verifies the index ----
    tc2 = ToolCall(run_id=run.id, tool="claude_code.verify", status="running")
    db.add(tc2)
    db.commit()
    verified = _claude_provider.run(
        "You are the VERIFICATION agent. Below is a document request and an index/table of "
        "contents produced by Codex. Check EVERY entry: completeness, logical ordering, no "
        "duplicates or gaps, page estimates consistent with the requested length, and full "
        "coverage of the user's request. Fix anything wrong and output the FINAL corrected "
        "index as structured Markdown, followed by a short list of the corrections you made.\n"
        + _skills_block(db, "claude", _chat_owner(db, run)) + "\n\n"
        f"## Document request\n{user_text}\n\n## Codex index\n{index}")
    tc2.status = "done"
    tc2.result = verified[:4000]
    db.commit()

    # ---- Stage 3: hand off to VS Code for Python-based generation ----
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    md_file = HANDOFF_DIR / f"bigdoc_{stamp}.md"
    md_file.write_text(
        "# Large Document Generation Task\n\n"
        "## Instructions for VS Code Copilot (Claude Fable 5)\n"
        "Use PYTHON to generate this document and its file structure:\n"
        f"1. Create a project folder under `{out_dir}` (one subfolder per document).\n"
        "2. Write one Markdown/content file per chapter following the verified index below.\n"
        "3. Write a Python build script (reportlab/fpdf2 for PDF, python-docx for DOCX) that "
        "assembles all chapters into the final file, with title page, table of contents and "
        "page numbers. Install required libraries with pip.\n"
        "4. Run the script and verify the output file exists and matches the requested length.\n\n"
        f"## Original request\n{user_text}\n\n"
        f"## Verified index (Claude Code)\n{verified}\n\n"
        f"## Original Codex index\n{index}\n",
        encoding="utf-8")
    tc3 = ToolCall(run_id=run.id, tool="vscode.open", status="running",
                   arguments=json.dumps({"file": str(md_file)}))
    db.add(tc3)
    db.commit()
    opened = _vscode.open(str(md_file))
    tc3.status = "done" if opened else "error"
    db.commit()

    return ("📚 LARGE DOCUMENT PIPELINE\n\n"
            "🧠 CODEX — INDEX\n" + index.strip() +
            "\n\n✅ CLAUDE CODE — VERIFIED INDEX\n" + verified.strip() +
            f"\n\n📄 Spec file: {md_file}" +
            ("\n🚀 Opened in VS Code — Copilot (Claude Fable 5) will generate the files "
             "and structure with Python." if opened and _vscode.available
             else f"\n🚀 VS Code is not available on this system — opened in "
                  f"{_vscode.fallback_name or 'a text editor'} instead (works on old "
                  "macOS/Windows too)." if opened
             else "\n⚠ No editor found — open the spec file manually."))


def _run_programming_pipeline(db: Session, run, user_text: str, system: str) -> str:
    from .db import ToolCall
    # ---- Stage 1: Codex plans ----
    tc1 = ToolCall(run_id=run.id, tool="codex.plan", status="running",
                   arguments=json.dumps({"prompt": user_text[:500]}))
    db.add(tc1)
    db.commit()
    plan = _agent_provider.run(
        "You are the PLANNING agent in a pipeline. Produce a clear, actionable "
        "implementation plan for the following request. Another agent (Claude Code) "
        "will implement it.\n\nRequest:\n" + user_text, system=system)
    tc1.status = "done"
    tc1.result = plan[:4000]
    db.commit()

    # ---- Stage 2: Claude Code implements ----
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    md_file = HANDOFF_DIR / f"task_{stamp}.md"
    tc2 = ToolCall(run_id=run.id, tool="claude_code.implement", status="running")
    db.add(tc2)
    db.commit()
    claude_out = _claude_provider.run(
        "You are the IMPLEMENTATION agent. Below is the user's request and a plan from Codex.\n"
        "1. IMPLEMENT the request now: create the actual files/code at the location the user "
        "specified (create directories as needed). If no location was given, use a sensible "
        "folder under the user's Desktop.\n"
        f"2. Also write a Markdown implementation spec to exactly this path: {md_file}\n"
        "   containing Objective, Files created, Code overview, How to run, and any follow-up "
        "work for VS Code Copilot (Claude Fable 5).\n"
        "3. Finally, summarize what you did.\n"
        + _skills_block(db, "claude", _chat_owner(db, run)) + "\n\n"
        f"## User request\n{user_text}\n\n## Codex plan\n{plan}")
    tc2.status = "done"
    tc2.result = claude_out[:4000]
    db.commit()

    if not md_file.exists():
        md_file.write_text(f"# Task Specification\n\n## Request\n{user_text}\n\n"
                           f"## Codex plan\n{plan}\n\n## Claude Code output\n{claude_out}",
                           encoding="utf-8")

    # ---- Stage 3: hand off to VS Code ----
    tc3 = ToolCall(run_id=run.id, tool="vscode.open", status="running",
                   arguments=json.dumps({"file": str(md_file)}))
    db.add(tc3)
    db.commit()
    opened = _vscode.open(str(md_file))
    tc3.status = "done" if opened else "error"
    db.commit()

    return ("🧠 CODEX PLAN\n" + plan.strip() +
            "\n\n⚙️ CLAUDE CODE IMPLEMENTATION\n" + claude_out.strip() +
            f"\n\n📄 Spec file: {md_file}" +
            ("\n🚀 Opened in VS Code — use Copilot (Claude Fable 5) for follow-up."
             if opened and _vscode.available
             else f"\n🚀 VS Code is not available on this system — opened in "
                  f"{_vscode.fallback_name or 'a text editor'} instead (works on old "
                  "macOS/Windows too)." if opened
             else "\n⚠ No editor found — open the spec file manually."))


def _handle_schedule_request(db: Session, chat: Chat, user_text: str,
                             run: AgentRun, user_id: str) -> dict | None:
    """Prompt-based cron creation: Codex parses the natural-language schedule.
    Returns None if the message isn't really a scheduling request."""
    from .db import ScheduledJob, ToolCall
    from .scheduler import describe_cron, validate_cron

    now = dt.datetime.now()
    tc = ToolCall(run_id=run.id, tool="codex.schedule", status="running",
                  arguments=json.dumps({"prompt": user_text[:500]}))
    db.add(tc)
    db.commit()
    parse_prompt = (
        "You are a scheduling parser. Decide whether the user wants a RECURRING task or a "
        "ONE-TIME task at a specific date/time. Respond ONLY with JSON, nothing else.\n"
        'Recurring: {"schedule": true, "name": short task name, "cron": 5-field cron string '
        '("min hour dom month dow", 0=Sunday), "task_prompt": ...}\n'
        'One-time: {"schedule": true, "name": short task name, "cron": "once:YYYY-MM-DDTHH:MM" '
        "(local time, 24h; convert from any timezone the user mentions), \"task_prompt\": ...}\n"
        'Not a schedule: {"schedule": false}\n'
        "task_prompt must be the exact, SELF-CONTAINED task the agent performs at trigger time — "
        "include every detail from the user's message: recipient email addresses, subject, body "
        "content, and full attachment file paths.\n"
        f"Current local time: {now.strftime('%Y-%m-%d %H:%M, %A')} "
        f"(timezone: {dt.datetime.now().astimezone().tzname()})\n\n"
        f"User message:\n{user_text}"
    )
    try:
        raw = _agent_provider.run(parse_prompt, system="")
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        data = {}
    if not data.get("schedule"):
        tc.status = "done"
        tc.result = "not a scheduling request"
        db.commit()
        return None  # fall through to normal routing
    cron = str(data.get("cron", "")).strip()
    if not validate_cron(cron):
        tc.status = "error"
        tc.result = f"invalid cron produced: {cron}"
        run.status = "done"
        db.commit()
        return {"kind": "clarify", "run_id": run.id, "message": (
            "⏰ I understood you want to schedule a task, but I couldn't derive a valid "
            "schedule. Please state the timing explicitly, e.g. “every day at 9:00” or "
            "“every Monday at 18:30”.")}
    job = ScheduledJob(name=str(data.get("name", "Scheduled task"))[:120], cron=cron,
                       prompt=str(data.get("task_prompt", user_text)),
                       chat_id=chat.id, user_id=user_id, enabled=True)
    db.add(job)
    tc.status = "done"
    tc.result = json.dumps(data)[:2000]
    run.status = "done"
    run.result = f"scheduled job {job.id}"
    db.commit()
    audit(db, "schedule.create", f"job={job.id} cron={cron}", company_id=chat.company_id, user_id=user_id)
    return {"kind": "scheduled", "run_id": run.id, "message": (
        f"⏰ SCHEDULED — “{job.name}”\n"
        f"• When: {describe_cron(cron)}  (cron: {cron})\n"
        f"• Task: {job.prompt[:400]}\n"
        f"• Results will be posted in this chat at each run.\n"
        "Manage it under ⏰ Schedules in the sidebar.")}


def _handle_config_request(db: Session, user_text: str, run: AgentRun, user_id: str) -> dict | None:
    """Prompt-based configuration: Codex maps the request onto known settings."""
    from .config import DEFAULTS, FIELD_META, get_config, save_config
    from .db import ToolCall

    tc = ToolCall(run_id=run.id, tool="codex.configure", status="running",
                  arguments=json.dumps({"prompt": user_text[:500]}))
    db.add(tc)
    db.commit()
    cfg = get_config()
    schema = {k: {"current": cfg[k], **{kk: vv for kk, vv in FIELD_META[k].items()}} for k in DEFAULTS}
    parse_prompt = (
        "You are a settings parser for an agent platform. Decide whether the user wants to "
        "change one of these settings. Respond ONLY with JSON.\n"
        f"Settings schema (key → meta+current):\n{json.dumps(schema, indent=1)}\n\n"
        'If YES: {"configure": true, "updates": {key: new_value, ...}}\n'
        'If NO: {"configure": false}\n\n'
        f"User message:\n{user_text}"
    )
    try:
        raw = _agent_provider.run(parse_prompt, system="")
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:  # noqa: BLE001
        data = {}
    updates = data.get("updates") or {}
    if not data.get("configure") or not isinstance(updates, dict) or not updates:
        tc.status = "done"
        tc.result = "not a config request"
        db.commit()
        return None
    new_cfg = save_config(updates)
    tc.status = "done"
    tc.result = json.dumps(updates)[:2000]
    run.status = "done"
    run.result = "config updated"
    db.commit()
    audit(db, "config.update", f"via-prompt {json.dumps(updates)[:300]}", user_id=user_id)
    lines = "\n".join(f"• {FIELD_META.get(k, {}).get('label', k)}: {new_cfg.get(k)}"
                      for k in updates if k in new_cfg)
    return {"kind": "configured", "run_id": run.id, "message":
            "⚙️ CONFIGURATION UPDATED\n" + lines +
            "\nYou can review everything under ⚙️ Settings."}


def _user_companies(db: Session, user_id: str) -> list:
    return (db.query(VirtualCompany)
            .filter(VirtualCompany.deleted_at.is_(None),
                    (VirtualCompany.owner_user_id == user_id) |
                    (VirtualCompany.owner_user_id.is_(None)))
            .all())


def _org_directory(db: Session, user_id: str):
    """(companies, employees, human-readable directory text) for this user."""
    companies = _user_companies(db, user_id)
    cids = [c.id for c in companies]
    emps = (db.query(VirtualEmployee)
            .filter(VirtualEmployee.company_id.in_(cids),
                    VirtualEmployee.deleted_at.is_(None)).all()) if cids else []
    by_company: dict[str, list] = {}
    for e in emps:
        by_company.setdefault(e.company_id, []).append(e)
    lines = []
    for c in companies:
        lines.append(f"- Company “{c.name}” (industry: {c.industry or '?'})")
        for e in by_company.get(c.id, []):
            lines.append(f"    • {e.full_name} — {e.job_title or 'no title'} [{e.status}]")
    return companies, emps, "\n".join(lines) or "(no companies yet)"


_EMP_FIELDS = {"full_name", "job_title", "biography", "responsibilities", "skills",
               "goals", "working_style", "system_instructions", "status", "avatar"}
_CO_FIELDS = {"name", "logo", "description", "industry", "website", "address",
              "timezone", "mission", "operating_principles", "brand_voice", "ai_instructions"}


def _handle_org_request(db: Session, user_text: str, run: AgentRun, user_id: str) -> "dict | None":
    """Create / update / remove virtual employees and companies from a prompt."""
    companies, emps, directory = _org_directory(db, user_id)
    prompt = (
        "You manage a virtual-company platform. Convert the user's request into JSON "
        "actions. Respond ONLY with JSON: {\"actions\": [...]}. Each action is one of:\n"
        '{"op":"create_company","name":str, ...optional: description,industry,mission}\n'
        '{"op":"update_company","company":str(existing name), "fields":{...}}\n'
        '{"op":"delete_company","company":str}\n'
        '{"op":"create_employee","company":str,"full_name":str, ...optional: job_title,'
        'responsibilities,skills,working_style,system_instructions,avatar}\n'
        '{"op":"update_employee","employee":str(existing full name), "fields":{...}}\n'
        '{"op":"delete_employee","employee":str}\n'
        "If the request is NOT about managing companies/employees, respond {\"actions\": []}.\n\n"
        f"Current directory:\n{directory}\n\nUser request: {user_text}"
    )
    try:
        raw = _agent_provider.run(prompt, system="You output only strict JSON.")
        m = re.search(r"\{.*\}", raw, re.S)
        actions = json.loads(m.group(0)).get("actions", []) if m else []
    except Exception as e:  # noqa: BLE001
        run.status = "error"; run.error = f"org parse: {e}"; db.commit()
        return {"kind": "error", "run_id": run.id,
                "message": f"❌ I could not understand the org change request: {e}"}
    if not actions:
        return None  # not an org request after all — fall through to normal handling

    def find_company(name):
        return next((c for c in companies if c.name.lower() == str(name).lower()), None) or \
               next((c for c in companies if str(name).lower() in c.name.lower()), None)

    def find_employee(name):
        return next((e for e in emps if e.full_name.lower() == str(name).lower()), None) or \
               next((e for e in emps if str(name).lower() in e.full_name.lower()), None)

    results = []
    for a in actions:
        op = a.get("op", "")
        try:
            if op == "create_company":
                ws = db.query(Workspace).first()
                fields = {k: v for k, v in a.items() if k in _CO_FIELDS}
                c = VirtualCompany(workspace_id=ws.id, owner_user_id=user_id, **fields)
                db.add(c); db.flush()
                companies.append(c)
                results.append(f"🏢 Created company “{c.name}”")
                audit(db, "company.create", c.name, company_id=c.id, user_id=user_id)
            elif op == "update_company":
                c = find_company(a.get("company", ""))
                if not c: results.append(f"❌ Company “{a.get('company')}” not found"); continue
                for k, v in (a.get("fields") or {}).items():
                    if k in _CO_FIELDS: setattr(c, k, v)
                results.append(f"✏️ Updated company “{c.name}”")
                audit(db, "company.update", c.name, company_id=c.id, user_id=user_id)
            elif op == "delete_company":
                c = find_company(a.get("company", ""))
                if not c: results.append(f"❌ Company “{a.get('company')}” not found"); continue
                c.deleted_at = dt.datetime.utcnow()
                results.append(f"🗑️ Removed company “{c.name}”")
                audit(db, "company.delete", c.name, company_id=c.id, user_id=user_id)
            elif op == "create_employee":
                c = find_company(a.get("company", "")) or (companies[0] if companies else None)
                if not c: results.append("❌ No company to add the employee to"); continue
                fields = {k: v for k, v in a.items() if k in _EMP_FIELDS}
                e = VirtualEmployee(company_id=c.id, **fields)
                db.add(e); db.flush()
                emps.append(e)
                results.append(f"👤 Hired “{e.full_name}” ({e.job_title or 'no title'}) at “{c.name}”")
                audit(db, "employee.create", e.full_name, company_id=c.id, user_id=user_id, employee_id=e.id)
            elif op == "update_employee":
                e = find_employee(a.get("employee", ""))
                if not e: results.append(f"❌ Employee “{a.get('employee')}” not found"); continue
                for k, v in (a.get("fields") or {}).items():
                    if k in _EMP_FIELDS: setattr(e, k, v)
                results.append(f"✏️ Updated employee “{e.full_name}”")
                audit(db, "employee.update", e.full_name, company_id=e.company_id, user_id=user_id, employee_id=e.id)
            elif op == "delete_employee":
                e = find_employee(a.get("employee", ""))
                if not e: results.append(f"❌ Employee “{a.get('employee')}” not found"); continue
                e.deleted_at = dt.datetime.utcnow()
                results.append(f"🗑️ Removed employee “{e.full_name}”")
                audit(db, "employee.delete", e.full_name, company_id=e.company_id, user_id=user_id, employee_id=e.id)
            else:
                results.append(f"❌ Unknown action “{op}”")
        except Exception as exc:  # noqa: BLE001
            results.append(f"❌ {op} failed: {exc}")
    db.commit()
    run.status = "done"; run.result = "; ".join(results)[:2000]; db.commit()
    return {"kind": "org_changed", "run_id": run.id,
            "message": "🏗️ ORGANIZATION UPDATED\n" + "\n".join(results) +
                       "\n\nRefresh the Companies/Employees pages to see the changes."}


def _handle_ops_request(db: Session, chat: Chat, user_text: str, run: AgentRun,
                        user_id: str) -> "dict | None":
    """Create / revise / remove Teams, Workflows, SOPs and Shift-roster entries
    from a chat prompt. The AI converts the request into JSON actions which are
    applied to the chat's company (falling back to the user's first company)."""
    from .db import SOP, Shift, Team, Workflow
    companies, emps, directory = _org_directory(db, user_id)
    company = next((c for c in companies if c.id == chat.company_id), None) \
        or (companies[0] if companies else None)
    if not company:
        return None
    cid = company.id

    def _rows(model):
        return db.query(model).filter(model.company_id == cid,
                                      model.deleted_at.is_(None)).all()
    teams, wfs, sops, shifts = _rows(Team), _rows(Workflow), _rows(SOP), _rows(Shift)
    emp_dir = "\n".join(f"  • {e.full_name} — {e.job_title or 'staff'}"
                        for e in emps if e.company_id == cid) or "  (none)"
    inv = []
    inv.append("Teams:\n" + ("\n".join(f"  • {t.name} [{t.status}]" for t in teams) or "  (none)"))
    inv.append("Workflows:\n" + ("\n".join(f"  • {w.name} [{w.status}]" for w in wfs) or "  (none)"))
    inv.append("SOPs:\n" + ("\n".join(f"  • {s.code} {s.title} [{s.status} v{s.version}]" for s in sops) or "  (none)"))
    inv.append("Shifts:\n" + ("\n".join(
        f"  • {s.name or 'shift'} — {next((e.full_name for e in emps if e.id == s.employee_id), '?')} "
        f"{s.start_time}-{s.end_time} [{s.status}]" for s in shifts) or "  (none)"))

    prompt = (
        "You manage the operations suite of a virtual-company platform "
        f"(company: {company.name}). Convert the user's request into JSON actions. "
        'Respond ONLY with JSON: {"actions": [...]}. Each action is one of:\n'
        '{"op":"create_team","name":str, ...optional: mission,lead(employee name),members(list of employee names),status}\n'
        '{"op":"update_team","team":str(existing name),"fields":{name?,mission?,lead?,members?,status?}}\n'
        '{"op":"delete_team","team":str}\n'
        '{"op":"create_workflow","name":str, ...optional: description,trigger(manual|schedule|task_created),status,'
        'stages:[{"name":str,"owner":str(employee or team name),"approval_required":bool}]}\n'
        '{"op":"update_workflow","workflow":str,"fields":{name?,description?,trigger?,status?,stages?}}\n'
        '{"op":"delete_workflow","workflow":str}\n'
        '{"op":"create_sop","title":str, ...optional: category,purpose,scope,procedure(numbered steps),status,owner(employee name),review_date}\n'
        '{"op":"update_sop","sop":str(title or code),"fields":{title?,category?,purpose?,scope?,procedure?,status?,owner?,review_date?}}\n'
        '{"op":"delete_sop","sop":str}\n'
        '{"op":"create_shift","employee":str(employee name), ...optional: name,days(list of weekday names),'
        'start_time("HH:MM"),end_time("HH:MM"),date("YYYY-MM-DD" one-off),role,notes,status(Active|Paused)}\n'
        '{"op":"update_shift","shift":str(shift name or employee name),"fields":{...same keys}}\n'
        '{"op":"delete_shift","shift":str}\n'
        "Write professional content yourself when details are missing (e.g. author full "
        "SOP procedures with numbered steps). If the request is NOT about teams/"
        'workflows/SOPs/shifts, respond {"actions": []}.\n\n'
        f"Employees:\n{emp_dir}\n\nCurrent operations inventory:\n" + "\n".join(inv) +
        f"\n\nUser request: {user_text}"
    )
    try:
        raw = _agent_provider.run(prompt, system="You output only strict JSON.")
        m = re.search(r"\{.*\}", raw, re.S)
        actions = json.loads(m.group(0)).get("actions", []) if m else []
    except Exception as e:  # noqa: BLE001
        run.status = "error"; run.error = f"ops parse: {e}"; db.commit()
        return {"kind": "error", "run_id": run.id,
                "message": f"❌ I could not understand the operations request: {e}"}
    if not actions:
        return None  # not an ops request — fall through to normal handling

    DAYS = {"mon": 0, "monday": 0, "tue": 1, "tuesday": 1, "wed": 2, "wednesday": 2,
            "thu": 3, "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5,
            "sun": 6, "sunday": 6}

    def femp(name):
        n = str(name or "").lower()
        return next((e for e in emps if e.company_id == cid and e.full_name.lower() == n), None) or \
               next((e for e in emps if e.company_id == cid and n and n in e.full_name.lower()), None)

    def fbyname(rows, name, *attrs):
        n = str(name or "").lower()
        for attr in attrs:
            r = next((x for x in rows if str(getattr(x, attr, "")).lower() == n), None)
            if r: return r
        for attr in attrs:
            r = next((x for x in rows if n and n in str(getattr(x, attr, "")).lower()), None)
            if r: return r
        return None

    def to_days(lst):
        out = []
        for d in (lst or []):
            if isinstance(d, int) and 0 <= d <= 6: out.append(d)
            else:
                v = DAYS.get(str(d).strip().lower()[:9], DAYS.get(str(d).strip().lower()[:3]))
                if v is not None: out.append(v)
        return sorted(set(out))

    def stages_json(lst):
        out = []
        for st in (lst or []):
            owner = str(st.get("owner") or "")
            t = fbyname(teams, owner, "name")
            e = femp(owner)
            out.append({"name": str(st.get("name") or ""),
                        "owner_kind": "team" if t else "employee",
                        "owner_id": t.id if t else (e.id if e else None),
                        "approval_required": bool(st.get("approval_required"))})
        return json.dumps(out)

    def team_fields(a):
        f = {}
        src = a.get("fields") if "fields" in a else a
        if src.get("name"): f["name"] = src["name"]
        for k in ("mission", "status", "icon"):
            if src.get(k): f[k] = src[k]
        if "lead" in src:
            e = femp(src["lead"]); f["lead_id"] = e.id if e else None
        if "members" in src:
            ids = [femp(nm).id for nm in (src["members"] or []) if femp(nm)]
            f["member_ids"] = json.dumps(ids)
        return f

    def sop_fields(a):
        src = a.get("fields") if "fields" in a else a
        f = {k: src[k] for k in ("title", "category", "purpose", "scope",
                                 "procedure", "status", "review_date") if src.get(k)}
        if "owner" in src:
            e = femp(src["owner"]); f["owner_id"] = e.id if e else None
        return f

    def shift_fields(a):
        src = a.get("fields") if "fields" in a else a
        f = {k: src[k] for k in ("name", "start_time", "end_time", "date",
                                 "role", "notes", "status") if src.get(k)}
        if "days" in src: f["days"] = json.dumps(to_days(src["days"]))
        if "employee" in src:
            e = femp(src["employee"])
            if e: f["employee_id"] = e.id
        return f

    results = []
    for a in actions:
        op = a.get("op", "")
        try:
            if op == "create_team":
                row = Team(company_id=cid, **team_fields(a))
                db.add(row); db.flush(); teams.append(row)
                results.append(f"🤝 Created team “{row.name}”")
                audit(db, "team.create", row.name, company_id=cid, user_id=user_id)
            elif op == "update_team":
                row = fbyname(teams, a.get("team"), "name")
                if not row: results.append(f"❌ Team “{a.get('team')}” not found"); continue
                for k, v in team_fields(a).items(): setattr(row, k, v)
                results.append(f"✏️ Updated team “{row.name}”")
                audit(db, "team.update", row.name, company_id=cid, user_id=user_id)
            elif op == "delete_team":
                row = fbyname(teams, a.get("team"), "name")
                if not row: results.append(f"❌ Team “{a.get('team')}” not found"); continue
                row.deleted_at = dt.datetime.utcnow()
                results.append(f"🗑️ Removed team “{row.name}”")
                audit(db, "team.delete", row.name, company_id=cid, user_id=user_id)
            elif op == "create_workflow":
                row = Workflow(company_id=cid, name=a.get("name") or "Workflow",
                               description=a.get("description") or "",
                               trigger=a.get("trigger") or "manual",
                               status=a.get("status") or "Active",
                               stages=stages_json(a.get("stages")))
                db.add(row); db.flush(); wfs.append(row)
                n = len(json.loads(row.stages))
                results.append(f"🔁 Created workflow “{row.name}” with {n} stage(s)")
                audit(db, "workflow.create", row.name, company_id=cid, user_id=user_id)
            elif op == "update_workflow":
                row = fbyname(wfs, a.get("workflow"), "name")
                if not row: results.append(f"❌ Workflow “{a.get('workflow')}” not found"); continue
                src = a.get("fields") or {}
                for k in ("name", "description", "trigger", "status"):
                    if src.get(k): setattr(row, k, src[k])
                if "stages" in src: row.stages = stages_json(src["stages"])
                results.append(f"✏️ Updated workflow “{row.name}”")
                audit(db, "workflow.update", row.name, company_id=cid, user_id=user_id)
            elif op == "delete_workflow":
                row = fbyname(wfs, a.get("workflow"), "name")
                if not row: results.append(f"❌ Workflow “{a.get('workflow')}” not found"); continue
                row.deleted_at = dt.datetime.utcnow()
                results.append(f"🗑️ Removed workflow “{row.name}”")
                audit(db, "workflow.delete", row.name, company_id=cid, user_id=user_id)
            elif op == "create_sop":
                f = sop_fields(a)
                if not f.get("title"): results.append("❌ SOP needs a title"); continue
                n = db.query(SOP).filter(SOP.company_id == cid).count() + 1
                row = SOP(company_id=cid, code=f"SOP-{n:03d}", **f)
                db.add(row); db.flush(); sops.append(row)
                results.append(f"📘 Created {row.code} “{row.title}” [{row.status}]")
                audit(db, "sop.create", row.title, company_id=cid, user_id=user_id)
            elif op == "update_sop":
                row = fbyname(sops, a.get("sop"), "code", "title")
                if not row: results.append(f"❌ SOP “{a.get('sop')}” not found"); continue
                f = sop_fields(a)
                if any(k in f and f[k] != getattr(row, k) for k in ("purpose", "scope", "procedure")):
                    row.version = (row.version or 1) + 1
                for k, v in f.items(): setattr(row, k, v)
                results.append(f"✏️ Updated {row.code} “{row.title}” → rev v{row.version}")
                audit(db, "sop.update", row.title, company_id=cid, user_id=user_id)
            elif op == "delete_sop":
                row = fbyname(sops, a.get("sop"), "code", "title")
                if not row: results.append(f"❌ SOP “{a.get('sop')}” not found"); continue
                row.deleted_at = dt.datetime.utcnow()
                results.append(f"🗑️ Removed {row.code} “{row.title}”")
                audit(db, "sop.delete", row.title, company_id=cid, user_id=user_id)
            elif op == "create_shift":
                f = shift_fields(a)
                if "employee_id" not in f:
                    e = femp(a.get("employee"))
                    if not e: results.append(f"❌ Employee “{a.get('employee')}” not found for the shift"); continue
                    f["employee_id"] = e.id
                row = Shift(company_id=cid, **f)
                db.add(row); db.flush(); shifts.append(row)
                who = next((e.full_name for e in emps if e.id == row.employee_id), "?")
                results.append(f"🕑 Rostered {who}: {row.start_time}–{row.end_time}"
                               f"{' on ' + row.date if row.date else ''}")
                audit(db, "shift.create", who, company_id=cid, user_id=user_id)
            elif op == "update_shift":
                key = str(a.get("shift") or "").lower()
                row = fbyname(shifts, key, "name") or next(
                    (s for s in shifts for e in emps
                     if s.employee_id == e.id and key and key in e.full_name.lower()), None)
                if not row: results.append(f"❌ Shift “{a.get('shift')}” not found"); continue
                for k, v in shift_fields(a).items(): setattr(row, k, v)
                results.append("✏️ Updated shift" + (f" “{row.name}”" if row.name else ""))
                audit(db, "shift.update", row.name or row.id, company_id=cid, user_id=user_id)
            elif op == "delete_shift":
                key = str(a.get("shift") or "").lower()
                row = fbyname(shifts, key, "name") or next(
                    (s for s in shifts for e in emps
                     if s.employee_id == e.id and key and key in e.full_name.lower()), None)
                if not row: results.append(f"❌ Shift “{a.get('shift')}” not found"); continue
                row.deleted_at = dt.datetime.utcnow()
                results.append("🗑️ Removed shift" + (f" “{row.name}”" if row.name else ""))
                audit(db, "shift.delete", row.name or row.id, company_id=cid, user_id=user_id)
            else:
                results.append(f"❌ Unknown action “{op}”")
        except Exception as exc:  # noqa: BLE001
            results.append(f"❌ {op} failed: {exc}")
    db.commit()
    run.status = "done"; run.result = "; ".join(results)[:2000]; db.commit()
    return {"kind": "ops_changed", "run_id": run.id,
            "message": f"🏭 OPERATIONS UPDATED — {company.name}\n" + "\n".join(results) +
                       "\n\nSee 🤝 Teams / 🔁 Workflows / 📘 SOPs / 🕑 Shift Roster for details."}


def _handle_collab_request(db: Session, chat: Chat, company, employee,
                           user_text: str, run: AgentRun, user_id: str) -> "dict | None":
    """Multiple employees (possibly from different companies) work on a task
    together. Each employee speaks in their own role and every turn is saved
    as a visible chat message."""
    companies, emps, directory = _org_directory(db, user_id)
    co_by_id = {c.id: c for c in companies}

    # participants = employees explicitly named in the prompt…
    low = user_text.lower()
    participants = [e for e in emps if e.full_name.lower() in low
                    or (e.full_name.split() and e.full_name.split()[0].lower() in low)]
    # …plus every employee of any company named in the prompt
    named_cos = [c for c in companies if c.name.lower() in low]
    for c in named_cos:
        for e in emps:
            if e.company_id == c.id and e not in participants:
                participants.append(e)
    # “all employees / everyone / the team” → whole active company
    if re.search(r"\b(all|every)\b.{0,20}\b(employees?|empolyees?|staff)\b|\beveryone\b|\bwhole team\b", low):
        for e in emps:
            if (not company or e.company_id == company.id) and e not in participants:
                participants.append(e)
    participants = [e for e in participants if e.status == "Active"]
    if len(participants) < 2:
        return None  # not enough named participants — fall through to normal handling

    def say(emp, text):
        db.add(Message(chat_id=chat.id, role="employee", employee_id=emp.id, content=text))
        db.commit()

    def label(emp):
        co = co_by_id.get(emp.company_id)
        return f"{emp.avatar} **{emp.full_name}** ({emp.job_title or 'staff'}, {co.name if co else '?'})"

    roster = ", ".join(f"{e.full_name} ({e.job_title or 'staff'}, "
                       f"{co_by_id.get(e.company_id).name if co_by_id.get(e.company_id) else '?'})"
                       for e in participants)
    say(participants[0], f"🤝 **COLLABORATION SESSION STARTED**\nTask: {user_text}\nParticipants: {roster}")

    transcript: list[str] = []
    rounds = 2
    try:
        for rnd in range(1, rounds + 1):
            for emp in participants:
                co = co_by_id.get(emp.company_id)
                system = _employee_system_prompt(co, emp, None) if co else f"You are {emp.full_name}."
                convo = "\n\n".join(transcript[-8:]) or "(you speak first)"
                phase = ("Contribute your part of the work from your own role's perspective. "
                         "Be concrete and brief (≤150 words)." if rnd == 1 else
                         "React to your colleagues, resolve conflicts, and state your final "
                         "deliverable/commitment. Be brief (≤120 words).")
                reply = _agent_provider.run(
                    f"## Joint task from the boss\n{user_text}\n\n## Team so far\n{convo}\n\n## Your turn\n{phase}",
                    system=system + "\nYou are in a working meeting with colleagues; speak as yourself only.")
                reply = (reply or "").strip() or "(no response)"
                transcript.append(f"{emp.full_name}: {reply}")
                say(emp, f"{label(emp)} — round {rnd}\n\n{reply}")
    except Exception as e:  # noqa: BLE001
        run.status = "error"; run.error = str(e); db.commit()
        return {"kind": "error", "run_id": run.id,
                "message": f"⚠ Collaboration stopped: {e}"}

    # closing summary by the acting employee (or first participant)
    closer = employee if employee in participants else participants[0]
    try:
        summary = _agent_provider.run(
            "Summarize this team discussion into: 1) decisions, 2) who does what, "
            "3) next steps. Be concise.\n\n" + "\n\n".join(transcript),
            system="You are the meeting facilitator.").strip()
    except Exception:  # noqa: BLE001
        summary = "(summary unavailable)"
    final = f"📋 **COLLABORATION SUMMARY**\n\n{summary}"
    say(closer, final)
    run.status = "done"; run.result = "collaboration finished"; db.commit()
    audit(db, "collab.session", f"participants={len(participants)} rounds={rounds}",
          company_id=company.id if company else None, user_id=user_id)
    return {"kind": "collaboration", "run_id": run.id, "message": final}


def _handle_mailbox_request(db: Session, company, employee, user_text: str,
                            run: AgentRun) -> dict:
    """List received (internal inbox) and sent mail for the company's employees."""
    wants_all = bool(re.search(r"\b(all|every|each)\b", user_text, re.I)) or not employee
    emps = (db.query(VirtualEmployee)
            .filter(VirtualEmployee.company_id == company.id,
                    VirtualEmployee.deleted_at.is_(None)).all()) if wants_all else [employee]

    # “list email ADDRESSES …” → identity directory, not the mailbox contents
    if re.search(r"\b(e-?mail\s+address(es)?|address(es)?\b.{0,20}\be-?mails?)\b", user_text, re.I):
        lines = []
        for emp in emps:
            idents = (db.query(EmailIdentity)
                      .filter(EmailIdentity.employee_id == emp.id,
                              EmailIdentity.deleted_at.is_(None)).all())
            addr = ", ".join(i.email_address for i in idents) if idents \
                else "(no email identity connected)"
            lines.append(f"• {emp.avatar} **{emp.full_name}** — {emp.job_title or 'staff'}: {addr}")
        run.status = "done"
        run.result = "email directory listed"
        db.commit()
        return {"kind": "email_directory", "run_id": run.id,
                "message": "📇 EMPLOYEE EMAIL DIRECTORY (in this system)\n" + "\n".join(lines)}

    lines: list[str] = []
    for emp in emps:
        inbox = (db.query(InboxMessage)
                 .filter(InboxMessage.employee_id == emp.id,
                         InboxMessage.deleted_at.is_(None))
                 .order_by(InboxMessage.created_at.desc()).limit(20).all())
        sent = (db.query(EmailMessage).join(EmailDraft, EmailMessage.draft_id == EmailDraft.id)
                .filter(EmailDraft.employee_id == emp.id)
                .order_by(EmailMessage.sent_at.desc()).limit(20).all())
        lines.append(f"\n**{emp.avatar} {emp.full_name}** — {emp.job_title}")
        if inbox:
            lines.append(f"  📥 Inbox ({len(inbox)}):")
            for m in inbox:
                flag = "🆕 " if not m.read else ""
                lines.append(f"    • {flag}From {m.from_address} — “{m.subject}” ({m.created_at:%Y-%m-%d %H:%M})")
        else:
            lines.append("  📥 Inbox: empty")
        if sent:
            lines.append(f"  📤 Sent ({len(sent)}):")
            for m in sent:
                when = m.sent_at.strftime("%Y-%m-%d %H:%M") if m.sent_at else "?"
                lines.append(f"    • To {m.recipients} — ({when})")
        else:
            lines.append("  📤 Sent: none")
    # mark the acting employee's inbox as read
    if employee and not wants_all:
        (db.query(InboxMessage)
         .filter(InboxMessage.employee_id == employee.id, InboxMessage.read == 0)
         .update({InboxMessage.read: 1}))
    run.status = "done"
    run.result = "mailbox listed"
    db.commit()
    return {"kind": "mailbox", "run_id": run.id,
            "message": "📬 EMAIL OVERVIEW" + "\n".join(lines)}


def _handle_email_request(db: Session, company, employee, user_text: str,
                          run: AgentRun, user_id: str, attachment: str | None = None) -> dict:
    """Spec §5.2 — email request workflow with strict identity controls."""
    if not employee_has_permission(employee, "draft_external"):
        run.status = "error"
        run.error = "Employee lacks draft_external permission"
        db.commit()
        return {"kind": "error", "message": f"❌ {employee.full_name} is not permitted to draft external communication.", "run_id": run.id}

    identity = (db.query(EmailIdentity)
                .filter(EmailIdentity.employee_id == employee.id,
                        EmailIdentity.verified.is_(True),
                        EmailIdentity.deleted_at.is_(None)).first())
    if not identity:
        run.status = "error"
        run.error = "No verified email identity"
        db.commit()
        return {"kind": "needs_identity", "run_id": run.id, "message": (
            f"❌ {employee.full_name} has no verified email account connected. "
            "I will not send from another employee's address. Please connect an "
            "authorized mailbox in Integrations, or select an employee that has one.")}

    recipients = EMAIL_RE.findall(user_text)

    # “… in this system” directory: every employee (across ALL of this user's
    # companies) with a connected identity. Used for recipient resolution by
    # NAME, for “all employees” expansion, and so the drafting model can list
    # the addresses when asked.
    cids = [c.id for c in _user_companies(db, user_id)] or [company.id]
    company_idents = (db.query(EmailIdentity, VirtualEmployee)
                      .join(VirtualEmployee, EmailIdentity.employee_id == VirtualEmployee.id)
                      .filter(EmailIdentity.company_id.in_(cids),
                              EmailIdentity.verified.is_(True),
                              EmailIdentity.deleted_at.is_(None),
                              VirtualEmployee.deleted_at.is_(None)).all())
    directory = [(emp.full_name, emp.job_title, ident.email_address)
                 for ident, emp in company_idents]

    # Employees mentioned BY NAME → resolve to their connected addresses
    # (“send the email to JianJia Huang and Alan Djen” works without typing
    # any address — the Employees registry is the source of truth).
    low = user_text.lower()
    named_missing: list[str] = []
    for name, _title, addr in directory:
        first = name.split()[0].lower() if name.split() else ""
        if (name.lower() in low or (first and re.search(rf"\b{re.escape(first)}\b", low))) \
                and addr not in recipients and addr != identity.email_address:
            recipients.append(addr)
    # names mentioned but WITHOUT a connected identity → tell the user
    all_emps = (db.query(VirtualEmployee)
                .filter(VirtualEmployee.company_id.in_(cids),
                        VirtualEmployee.deleted_at.is_(None)).all())
    with_ident = {n.lower() for n, _t, _a in directory}
    for e in all_emps:
        if e.full_name.lower() in low and e.full_name.lower() not in with_ident:
            named_missing.append(e.full_name)

    # “send to them / all employees / everyone / each employee” → resolve to the
    # employees' connected identities in this system.
    if re.search(r"\b(all|every|each)\b.{0,30}\b(employees?|staff|team)\b"
                 r"|\b(team|everyone)\b", user_text, re.I):
        for _name, _title, addr in directory:
            if addr not in recipients and addr != identity.email_address:
                recipients.append(addr)

    if not recipients:
        run.status = "done"
        run.result = "clarification requested: no recipient"
        db.commit()
        hint = (f" Note: {', '.join(named_missing)} has no email identity connected in "
                "this system." if named_missing else "")
        return {"kind": "clarify", "run_id": run.id, "message": (
            "I can draft that email, but the recipient is ambiguous. "
            "Please tell me the exact email address(es) to send to, or use an "
            "employee's name that has a connected identity." + hint)}

    system = _employee_system_prompt(company, employee, None)
    directory_block = "\n".join(f"- {n} ({t}): {a}" for n, t, a in directory) or "- (none)"
    draft_prompt = (
        "Draft a professional email for the following request. Respond ONLY with "
        "JSON: {\"subject\": str, \"body\": str}. Write in the employee's voice.\n\n"
        "Employee email directory IN THIS SYSTEM (use this exact data if the "
        "request asks to list/show the employees' emails; do not invent any):\n"
        f"{directory_block}\n\n"
        f"Request: {user_text}\nSignature to append: {identity.signature or employee.full_name}"
    )
    subject, body = "Update", ""
    try:
        raw = _agent_provider.run(draft_prompt, system=system)
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            data = json.loads(m.group(0))
            subject = data.get("subject", subject)
            body = data.get("body", "")
    except Exception:  # noqa: BLE001
        pass
    if not body:
        body = (f"(Draft generation unavailable — please edit)\n\nRegarding: {user_text}"
                f"\n\nEmployee email directory in this system:\n{directory_block}")
    body = body.rstrip() + f"\n\n{identity.signature or employee.full_name}"

    # Attachments: file the user attached in the chat + any local file paths mentioned in the prompt
    attach_paths: list[str] = []
    if attachment and Path(attachment).is_file():
        attach_paths.append(str(Path(attachment)))
    for m in re.findall(r"[A-Za-z]:\\[^\"'`|<>*?\r\n]+?\.[A-Za-z0-9]{1,6}(?![A-Za-z0-9.])", user_text):
        p = Path(m.strip())
        if p.is_file() and str(p) not in attach_paths:
            attach_paths.append(str(p))

    draft = EmailDraft(company_id=company.id, employee_id=employee.id,
                       identity_id=identity.id, to=", ".join(recipients),
                       subject=subject, body=body, status="awaiting_approval",
                       attachments=json.dumps(attach_paths))
    db.add(draft)
    db.commit()

    appr = ApprovalRequest(company_id=company.id, employee_id=employee.id,
                           kind="send_email", payload_ref=draft.id,
                           summary=f"Send email as {identity.email_address} to {', '.join(recipients)} — “{subject}”")
    db.add(appr)
    run.status = "done"
    run.result = f"email draft {draft.id} awaiting approval"
    db.commit()
    audit(db, "email.draft_created", f"draft={draft.id} to={draft.to}",
          company_id=company.id, user_id=user_id, employee_id=employee.id)

    # Auto-approval: emails (manual and scheduled) are approved and sent
    # immediately. The draft + approval records are kept for the audit trail.
    scheduled = user_text.startswith("[SCHEDULED TASK")
    appr.status = "approved"
    appr.decided_by = user_id
    appr.decided_at = dt.datetime.utcnow()
    db.commit()
    audit(db, "approval.auto_approved",
          f"approval={appr.id} ({'scheduled task' if scheduled else 'auto-approval policy'})",
          company_id=company.id, user_id=user_id, employee_id=employee.id)
    try:
        res = execute_approved_email(db, appr, user_id)
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "error": str(exc)}
    label = "Scheduled email" if scheduled else "Email"
    if res.get("ok"):
        mode = "simulated (no SMTP configured)" if res.get("simulated") else "sent for real via SMTP"
        return {"kind": "email_sent", "run_id": run.id, "draft_id": draft.id,
                "approval_id": appr.id, "message": (
                    f"📧 ✅ {label} auto-approved and {mode} from "
                    f"**{identity.display_name or employee.full_name} <{identity.email_address}>** "
                    f"to {', '.join(recipients)}.\n\nSubject: {subject}\n\n{body}\n\n"
                    + (f"📎 Attachments: {', '.join(attach_paths)}\n" if attach_paths else ""))}
    return {"kind": "email_draft", "run_id": run.id, "draft_id": draft.id,
            "approval_id": appr.id, "message": (
                f"📧 ⚠️ {label} was auto-approved but sending failed: "
                f"{res.get('error', 'unknown error')}. The draft is in the Approval Inbox "
                "so you can retry manually.")}


def execute_approved_email(db: Session, appr: ApprovalRequest, user_id: str) -> dict:
    draft = db.get(EmailDraft, appr.payload_ref)
    if not draft:
        raise HTTPException(404, "Draft not found")
    identity = db.get(EmailIdentity, draft.identity_id)
    if not identity or not identity.verified:
        raise HTTPException(400, "Sender identity is no longer verified")
    provider = get_email_provider(identity.provider)
    to = [a.strip() for a in draft.to.split(",") if a.strip()]
    cc = [a.strip() for a in draft.cc.split(",") if a.strip()]
    bcc = [a.strip() for a in draft.bcc.split(",") if a.strip()]
    try:
        attach_paths = [p for p in json.loads(draft.attachments or "[]") if Path(p).is_file()]
    except (ValueError, TypeError):
        attach_paths = []
    from .providers import SmtpEmailProvider
    if isinstance(provider, SmtpEmailProvider):
        res = provider.send(identity.email_address, to, cc, bcc, draft.subject,
                            draft.body, draft.idempotency_key, attachments=attach_paths)
    else:
        body = draft.body + ("\n\n📎 Attachments (paths recorded, simulated send):\n"
                             + "\n".join(attach_paths) if attach_paths else "")
        res = provider.send(identity.email_address, to, cc, bcc, draft.subject,
                            body, draft.idempotency_key)
    if res.ok:
        draft.status = "sent"
        msg = EmailMessage(draft_id=draft.id, provider_message_id=res.provider_message_id,
                           sent_at=dt.datetime.utcnow(), sender=identity.email_address,
                           recipients=draft.to, approved_by=user_id,
                           final_content=f"Subject: {draft.subject}\n\n{draft.body}")
        db.add(msg)
        # Internal delivery: recipients matching a virtual employee's connected
        # identity get the mail in their platform inbox (works even with the
        # simulated local-dev provider).
        for addr in to + cc + bcc:
            rcpt_idents = (db.query(EmailIdentity)
                           .filter(EmailIdentity.email_address == addr,
                                   EmailIdentity.deleted_at.is_(None)).all())
            for ri in rcpt_idents:
                db.add(InboxMessage(company_id=ri.company_id, employee_id=ri.employee_id,
                                    from_address=identity.email_address, to_address=addr,
                                    subject=draft.subject, body=draft.body))
        appr.status = "executed"
        db.commit()
        audit(db, "email.sent",
              f"draft={draft.id} provider_id={res.provider_message_id} simulated={res.simulated}",
              company_id=draft.company_id, user_id=user_id, employee_id=draft.employee_id)
        return {"ok": True, "provider_message_id": res.provider_message_id,
                "simulated": res.simulated}
    draft.status = "failed"
    appr.status = "failed"
    db.commit()
    audit(db, "email.failed", f"draft={draft.id} error={res.error}",
          company_id=draft.company_id, user_id=user_id)
    return {"ok": False, "error": res.error}
