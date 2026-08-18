# SPDX-License-Identifier: MIT
"""Enterprise POS Server — restaurant & supermarket point-of-sale backbone.

Implements the spec in handoff/Enterprise_Restaurant_Supermarket_Platform_
VSCode_Prompt.md:
  * business-type-aware navigation (POS/Purchasing/Accounting appear ONLY
    for restaurant / supermarket deployments — enforced server-side too)
  * POS Server configuration objects: categories, items, option groups,
    dining zones + tables (layout coordinates), departments, sub-items,
    to-go/pickup settings, third-party delivery platforms (credentials
    encrypted, never returned), kiosks (device tokens), receipt printers,
    cash drawers, POS accounts (HR-linked), shifts and drawer events.
  * risk-classified operations with full audit trail (caller audits).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets

POS_BUSINESS_TYPES = ("restaurant", "supermarket")


def pos_enabled(company_type: str) -> bool:
    return company_type in POS_BUSINESS_TYPES


# ============================================================
# Kind registry — every POS object kind with its field schema
# (schema is served to the frontend to build professional forms)
# scope: both | restaurant | supermarket
# ============================================================
POS_KINDS: dict[str, dict] = {
    "category": {"label": "Item Categories", "icon": "🗂️", "scope": "both",
        "fields": [["name", "Name", "text"], ["color", "Color", "text"],
                   ["image", "Image URL", "text"], ["schedule", "Availability schedule", "text"],
                   ["department", "Department (supermarket)", "text"]]},
    "item": {"label": "Items / Products", "icon": "🍔", "scope": "both",
        "fields": [["name", "Name", "text"], ["description", "Description", "textarea"],
                   ["sku", "SKU", "text"], ["upc", "UPC / Barcode", "text"],
                   ["category", "Category", "text"], ["department", "Department", "text"],
                   ["price", "Price $", "number"], ["cost", "Cost $", "number"],
                   ["tax_rate", "Tax %", "number"],
                   ["unit", "Unit type", "select:each,lb,kg,oz,case,pack"],
                   ["prep_location", "Prep location", "select:,kitchen,bar,bakery,deli,none"],
                   ["price_dinein", "Dine-in $", "number"], ["price_pickup", "Pickup $", "number"],
                   ["price_drivethru", "Drive-thru $", "number"], ["price_delivery", "Delivery $", "number"],
                   ["sale_price", "Sale price $", "number"], ["weight_based", "Weight-based", "select:no,yes"],
                   ["sold_out", "Temporarily sold out", "select:no,yes"],
                   ["image", "Image URL", "text"]]},
    "sub_item": {"label": "Sub-Items / Variants", "icon": "🧃", "scope": "supermarket",
        "fields": [["name", "Variant name", "text"], ["parent_sku", "Parent item SKU", "text"],
                   ["sku", "Variant SKU", "text"], ["upc", "UPC / Barcode", "text"],
                   ["attr", "Attribute", "select:size,flavor,color,pack qty,weight"],
                   ["value", "Attribute value", "text"], ["price", "Price $", "number"],
                   ["cost", "Cost $", "number"], ["qty", "Inventory qty", "number"]]},
    "option_group": {"label": "Item Options / Modifiers", "icon": "🎛️", "scope": "restaurant",
        "fields": [["name", "Group name", "text"],
                   ["type", "Type", "select:size,temperature,toppings,add-ons,cooking preference,sides,custom"],
                   ["required", "Required", "select:no,yes"],
                   ["min_sel", "Min selections", "number"], ["max_sel", "Max selections", "number"],
                   ["options", "Options (name:+price, one per line)", "textarea"],
                   ["items", "Applies to items (SKUs, comma)", "text"]]},
    "zone": {"label": "Dining Zones", "icon": "🏛️", "scope": "restaurant",
        "fields": [["name", "Zone name", "text"], ["x", "X", "number"], ["y", "Y", "number"],
                   ["w", "Width", "number"], ["h", "Height", "number"],
                   ["color", "Color", "text"]]},
    "structure": {"label": "Building Structures", "icon": "🧱", "scope": "restaurant",
        "fields": [["name", "Label", "text"],
                   ["type", "Type", "select:wall,door,window,entrance,kitchen,bar,counter,restroom,stairs,pillar,divider,plant,other"],
                   ["zone", "Zone (optional)", "text"],
                   ["x", "X", "number"], ["y", "Y", "number"],
                   ["w", "Width", "number"], ["h", "Height", "number"],
                   ["rot", "Rotation °", "number"]]},
    "table": {"label": "Tables", "icon": "🪑", "scope": "restaurant",
        "fields": [["name", "Table name/number", "text"], ["zone", "Zone", "text"],
                   ["shape", "Shape", "select:round,square,rectangle"],
                   ["seats", "Seats", "number"], ["x", "X", "number"], ["y", "Y", "number"],
                   ["w", "Width", "number"], ["h", "Height", "number"], ["rot", "Rotation °", "number"],
                   ["status", "Status", "select:available,occupied,reserved,awaiting payment,cleaning,disabled"]]},
    "department": {"label": "Departments", "icon": "🏬", "scope": "supermarket",
        "fields": [["name", "Department", "select:Produce,Meat,Seafood,Bakery,Dairy,Frozen Food,Grocery,Household,Other"],
                   ["custom", "Custom name", "text"], ["manager", "Manager", "text"]]},
    "togo": {"label": "To-Go / Pickup Settings", "icon": "🥡", "scope": "both",
        "fields": [["mode", "Mode", "select:pickup,drive-thru"],
                   ["prep_minutes", "Prep time (min)", "number"],
                   ["hours", "Operating hours", "text"],
                   ["instructions", "Pickup instructions", "textarea"],
                   ["notify", "Notification", "select:none,sms,email,both"]]},
    "delivery_platform": {"label": "Delivery Platforms", "icon": "🛵", "scope": "both",
        "fields": [["provider", "Provider", "select:Uber Eats,DoorDash,Grubhub,Other"],
                   ["store_id", "Store ID", "text"],
                   ["sync_menu", "Sync menu & prices", "select:yes,no"],
                   ["sync_inventory", "Sync inventory (supermarket)", "select:no,yes"],
                   ["status", "Status", "select:inactive,testing,active,error"]],
        "secret_fields": [["api_key", "API key"], ["api_secret", "API secret"]]},
    "kiosk": {"label": "POS Kiosks", "icon": "🖥️", "scope": "both",
        "fields": [["name", "Kiosk name", "text"], ["location", "Location", "text"],
                   ["order_types", "Order types", "text"],
                   ["printer", "Assigned printer", "text"], ["drawer", "Assigned drawer", "text"],
                   ["workers", "Assigned workers/roles (comma)", "text"],
                   ["status", "Status", "select:active,inactive"]]},
    "printer": {"label": "Receipt Printers", "icon": "🖨️", "scope": "both",
        "fields": [["name", "Printer name", "text"], ["model", "Model", "text"],
                   ["type", "Type", "select:receipt,kitchen,label"],
                   ["conn", "Connection", "select:ethernet,wifi,usb,bluetooth"],
                   ["address", "IP / device ID", "text"], ["paper", "Paper width", "select:80mm,58mm"],
                   ["copies", "Copies", "number"], ["auto_print", "Auto print", "select:yes,no"],
                   ["kiosk", "Assigned kiosk", "text"],
                   ["status", "Status", "select:online,offline,error"]]},
    "drawer": {"label": "Cash Drawers", "icon": "💵", "scope": "both",
        "fields": [["name", "Drawer name", "text"],
                   ["conn", "Connection", "select:printer RJ11/RJ12,usb,network,bluetooth"],
                   ["printer", "Connected printer (RJ11)", "text"], ["device_id", "Device ID", "text"],
                   ["kiosk", "Assigned kiosk", "text"],
                   ["auto_open_cash", "Auto-open on cash payment", "select:yes,no"],
                   ["manual_needs_approval", "Manual open needs manager approval", "select:yes,no"],
                   ["status", "Status", "select:active,inactive,error"]]},
    "pos_account": {"label": "POS Accounts", "icon": "👤", "scope": "both",
        "fields": [["username", "Username / Employee ID", "text"], ["worker", "HR worker name", "text"],
                   ["role", "Role", "select:POS Administrator,Business Owner,Manager,Supervisor,Cashier,Server,Kitchen Worker,Inventory Worker,Purchasing Worker,Read-Only Auditor"],
                   ["pos_scope", "POS systems allowed", "select:both,restaurant,supermarket"],
                   ["kiosk", "Assigned kiosk", "text"],
                   ["permissions", "Extra permissions (comma)", "text"],
                   ["schedule", "Login schedule", "text"],
                   ["status", "Status", "select:active,suspended,terminated"]],
        "secret_fields": [["pin", "PIN / password"]]},
    "shift": {"label": "Cashier Shifts", "icon": "⏲️", "scope": "both",
        "fields": [["worker", "Worker", "text"], ["kiosk", "Kiosk", "text"],
                   ["drawer", "Drawer", "text"],
                   ["opening", "Opening balance $", "number"], ["counted", "Counted at close $", "number"],
                   ["expected", "Expected close $", "number"],
                   ["status", "Status", "select:open,closed"], ["note", "Note", "textarea"]]},
    "drawer_event": {"label": "Drawer Activity Log", "icon": "📜", "scope": "both",
        "fields": [["drawer", "Drawer", "text"], ["kiosk", "Kiosk", "text"], ["worker", "Worker", "text"],
                   ["action", "Action", "select:auto open (cash sale),manual open,cash in,cash out,cash drop,payout,adjustment,test"],
                   ["amount", "Amount $", "number"], ["reason", "Reason (required for manual)", "textarea"],
                   ["approved_by", "Manager approval", "text"],
                   ["result", "Result", "select:ok,error"]]},
    "order": {"label": "POS Orders", "icon": "🧾", "scope": "both",
        "fields": [["number", "Order #", "text"],
                   ["type", "Type", "select:dine-in,pickup,drive-thru,delivery"],
                   ["table", "Table (dine-in)", "text"],
                   ["items", "Items (name x qty @price, per line)", "textarea"],
                   ["subtotal", "Subtotal $", "number"], ["discount", "Discount $", "number"],
                   ["tax", "Tax $", "number"], ["tip", "Tip $", "number"], ["total", "Total $", "number"],
                   ["payment", "Payment", "select:cash,card,digital,split,on account"],
                   ["status", "Status", "select:open,preparing,ready,completed,refunded,voided"],
                   ["worker", "Worker", "text"], ["kiosk", "Kiosk", "text"]]},
}

# which kinds appear for a given business type
def kinds_for(company_type: str) -> list[str]:
    if not pos_enabled(company_type):
        return []
    return [k for k, v in POS_KINDS.items()
            if v["scope"] in ("both", company_type)]


# ============================================================
# Navigation config (spec §2) — modules by business type.
# The frontend renders exactly this; the API endpoints check
# pos_enabled() server-side so hiding is never the only guard.
# ============================================================
def navigation_for(company_type: str) -> dict:
    if not pos_enabled(company_type):
        return {"pos": False, "sections": []}
    common_srv = [
        {"kind": "category", **_ki("category")}, {"kind": "item", **_ki("item")}]
    if company_type == "restaurant":
        common_srv += [{"kind": "option_group", **_ki("option_group")},
                       {"kind": "zone", **_ki("zone")}, {"kind": "structure", **_ki("structure")},
                       {"kind": "table", **_ki("table")}]
    else:
        common_srv += [{"kind": "sub_item", **_ki("sub_item")},
                       {"kind": "department", **_ki("department")}]
    common_srv += [{"kind": "togo", **_ki("togo")},
                   {"kind": "delivery_platform", **_ki("delivery_platform")}]
    devices = [{"kind": "kiosk", **_ki("kiosk")}, {"kind": "printer", **_ki("printer")},
               {"kind": "drawer", **_ki("drawer")}, {"kind": "pos_account", **_ki("pos_account")}]
    ops = [{"kind": "order", **_ki("order")}, {"kind": "shift", **_ki("shift")},
           {"kind": "drawer_event", **_ki("drawer_event")}]
    return {"pos": True, "type": company_type, "sections": [
        {"label": "POS SERVER", "items": common_srv},
        {"label": "DEVICES & ACCOUNTS", "items": devices},
        {"label": "POS OPERATIONS", "items": ops},
    ]}


def _ki(kind: str) -> dict:
    v = POS_KINDS[kind]
    return {"label": v["label"], "icon": v["icon"]}


def kind_schema(kind: str) -> dict | None:
    v = POS_KINDS.get(kind)
    if not v:
        return None
    return {"kind": kind, "label": v["label"], "icon": v["icon"],
            "fields": v["fields"],
            "secret_fields": v.get("secret_fields", [])}


# ============================================================
# CRUD helpers (called from main.py endpoints)
# ============================================================
def object_dict(o) -> dict:
    try:
        d = json.loads(o.data or "{}")
    except Exception:
        d = {}
    return {"id": o.id, "kind": o.kind, "name": o.name, "data": d,
            "parent_id": o.parent_id or "", "sort": o.sort or 0,
            "active": bool(o.active), "has_secret": bool(o.secret),
            "created_at": str(o.created_at or "")}


def new_kiosk_token() -> str:
    """Unique kiosk device authentication token (revocable)."""
    return "kiosk-" + secrets.token_urlsafe(24)


def find_kiosk_by_token(db, token: str):
    """Constant-time device-token authentication (spec §3.2). Returns the
    active kiosk PosObject whose encrypted secret matches, else None."""
    if not token or not token.startswith("kiosk-"):
        return None
    from .db import PosObject
    from .security import decrypt_secret
    match = None
    for k in db.query(PosObject).filter(PosObject.kind == "kiosk").all():
        try:
            stored = decrypt_secret(k.secret or "")
        except Exception:
            continue
        # compare every candidate to keep timing uniform
        if stored and secrets.compare_digest(stored, token) and match is None:
            match = k
    if match is not None and not match.active:
        return None  # deactivated kiosks lose access immediately
    return match


def mask(v: str) -> str:
    v = v or ""
    return (v[:3] + "•" * max(4, len(v) - 6) + v[-3:]) if len(v) > 8 else "•" * len(v)


def file_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# manual drawer opening requires a reason (spec §9)
def validate_drawer_event(data: dict) -> str | None:
    if (data.get("action") or "").startswith("manual") and not (data.get("reason") or "").strip():
        return "Manual drawer opening requires a reason."
    return None


# ============================================================
# Multilingual AI Command Center (spec §21) — chat control of
# POS / Purchasing / Accounting. Input arrives pre-normalized
# to English tokens by i18n_intents (EN/繁中/简中/ES/…).
# Controlled architecture: the model never writes to the DB;
# this handler validates, enforces the business-type gate and
# permissions, then calls the SAME code paths as the GUI.
# Risk classes: read-only runs immediately; sensitive ops
# (refunds, voids, drawer opening, invoice approval) are
# refused or routed to the GUI workflow.
# ============================================================
import re as _re

POS_KIND_SYNONYMS: dict[str, str] = {
    "category": "category", "categories": "category", "menu category": "category",
    "item": "item", "product": "item", "menu item": "item", "dish": "item",
    "sub item": "sub_item", "variant": "sub_item",
    "option": "option_group", "modifier": "option_group", "topping": "option_group",
    "zone": "zone", "dining zone": "zone", "dining area": "zone",
    "structure": "structure", "wall": "structure", "building structure": "structure",
    "table": "table", "department": "department",
    "kiosk": "kiosk", "printer": "printer", "receipt printer": "printer",
    "drawer": "drawer", "cash drawer": "drawer",
    "pos account": "pos_account", "shift": "shift",
    "vendor": "__vendor", "purchase order": "__po", "po": "__po",
    "vendor invoice": "__invoice", "journal": "__journal", "journal entry": "__journal",
}
_PK_SORTED = sorted(POS_KIND_SYNONYMS, key=len, reverse=True)
_PK_WORDS = "|".join(_re.escape(s) for s in _PK_SORTED)

POS_INTENT = _re.compile(
    r"\b(?:(?:list|show|view|check|count)\b.{0,40}\b(?:" + _PK_WORDS + r")s?\b"
    r"|(?:add|create|new)\b.{0,40}\b(?:" + _PK_WORDS + r")s?\b"
    r"|(?:" + _PK_WORDS + r")s?\b.{0,30}\b(?:list|show|report|add|create|new)\b"
    r"|\b(?:profit\s+and\s+loss|p&l|balance\s+sheet|trial\s+balance|general\s+ledger|cash\s*flow)\b"
    r"|\b(?:tax|xlsx)\s+(?:export|report|package)\b"
    r"|\bexport\b.{0,30}\b(?:tax|xlsx)\b"
    r"|\b(?:approve|post)\b.{0,20}\binvoices?\b"
    r"|\bopen\b.{0,20}\bdrawer\b)", _re.I)

_SENSITIVE = _re.compile(r"\b(refund|void|open\b.{0,20}\bdrawer|delete|remove|revoke)\b", _re.I)
_BULK_INVOICE = _re.compile(r"\b(approve|post|confirm)\b.{0,20}\b(all\s+)?invoices?\b", _re.I)


def handle_pos_prompt(db, text: str, user_id: str) -> "str | None":
    """Chat operations on the POS/Purchasing/Accounting layer."""
    from .db import BusinessProfile, JournalEntry, PosObject, Vendor, VendorInvoice
    bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == user_id).first()
    if not bp or bp.usage_mode != "commercial" or not pos_enabled(bp.company_type):
        return None
    low = text.lower()

    # ---- invoice safety (spec §21.5): NEVER bulk-approve / auto-post ----
    if _BULK_INVOICE.search(low):
        pend = (db.query(VendorInvoice)
                .filter(VendorInvoice.user_id == user_id,
                        VendorInvoice.status.notin_(["posted", "rejected"])).count())
        return ("🛑 **Invoice verification cannot be bypassed or done in bulk.**\n"
                f"You have {pend} invoice(s) pending review. Each one must be reviewed "
                "field-by-field against the original document, corrected, and explicitly "
                "confirmed by a human in 🏢 Business → Purchasing → Invoice Review. "
                "This is a mandatory control (ISO 9001 §8.6 / AP separation of duties).")

    # ---- sensitive ops require the GUI workflow ----
    if _SENSITIVE.search(low) and _re.search(r"\b(drawer|refund|void|kiosk|token)\b", low):
        return ("⚠ This is a **sensitive operation** (risk class 3/4). For safety it "
                "requires the GUI workflow with manager approval, reason logging and "
                "device confirmation — open 🏢 Business → POS to proceed. "
                "Read-only queries and standard record creation work here in chat.")

    # ---- accounting reports ----
    if _re.search(r"\bprofit\s+and\s+loss\b|\bp&l\b", low):
        from .accounting import profit_and_loss, seed_coa
        seed_coa(db, user_id)
        pl = profit_and_loss(db, user_id)
        return ("📊 **PROFIT & LOSS (all posted entries)**\n"
                f"Revenue: ${pl['revenue']:,.2f}\nCOGS: ${pl['cogs']:,.2f}\n"
                f"Gross Profit: ${pl['gross_profit']:,.2f}\nExpenses: ${pl['expenses']:,.2f}\n"
                f"**Net Income: ${pl['net_income']:,.2f}**")
    if "balance sheet" in low:
        from .accounting import balance_sheet, seed_coa
        seed_coa(db, user_id)
        bs = balance_sheet(db, user_id)
        return ("📊 **BALANCE SHEET**\n"
                f"Total Assets: ${bs['total_assets']:,.2f}\n"
                f"Total Liabilities: ${bs['total_liabilities']:,.2f}\n"
                f"Total Equity: ${bs['total_equity']:,.2f}\n"
                f"{'✅ Balanced' if bs['balanced'] else '⚠ NOT balanced — investigate'}")
    if "trial balance" in low:
        from .accounting import seed_coa, trial_balance
        seed_coa(db, user_id)
        tb = trial_balance(db, user_id)
        if not tb:
            return "📊 Trial balance is empty — no posted journal entries yet."
        lines = ["📊 **TRIAL BALANCE**"]
        for r in tb[:25]:
            lines.append(f"{r['account']}: D ${r['debit']:,.2f} / C ${r['credit']:,.2f}")
        return "\n".join(lines)
    if _re.search(r"\bcash\s*flow\b", low):
        from .accounting import cash_flow, seed_coa
        seed_coa(db, user_id)
        cf = cash_flow(db, user_id)
        return ("📊 **CASH FLOW STATEMENT (all posted entries)**\n"
                f"Operating: ${cf['operating']:,.2f}\nInvesting: ${cf['investing']:,.2f}\n"
                f"Financing: ${cf['financing']:,.2f}\nNet Change: ${cf['net_change']:,.2f}\n"
                f"**Ending Cash: ${cf['ending_cash']:,.2f}**")
    if _re.search(r"\b(?:tax|xlsx)\s+(?:export|report|package)\b|\bexport\b.{0,30}\b(?:tax|xlsx)\b", low):
        return ("📦 The accountant-ready tax XLSX package (21-section workbook: P&L, "
                "Balance Sheet, Trial Balance, General Ledger, Data Exceptions…) is "
                "generated from 🏢 Business → Accounting → **EXPORT TAX XLSX**, or "
                "directly: `GET /api/accounting/export/xlsx?year=YYYY`. Every export is "
                "audited with filters and file checksum.")

    # ---- find target kind ----
    target = None
    for syn in _PK_SORTED:
        if _re.search(r"\b" + _re.escape(syn) + r"s?\b", low):
            target = POS_KIND_SYNONYMS[syn]
            break
    if not target:
        return None

    creating = bool(_re.search(r"\b(add|create|new)\b", low))
    _KV = _re.compile(r"([A-Za-z_][A-Za-z_ ]{0,20}?)\s*[:=]\s*([^,;\n]+)")

    if target == "__vendor":
        if creating:
            kv = dict((k.strip().lower(), v.strip()) for k, v in _KV.findall(text))
            name = kv.get("name") or _re.sub(r".*\b(?:vendor)\b", "", text, flags=_re.I).strip(" :,.")
            if not name:
                return "ℹ Give the vendor a name, e.g. `add vendor: name=Sysco, terms=Net 30`"
            v = Vendor(user_id=user_id, name=name[:200], terms=kv.get("terms") or "Net 30",
                       phone=kv.get("phone") or "", email=kv.get("email") or "")
            db.add(v)
            db.commit()
            return f"✅ Vendor **{v.name}** created ({v.terms})."
        rows = db.query(Vendor).filter(Vendor.user_id == user_id).order_by(Vendor.name).limit(30).all()
        return ("🏭 **VENDORS**\n" + "\n".join(f"{i}. {v.name} · {v.terms} · {v.status}"
                for i, v in enumerate(rows, 1))) if rows else "🏭 No vendors yet — `add vendor: name=…`"

    if target == "__po":
        from .db import PurchaseOrder as PO_ERP
        rows = (db.query(PO_ERP).filter(PO_ERP.user_id == user_id)
                .order_by(PO_ERP.created_at.desc()).limit(20).all())
        if creating:
            return ("ℹ Purchase orders with line items are created in 🏢 Business → "
                    "Purchasing (vendor, lines, qty, cost, tax, approval workflow).")
        return ("📑 **PURCHASE ORDERS**\n" + "\n".join(
            f"{i}. {p.po_number} · ${p.total:,.2f} · {p.status}" for i, p in enumerate(rows, 1))) \
            if rows else "📑 No purchase orders yet."

    if target == "__invoice":
        rows = (db.query(VendorInvoice).filter(VendorInvoice.user_id == user_id)
                .order_by(VendorInvoice.created_at.desc()).limit(20).all())
        if not rows:
            return "🧾 No vendor invoices uploaded yet — upload in 🏢 Business → Purchasing."
        lines = ["🧾 **VENDOR INVOICES** (each requires human field-by-field verification)"]
        for i, v in enumerate(rows, 1):
            lines.append(f"{i}. {v.file_name} · {v.status}" + (f" · JE linked" if v.journal_id else ""))
        return "\n".join(lines)

    if target == "__journal":
        rows = (db.query(JournalEntry).filter(JournalEntry.user_id == user_id)
                .order_by(JournalEntry.number.desc()).limit(15).all())
        return ("📚 **JOURNAL ENTRIES**\n" + "\n".join(
            f"#{j.number} {str(j.at or '')[:10]} · {j.memo[:50]} · {j.status}" for j in rows)) \
            if rows else "📚 No journal entries yet."

    # ---- generic POS object kinds ----
    if target not in kinds_for(bp.company_type):
        return (f"🚫 '{target}' is not available for a {bp.company_type} business — "
                "business-type navigation is enforced server-side.")
    if creating:
        kv = dict((k.strip().lower().replace(" ", "_"), v.strip()) for k, v in _KV.findall(text))
        data = {}
        # natural-language attribute extraction (e.g. "create a square table
        # called O4 in Outside zone"): shape, zone, seats, status
        m = _re.search(r"\b(square|round|rectangle|rectangular|circular)\b", low)
        if m:
            shape = {"rectangular": "rectangle", "circular": "round",
                     "square": "square"}.get(m.group(1), m.group(1))
            data["shape"] = shape
        m = _re.search(r"\b(?:in|at|on)\s+(?:the\s+)?([A-Za-z][\w ]{0,30}?)\s+zone\b", text, _re.I) \
            or _re.search(r"\bzone\s+([A-Za-z][\w]{0,30})\b", text, _re.I)
        if m:
            data["zone"] = m.group(1).strip()
        m = _re.search(r"\b(\d{1,2})\s+seats?\b", low)
        if m:
            data["seats"] = m.group(1)
        # name: explicit name=…, then "called/named/call 'X'", then quoted text
        name = kv.get("name") or ""
        if not name:
            m = (_re.search(r"\b(?:called|named|call|name)\s+[\"'“”]?([\w #.-]{1,60}?)[\"'“”]?(?=\s+(?:in|at|on|with|for)\b|[,.]|$)", text, _re.I)
                 or _re.search(r"[\"'“”]([^\"'“”]{1,60})[\"'“”]", text))
            if m:
                name = m.group(1).strip()
        if not name:
            rest = _re.sub(r"\b(please|add|create|new|make|a|an|the|which|is|it)\b", " ", text, flags=_re.I)
            rest = _re.sub(r"\b(?:" + _PK_WORDS + r")s?\b", " ", rest, flags=_re.I)
            rest = _re.sub(r"\b(?:in|at|on)\s+[\w ]{0,30}?\s+zone\b", " ", rest, flags=_re.I)
            rest = _re.sub(r"\b(square|round|rectangle|rectangular|circular|for|pos|called|named|call)\b", " ", rest, flags=_re.I)
            name = _re.sub(r"\s+", " ", rest).strip(" :,.")[:100]
        if not name or len(name.split()) > 4:
            return (f"ℹ I couldn't extract a clear name. Try `add {target}: name=…` "
                    f"or e.g. `create a {target} called T1`")
        schema_fields = {f[0] for f in POS_KINDS[target]["fields"]}
        data.update({k: v for k, v in kv.items() if k in schema_fields})
        data = {k: v for k, v in data.items() if k in schema_fields or k == "name"}
        data.setdefault("name", name)
        o = PosObject(user_id=user_id, kind=target, name=name, data=json.dumps(data))
        db.add(o)
        db.commit()
        extra = ""
        if target == "kiosk":
            from .security import encrypt_secret
            token = new_kiosk_token()
            o.secret = encrypt_secret(token)
            db.commit()
            extra = f"\n🔑 Device token (shown once): `{token}`"
        detail = " · ".join(f"{k}={v}" for k, v in data.items() if k != "name" and v)
        return (f"✅ {POS_KINDS[target]['icon']} **{POS_KINDS[target]['label']}** — "
                f"'{name}' created{(' (' + detail + ')') if detail else ''}.{extra}")
    rows = (db.query(PosObject).filter(PosObject.user_id == user_id, PosObject.kind == target)
            .order_by(PosObject.sort, PosObject.created_at).limit(40).all())
    if not rows:
        return (f"{POS_KINDS[target]['icon']} **{POS_KINDS[target]['label']}** is empty — "
                f"`add {target}: name=…` or use 🏢 Business → POS.")
    lines = [f"{POS_KINDS[target]['icon']} **{POS_KINDS[target]['label'].upper()}**"]
    for i, o in enumerate(rows, 1):
        try:
            d = json.loads(o.data or "{}")
        except Exception:
            d = {}
        bits = " · ".join(f"{k}: {v}" for k, v in list(d.items())[:4] if k != "name" and v)
        lines.append(f"{i}. {'🟢' if o.active else '⚪'} {o.name}" + (f" · {bits}" if bits else ""))
    return "\n".join(lines)
