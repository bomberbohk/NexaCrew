# SPDX-License-Identifier: MIT
"""Enterprise Purchasing + AI invoice verification (spec §12–§20).

Vendors → Purchase Orders → Receiving → AI-assisted invoice extraction with
field-level confidence → MANDATORY human confirm-each-field review → posting
to Accounts Payable / Accounting / Inventory.  Automatic invoice posting is
disabled by design: `post_invoice` refuses unless every required field was
confirmed and the exact confirmation statement was signed.
"""
from __future__ import annotations

import datetime as dt
import json
import re

REQUIRED_STATEMENT = ("I have reviewed the original invoice and confirm that the "
                      "extracted and corrected information is accurate.")

# fields that MUST be human-confirmed before posting (spec §17)
REQUIRED_FIELDS = ["vendor", "invoice_number", "invoice_date", "due_date",
                   "subtotal", "tax", "total", "lines", "account"]

CONFIDENCE_LEVELS = ("high", "medium", "low", "unreadable", "missing", "conflicting")


# ------------------------------------------------------------
# AI extraction — best-effort text extraction + AI CLI analysis;
# every field is tagged with a confidence status. Values the AI
# cannot read are marked unreadable/missing, NEVER invented.
# ------------------------------------------------------------
_EXTRACT_PROMPT = """You are an accounts-payable document analyst.
Analyze the following invoice content and return STRICT JSON only (no prose):
{"doc_type": "invoice|receipt|credit memo|statement|unsupported",
 "fields": {
   "vendor": {"value": "...", "confidence": "high|medium|low|unreadable|missing|conflicting"},
   "invoice_number": {...}, "invoice_date": {...}, "due_date": {...},
   "po_number": {...}, "terms": {...}, "currency": {...},
   "subtotal": {...}, "tax": {...}, "freight": {...}, "total": {...},
   "lines": {"value": [{"desc": "...", "sku": "", "qty": 0, "unit": "", "unit_cost": 0, "line_total": 0}], "confidence": "..."}
 },
 "warnings": ["handwriting detected", "crossed-out value on line 2", ...]}
Rules: NEVER invent missing information — use confidence "missing" or
"unreadable" instead. Flag decimal ambiguity, conflicting totals (sum of
lines vs printed total), handwriting, rotation or blur in warnings.
INVOICE CONTENT:
"""


def extract_invoice(file_path: str, file_name: str) -> dict:
    """Returns {doc_type, fields, warnings}. Uses the AI CLI when available;
    falls back to regex heuristics on extractable text."""
    text = _file_text(file_path, file_name)
    ai = _ai_extract(text) if text else None
    if ai:
        return ai
    return _heuristic_extract(text or "")


def _file_text(path: str, name: str) -> str:
    from pathlib import Path
    ext = Path(name or path).suffix.lower()
    try:
        data = Path(path).read_bytes()
    except Exception:
        return ""
    if ext in (".txt", ".md", ".csv", ".json"):
        return data.decode("utf-8", errors="replace")
    if ext == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
            import io
            return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
        except Exception:
            return ""
    return ""  # images: no local OCR — AI review required with low confidence


def _ai_extract(text: str) -> dict | None:
    try:
        from . import services as _svc
        prov = getattr(_svc, "_agent_provider", None)
        if prov is None or not getattr(prov, "available", False):
            return None
        out = (prov.run(_EXTRACT_PROMPT + text[:12000]) or "").strip()
        m = re.search(r"\{.*\}", out, re.S)
        if not m:
            return None
        doc = json.loads(m.group(0))
        if not isinstance(doc.get("fields"), dict):
            return None
        # sanitize confidences
        for f in doc["fields"].values():
            if isinstance(f, dict) and f.get("confidence") not in CONFIDENCE_LEVELS:
                f["confidence"] = "low"
        doc.setdefault("doc_type", "invoice")
        doc.setdefault("warnings", [])
        return doc
    except Exception:
        return None


def _heuristic_extract(text: str) -> dict:
    """Regex fallback — everything found is at best medium confidence;
    anything not found is 'missing' (never invented)."""
    f: dict = {}

    def put(key, val, conf):
        f[key] = {"value": val, "confidence": conf}

    low = text.lower()
    m = re.search(r"invoice\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9\-]{3,20})", text, re.I)
    put("invoice_number", m.group(1) if m else "", "medium" if m else "missing")
    m = re.search(r"(?:invoice\s*)?date\s*[:#]?\s*(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})", text, re.I)
    put("invoice_date", m.group(1) if m else "", "medium" if m else "missing")
    m = re.search(r"due\s*(?:date)?\s*[:#]?\s*(\d{1,4}[-/]\d{1,2}[-/]\d{1,4})", text, re.I)
    put("due_date", m.group(1) if m else "", "medium" if m else "missing")
    m = re.search(r"(?:^|\n)\s*(?:from|vendor|bill\s+from|sold\s+by)\s*[:#]?\s*([^\n]{3,60})", text, re.I)
    put("vendor", m.group(1).strip() if m else "", "medium" if m else "missing")

    def money(label):
        mm = re.search(label + r"\s*[:#]?\s*\$?\s*([\d,]+\.?\d*)", text, re.I)
        return (mm.group(1).replace(",", "") if mm else "")
    for k, lab in (("subtotal", r"sub\s*-?total"), ("tax", r"(?:sales\s*)?tax"),
                   ("freight", r"(?:freight|shipping)"), ("total", r"(?:grand\s*)?\btotal")):
        v = money(lab)
        put(k, v, "medium" if v else "missing")
    put("po_number", "", "missing")
    put("terms", "", "missing")
    put("currency", "USD", "low")
    put("lines", [], "unreadable" if not text.strip() else "low")
    warnings = []
    if not text.strip():
        warnings.append("No machine-readable text found (image/scan) — every field requires manual review")
    return {"doc_type": "invoice", "fields": f, "warnings": warnings}


