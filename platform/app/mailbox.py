# SPDX-License-Identifier: MIT
"""Real-mail IMAP client — connect any number of personal email accounts
(IMAP server / port / SSL / auth method / username / password), browse
folders and messages in the Email view and operate the mailbox by chat
prompt (read / search / mark read / unread / delete)."""
from __future__ import annotations

import datetime as dt
import email
import email.header
import email.utils
import imaplib
import json
import re as _re
import smtplib
from email.message import EmailMessage as _OutMessage

from sqlalchemy.orm import Session

from .db import MailAccount
from .security import decrypt_secret, encrypt_secret

imaplib._MAXLINE = 10_000_000  # large mailboxes


# ==================== connection ====================
def _secret(acct: MailAccount) -> str:
    try:
        return decrypt_secret(acct.encrypted_secret)
    except Exception:  # noqa: BLE001
        return ""


def connect(acct: MailAccount) -> imaplib.IMAP4:
    """Open + authenticate an IMAP session for the account."""
    if acct.use_ssl:
        conn = imaplib.IMAP4_SSL(acct.imap_host, acct.imap_port or 993)
    else:
        conn = imaplib.IMAP4(acct.imap_host, acct.imap_port or 143)
        try:
            conn.starttls()
        except Exception:  # noqa: BLE001 — server without STARTTLS
            pass
    secret = _secret(acct)
    if acct.auth_method == "oauth2":
        auth = f"user={acct.username}\x01auth=Bearer {secret}\x01\x01"
        conn.authenticate("XOAUTH2", lambda _: auth.encode())
    else:
        conn.login(acct.username, secret)
    return conn


def save_account(db: Session, user_id: str, data: dict,
                 acct: MailAccount | None = None) -> MailAccount:
    """Create or update an account; the password/token is encrypted at rest."""
    if acct is None:
        acct = MailAccount(user_id=user_id)
        db.add(acct)
    acct.label = data.get("label") or data.get("username") or acct.label
    acct.imap_host = data["imap_host"].strip()
    acct.imap_port = int(data.get("imap_port") or (993 if data.get("use_ssl", True) else 143))
    acct.use_ssl = bool(data.get("use_ssl", True))
    acct.auth_method = data.get("auth_method") or "password"
    acct.username = data["username"].strip()
    acct.smtp_host = (data.get("smtp_host") or "").strip()
    acct.smtp_port = int(data.get("smtp_port") or 465)
    if data.get("password"):
        acct.encrypted_secret = encrypt_secret(data["password"])
    db.commit()
    return acct


def test_account(acct: MailAccount) -> dict:
    """Verify sign-in; update status/last_error on the row (caller commits)."""
    try:
        conn = connect(acct)
        typ, _ = conn.select("INBOX", readonly=True)
        conn.logout()
        acct.status = "connected"
        acct.last_error = ""
        acct.last_checked_at = dt.datetime.utcnow()
        return {"ok": typ == "OK"}
    except Exception as e:  # noqa: BLE001
        acct.status = "error"
        acct.last_error = str(e)[:300]
        return {"ok": False, "error": str(e)[:300]}


# ==================== decode helpers ====================
def _dec_hdr(raw) -> str:
    if raw is None:
        return ""
    parts = []
    for val, enc in email.header.decode_header(str(raw)):
        if isinstance(val, bytes):
            try:
                parts.append(val.decode(enc or "utf-8", errors="replace"))
            except LookupError:
                parts.append(val.decode("utf-8", errors="replace"))
        else:
            parts.append(val)
    return "".join(parts).strip()


def _dec_folder(raw: bytes) -> tuple[str, str, list[str]]:
    """LIST response line → (raw name, display name, flags)."""
    s = raw.decode(errors="replace")
    m = _re.match(r'\((?P<flags>[^)]*)\)\s+"(?P<sep>[^"]*)"\s+(?P<name>.+)$', s)
    if not m:
        return s, s, []
    name = m.group("name").strip().strip('"')
    flags = [f.strip().lstrip("\\").lower() for f in m.group("flags").split()]
    # modified-UTF7 decode for display (e.g. Gmail's non-ASCII folders)
    try:
        disp = name.encode("ascii").decode("utf-7") if "&" in name else name
    except Exception:  # noqa: BLE001
        disp = name
    return name, disp, flags


