"""Prompt queue engine — non-blocking chat prompts.

Each chat has its own FIFO queue. The user can keep typing prompts while the
first one runs; pending prompts can be revised or cancelled. Prompts of ONE
chat always run sequentially (conversation order), while DIFFERENT chats run
concurrently — but through a small, bounded worker pool so that even
100 chats × 100 queued prompts will not slow the computer down:

- max 3 agent pipelines run at any moment (CPU/GPU bound work is capped)
- queued items are tiny dicts (~a few hundred bytes each) — 10 000 queued
  prompts use only a few MB of RAM
- no thread per prompt: workers are reused from one small pool
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import uuid

MAX_WORKERS = 3          # concurrent agent pipelines (keeps CPU/GPU/RAM low)
MAX_QUEUE_PER_CHAT = 100  # safety cap per chat

# set by main.py — queues generated files for delivery to the client machine
# that submitted the prompt (signature: hook(db, client_ip, reply_text))
file_delivery_hook = None

_lock = threading.Lock()
_queues: "dict[str, list[dict]]" = {}      # chat_id -> pending/running items
_active_chats: "set[str]" = set()          # chats with a running item
_wakeup = threading.Event()
_started = False


def _new_item(chat_id: str, user_id: str, content: str, image_ref: "str | None",
              client_ip: str = "") -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "chat_id": chat_id,
        "user_id": user_id,
        "content": content,
        "image_ref": image_ref,
        "client_ip": client_ip,
        "status": "queued",           # queued | running | done | error
        "error": "",
        "queued_at": dt.datetime.utcnow().isoformat(),
        "started_at": None,
        "finished_at": None,
    }


def enqueue(chat_id: str, user_id: str, content: str,
            image_ref: "str | None" = None, client_ip: str = "") -> dict:
    with _lock:
        q = _queues.setdefault(chat_id, [])
        if len([i for i in q if i["status"] in ("queued", "running")]) >= MAX_QUEUE_PER_CHAT:
            raise ValueError(f"Queue limit reached ({MAX_QUEUE_PER_CHAT} prompts per chat)")
        item = _new_item(chat_id, user_id, content, image_ref, client_ip)
        q.append(item)
    _wakeup.set()
    return dict(item)


def list_queue(chat_id: str) -> "list[dict]":
    with _lock:
        q = _queues.get(chat_id, [])
        # drop finished items older than 5 minutes to keep memory flat
        cutoff = time.time() - 300
        q[:] = [i for i in q
                if i["status"] in ("queued", "running")
                or (i["finished_at"] and
                    dt.datetime.fromisoformat(i["finished_at"]).timestamp() > cutoff)]
        return [dict(i) for i in q]


def revise(chat_id: str, item_id: str, user_id: str, content: str) -> "dict | None":
    """Edit a prompt that has not started yet."""
    with _lock:
        for i in _queues.get(chat_id, []):
            if i["id"] == item_id and i["user_id"] == user_id:
                if i["status"] != "queued":
                    return None
                i["content"] = content
                return dict(i)
    return None


def cancel(chat_id: str, item_id: str, user_id: str) -> bool:
    """Remove a prompt that has not started yet."""
    with _lock:
        q = _queues.get(chat_id, [])
        for i in q:
            if i["id"] == item_id and i["user_id"] == user_id and i["status"] == "queued":
                q.remove(i)
                return True
    return False


def _pick_next() -> "dict | None":
    """Next queued item from a chat that is not already running (per-chat
    sequential, cross-chat concurrent)."""
    with _lock:
        if len(_active_chats) >= MAX_WORKERS:
            return None
        for chat_id, q in _queues.items():
            if chat_id in _active_chats:
                continue
            for i in q:
                if i["status"] == "queued":
                    i["status"] = "running"
                    i["started_at"] = dt.datetime.utcnow().isoformat()
                    _active_chats.add(chat_id)
                    return i
    return None


def _run_item(item: dict) -> None:
    from .db import Chat, SessionLocal
    from .services import run_agent_message
    db = SessionLocal()
    try:
        chat = db.get(Chat, item["chat_id"])
        if not chat or chat.deleted_at:
            raise ValueError("Chat was deleted")
        res = run_agent_message(db, chat, item["content"], item["user_id"],
                                image_ref=item.get("image_ref"))
        item["status"] = "done"
        if file_delivery_hook and item.get("client_ip"):
            try:
                file_delivery_hook(db, item["client_ip"],
                                   (res or {}).get("message", ""))
            except Exception:  # noqa: BLE001 — delivery must never break the run
                pass
    except Exception as e:  # noqa: BLE001 — a failed prompt must not kill the worker
        item["status"] = "error"
        item["error"] = str(e)[:500]
        try:
            from .db import Message
            db.add(Message(chat_id=item["chat_id"], role="employee",
                           content=f"❌ This queued prompt failed: {item['error']}"))
            db.commit()
        except Exception:  # noqa: BLE001
            pass
    finally:
        db.close()
        item["finished_at"] = dt.datetime.utcnow().isoformat()
        with _lock:
            _active_chats.discard(item["chat_id"])
        _wakeup.set()


def _worker() -> None:
    while True:
        item = _pick_next()
        if item is None:
            _wakeup.wait(timeout=2)
            _wakeup.clear()
            continue
        _run_item(item)


def start_workers() -> None:
    global _started
    if _started:
        return
    _started = True
    for n in range(MAX_WORKERS):
        threading.Thread(target=_worker, daemon=True,
                         name=f"prompt-queue-{n}").start()
