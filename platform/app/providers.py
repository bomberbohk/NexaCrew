"""Provider adapters: Codex agent provider and email providers.

Provider-specific logic is abstracted behind interfaces so real providers
can be swapped in without changing the core application (spec §8, §14).
The LocalDevEmailProvider is clearly labeled and never misrepresents a
simulated send as a real-world delivery.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


# ==================== Agent provider ====================
# Per-request token usage tracking (reset by services at the start of each
# message). CLIs don't report exact counts, so tokens are estimated at ~4
# characters/token — clearly labeled as estimates in the UI.
USAGE: dict[str, dict[str, int]] = {}


def reset_usage() -> None:
    USAGE.clear()


def _track_usage(agent: str, prompt_chars: int, output_chars: int) -> None:
    u = USAGE.setdefault(agent, {"input_tokens": 0, "output_tokens": 0, "calls": 0})
    u["input_tokens"] += max(1, prompt_chars // 4)
    u["output_tokens"] += max(1, output_chars // 4)
    u["calls"] += 1


def get_usage() -> dict:
    return {k: dict(v) for k, v in USAGE.items()}


class AgentProvider(ABC):
    @abstractmethod
    def run(self, prompt: str, system: str = "", **kwargs) -> str: ...


class CodexProvider(AgentProvider):
    """Runs the locally installed OpenAI Codex CLI."""

    def __init__(self) -> None:
        self.cli = self._find()

    @staticmethod
    def _find() -> Optional[str]:
        for name in ("codex.cmd", "codex.exe", "codex"):
            p = shutil.which(name)
            if p:
                return p
        return None

    @property
    def available(self) -> bool:
        return bool(self.cli)

    def run(self, prompt: str, system: str = "", cwd: Optional[str] = None,
            allow_write: bool = False) -> str:
        # Enterprise cluster: controllers load-balance runs to workers
        from .cluster import remote_run, job_started, job_finished
        remote = remote_run("codex", prompt, system, allow_write)
        if remote is not None:
            _track_usage("codex", len(system) + len(prompt), len(remote))
            return remote
        if not self.cli:
            result = _legacy_fallback(prompt, system)
            if result is not None:
                return result
            raise RuntimeError("Codex CLI not found on PATH — install it, configure "
                               "an AI API in Settings → AI APIs, or use the Copilot relay "
                               "(VS Code + GitHub Copilot)")
        from .gpu import gpu_env, gpu_prompt_directive
        full = (system + "\n\n" if system else "") + prompt + gpu_prompt_directive()
        # No sandbox: full read/write access to the whole machine so prompts can
        # target any folder (e.g. C:\Users\...\Desktop). The platform's own
        # approval/audit layer remains the safety net.
        cmd = [self.cli, "exec", "--skip-git-repo-check",
               "--sandbox", "danger-full-access"]
        # Pass the prompt via stdin ("-") — Windows argv mangles non-ASCII
        # characters (e.g. em-dashes), which corrupts the prompt.
        cmd.append("-")
        from .config import get_config
        job_started()
        try:
            proc = subprocess.run(
                cmd,
                input=full,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=get_config()["codex_timeout"], cwd=cwd or str(Path.home()), env=gpu_env(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        finally:
            job_finished()
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 and not out:
            # The banner is at the head of stderr; the actual error is at the tail.
            raise RuntimeError(f"Codex failed (exit {proc.returncode}): {(proc.stderr or '').strip()[-800:]}")
        result = out or (proc.stderr or "").strip()
        _track_usage("codex", len(full), len(result))
        return result


class EchoProvider(AgentProvider):
    """Deterministic offline provider used in tests."""

    def run(self, prompt: str, system: str = "", **kwargs) -> str:
        return f"[echo-provider] {prompt[:500]}"


class ApiAgentProvider(AgentProvider):
    """Bring-your-own AI APIs: OpenAI-compatible (OpenAI, Azure, Ollama, LM
    Studio, DeepSeek, Groq…) or Anthropic. Multiple APIs may be configured;
    they are tried in order with automatic failover. Used automatically when
    the Codex / Claude Code CLIs are not installed."""

    @staticmethod
    def configured() -> bool:
        from .config import enabled_ai_apis
        return bool(enabled_ai_apis())

    def run(self, prompt: str, system: str = "", **kwargs) -> str:
        from .config import get_config, enabled_ai_apis
        apis = enabled_ai_apis()
        if not apis:
            raise RuntimeError("No AI API configured — add one in Settings → AI APIs")
        timeout = int(get_config().get("codex_timeout", 600))
        errors = []
        for api in apis:
            try:
                result = self._call(api, prompt, system, timeout)
                _track_usage(f"api:{api.get('name') or api.get('model') or 'custom'}",
                             len(system) + len(prompt), len(result))
                return result
            except Exception as e:  # failover to the next API
                errors.append(f"{api.get('name') or api.get('base_url')}: {e}")
        raise RuntimeError("All configured AI APIs failed — " + " | ".join(errors)[:800])

    @staticmethod
    def _call(api: dict, prompt: str, system: str, timeout: int) -> str:
        import urllib.request
        base = (api.get("base_url") or "").rstrip("/")
        if not base:
            raise RuntimeError("no base URL")
        model = api.get("model") or "gpt-4o"
        key = api.get("key", "")
        if api.get("type") == "anthropic":
            url = base + "/messages"
            payload = {"model": model, "max_tokens": 8192,
                       "messages": [{"role": "user", "content": prompt}]}
            if system:
                payload["system"] = system
            headers = {"Content-Type": "application/json",
                       "x-api-key": key, "anthropic-version": "2023-06-01"}
        else:  # openai-compatible chat completions
            url = base + "/chat/completions"
            msgs = ([{"role": "system", "content": system}] if system else []) + \
                   [{"role": "user", "content": prompt}]
            payload = {"model": model, "messages": msgs}
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        if api.get("type") == "anthropic":
            return "".join(b.get("text", "") for b in data.get("content", []))
        return data["choices"][0]["message"]["content"]


class CopilotRelayProvider(AgentProvider):
    """Legacy-macOS relay — sends prompts to GitHub Copilot inside VS Code.

    On macOS 10.13 High Sierra / 10.14 Mojave the Codex and Claude Code CLIs
    cannot run (they need Node 18+/newer OS), but VS Code 1.85.2 with GitHub
    Copilot still works. This provider:
      1. writes the prompt to  platform/data/handoff/copilot_relay/<id>_prompt.md
         with instructions telling Copilot to save its complete answer to
         <id>_response.md,
      2. opens the prompt file in VS Code (Copilot chat: ⌘I / ⌘⇧I),
      3. polls for the response file and returns its content.
    The same mechanism is used by the test-suite OS simulator
    (NEXACREW_SIMULATE_OS=high_sierra) to prove the path works end-to-end."""

    RELAY_DIR = Path(__file__).resolve().parent.parent / "data" / "handoff" / "copilot_relay"

    def __init__(self) -> None:
        self._vscode = shutil.which("code.cmd") or shutil.which("code")

    @property
    def available(self) -> bool:
        return bool(self._vscode)

    def run(self, prompt: str, system: str = "", **kwargs) -> str:
        import time as _t
        self.RELAY_DIR.mkdir(parents=True, exist_ok=True)
        rid = uuid.uuid4().hex[:10]
        prompt_file = self.RELAY_DIR / f"{rid}_prompt.md"
        response_file = self.RELAY_DIR / f"{rid}_response.md"
        prompt_file.write_text(
            "# NexaCrew → GitHub Copilot relay\n\n"
            "**Instructions for Copilot (or the user driving Copilot Chat):**\n"
            "answer the request below completely, then SAVE the full answer as:\n\n"
            f"    {response_file}\n\n"
            "---\n\n"
            + (("## System context\n" + system + "\n\n") if system else "")
            + "## Request\n" + prompt + "\n",
            encoding="utf-8")
        if self._vscode:
            try:
                subprocess.Popen(
                    [self._vscode, "--goto", str(prompt_file)],
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            except OSError:
                pass
        # poll for Copilot's response file (written by Copilot/the simulator)
        from .config import get_config
        timeout = int(get_config().get("codex_timeout", 600))
        deadline = _t.time() + timeout
        last_size = -1
        while _t.time() < deadline:
            if response_file.is_file():
                size = response_file.stat().st_size
                if size > 0 and size == last_size:   # stable → finished writing
                    result = response_file.read_text(encoding="utf-8", errors="replace").strip()
                    _track_usage("copilot_relay", len(system) + len(prompt), len(result))
                    try:
                        prompt_file.unlink()
                        response_file.unlink()
                    except OSError:
                        pass
                    return result
                last_size = size
            _t.sleep(1.0)
        raise RuntimeError(
            "Copilot relay timed out — open the prompt file in VS Code, ask Copilot, "
            f"and save the answer to {response_file.name}. "
            "Alternatively configure an AI API in Settings → AI APIs.")


def _legacy_fallback(prompt: str, system: str) -> "str | None":
    """OS-tier-aware fallback used when a CLI is missing: High Sierra/Mojave
    relay to Copilot in VS Code; anything with configured AI APIs uses them."""
    from .oscompat import detect
    tier = detect()
    if tier["ai_strategy"] == "copilot_relay":
        relay = CopilotRelayProvider()
        if relay.available:
            return relay.run(prompt, system=system)
    if ApiAgentProvider.configured():
        return ApiAgentProvider().run(prompt, system=system)
    return None


class ClaudeCodeProvider(AgentProvider):
    """Runs the locally installed Claude Code CLI (implementation agent).

    Runs with acceptEdits so Claude can actually create/edit files, with the
    working directory set to the user's home so paths like Desktop\\... work.
    """

    def __init__(self) -> None:
        self.cli = self._find()

    @staticmethod
    def _find() -> Optional[str]:
        for name in ("claude.cmd", "claude.exe", "claude"):
            p = shutil.which(name)
            if p:
                return p
        return None

    @property
    def available(self) -> bool:
        return bool(self.cli)

    def run(self, prompt: str, system: str = "", **kwargs) -> str:
        from .cluster import remote_run, job_started, job_finished
        remote = remote_run("claude", prompt, system)
        if remote is not None:
            _track_usage("claude_code", len(system) + len(prompt), len(remote))
            return remote
        if not self.cli:
            result = _legacy_fallback(prompt, system)
            if result is not None:
                return result
            raise RuntimeError("Claude Code CLI not found on PATH — install it, configure "
                               "an AI API in Settings → AI APIs, or use the Copilot relay "
                               "(VS Code + GitHub Copilot)")
        from .gpu import gpu_env, gpu_prompt_directive
        full = (system + "\n\n" if system else "") + prompt + gpu_prompt_directive()
        from .config import get_config
        job_started()
        try:
            proc = subprocess.run(
                # No sandbox / permission prompts: full tool access so prompts
                # can read & write anywhere on this machine.
                [self.cli, "-p", "--permission-mode", "bypassPermissions",
                 "--dangerously-skip-permissions"],
                input=full,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=get_config()["claude_timeout"], cwd=str(Path.home()), env=gpu_env(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        finally:
            job_finished()
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 and not out:
            raise RuntimeError(f"Claude Code failed (exit {proc.returncode}): {(proc.stderr or '')[:800]}")
        result = out or (proc.stderr or "").strip()
        _track_usage("claude_code", len(full), len(result))
        return result


class VSCodeLauncher:
    """Opens files/folders in VS Code for Copilot (Claude Fable 5) follow-up.

    Old systems where VS Code cannot be installed (e.g. macOS 10.8 Mountain
    Lion — VS Code needs 10.15+) automatically fall back to an alternative
    editor so the coding handoff still works: Sublime/TextMate/Atom if
    present, else the OS default text editor (TextEdit / Notepad / xdg-open).
    The agents themselves run via CLI/API, so nothing else is lost."""

    def __init__(self) -> None:
        self.cli = shutil.which("code.cmd") or shutil.which("code")
        self.fallback: "list[str] | None" = None
        self.fallback_name = ""
        if not self.cli:
            for exe, name in (("code-insiders", "VS Code Insiders"),
                              ("codium", "VSCodium"), ("subl", "Sublime Text"),
                              ("mate", "TextMate"), ("atom", "Atom")):
                p = shutil.which(exe)
                if p:
                    self.fallback, self.fallback_name = [p], name
                    break
            if not self.fallback:
                if sys.platform == "darwin":       # works on macOS 10.8+
                    self.fallback, self.fallback_name = ["open", "-t"], "the default text editor"
                elif os.name == "nt":
                    self.fallback, self.fallback_name = ["notepad"], "Notepad"
                elif shutil.which("xdg-open"):
                    self.fallback, self.fallback_name = ["xdg-open"], "the default editor"

    @property
    def available(self) -> bool:
        """True when a real VS Code CLI is present."""
        return bool(self.cli)

    def open(self, *paths: str) -> bool:
        cmd = [self.cli] if self.cli else self.fallback
        if not cmd:
            return False
        try:
            subprocess.Popen(
                [*cmd, *paths],
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return True
        except OSError:
            return False


# ==================== Email providers ====================
class SendResult:
    def __init__(self, ok: bool, provider_message_id: str = "", error: str = "",
                 simulated: bool = False) -> None:
        self.ok = ok
        self.provider_message_id = provider_message_id
        self.error = error
        self.simulated = simulated


class EmailProvider(ABC):
    name = "abstract"

    @abstractmethod
    def send(self, sender: str, to: list[str], cc: list[str], bcc: list[str],
             subject: str, body: str, idempotency_key: str) -> SendResult: ...


class LocalDevEmailProvider(EmailProvider):
    """LOCAL DEVELOPMENT ADAPTER — writes email to an outbox folder on disk.

    No real email is ever delivered. Results are flagged simulated=True and
    the UI labels them accordingly.
    """

    name = "local-dev"

    def __init__(self, outbox: Optional[Path] = None) -> None:
        self.outbox = outbox or Path(__file__).resolve().parent.parent / "data" / "outbox"
        self.outbox.mkdir(parents=True, exist_ok=True)
        self._sent_keys_file = self.outbox / ".sent_keys.json"

    def _sent_keys(self) -> dict:
        if self._sent_keys_file.exists():
            return json.loads(self._sent_keys_file.read_text(encoding="utf-8"))
        return {}

    def send(self, sender, to, cc, bcc, subject, body, idempotency_key) -> SendResult:
        keys = self._sent_keys()
        if idempotency_key in keys:  # idempotent retry — do not duplicate
            return SendResult(True, keys[idempotency_key], simulated=True)
        msg_id = f"local-dev-{uuid.uuid4().hex}"
        record = {
            "provider": self.name, "message_id": msg_id,
            "timestamp": dt.datetime.utcnow().isoformat(),
            "from": sender, "to": to, "cc": cc, "bcc": bcc,
            "subject": subject, "body": body,
            "note": "SIMULATED SEND — local development adapter, no real email delivered",
        }
        (self.outbox / f"{msg_id}.json").write_text(
            json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        keys[idempotency_key] = msg_id
        self._sent_keys_file.write_text(json.dumps(keys), encoding="utf-8")
        return SendResult(True, msg_id, simulated=True)


class SmtpEmailProvider(EmailProvider):
    """Real email delivery over SMTP (STARTTLS). Attaches local files when given.
    Gmail: host smtp.gmail.com, port 587, and an App Password
    (https://myaccount.google.com/apppasswords — normal passwords won't work)."""

    name = "smtp"

    def __init__(self, host: str, port: int, username: str, password: str, from_addr: str) -> None:
        self.host, self.port = host, port
        self.username, self.password = username, password
        self.from_addr = from_addr or username
        self._sent: dict[str, str] = {}

    def send(self, sender, to, cc, bcc, subject, body, idempotency_key,
             attachments: Optional[list[str]] = None) -> SendResult:
        if idempotency_key in self._sent:
            return SendResult(True, self._sent[idempotency_key])
        import smtplib
        from email.message import EmailMessage as _EM
        msg = _EM()
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(to)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        msg.set_content(body)
        total = 0
        for path_str in (attachments or []):
            p = Path(path_str)
            if not p.is_file():
                continue
            data = p.read_bytes()
            total += len(data)
            if total > 20 * 1024 * 1024:  # keep under common 25 MB limits
                msg.set_content(body + f"\n\n⚠ Some attachments were too large to email: {p.name}")
                break
            import mimetypes
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=p.name)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=60) as s:
                s.starttls()
                s.login(self.username, self.password)
                s.send_message(msg, to_addrs=[*to, *cc, *bcc])
            msg_id = f"smtp-{uuid.uuid4().hex[:12]}"
            self._sent[idempotency_key] = msg_id
            return SendResult(True, msg_id, simulated=False)
        except Exception as e:  # noqa: BLE001
            return SendResult(False, error=str(e)[:500])


def get_email_provider(provider_name: str) -> EmailProvider:
    """Real SMTP when configured in Settings; otherwise the local-dev simulator."""
    from .config import get_config
    cfg = get_config()
    if cfg["smtp_host"] and cfg["smtp_username"] and cfg["smtp_password"]:
        return SmtpEmailProvider(cfg["smtp_host"], int(cfg["smtp_port"]),
                                 cfg["smtp_username"], cfg["smtp_password"], cfg["smtp_from"])
    return LocalDevEmailProvider()