def _body_of(msg: email.message.Message) -> tuple[str, str, list[str]]:
    """(text, html, attachment names) of a parsed message."""
    text, html, atts = "", "", []
    for part in msg.walk():
        cd = str(part.get("Content-Disposition") or "")
        fn = part.get_filename()
        if fn and "attachment" in cd.lower():
            atts.append(_dec_hdr(fn))
            continue
        if part.get_content_maintype() == "multipart":
            continue
        try:
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if part.get_content_type() == "text/plain" and not text:
            text = body
        elif part.get_content_type() == "text/html" and not html:
            html = body
    return text, html, atts


def _hdr_summary(uid: str, raw: bytes, flags_raw: bytes | str) -> dict:
    msg = email.message_from_bytes(raw)
    flags = str(flags_raw)
    d = None
    try:
        d = email.utils.parsedate_to_datetime(msg.get("Date"))
    except Exception:  # noqa: BLE001
        pass
    return {
        "uid": uid,
        "from": _dec_hdr(msg.get("From")),
        "to": _dec_hdr(msg.get("To")),
        "subject": _dec_hdr(msg.get("Subject")) or "(no subject)",
        "date": d.isoformat() if d else "",
        "seen": "\\Seen" in flags,
        "answered": "\\Answered" in flags,
        "flagged": "\\Flagged" in flags,
    }


# ==================== operations ====================
def list_folders(acct: MailAccount) -> list[dict]:
    conn = connect(acct)
    try:
        typ, rows = conn.list()
        out = []
        for row in rows or []:
            if not row:
                continue
            name, disp, flags = _dec_folder(row)
            if "noselect" in flags:
                continue
            info = {"name": name, "display": disp, "flags": flags,
                    "total": 0, "unseen": 0}
            try:
                typ, st = conn.status(f'"{name}"', "(MESSAGES UNSEEN)")
                if typ == "OK" and st and st[0]:
                    s = st[0].decode(errors="replace")
                    m = _re.search(r"MESSAGES\s+(\d+)", s)
                    u = _re.search(r"UNSEEN\s+(\d+)", s)
                    info["total"] = int(m.group(1)) if m else 0
                    info["unseen"] = int(u.group(1)) if u else 0
            except Exception:  # noqa: BLE001
                pass
            out.append(info)
        # INBOX first, then special folders, then the rest alphabetically
        rank = {"inbox": 0, "sent": 1, "drafts": 2, "junk": 3, "spam": 3,
                "trash": 4, "deleted": 4, "archive": 5}
        out.sort(key=lambda f: (rank.get(f["display"].split("/")[-1].lower(),
                                         0 if f["name"].upper() == "INBOX" else 9),
                                f["display"].lower()))
        return out
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def list_messages(acct: MailAccount, folder: str = "INBOX", limit: int = 50,
                  page: int = 0, query: str = "", unseen_only: bool = False,
                  category: str = "") -> dict:
    conn = connect(acct)
    try:
        typ, data = conn.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise RuntimeError(f"Cannot open folder {folder}")
        crit_parts = []
        if unseen_only:
            crit_parts.append("UNSEEN")
        if query:
            q = query.replace('"', "")
            crit_parts.append(f'OR SUBJECT "{q}" FROM "{q}"')
        # Gmail category tabs (Primary/Promotions/Social/…) — X-GM-RAW extension
        if category and "gmail" in acct.imap_host.lower():
            if category == "primary":
                crit_parts.append('X-GM-RAW "category:primary"')
            else:
                crit_parts.append(f'X-GM-RAW "category:{category}"')
        crit = "(" + " ".join(crit_parts) + ")" if crit_parts else "ALL"
        typ, found = conn.uid("SEARCH", None, crit)
        uids = (found[0] or b"").split()
        total = len(uids)
        uids = uids[::-1]                                       # newest first
        chunk = uids[page * limit:(page + 1) * limit]
        out = []
        if chunk:
            typ, rows = conn.uid("FETCH", b",".join(chunk).decode(),
                                 "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])")
            i = 0
            while rows and i < len(rows):
                if isinstance(rows[i], tuple):
                    meta = rows[i][0].decode(errors="replace")
                    m = _re.search(r"UID (\d+)", meta)
                    if m:
                        out.append(_hdr_summary(m.group(1), rows[i][1], meta))
                i += 1
        # newest first by REAL timestamp (date + time normalized to UTC) —
        # plain ISO-string comparison mis-orders mixed timezone offsets
        def _ts(r: dict) -> float:
            try:
                return dt.datetime.fromisoformat(r["date"]).timestamp()
            except Exception:  # noqa: BLE001
                return 0.0
        out.sort(key=_ts, reverse=True)
        return {"folder": folder, "total": total, "page": page,
                "limit": limit, "messages": out}
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def fetch_message(acct: MailAccount, folder: str, uid: str,
                  mark_seen: bool = True) -> dict:
    conn = connect(acct)
    try:
        conn.select(f'"{folder}"', readonly=not mark_seen)
        typ, rows = conn.uid("FETCH", uid, "(FLAGS RFC822)")
        raw = None
        for row in rows or []:
            if isinstance(row, tuple):
                raw = row[1]
        if raw is None:
            raise RuntimeError("Message not found")
        msg = email.message_from_bytes(raw)
        text, html, atts = _body_of(msg)
        if mark_seen:
            try:
                conn.uid("STORE", uid, "+FLAGS", r"(\Seen)")
            except Exception:  # noqa: BLE001
                pass
        d = None
        try:
            d = email.utils.parsedate_to_datetime(msg.get("Date"))
        except Exception:  # noqa: BLE001
            pass
        return {"uid": uid, "folder": folder,
                "from": _dec_hdr(msg.get("From")), "to": _dec_hdr(msg.get("To")),
                "cc": _dec_hdr(msg.get("Cc")),
                "subject": _dec_hdr(msg.get("Subject")) or "(no subject)",
                "date": d.isoformat() if d else "",
                "text": text, "html": html, "attachments": atts}
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