# ------------------------------------------------------------
# Validation (spec §18) — totals, duplicates
# ------------------------------------------------------------
def validate_invoice(db, user_id: str, inv) -> list[str]:
    problems: list[str] = []
    vals = merged_values(inv)
    try:
        sub = float(vals.get("subtotal") or 0)
        tax = float(vals.get("tax") or 0)
        freight = float(vals.get("freight") or 0)
        tot = float(vals.get("total") or 0)
        if tot and abs((sub + tax + freight) - tot) > 0.02:
            problems.append(f"Total mismatch: subtotal {sub} + tax {tax} + freight {freight} ≠ total {tot}")
    except (TypeError, ValueError):
        problems.append("Unreadable amount — subtotal/tax/total must be numeric before posting")
    lines = vals.get("lines") or []
    if isinstance(lines, list) and lines:
        try:
            lsum = sum(float(x.get("line_total") or (float(x.get("qty") or 0) * float(x.get("unit_cost") or 0))) for x in lines)
            if vals.get("subtotal") and abs(lsum - float(vals["subtotal"])) > 0.02:
                problems.append(f"Line totals ({lsum:.2f}) don't match subtotal ({vals['subtotal']})")
        except (TypeError, ValueError):
            problems.append("A line item has an unreadable quantity or price")
    # duplicate detection: same vendor + invoice number OR same checksum
    from .db import VendorInvoice
    dup = (db.query(VendorInvoice)
           .filter(VendorInvoice.user_id == user_id, VendorInvoice.id != inv.id,
                   VendorInvoice.checksum == inv.checksum).first())
    if dup:
        problems.append(f"Duplicate file — identical checksum as invoice {dup.file_name} ({dup.status})")
    invno = str(vals.get("invoice_number") or "")
    if invno:
        others = (db.query(VendorInvoice)
                  .filter(VendorInvoice.user_id == user_id, VendorInvoice.id != inv.id).all())
        for o in others:
            if str(merged_values(o).get("invoice_number") or "") == invno and (o.vendor_id == inv.vendor_id):
                problems.append(f"Possible duplicate — invoice number {invno} already exists ({o.status})")
                break
    return problems


def merged_values(inv) -> dict:
    """extracted values overridden by human corrections."""
    try:
        ext = json.loads(inv.extracted or "{}").get("fields", {})
    except Exception:
        ext = {}
    out = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in ext.items()}
    try:
        out.update(json.loads(inv.corrected or "{}"))
    except Exception:
        pass
    return out


# ------------------------------------------------------------
# Three-way matching (spec §18) — PO ↔ Receiving ↔ Invoice
# ------------------------------------------------------------
def three_way_match(inv_vals: dict, po_lines: list[dict], po_total: float = 0.0,
                    tolerance_pct: float = 2.0, tolerance_abs: float = 0.02) -> dict:
    """Pure comparison of invoice values against PO lines (which carry the
    receiving state in `received`/`damaged`). Returns
    {matched, issues[], lines[]}. Never mutates anything."""
    issues: list[str] = []
    line_results: list[dict] = []

    def _key(x: dict) -> str:
        return (str(x.get("sku") or "").strip().lower()
                or str(x.get("desc") or "").strip().lower())

    po_by_key = {_key(ln): ln for ln in (po_lines or []) if _key(ln)}
    inv_lines = inv_vals.get("lines") or []
    if not isinstance(inv_lines, list):
        inv_lines = []
    if not po_by_key:
        issues.append("No PO lines to match against — two-way (invoice-only) review required")
    for il in inv_lines:
        k = _key(il)
        pl = po_by_key.get(k)
        res = {"line": il.get("desc") or il.get("sku") or "?", "status": "matched", "problems": []}
        if not pl:
            res["status"] = "no_po_line"
            res["problems"].append("Invoice line not found on the PO")
            issues.append(f"Line '{res['line']}': not on PO")
            line_results.append(res)
            continue
        try:
            q_inv = float(il.get("qty") or 0)
            q_recv = float(pl.get("received") or 0)
            q_ord = float(pl.get("qty") or 0)
            c_inv = float(il.get("unit_cost") or 0)
            c_po = float(pl.get("unit_cost") or 0)
        except (TypeError, ValueError):
            res["status"] = "unreadable"
            res["problems"].append("Unreadable quantity or price — blocks posting")
            issues.append(f"Line '{res['line']}': unreadable qty/price")
            line_results.append(res)
            continue
        if q_inv > q_recv + 1e-9:
            res["status"] = "exception"
            res["problems"].append(f"Invoiced qty {q_inv:g} exceeds received qty {q_recv:g}")
            issues.append(f"Line '{res['line']}': invoiced {q_inv:g} > received {q_recv:g}")
        if q_inv > q_ord + 1e-9:
            res["status"] = "exception"
            res["problems"].append(f"Invoiced qty {q_inv:g} exceeds ordered qty {q_ord:g}")
            issues.append(f"Line '{res['line']}': invoiced {q_inv:g} > ordered {q_ord:g}")
        if c_po and abs(c_inv - c_po) > max(tolerance_abs, c_po * tolerance_pct / 100.0):
            res["status"] = "exception"
            res["problems"].append(f"Unit cost {c_inv:.2f} outside tolerance of PO cost {c_po:.2f}")
            issues.append(f"Line '{res['line']}': cost {c_inv:.2f} vs PO {c_po:.2f}")
        line_results.append(res)
    try:
        inv_total = float(inv_vals.get("total") or 0)
    except (TypeError, ValueError):
        inv_total = 0.0
    if po_total and inv_total and abs(inv_total - po_total) > max(
            tolerance_abs, po_total * tolerance_pct / 100.0):
        issues.append(f"Invoice total {inv_total:.2f} differs from PO total {po_total:.2f} "
                      "beyond tolerance")
    return {"matched": not issues, "issues": issues, "lines": line_results,
            "tolerance_pct": tolerance_pct, "tolerance_abs": tolerance_abs}


