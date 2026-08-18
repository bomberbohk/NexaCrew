# SPDX-License-Identifier: MIT
"""Self-learning of each user's personal operation vocabulary.

Different users phrase the same operation differently (dialect, slang,
shorthand).  This module makes the platform ADAPT to each user:

1. Explicit teaching — "teach: 睇下 = check", "學習: 丟咗佢 = delete",
   "when I say sup mail I mean check email".
2. Habit learning — words that were NOT understood by the built-in
   dictionary are tracked per user; when the same unknown word keeps
   appearing in prompts that end up as the same operation, it is
   auto-promoted into the user's personal dictionary.
3. Management — "show my phrases", "forget phrase 睇下".

Learned phrases are applied BEFORE the built-in dictionary in
``normalize_intent_text``, so the user's own wording always wins."""
from __future__ import annotations

import datetime as dt
import re

from sqlalchemy.orm import Session

from .db import UserPhrase

# activate an auto-learned phrase after this many consistent observations
AUTO_ACTIVATE_HITS = 3

# operation verbs we can associate an unknown word with
_OP_VERBS = ("check", "read", "open", "show", "list", "search", "find",
             "delete", "remove", "cancel", "reply", "forward", "send",
             "mark", "add", "create", "book", "move", "reschedule",
             "change", "update")

TEACH_INTENT = re.compile(
    r"^\s*(?:teach|learn|記住|记住|學習|学习|教)\s*[:：]?\s*(?P<phrase>.+?)\s*[=＝→]\s*(?P<repl>.+?)\s*$"
    r"|^\s*when\s+i\s+say\s+[\"“']?(?P<phrase2>.+?)[\"”']?\s*,?\s*i\s+mean\s+(?P<repl2>.+?)\s*$",
    re.I)
SHOW_INTENT = re.compile(
    r"\b(show|list)\b.{0,20}\b(my\s+)?(learned\s+)?(phrases|vocabulary|words)\b"
    r"|(顯示|显示|列出).{0,8}(詞彙|词汇|短語|短语|用語|用语)", re.I)
FORGET_INTENT = re.compile(
    r"\b(forget|unlearn|delete)\s+(the\s+)?phrase\s+[\"“']?(?P<phrase>.+?)[\"”']?\s*$"
    r"|(忘記|忘记|刪除|删除)(短語|短语|詞彙|词汇|用語|用语)\s*[:：]?\s*(?P<phrase2>.+?)\s*$", re.I)

_CJK_WORD = re.compile(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]{1,6}")
_LATIN_WORD = re.compile(r"[a-zA-ZÀ-ÿ]{3,}")


def get_user_phrases(db: Session, user_id: str) -> list[tuple[str, str]]:
    rows = (db.query(UserPhrase)
            .filter(UserPhrase.user_id == user_id, UserPhrase.active.is_(True))
            .all())
    return [(r.phrase, r.replacement) for r in rows]


def handle_phrase_prompt(db: Session, text: str, user_id: str) -> str | None:
    """Teach / show / forget commands. Returns reply or None."""
    m = TEACH_INTENT.match(text.strip())
    if m:
        phrase = (m.group("phrase") or m.group("phrase2") or "").strip(" \"'“”‘’")
        repl = (m.group("repl") or m.group("repl2") or "").strip(" \"'“”‘’").lower()
        if not phrase or not repl or len(phrase) > 60 or len(repl) > 60:
            return "❓ Use: teach: <your phrase> = <meaning> — e.g. “teach: 睇下 = check”."
        row = (db.query(UserPhrase)
               .filter(UserPhrase.user_id == user_id, UserPhrase.phrase == phrase).first())
        if not row:
            row = UserPhrase(user_id=user_id, phrase=phrase)
            db.add(row)
        row.replacement = repl
        row.source = "taught"
        row.active = True
        row.hits = AUTO_ACTIVATE_HITS
        db.commit()
        return (f"🧠 Learned: from now on, when you say “{phrase}” I understand “{repl}”. "
                "It applies to all operations (email, calendar, schedules …). "
                "Say “show my phrases” to review everything I've learned from you.")

    if FORGET_INTENT.search(text):
        m2 = FORGET_INTENT.search(text)
        phrase = ((m2.group("phrase") or m2.group("phrase2")) or "").strip(" \"'“”‘’")
        row = (db.query(UserPhrase)
               .filter(UserPhrase.user_id == user_id, UserPhrase.phrase == phrase).first())
        if not row:
            return f"❌ I have no learned phrase “{phrase}”."
        db.delete(row)
        db.commit()
        return f"🗑️ Forgotten: “{phrase}”."

    if SHOW_INTENT.search(text):
        rows = (db.query(UserPhrase).filter(UserPhrase.user_id == user_id)
                .order_by(UserPhrase.hits.desc()).all())
        if not rows:
            return ("🧠 I haven't learned any personal phrases from you yet.\n"
                    "Teach me directly — “teach: 睇下 = check” — or just keep using "
                    "your own wording: I learn it automatically from your habits.")
        act = [r for r in rows if r.active]
        pend = [r for r in rows if not r.active]
        out = [f"🧠 **Your personal vocabulary** ({len(act)} active"
               + (f", {len(pend)} still learning" if pend else "") + "):"]
        for r in act:
            src = "taught" if r.source == "taught" else f"learned from habit ×{r.hits}"
            out.append(f"• “{r.phrase}” → {r.replacement}  ({src})")
        for r in pend:
            out.append(f"◦ “{r.phrase}” → {r.replacement}?  (observing {r.hits}/{AUTO_ACTIVATE_HITS})")
        out.append("\n💡 “teach: <phrase> = <meaning>” · “forget phrase <phrase>”")
        return "\n".join(out)
    return None


def _unknown_tokens(original: str, normalized: str) -> list[str]:
    """Words of the user's prompt that survived normalization un-translated."""
    toks: list[str] = []
    for m in _CJK_WORD.finditer(original):
        w = m.group(0)
        if w in normalized:          # not consumed by any dictionary
            toks.append(w)
    return [t for t in toks if 1 <= len(t) <= 6][:6]


def learn_from_success(db: Session, user_id: str, original: str,
                       normalized: str) -> None:
    """Habit learning: after an operation prompt SUCCEEDED, associate the
    still-unknown words with the operation verb that fired.  The same
    association observed AUTO_ACTIVATE_HITS times becomes an active phrase."""
    try:
        low = f" {normalized.lower()} "
        verb = next((v for v in _OP_VERBS if f" {v} " in low), None)
        if not verb:
            return
        for tok in _unknown_tokens(original, normalized):
            row = (db.query(UserPhrase)
                   .filter(UserPhrase.user_id == user_id, UserPhrase.phrase == tok).first())
            if row is None:
                db.add(UserPhrase(user_id=user_id, phrase=tok, replacement=verb,
                                  source="auto", hits=1, active=False))
            elif row.source == "auto" and not row.active:
                if row.replacement == verb:
                    row.hits += 1
                    if row.hits >= AUTO_ACTIVATE_HITS:
                        row.active = True
                else:                 # verb changed — restart observation
                    row.replacement = verb
                    row.hits = 1
            if row is not None:
                row.last_used_at = dt.datetime.utcnow()
        db.commit()
    except Exception:  # noqa: BLE001 — learning must never break operations
        db.rollback()