def message_action(acct: MailAccount, folder: str, uid: str, action: str) -> dict:
    """read | unread | flag | unflag | delete on one message."""
    conn = connect(acct)
    try:
        conn.select(f'"{folder}"')
        if action == "read":
            conn.uid("STORE", uid, "+FLAGS", r"(\Seen)")
        elif action == "unread":
            conn.uid("STORE", uid, "-FLAGS", r"(\Seen)")
        elif action == "flag":
            conn.uid("STORE", uid, "+FLAGS", r"(\Flagged)")
        elif action == "unflag":
            conn.uid("STORE", uid, "-FLAGS", r"(\Flagged)")
        elif action == "delete":
            conn.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
            conn.expunge()
        else:
            raise RuntimeError(f"Unknown action {action}")
        return {"ok": True}
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass


# ==================== outbound (SMTP): reply / forward / compose ====================
def _smtp_host_of(acct: MailAccount) -> tuple[str, int]:
    if acct.smtp_host:
        return acct.smtp_host, acct.smtp_port or 465
    h = acct.imap_host.lower()
    if h.startswith("imap."):
        return "smtp." + h[5:], 465
    if h.startswith("mail."):
        return h, 465
    return "smtp." + h, 465


def send_message(acct: MailAccount, to: str, subject: str, body: str,
                 cc: str = "", in_reply_to: str = "",
                 references: str = "") -> dict:
    """Send via the account's SMTP server and append a copy to the Sent folder."""
    host, port = _smtp_host_of(acct)
    msg = _OutMessage()
    msg["From"] = acct.username
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=acct.username.split("@")[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = (references + " " + in_reply_to).strip()
    msg.set_content(body)
    secret = _secret(acct)
    if port == 465:
        smtp = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        smtp = smtplib.SMTP(host, port, timeout=30)
        smtp.starttls()
    try:
        if acct.auth_method == "oauth2":
            import base64
            auth = f"user={acct.username}\x01auth=Bearer {secret}\x01\x01"
            smtp.docmd("AUTH", "XOAUTH2 " + base64.b64encode(auth.encode()).decode())
        else:
            smtp.login(acct.username, secret)
        smtp.send_message(msg)
    finally:
        try:
            smtp.quit()
        except Exception:  # noqa: BLE001
            pass
    # append a copy to the Sent folder so it shows up in every client
    try:
        conn = connect(acct)
        sent = None
        typ, rows = conn.list()
        for row in rows or []:
            name, disp, flags = _dec_folder(row or b"")
            if "sent" in flags or "sent" in disp.lower():
                sent = name
                break
        if sent:
            conn.append(f'"{sent}"', r"(\Seen)",
                        imaplib.Time2Internaldate(dt.datetime.now().timestamp()),
                        msg.as_bytes())
        conn.logout()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "smtp": f"{host}:{port}"}


def reply_message(acct: MailAccount, folder: str, uid: str, body: str,
                  reply_all: bool = False) -> dict:
    """Reply to a message: proper threading headers + quoted original."""
    conn = connect(acct)
    try:
        conn.select(f'"{folder}"', readonly=True)
        typ, rows = conn.uid("FETCH", uid, "(RFC822)")
        raw = next((r[1] for r in rows or [] if isinstance(r, tuple)), None)
        if raw is None:
            raise RuntimeError("Original message not found")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    orig = email.message_from_bytes(raw)
    sender = email.utils.parseaddr(orig.get("Reply-To") or orig.get("From"))[1]
    cc = ""
    if reply_all:
        others = email.utils.getaddresses(orig.get_all("To", []) + orig.get_all("Cc", []))
        cc = ", ".join(a for _, a in others
                       if a and a.lower() not in (acct.username.lower(), sender.lower()))
    subj = _dec_hdr(orig.get("Subject"))
    if not subj.lower().startswith("re:"):
        subj = "Re: " + subj
    text, html, _ = _body_of(orig)
    quoted = text or _re.sub(r"<[^>]+>", " ", html)
    quote = "\n".join("> " + ln for ln in quoted.splitlines()[:60])
    full = f"{body}\n\nOn {_dec_hdr(orig.get('Date'))}, {_dec_hdr(orig.get('From'))} wrote:\n{quote}"
    return send_message(acct, sender, subj, full, cc=cc,
                        in_reply_to=orig.get("Message-ID", ""),
                        references=orig.get("References", ""))


def forward_message(acct: MailAccount, folder: str, uid: str, to: str,
                    body: str = "") -> dict:
    conn = connect(acct)
    try:
        conn.select(f'"{folder}"', readonly=True)
        typ, rows = conn.uid("FETCH", uid, "(RFC822)")
        raw = next((r[1] for r in rows or [] if isinstance(r, tuple)), None)
        if raw is None:
            raise RuntimeError("Original message not found")
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass
    orig = email.message_from_bytes(raw)
    subj = _dec_hdr(orig.get("Subject"))
    if not subj.lower().startswith(("fwd:", "fw:")):
        subj = "Fwd: " + subj
    text, html, atts = _body_of(orig)
    content = text or _re.sub(r"<[^>]+>", " ", html)
    full = (f"{body}\n\n---------- Forwarded message ----------\n"
            f"From: {_dec_hdr(orig.get('From'))}\nDate: {_dec_hdr(orig.get('Date'))}\n"
            f"Subject: {_dec_hdr(orig.get('Subject'))}\nTo: {_dec_hdr(orig.get('To'))}\n"
            + (f"Attachments (not included): {', '.join(atts)}\n" if atts else "")
            + f"\n{content[:20000]}")
    return send_message(acct, to, subj, full)


# ==================== chat-prompt integration ====================
# "check my email", "any new emails?", "read the email from Amazon",
# "mark the email from PayPal as read", "delete the email about invoice" …
REALMAIL_INTENT = _re.compile(
    r"\b(check|read|open|show|list|any|search|find|delete|remove|mark|reply|forward)\b"
    r".{0,60}\b(my\s+)?(e-?mails?|inbox|mailbox)\b"
    r"|\b(e-?mails?|inbox|mailbox)\b.{0,40}"
    r"\b(check|read|open|show|list|search|find|delete|remove|mark|reply|forward)\b"
    r"|\bnew\s+e-?mails?\b"
    r"|\b(reply|forward|read|open|delete|remove|mark)\b[^\n]{0,25}#\s?\d", _re.I)
_MAIL_DELETE = _re.compile(r"\b(delete|remove|trash)\b", _re.I)
_MAIL_REPLY = _re.compile(r"\breply\b(?:.{0,60}?\bwith\b\s*[:：]?\s*(?P<body>.+))?", _re.I | _re.S)
_MAIL_FORWARD = _re.compile(r"\bforward\b.{0,80}?\bto\s+(?P<to>[\w.+-]+@[\w-]+\.[\w.-]+)", _re.I)
_MAIL_READFULL = _re.compile(r"\b(read|open|show)\b.{0,40}\be-?mail\b", _re.I)
_MAIL_MARK_READ = _re.compile(r"\bmark\b.{0,50}\b(as\s+)?read\b", _re.I)
_MAIL_MARK_UNREAD = _re.compile(r"\bmark\b.{0,50}\b(as\s+)?unread\b", _re.I)
_MAIL_UNREAD_ONLY = _re.compile(r"\b(new|unread|unseen)\b", _re.I)
_FROM_ABOUT = _re.compile(
    r"\b(?:from|about|regarding|re:?|sender)\s+[\"“']?([\w @.&'\-]{2,60})[\"”']?", _re.I)
_SENDER_ADDR = _re.compile(
    r"\b(?:sender|from)\b[^\n]{0,20}?([\w.+-]+@[\w-]+\.[\w.-]+)", _re.I)
_MAIL_NUM = _re.compile(r"(?:e-?mail|message|item)\s*#?\s*(\d{1,3})\b|#(\d{1,3})\b", _re.I)


