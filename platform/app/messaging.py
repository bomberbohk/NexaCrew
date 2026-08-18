"""Mobile messaging bridge: WhatsApp / WeChat → agent → reply with attachments.

Inbound: POST /api/webhook/{channel} with the shared secret token. The prompt
runs through the normal agent pipeline; the answer (and any generated files)
are sent back on the same channel AND emailed to the configured address.

Outbound providers:
  * TwilioWhatsAppProvider — real WhatsApp delivery when Twilio credentials
    are configured in Settings.
  * LocalDevMessagingProvider — simulation fallback: every outbound message is
    written to platform/data/messaging_outbox/ (clearly labeled, nothing is
    actually delivered). WeChat uses this adapter until a real WeChat Work
    provider is configured.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import mimetypes
import urllib.parse
import urllib.request
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from .config import get_config

OUTBOX = Path(__file__).resolve().parent.parent / "data" / "messaging_outbox"


class MessagingProvider(ABC):
    name = "abstract"
    simulated = True

    @abstractmethod
    def send(self, to: str, text: str, attachments: list[str] | None = None) -> dict: ...


class LocalDevMessagingProvider(MessagingProvider):
    """SIMULATED delivery — writes messages to disk for local development."""

    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.name = f"local-dev-{channel}"
        OUTBOX.mkdir(parents=True, exist_ok=True)

    def send(self, to: str, text: str, attachments: list[str] | None = None) -> dict:
        msg_id = f"{self.channel}-{uuid.uuid4().hex[:12]}"
        record = {
            "provider": self.name, "channel": self.channel, "message_id": msg_id,
            "timestamp": dt.datetime.utcnow().isoformat(),
            "to": to, "text": text, "attachments": attachments or [],
            "note": "SIMULATED SEND — local-dev messaging adapter, nothing was delivered. "
                    "Configure Twilio (WhatsApp) in Settings for real delivery.",
        }
        (OUTBOX / f"{msg_id}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "message_id": msg_id, "simulated": True}


class TwilioWhatsAppProvider(MessagingProvider):
    """Real WhatsApp delivery through the Twilio API (no extra dependencies)."""

    name = "twilio-whatsapp"
    simulated = False

    def __init__(self, sid: str, token: str, from_number: str) -> None:
        self.sid, self.token, self.from_number = sid, token, from_number

    def send(self, to: str, text: str, attachments: list[str] | None = None) -> dict:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json"
        if not to.startswith("whatsapp:"):
            to = "whatsapp:" + to
        data = {"From": self.from_number, "To": to, "Body": text[:1500]}
        # Twilio media must be a public URL; local files can't be attached directly,
        # so file paths are listed in the body and the email carries the attachments.
        if attachments:
            data["Body"] += "\n\n📎 Generated files (also emailed to you):\n" + "\n".join(attachments)
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode())
        auth = base64.b64encode(f"{self.sid}:{self.token}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                return {"ok": True, "message_id": body.get("sid", ""), "simulated": False}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:300], "simulated": False}


def get_messaging_provider(channel: str) -> MessagingProvider:
    cfg = get_config()
    if channel == "whatsapp" and cfg["twilio_account_sid"] and cfg["twilio_auth_token"] \
            and cfg["twilio_whatsapp_from"]:
        return TwilioWhatsAppProvider(cfg["twilio_account_sid"], cfg["twilio_auth_token"],
                                      cfg["twilio_whatsapp_from"])
    return LocalDevMessagingProvider(channel)


def sender_allowed(sender: str) -> bool:
    allowed = [s.strip() for s in get_config()["allowed_senders"].split(",") if s.strip()]
    if not allowed:
        return False  # explicit allow-list required — secure by default
    norm = sender.replace("whatsapp:", "").strip()
    return any(norm == a.replace("whatsapp:", "") for a in allowed)


def email_attachments(to_addr: str, subject: str, body: str, attachments: list[str]) -> dict:
    """Email generated files. Uses real SMTP (with actual file attachments) when
    configured in Settings; otherwise the clearly-labeled local-dev simulator."""
    from .providers import SmtpEmailProvider, get_email_provider
    provider = get_email_provider("auto")
    if isinstance(provider, SmtpEmailProvider):
        result = provider.send(sender=provider.from_addr, to=[to_addr], cc=[], bcc=[],
                               subject=subject, body=body,
                               idempotency_key=uuid.uuid4().hex, attachments=attachments)
    else:
        listing = "\n".join(attachments)
        full_body = f"{body}\n\n📎 Attachments generated on your computer:\n{listing}"
        result = provider.send(sender="agent@platform.local", to=[to_addr], cc=[], bcc=[],
                               subject=subject, body=full_body,
                               idempotency_key=uuid.uuid4().hex)
    return {"ok": result.ok, "message_id": result.provider_message_id,
            "simulated": result.simulated, "error": result.error}


def extract_file_paths(text: str) -> list[str]:
    """Pull existing generated-file paths out of an agent answer."""
    import re
    paths = []
    for m in re.findall(r"[A-Za-z]:\\[^\"'`|<>*?\r\n]+?\.[A-Za-z0-9]{1,6}(?![A-Za-z0-9.])", text):
        p = Path(m.strip())
        if p.is_file() and str(p) not in paths:
            paths.append(str(p))
    return paths
