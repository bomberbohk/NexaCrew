"""Runtime configuration for the agent platform.

Stored in platform/data/config.json and editable from the web UI
(Settings page at http://127.0.0.1:8600/). Missing keys fall back to defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parent.parent / "data" / "config.json"

DEFAULTS: dict = {
    # --- deployment (server / client) ---
    "deploy_mode": "server",        # "server" = run the platform here; "client" = connect to a remote server
    "server_port": 8600,            # port this machine listens on (server mode)
    "server_bind": "0.0.0.0",       # bind address (0.0.0.0 = reachable by clients on the LAN)
    "client_server_ip": "",         # server IP address to connect to (client mode)
    "client_server_port": 8600,     # server port to connect to (client mode)
    # --- enterprise cluster (multi-server co-operation) ---
    "cluster_role": "standalone",   # standalone | controller | worker
    "node_name": "",                # friendly name shown on the network graph (default: hostname)
    "cluster_secret": "",           # shared secret all cluster nodes must present
    "controller_ip": "",            # worker mode: IP of the controller node
    "controller_port": 8600,        # worker mode: port of the controller node
    "discovery_port": 8601,         # UDP port for LAN auto-discovery protocol
    "codex_timeout": 600,           # seconds for a single Codex run
    "claude_timeout": 900,          # seconds for a single Claude Code run
    # --- custom AI APIs (used when Codex / Claude Code CLIs are not installed) ---
    # list of {name, type: openai-compatible|anthropic, base_url, key, model, enabled}
    "ai_apis": [],
    # legacy single-API fields (auto-migrated into ai_apis)
    "ai_api_type": "none",
    "ai_api_base_url": "",
    "ai_api_key": "",
    "ai_api_model": "",
    "images_dir": str(Path.home() / "Desktop" / "Generated Images"),
    "files_dir": str(Path.home() / "Desktop" / "Generated Files"),
    "big_doc_min_pages": 20,        # page count that triggers the 3-stage big-doc pipeline
    "history_context_messages": 7,  # chat messages included as context for short follow-ups
    # --- mobile messaging bridge (WhatsApp / WeChat) ---
    "webhook_token": "",            # shared secret for inbound webhooks (empty = webhooks disabled)
    "allowed_senders": "",          # comma-separated WhatsApp numbers / WeChat IDs allowed to command the agent
    "notify_email": "",             # email address that receives generated attachments
    "twilio_account_sid": "",       # optional: real WhatsApp delivery via Twilio
    "twilio_auth_token": "",
    "twilio_whatsapp_from": "",     # e.g. whatsapp:+14155238886
    # --- real email delivery (SMTP) ---
    "smtp_host": "",                # e.g. smtp.gmail.com (empty = simulated local-dev email)
    "smtp_port": 587,
    "smtp_username": "",            # e.g. your@gmail.com
    "smtp_password": "",            # Gmail: use an App Password (myaccount.google.com/apppasswords)
    "smtp_from": "",                # sender address; defaults to smtp_username
    # --- calendar synchronization (OAuth apps for Google / Microsoft sign-in) ---
    "google_client_id": "",         # Google Cloud OAuth client ID (Calendar scope)
    "google_client_secret": "",
    "ms_client_id": "",             # Azure app registration (client) ID — Graph Calendars.ReadWrite
    "ms_client_secret": "",
    # --- cameras (server-wide defaults; each client computer can override
    #     them in its tray settings / Setup page) ---
    "camera_internal": "",          # face capture for the operations log — device-name substring
    "camera_external": "",          # serial-number / document capture — device-name substring
    # --- license authority (mapstudiousa.com) — server-installation license ---
    "authority_url": "https://mapstudiousa.com/backend/nexacrew-license-api.php",
    "authority_license_key": "",    # key purchased on mapstudiousa.com (XXXXX-XXXXX-XXXXX-XXXXX)
    "authority_check_hours": 12,    # re-validation interval (72 h offline grace)
    # --- developer mode (highest permission — above administrator) ---
    "developer_username": "",       # username granted developer mode on this server
    # --- automatic updates from mapstudiousa.com ---
    "auto_update_from_portal": "on",   # "on" | "off" — server self-updates when the portal has a newer version
    "portal_package_url": "https://mapstudiousa.com/backend/nexacrew-package-api.php",
}

FIELD_META = {
    "deploy_mode": {"label": "Deployment mode (server = run here, client = connect to a remote server)",
                     "type": "select", "options": ["server", "client"], "group": "deploy"},
    "server_port": {"label": "Server port (server mode — takes effect on next start)", "type": "number", "min": 1, "max": 65535, "group": "deploy"},
    "server_bind": {"label": "Server bind address (0.0.0.0 = LAN access, 127.0.0.1 = this machine only)", "type": "text", "group": "deploy"},
    "client_server_ip": {"label": "Server IP address (client mode, e.g. 192.168.1.50)", "type": "text", "group": "deploy"},
    "client_server_port": {"label": "Server port (client mode)", "type": "number", "min": 1, "max": 65535, "group": "deploy"},
    "cluster_role": {"label": "Cluster role (standalone / controller = master / worker = slave)",
                      "type": "select", "options": ["standalone", "controller", "worker"], "group": "cluster"},
    "node_name": {"label": "Node name on the network graph (default: hostname)", "type": "text", "group": "cluster"},
    "cluster_secret": {"label": "Cluster shared secret (must match on every node)", "type": "text", "group": "cluster"},
    "controller_ip": {"label": "Controller IP address (worker mode)", "type": "text", "group": "cluster"},
    "controller_port": {"label": "Controller port (worker mode)", "type": "number", "min": 1, "max": 65535, "group": "cluster"},
    "discovery_port": {"label": "LAN auto-discovery UDP port", "type": "number", "min": 1, "max": 65535, "group": "cluster"},
    "codex_timeout": {"label": "Codex timeout (seconds)", "type": "number", "min": 60, "max": 7200, "group": "agents"},
    "camera_internal": {"label": "Internal camera — operator face capture for the operations log (device name contains, e.g. 'integrated')", "type": "text", "group": "cameras"},
    "camera_external": {"label": "External camera — serial number / document capture (device name contains, e.g. 'USB')", "type": "text", "group": "cameras"},
    "claude_timeout": {"label": "Claude Code timeout (seconds)", "type": "number", "min": 60, "max": 7200, "group": "agents"},
    "images_dir": {"label": "Generated images folder", "type": "text", "group": "agents"},
    "files_dir": {"label": "Generated files folder", "type": "text", "group": "agents"},
    "big_doc_min_pages": {"label": "Big-document pipeline threshold (pages)", "type": "number", "min": 5, "max": 1000, "group": "agents"},
    "history_context_messages": {"label": "Context messages for follow-ups", "type": "number", "min": 0, "max": 50, "group": "agents"},
    "webhook_token": {"label": "Mobile webhook secret token (WhatsApp/WeChat)", "type": "text", "group": "mobile"},
    "allowed_senders": {"label": "Allowed mobile senders (comma-separated numbers/IDs)", "type": "text", "group": "mobile"},
    "notify_email": {"label": "Email address for generated attachments", "type": "text", "group": "mobile"},
    "twilio_account_sid": {"label": "Twilio Account SID (real WhatsApp, optional)", "type": "text", "group": "mobile"},
    "twilio_auth_token": {"label": "Twilio Auth Token (optional)", "type": "password", "group": "mobile"},
    "twilio_whatsapp_from": {"label": "Twilio WhatsApp sender (e.g. whatsapp:+1415…)", "type": "text", "group": "mobile"},
    "smtp_host": {"label": "SMTP host (e.g. smtp.gmail.com — empty = simulated email)", "type": "text", "group": "email"},
    "smtp_port": {"label": "SMTP port (587 = TLS)", "type": "number", "min": 1, "max": 65535, "group": "email"},
    "smtp_username": {"label": "SMTP username (your email address)", "type": "text", "group": "email"},
    "smtp_password": {"label": "SMTP password (Gmail: App Password)", "type": "password", "group": "email"},
    "smtp_from": {"label": "From address (default: SMTP username)", "type": "text", "group": "email"},
    "google_client_id": {"label": "Google OAuth client ID (Calendar sign-in)", "type": "text", "group": "calendar"},
    "google_client_secret": {"label": "Google OAuth client secret", "type": "password", "group": "calendar"},
    "ms_client_id": {"label": "Microsoft application (client) ID (Outlook sign-in)", "type": "text", "group": "calendar"},
    "ms_client_secret": {"label": "Microsoft client secret", "type": "password", "group": "calendar"},
    "authority_url": {"label": "License authority URL (mapstudiousa.com validation endpoint)", "type": "text", "group": "license"},
    "authority_license_key": {"label": "Server license key purchased on mapstudiousa.com (empty = unlicensed evaluation)", "type": "text", "group": "license"},
    "authority_check_hours": {"label": "License re-validation interval (hours, 72 h offline grace)", "type": "number", "min": 1, "max": 72, "group": "license"},
    "developer_username": {"label": "Developer account username (highest permission — above administrator; empty = no developer on this server)", "type": "text", "group": "developer"},
    "auto_update_from_portal": {"label": "Auto-update this server from mapstudiousa.com when a newer version is published", "type": "select", "options": ["on", "off"], "group": "developer"},
    "portal_package_url": {"label": "Portal package API URL (mapstudiousa.com)", "type": "text", "group": "developer"},
}


def get_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        if CONFIG_FILE.is_file():
            # utf-8-sig tolerates a BOM (e.g. written by PowerShell)
            cfg.update({k: v for k, v in json.loads(
                CONFIG_FILE.read_text(encoding="utf-8-sig")).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    # migrate legacy single-API fields into the ai_apis list
    if not cfg.get("ai_apis") and cfg.get("ai_api_type", "none") != "none" and cfg.get("ai_api_base_url"):
        cfg["ai_apis"] = [{"name": "Default API", "type": cfg["ai_api_type"],
                           "base_url": cfg["ai_api_base_url"], "key": cfg.get("ai_api_key", ""),
                           "model": cfg.get("ai_api_model", ""), "enabled": True}]
    return cfg


def enabled_ai_apis() -> list:
    """All enabled custom AI APIs, in priority order."""
    return [a for a in get_config().get("ai_apis", [])
            if isinstance(a, dict) and a.get("enabled", True) and a.get("base_url")]


def save_config(updates: dict) -> dict:
    cfg = get_config()
    for k, v in updates.items():
        if k not in DEFAULTS:
            continue
        meta = FIELD_META.get(k, {})
        if meta.get("type") == "select" and v not in meta.get("options", []):
            continue
        if isinstance(DEFAULTS[k], list):
            if not isinstance(v, list):
                continue
            cfg[k] = v
            continue
        if isinstance(DEFAULTS[k], int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
            v = max(meta.get("min", v), min(meta.get("max", v), v))
        cfg[k] = v
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg
