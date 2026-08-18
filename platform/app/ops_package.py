# SPDX-License-Identifier: MIT
"""Operations Package engine — externalized, per-company operations.

The industry OPERATIONS registers (the A-N groups such as the ACME
SUPPLIES recycling / refurbishing workflow) are no longer welded to the
program: they are distributable JSON packages that any company installs,
exports, edits or builds from scratch through the API and the Operations
Studio UI.  The built-in industry templates remain available as STARTER
packages, so existing deployments keep working unchanged until a custom
package is installed.

Storage: one JSON document per platform user (= per company tenant) at
data/op_packages/<user_id>.json — atomic replace on write, validated on
every load, and covered by the existing data/ backup path.

Failure modes considered: malformed/hostile JSON uploads (full schema
validation, size caps), concurrent writes (atomic os.replace), package
removal with historical records (records are retained; modules simply
reappear when the package returns).  Scale: packages are tiny (<256 KB)
and cached per-user with a short TTL, so the hot path (every workspace
render) does no disk I/O in steady state.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

log = logging.getLogger("ops_package")

PKG_DIR = Path(__file__).resolve().parent.parent / "data" / "op_packages"

MAX_PACKAGE_BYTES = 256 * 1024
MAX_MODULES = 60
MAX_FIELDS = 60
SCHEMA_VERSION = 1

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_FIELD_ID_RE = re.compile(r"^[a-z_][a-z0-9_]{0,39}$")
_BASE_FIELD_TYPES = {"text", "number", "date", "textarea", "password", "section"}

# 5-second cache: workspace + record endpoints hit this on every render
_CACHE_TTL = 5.0
_cache: dict[str, tuple[float, "dict | None"]] = {}
_cache_lock = threading.Lock()


# ------------------------------------------------------------------ schema
def _field_errors(f, mi: int, fi: int) -> list[str]:
    where = f"module[{mi}].fields[{fi}]"
    if not isinstance(f, (list, tuple)) or len(f) != 3:
        return [f"{where}: each field must be [id, label, type]"]
    fid, label, ftype = f
    errs = []
    if not isinstance(fid, str) or not _FIELD_ID_RE.fullmatch(fid):
        errs.append(f"{where}: field id '{fid}' must be lowercase snake_case (max 40 chars)")
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
        errs.append(f"{where}: label must be 1-80 characters")
    if not isinstance(ftype, str):
        errs.append(f"{where}: type must be a string")
    elif ftype.startswith("select:"):
        opts = [o.strip() for o in ftype[7:].split(",") if o.strip()]
        if not 1 <= len(opts) <= 40 or any(len(o) > 60 for o in opts):
            errs.append(f"{where}: select needs 1-40 options of max 60 chars")
    elif ftype not in _BASE_FIELD_TYPES:
        errs.append(f"{where}: unknown field type '{ftype}' "
                    f"(allowed: {', '.join(sorted(_BASE_FIELD_TYPES))}, select:a,b)")
    return errs


def validate_package(pkg) -> list[str]:
    """Full structural validation. Returns [] when the package is valid."""
    errs: list[str] = []
    if not isinstance(pkg, dict):
        return ["package must be a JSON object"]
    if pkg.get("schema") != SCHEMA_VERSION:
        errs.append(f"schema must be {SCHEMA_VERSION}")
    name = pkg.get("name")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:
        errs.append("name: required, 1-120 characters")
    ver = pkg.get("version", "1.0.0")
    if not isinstance(ver, str) or not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        errs.append("version: must be MAJOR.MINOR.PATCH")
    cp = pkg.get("chat_prompt", "")
    if not isinstance(cp, str) or len(cp) > 20000:
        errs.append("chat_prompt: must be a string of max 20000 characters")
    mods = pkg.get("modules")
    if not isinstance(mods, list) or not 1 <= len(mods) <= MAX_MODULES:
        return errs + [f"modules: required list of 1-{MAX_MODULES} modules"]
    seen_keys: set[str] = set()
    for mi, m in enumerate(mods):
        if not isinstance(m, dict):
            errs.append(f"module[{mi}]: must be an object")
            continue
        key = m.get("key")
        if not isinstance(key, str) or not _KEY_RE.fullmatch(key):
            errs.append(f"module[{mi}]: key must be lowercase snake_case (max 40 chars)")
        elif key in seen_keys:
            errs.append(f"module[{mi}]: duplicate key '{key}'")
        else:
            seen_keys.add(key)
        mname = m.get("name")
        if not isinstance(mname, str) or not 1 <= len(mname.strip()) <= 120:
            errs.append(f"module[{mi}]: name required, 1-120 characters")
        for opt_key, cap in (("iso", 80), ("icon", 8), ("grp", 80)):
            v = m.get(opt_key, "")
            if not isinstance(v, str) or len(v) > cap:
                errs.append(f"module[{mi}]: {opt_key} must be a string of max {cap} chars")
        fields = m.get("fields")
        if not isinstance(fields, list) or not 1 <= len(fields) <= MAX_FIELDS:
            errs.append(f"module[{mi}]: fields must be a list of 1-{MAX_FIELDS}")
            continue
        seen_ids: set[str] = set()
        for fi, f in enumerate(fields):
            errs += _field_errors(f, mi, fi)
            if isinstance(f, (list, tuple)) and len(f) == 3 and isinstance(f[0], str):
                if f[0] in seen_ids and f[2] != "section":
                    errs.append(f"module[{mi}].fields[{fi}]: duplicate field id '{f[0]}'")
                seen_ids.add(f[0])
        data_fields = [f for f in fields
                       if isinstance(f, (list, tuple)) and len(f) == 3 and f[2] != "section"]
        if not data_fields:
            errs.append(f"module[{mi}]: needs at least one non-section field")
    return errs


def normalize(pkg: dict) -> dict:
    """Strip unknown keys and trim strings — store only what we validated."""
    return {
        "schema": SCHEMA_VERSION,
        "name": str(pkg["name"]).strip(),
        "version": str(pkg.get("version", "1.0.0")),
        "description": str(pkg.get("description", ""))[:2000],
        # per-company OPERATIONS CHAT DIRECTIVE — injected into every chat
        # when this package is installed (replaces the AI-generated one)
        "chat_prompt": str(pkg.get("chat_prompt", ""))[:20000],
        "modules": [{
            "key": m["key"],
            "name": str(m["name"]).strip(),
            "iso": str(m.get("iso", ""))[:80],
            "icon": str(m.get("icon", "🏭"))[:8],
            "grp": str(m.get("grp", ""))[:80],
            "fields": [[f[0], str(f[1]).strip(), f[2]] for f in m["fields"]],
        } for m in pkg["modules"]],
    }


# ------------------------------------------------------------------ storage
def _path(user_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(user_id))[:64]
    if not safe:
        raise ValueError("invalid user id")
    return PKG_DIR / f"{safe}.json"


def load_package(user_id: str) -> "dict | None":
    """Cached read of the installed package; None = use built-in template."""
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(user_id)
        if hit and now - hit[0] < _CACHE_TTL:
            return hit[1]
    pkg: "dict | None" = None
    try:
        p = _path(user_id)
        if p.exists():
            raw = p.read_text(encoding="utf-8")
            if len(raw.encode()) <= MAX_PACKAGE_BYTES:
                cand = json.loads(raw)
                if not validate_package(cand):
                    pkg = cand
                else:
                    log.error("ops package for user %s failed validation on load — "
                              "ignored; re-install or repair via Operations Studio",
                              user_id[:8])
    except (OSError, ValueError, json.JSONDecodeError) as e:
        log.error("ops package load failed for user %s: %s — using built-in template",
                  user_id[:8], e)
    with _cache_lock:
        _cache[user_id] = (now, pkg)
    return pkg


def save_package(user_id: str, pkg: dict) -> dict:
    """Validate, normalize and atomically persist. Raises ValueError on bad input."""
    errs = validate_package(pkg)
    if errs:
        raise ValueError("; ".join(errs[:12]))
    clean = normalize(pkg)
    raw = json.dumps(clean, ensure_ascii=False, indent=1)
    if len(raw.encode()) > MAX_PACKAGE_BYTES:
        raise ValueError(f"package exceeds {MAX_PACKAGE_BYTES // 1024} KB limit")
    PKG_DIR.mkdir(parents=True, exist_ok=True)
    p = _path(user_id)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)             # atomic on POSIX and Windows
    with _cache_lock:
        _cache.pop(user_id, None)
    return clean


def delete_package(user_id: str) -> bool:
    try:
        p = _path(user_id)
        existed = p.exists()
        if existed:
            p.unlink()
        with _cache_lock:
            _cache.pop(user_id, None)
        return existed
    except OSError as e:
        log.error("ops package delete failed for user %s: %s", user_id[:8], e)
        raise


# ------------------------------------------------------------------ starter
def builtin_as_package(company_type: str, label: str = "",
                       chat_prompt: str = "") -> "dict | None":
    """Export the built-in industry template as an editable starter package.
    ONE package covers ALL operations of the company (never split), named
    after the company itself — e.g. 'ACME SUPPLIES BUILD'."""
    from . import business as biz
    t = biz.INDUSTRY_TEMPLATES.get(company_type)
    if not t:
        return None
    return {
        "schema": SCHEMA_VERSION,
        "name": ((label or t["label"]).strip().upper() + " BUILD"),
        "version": "1.0.0",
        "description": f"Complete operations build exported from the built-in "
                       f"'{t['label']}' industry template — one package for all "
                       f"operations of this company.",
        "chat_prompt": (chat_prompt or "")[:20000],
        "modules": [{
            "key": m["key"], "name": m["name"], "iso": m.get("iso", ""),
            "icon": m.get("icon", t.get("icon", "🏭")), "grp": m.get("grp", ""),
            "fields": [list(f) for f in m["fields"]],
        } for m in t["modules"]],
    }