def match_invoice(db, user_id: str, inv) -> dict:
    """DB wrapper: loads the linked PO (with its receiving state) and runs
    three_way_match on the invoice's merged (extracted+corrected) values."""
    from .db import PurchaseOrder
    vals = merged_values(inv)
    po = None
    if inv.po_id:
        po = (db.query(PurchaseOrder)
              .filter(PurchaseOrder.id == inv.po_id, PurchaseOrder.user_id == user_id).first())
    if not po:
        return {"matched": False, "issues": ["No purchase order linked — link a PO or "
                                             "treat as invoice-only expense"], "lines": []}
    r = three_way_match(vals, json.loads(po.lines or "[]"), float(po.total or 0))
    r["po_number"] = po.po_number
    r["po_status"] = po.status
    return r


# ------------------------------------------------------------
# MANDATORY human confirmation gate (spec §16) + posting (§20)
# ------------------------------------------------------------
def can_post(inv) -> str | None:
    """Return an error string when posting must be refused."""
    if inv.status == "posted":
        return "Invoice is already posted."
    try:
        confirmed = set(json.loads(inv.fields_confirmed or "[]"))
    except Exception:
        confirmed = set()
    missing = [f for f in REQUIRED_FIELDS if f not in confirmed]
    if missing:
        return ("Human verification incomplete — the following required fields are not "
                "confirmed yet: " + ", ".join(missing) +
                ". Every invoice requires field-by-field human review; AI confidence "
                "never bypasses verification.")
    if (inv.confirm_statement or "").strip() != REQUIRED_STATEMENT:
        return ("The confirmation statement has not been signed. The reviewer must check: "
                f"\u201c{REQUIRED_STATEMENT}\u201d")
    return None


def post_invoice(db, user_id: str, inv, account: str = "") -> dict:
    """Create the balanced AP journal entry (Debit Inventory/Expense; Credit
    Accounts Payable). Refuses unless can_post() passes. Idempotent via
    inv.journal_id."""
    err = can_post(inv)
    if err:
        raise ValueError(err)
    if inv.journal_id:
        return {"journal_id": inv.journal_id, "idempotent": True}
    vals = merged_values(inv)
    total = float(vals.get("total") or 0)
    tax = float(vals.get("tax") or 0)
    freight = float(vals.get("freight") or 0)
    net = round(total - tax - freight, 2)
    debit_acct = account or vals.get("account") or "5000 Cost of Goods Sold"
    lines = [{"account": debit_acct, "debit": net, "credit": 0, "memo": "Invoice net"},
             *([{"account": "2200 Sales Tax Payable", "debit": tax, "credit": 0, "memo": "Tax"}] if tax else []),
             *([{"account": "6300 Freight In", "debit": freight, "credit": 0, "memo": "Freight"}] if freight else []),
             {"account": "2000 Accounts Payable", "debit": 0, "credit": total, "memo": f"AP — {vals.get('vendor', '')} {vals.get('invoice_number', '')}"}]
    from .accounting import create_journal
    je = create_journal(db, user_id, lines, memo=f"Vendor invoice {vals.get('invoice_number', '')} — {vals.get('vendor', '')}",
                        source="purchasing", source_ref=inv.id, post=True)
    inv.journal_id = je.id
    inv.status = "posted"
    db.commit()
    return {"journal_id": je.id, "idempotent": False}
