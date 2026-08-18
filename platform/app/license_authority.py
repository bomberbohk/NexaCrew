# SPDX-License-Identifier: MIT
"""License-authority client — validates this NexaCrew server installation
against mapstudiousa.com (the licensing authority).

Design (data-center grade):
  - Activation binds the purchased key to THIS server's hardware fingerprint
    (hostname + MAC + CPU serial hash) on first contact.
  - Re-validation runs every ``authority_check_hours`` (default 12 h) in a
    daemon thread with timeout, capped exponential backoff + jitter.
  - The authority returns an HMAC-signed grant valid 72 h: short WAN outages
    NEVER interrupt operations (cached grant honoured), while an explicitly
    ``revoked``/``suspended`` answer takes effect on the next check.
  - Fail-safe posture: only a *definitive* rejection from the authority
    (HTTP 401/403/409) marks the installation unlicensed; network errors
    keep the last known state until the grace window lapses.

State is exposed via :func:`authority_status` for the admin Settings panel
and the ``/api/license-authority`` endpoint.
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import random
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

log = logging.getLogger("license_authority")

GRACE_S = 72 * 3600                 # offline grace window (matches authority)
_HTTP_TIMEOUT_S = 15
_RETRY_MAX = 3
_STATE_LOCK = threading.Lock()
_STOP = threading.Event()

# persisted grant cache (survives restarts so the grace window is honoured)
_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "authority_grant.json"

_state: dict = {
    "configured": False,     # a key is present in config
    "licensed": False,       # authority (or grace window) says we may run
    "status": "unconfigured",  # unconfigured|active|grace|revoked|suspended|expired|invalid|bound|error
    "company": "",
    "plan": "",
    "seats": 0,
    "tokens_included": 0,
    "expires_at": None,
    "last_check_at": None,
    "last_ok_at": None,
    "detail": "",
}


def _fingerprint() -> str:
    """Stable hardware fingerprint of THIS server (privacy-preserving hash)."""
    mac = uuid.getnode()
    basis = f"{socket.gethostname()}|{mac:012x}|{platform.system()}|{platform.machine()}"
    return hashlib.sha256(basis.encode()).hexdigest()


def _mac_str() -> str:
    n = uuid.getnode()
    return ":".join(f"{(n >> i) & 0xFF:02X}" for i in range(40, -1, -8))


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


def _usage_report() -> list[dict]:
    """Cumulative per-user token totals for the authority (bounded to 200
    users, largest consumers first). Never raises — usage reporting must
    not interfere with license validation."""
    try:
        from sqlalchemy import func
        from .db import SessionLocal, TokenUsage, User
        db = SessionLocal()
        try:
            rows = (db.query(User.username,
                             func.coalesce(func.sum(TokenUsage.input_tokens), 0),
                             func.coalesce(func.sum(TokenUsage.output_tokens), 0),
                             func.coalesce(func.sum(TokenUsage.calls), 0))
                    .join(TokenUsage, TokenUsage.user_id == User.id)
                    .group_by(User.username)
                    .order_by((func.sum(TokenUsage.input_tokens)
                               + func.sum(TokenUsage.output_tokens)).desc())
                    .limit(200).all())
            return [{"username": r[0], "input_tokens": int(r[1]),
                     "output_tokens": int(r[2]), "calls": int(r[3])}
                    for r in rows]
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001 — reporting is best-effort
        log.warning("token usage report unavailable: %s", e)
        return []


DEVICE_ACTIVE_WINDOW_S = 30 * 24 * 3600   # browser devices count as a seat
                                          # while seen within the last 30 days


def _devices_report() -> list[dict]:
    """Snapshot of every device consuming a seat on THIS server:
      - the server itself (type "server")
      - each claimed, unrevoked client license key (desktop/laptop programs;
        real device type taken from the client-reported hardware identity)
      - each recently-seen browser device (mobile / tablet / kiosk terminals
        self-registered via /api/client/device-register)
    Bounded to 500 entries. Never raises — reporting must not interfere
    with license validation."""
    out: list[dict] = [{
        "id": "server:" + _fingerprint()[:32],
        "hostname": socket.gethostname()[:160],
        "ip": _local_ip()[:60],
        "type": "server"}]
    try:
        import datetime as _dt
        from .db import ClientDevice, LicenseKey, SessionLocal
        db = SessionLocal()
        try:
            rows = (db.query(LicenseKey)
                    .filter(LicenseKey.used.is_(True), LicenseKey.revoked.is_(False))
                    .order_by(LicenseKey.last_seen_at.desc().nullslast())
                    .limit(400).all())
            for r in rows:
                try:
                    dtype = (json.loads(r.client_hw or "{}").get("device_type")
                             or "desktop")
                except ValueError:
                    dtype = "desktop"
                out.append({"id": r.key[:64],
                            "hostname": (r.used_by_host or "")[:160],
                            "ip": (r.used_by_ip or "")[:60],
                            "type": str(dtype)[:20]})
            cutoff = _dt.datetime.utcnow() - _dt.timedelta(seconds=DEVICE_ACTIVE_WINDOW_S)
            devs = (db.query(ClientDevice)
                    .filter(ClientDevice.last_seen_at >= cutoff)
                    .order_by(ClientDevice.last_seen_at.desc())
                    .limit(500 - len(out)).all())
            for d in devs:
                name = (d.model or d.os or d.usage or d.device_uid or "")[:160]
                out.append({"id": ("dev:" + (d.device_uid or ""))[:64],
                            "hostname": name,
                            "ip": (d.ip or "")[:60],
                            "type": (d.kind or "mobile")[:20]})
        finally:
            db.close()
    except Exception as e:  # noqa: BLE001
        log.warning("device report unavailable: %s", e)
    return out[:500]


def seats_in_use(db) -> dict:
    """Seat consumption on THIS server across ALL device classes:
    server (always 1) + claimed desktop client keys + browser devices
    (mobile / tablet / kiosk) active within the 30-day window.
    Returns {"used": n, "by_type": {...}}. Never raises."""
    by_type: dict[str, int] = {"server": 1}
    try:
        import datetime as _dt
        from .db import ClientDevice, LicenseKey
        rows = (db.query(LicenseKey)
                .filter(LicenseKey.used.is_(True), LicenseKey.revoked.is_(False))
                .all())
        for r in rows:
            try:
                dtype = (json.loads(r.client_hw or "{}").get("device_type")
                         or "desktop")
            except ValueError:
                dtype = "desktop"
            by_type[dtype] = by_type.get(dtype, 0) + 1
        cutoff = _dt.datetime.utcnow() - _dt.timedelta(seconds=DEVICE_ACTIVE_WINDOW_S)
        for d in (db.query(ClientDevice)
                  .filter(ClientDevice.last_seen_at >= cutoff).all()):
            k = d.kind or "mobile"
            by_type[k] = by_type.get(k, 0) + 1
    except Exception as e:  # noqa: BLE001
        log.warning("seat usage computation degraded: %s", e)
    return {"used": sum(by_type.values()), "by_type": by_type}


def seat_limit() -> int:
    """Authorized seats from the last successful validation (0 = no limit
    known / evaluation mode)."""
    with _STATE_LOCK:
        return int(_state.get("seats") or 0) if _state.get("configured") else 0


def token_quota(db) -> dict:
    """Token allowance vs cumulative usage on THIS server.
    Returns {"included": n, "used": n, "exceeded": bool}. included=0 means
    no quota known (evaluation mode) — never blocks. Never raises."""
    with _STATE_LOCK:
        included = (int(_state.get("tokens_included") or 0)
                    if _state.get("configured") else 0)
    used = 0
    if included > 0:
        try:
            from sqlalchemy import func
            from .db import TokenUsage
            used = int(db.query(
                func.coalesce(func.sum(TokenUsage.input_tokens), 0)
                + func.coalesce(func.sum(TokenUsage.output_tokens), 0)).scalar() or 0)
        except Exception as e:  # noqa: BLE001 — fail-open, never block on errors
            log.warning("token quota check degraded: %s", e)
            return {"included": included, "used": 0, "exceeded": False}
    return {"included": included, "used": used,
            "exceeded": included > 0 and used >= included}


def _load_cache() -> dict:
    try:
        if _CACHE_FILE.is_file():
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("grant cache unreadable (%s) — treating as absent", e)
    return {}


def _save_cache(data: dict) -> None:
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(_CACHE_FILE)
    except OSError as e:
        log.warning("grant cache write failed: %s", e)


def _post(url: str, payload: dict) -> tuple[int, dict]:
    """POST JSON with bounded retries (backoff + jitter). Returns (status, body).
    4xx are definitive — returned immediately without retry."""
    body = json.dumps(payload).encode()
    last_exc: Exception | None = None
    for attempt in range(_RETRY_MAX):
        try:
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json",
                         "User-Agent": "NexaCrew-LicenseClient/1.0"})
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                data = json.loads(e.read() or b"{}")
            except ValueError:
                data = {}
            if 400 <= e.code < 500 and e.code != 429:
                return e.code, data           # definitive answer — no retry
            last_exc = e
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last_exc = e
        time.sleep(min(30.0, (2 ** attempt) + random.uniform(0, 1)))
    raise ConnectionError(f"authority unreachable after {_RETRY_MAX} attempts: {last_exc}")


def _apply_definitive(status: str, detail: str) -> None:
    with _STATE_LOCK:
        _state.update({"licensed": False, "status": status, "detail": detail,
                       "last_check_at": time.time()})
    log.error("license authority rejected this installation: %s — %s. "
              "Remediation: verify the key in Settings → License, or contact "
              "mapstudiousa.com support.", status, detail)


def check_once(cfg: dict) -> dict:
    """One activation/validation round-trip. Never raises; updates _state."""
    key = (cfg.get("authority_license_key") or "").strip()
    url = (cfg.get("authority_url") or "").strip()
    if not key or not url:
        with _STATE_LOCK:
            _state.update({"configured": False, "licensed": True,
                           "status": "unconfigured",
                           "detail": "no authority key configured — evaluation mode"})
        return dict(_state)

    with _STATE_LOCK:
        _state["configured"] = True

    cache = _load_cache()
    action = "validate" if cache.get("activated") else "activate"
    payload = {"action": action, "key": key, "fingerprint": _fingerprint()}
    if action == "activate":
        payload.update({"hostname": socket.gethostname()[:160],
                        "mac": _mac_str(), "ip": _local_ip()})
    usage = _usage_report()
    if usage:
        payload["usage"] = usage
    devices = _devices_report()
    if devices:
        payload["devices"] = devices
    t0 = time.monotonic()
    try:
        code, data = _post(url, payload)
    except ConnectionError as e:
        # network failure — honour the cached grant within the grace window
        ok_at = float(cache.get("ok_at") or 0)
        in_grace = ok_at and (time.time() - ok_at) < GRACE_S
        with _STATE_LOCK:
            _state.update({
                "licensed": bool(in_grace) or not cache.get("activated"),
                "status": "grace" if in_grace else "error",
                "detail": f"authority unreachable ({e}); "
                          + ("operating in 72 h grace window" if in_grace
                             else "no valid cached grant"),
                "last_check_at": time.time()})
        log.warning("license validation skipped — %s", _state["detail"])
        return dict(_state)

    latency_ms = int((time.monotonic() - t0) * 1000)
    if code == 200 and data.get("ok"):
        _save_cache({"activated": True, "ok_at": time.time(),
                     "grant": data.get("grant", "")})
        with _STATE_LOCK:
            _state.update({
                "licensed": True, "status": "active",
                "company": str(data.get("company") or ""),
                "plan": str(data.get("plan") or ""),
                "seats": int(data.get("seats") or 0),
                "tokens_included": int(data.get("tokens_included") or 0),
                "expires_at": data.get("expires_at"),
                "last_check_at": time.time(), "last_ok_at": time.time(),
                "detail": f"validated in {latency_ms} ms"})
        log.info("license OK — company=%s plan=%s seats=%s (%d ms)",
                 _state["company"], _state["plan"], _state["seats"], latency_ms)
    else:
        _apply_definitive(str(data.get("status") or "invalid"),
                          str(data.get("error") or f"HTTP {code}"))
    return dict(_state)


def authority_status() -> dict:
    with _STATE_LOCK:
        return dict(_state)


_SYNC_DEBOUNCE_S = 30           # coalesce bursts of device registrations
_sync_timer: "threading.Timer | None" = None
_SYNC_TIMER_LOCK = threading.Lock()


def request_sync() -> None:
    """Schedule an out-of-band validation round-trip (debounced 30 s) so the
    connected-device snapshot reaches mapstudiousa.com promptly when a new
    device connects — instead of waiting for the next periodic check (≤12 h).
    No-op in evaluation mode. Never raises."""
    global _sync_timer
    with _STATE_LOCK:
        if not _state.get("configured"):
            return
    def _run() -> None:
        global _sync_timer
        with _SYNC_TIMER_LOCK:
            _sync_timer = None
        try:
            from .config import get_config
            check_once(get_config())
            log.info("out-of-band device sync completed")
        except Exception as e:  # noqa: BLE001 — best-effort background sync
            log.warning("out-of-band device sync failed: %s", e)
    with _SYNC_TIMER_LOCK:
        if _sync_timer is not None:
            return                          # a sync is already pending
        _sync_timer = threading.Timer(_SYNC_DEBOUNCE_S, _run)
        _sync_timer.daemon = True
        _sync_timer.start()


def verify_key(cfg: dict, key: str) -> dict:
    """Verify a purchased license key against mapstudiousa.com WITHOUT
    binding it (action=check). Returns {ok, error?, plan?, seats?, company?,
    expires_at?}. Raises nothing — network failures return ok=False with an
    actionable message."""
    url = (cfg.get("authority_url") or "").strip()
    if not url:
        return {"ok": False, "error": "licensing authority URL is not configured "
                                      "(Settings → License → Authority URL)"}
    try:
        code, data = _post(url, {"action": "check", "key": key.strip(),
                                 "fingerprint": _fingerprint()})
    except ConnectionError as e:
        return {"ok": False, "error": f"mapstudiousa.com unreachable — try again later ({e})"}
    if code == 200 and data.get("ok"):
        return {"ok": True, "plan": str(data.get("plan") or ""),
                "seats": int(data.get("seats") or 0),
                "company": str(data.get("company") or ""),
                "expires_at": data.get("expires_at")}
    return {"ok": False,
            "error": str(data.get("error") or f"authority rejected the key (HTTP {code})"),
            "status": str(data.get("status") or "invalid")}


def portal_auth(cfg: dict, email: str, password: str) -> dict:
    """Authenticate portal credentials (mapstudiousa.com NexaCrew customer
    account) through the licensing authority. Requires this server's own
    authority key so credentials can never be probed anonymously.
    Returns {ok, email?, display_name?, error?}."""
    url = (cfg.get("authority_url") or "").strip()
    key = (cfg.get("authority_license_key") or "").strip()
    if not url or not key:
        return {"ok": False, "error": "portal login unavailable — no authority "
                                      "license configured on this server"}
    try:
        code, data = _post(url, {"action": "auth", "key": key,
                                 "fingerprint": _fingerprint(),
                                 "email": email.strip()[:190],
                                 "password": password[:200]})
    except ConnectionError as e:
        return {"ok": False, "error": f"mapstudiousa.com unreachable ({e})"}
    if code == 200 and data.get("ok"):
        return {"ok": True, "email": str(data.get("email") or ""),
                "display_name": str(data.get("display_name") or "")}
    return {"ok": False, "error": str(data.get("error") or f"HTTP {code}")}


def start_background_validation(get_config) -> None:
    """Launch the periodic re-validation daemon (call once at startup)."""
    def _loop() -> None:
        while not _STOP.is_set():
            try:
                cfg = get_config()
                check_once(cfg)
                hours = max(1, min(72, int(cfg.get("authority_check_hours") or 12)))
            except Exception:                     # noqa: BLE001 — never kill the loop
                log.exception("license validation loop error — retrying in 1 h")
                hours = 1
            _STOP.wait(hours * 3600)
    threading.Thread(target=_loop, name="license-authority", daemon=True).start()
    log.info("license-authority background validation started")


def stop_background_validation() -> None:
    _STOP.set()