def _date_filter(text: str) -> "dt.date | None":
    """'today' / 'yesterday' / explicit date in the prompt → filter date."""
    tl = text.lower()
    if "today" in tl:
        return dt.date.today()
    if "yesterday" in tl:
        return dt.date.today() - dt.timedelta(days=1)
    m = _re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", tl)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = _re.search(r"\bon\s+(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", tl)
    if m:
        y = int(m.group(3)) if m.group(3) else dt.date.today().year
        if y < 100:
            y += 2000
        try:
            return dt.date(y, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    return None


def _msg_date(r: dict) -> "dt.date | None":
    try:
        return dt.datetime.fromisoformat(r["date"]).astimezone().date()
    except Exception:  # noqa: BLE001
        return None


def _pick_account(db: Session, user_id: str, text: str) -> MailAccount | None:
    accts = db.query(MailAccount).filter(MailAccount.user_id == user_id).all()
    if not accts:
        return None
    tl = text.lower()
    for a in accts:
        for token in (a.label, a.username):
            if token and token.lower() in tl:
                return a
    return accts[0]


def _match_msg(msgs: list[dict], text: str) -> dict | None:
    """Best message match for 'the email from X / about Y / email #N'."""
    # explicit reference by list number — “email #3” / “reply to #2”
    mn = _MAIL_NUM.search(text)
    if mn:
        n = int(mn.group(1) or mn.group(2))
        if 1 <= n <= len(msgs):
            return msgs[n - 1]
    # exact sender address — “the email from x@y.com”
    ma = _SENDER_ADDR.search(text)
    if ma:
        addr = ma.group(1).lower()
        for r in msgs:
            if addr in r["from"].lower():
                return r
    m = _FROM_ABOUT.search(text)
    needle = (m.group(1).strip().lower() if m else "")
    if needle:
        for r in msgs:
            if needle in r["from"].lower() or needle in r["subject"].lower():
                return r
    # fall back on any content word ≥4 chars appearing in subject/from
    words = [w for w in _re.findall(r"[\w'&.-]{4,}", text.lower())
             if w not in ("email", "mail", "emails", "mails", "read", "open",
                          "show", "delete", "remove", "mark", "unread",
                          "inbox", "mailbox", "please", "about", "from")]
    best, score = None, 0
    for r in msgs:
        blob = (r["from"] + " " + r["subject"]).lower()
        hit = sum(1 for w in words if w in blob)
        if hit > score:
            best, score = r, hit
    return best


def _fmt_row(r: dict, n: int, acct_id: str, folder: str = "INBOX") -> str:
    flag = "🆕 " if not r["seen"] else ""
    when = r["date"][:16].replace("T", " ") if r["date"] else "?"
    # [[MAIL|…]] token → the chat UI renders it as a clickable OPEN control
    return (f"{n}. {flag}**{r['subject']}** — {r['from']} ({when}) "
            f"[[MAIL|{acct_id}|{folder}|{r['uid']}]]")


def handle_mail_prompt(db: Session, user_text: str, user_id: str) -> str | None:
    """Operate the user's real IMAP mailboxes from a chat prompt.
    Returns a reply string, or None when this is not a real-mail command
    (so the internal virtual-employee mailbox handler still runs)."""
    if not REALMAIL_INTENT.search(user_text):
        return None
    acct = _pick_account(db, user_id, user_text)
    if not acct:
        return None  # no real accounts — let the internal mailbox answer
    try:
        # optional filters — “sender is x@y.com”, “from …”, “today”, “on 8/11”
        want_sender = _SENDER_ADDR.search(user_text)
        want_day = _date_filter(user_text)
        fetch_n = 50 if (want_sender or want_day) else 25
        listing = list_messages(acct, "INBOX", limit=fetch_n,
                                # sender filter runs on the IMAP server (SEARCH FROM)
                                query=want_sender.group(1) if want_sender else "",
                                unseen_only=bool(_MAIL_UNREAD_ONLY.search(user_text)
                                                 and not _MAIL_MARK_UNREAD.search(user_text)))
        msgs = listing["messages"]
        filters = []
        if want_sender:
            addr = want_sender.group(1).lower()
            msgs = [r for r in msgs if addr in r["from"].lower()]
            filters.append(f"FROM {addr}")
        if want_day:
            msgs = [r for r in msgs if _msg_date(r) == want_day]
            filters.append(want_day.strftime("DATE %Y-%m-%d"))
        acct.status, acct.last_error = "connected", ""
        acct.last_checked_at = dt.datetime.utcnow()
        db.commit()

        # -- operations on one message ------------------------------------
        if _MAIL_FORWARD.search(user_text):
            m = _MAIL_FORWARD.search(user_text)
            allm = msgs or list_messages(acct, "INBOX", limit=25)["messages"]
            r = _match_msg(allm, user_text)
            if not r:
                return "❌ I couldn't find a matching email to forward."
            forward_message(acct, "INBOX", r["uid"], m.group("to"))
            return f"📤 Forwarded **{r['subject']}** to {m.group('to')}."
        if _re.search(r"\breply\b", user_text, _re.I) and (_FROM_ABOUT.search(user_text)
                                                           or _MAIL_NUM.search(user_text)):
            allm = msgs or list_messages(acct, "INBOX", limit=25)["messages"]
            r = _match_msg(allm, user_text)
            if not r:
                return "❌ I couldn't find a matching email to reply to."
            mb = _MAIL_REPLY.search(user_text)
            body = (mb.group("body") or "").strip() if mb else ""
            if not body:
                return (f"❓ Found **{r['subject']}** from {r['from']} — what should the reply "
                        "say? Try: “reply to the email from … with: <your message>”.")
            reply_message(acct, "INBOX", r["uid"], body)
            return f"↩️ Replied to **{r['subject']}** ({r['from']})."
        if _MAIL_DELETE.search(user_text):
            if not msgs:
                msgs = list_messages(acct, "INBOX", limit=25)["messages"]
            r = _match_msg(msgs, user_text)
            if not r:
                return "❌ I couldn't find a matching email in the inbox to delete."
            message_action(acct, "INBOX", r["uid"], "delete")
            return (f"🗑️ Deleted the email **{r['subject']}** from {r['from']} "
                    f"in {acct.label or acct.username}.")
        if _MAIL_MARK_UNREAD.search(user_text):
            allm = list_messages(acct, "INBOX", limit=25)["messages"]
            r = _match_msg(allm, user_text)
            if not r:
                return "❌ I couldn't find a matching email to mark as unread."
            message_action(acct, "INBOX", r["uid"], "unread")
            return f"✉️ Marked **{r['subject']}** as unread."
        if _MAIL_MARK_READ.search(user_text):
            allm = list_messages(acct, "INBOX", limit=25)["messages"]
            r = _match_msg(allm, user_text)
            if not r:
                return "❌ I couldn't find a matching email to mark as read."
            message_action(acct, "INBOX", r["uid"], "read")
            return f"📖 Marked **{r['subject']}** as read."
        if _MAIL_READFULL.search(user_text) and (_FROM_ABOUT.search(user_text)
                                                 or _MAIL_NUM.search(user_text)
                                                 or want_sender or want_day):
            allm = msgs or list_messages(acct, "INBOX", limit=25)["messages"]
            r = _match_msg(allm, user_text) or (allm[0] if len(allm) == 1 else None)
            if not r:
                if allm:  # several candidates — show them as a clickable list
                    rows = "\n".join(_fmt_row(m2, i + 1, acct.id) for i, m2 in enumerate(allm[:15]))
                    return (f"🔎 I found {len(allm)} matching email(s) — click one to open it, "
                            f"or say “read email #N”:\n{rows}")
                return "❌ I couldn't find that email in the inbox."
            full = fetch_message(acct, "INBOX", r["uid"], mark_seen=True)
            body = (full["text"] or _re.sub(r"<[^>]+>", " ", full["html"]))[:2500].strip()
            atts = ("\n📎 Attachments: " + ", ".join(full["attachments"])) \
                if full["attachments"] else ""
            return (f"📧 **{full['subject']}** [[MAIL|{acct.id}|INBOX|{r['uid']}]]\n"
                    f"From: {full['from']}\n"
                    f"To: {full['to']}\nDate: {full['date'][:16].replace('T', ' ')}"
                    f"{atts}\n\n{body}")

        # -- default: list the inbox ---------------------------------------
        unseen = sum(1 for r in msgs if not r["seen"])
        fdesc = (" · " + " · ".join(filters)) if filters else ""
        if not msgs:
            return (f"📭 No {'unread ' if _MAIL_UNREAD_ONLY.search(user_text) else ''}"
                    f"emails in {acct.label or acct.username} (INBOX{fdesc}).")
        head = (f"📬 **{acct.label or acct.username}** — INBOX{fdesc} · "
                + (f"{len(msgs)} matching message(s)" if filters else
                   f"{listing['total']} message(s), {unseen} unread (showing {len(msgs)})") + ":")
        return head + "\n" + "\n".join(_fmt_row(r, i + 1, acct.id)
                                       for i, r in enumerate(msgs[:15])) + \
            "\n\n💡 Click an email to open it — or reference it by number: “read email #2”, " \
            "“reply to #1 with: …”, “forward #3 to addr@example.com”, “delete email #4”."
    except Exception as e:  # noqa: BLE001
        acct.status = "error"
        acct.last_error = str(e)[:300]
        db.commit()
        return (f"❌ Could not check {acct.label or acct.username}: {str(e)[:200]}\n"
                "Verify the IMAP settings in the 📧 Email page.")
