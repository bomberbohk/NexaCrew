# SPDX-License-Identifier: MIT
"""Tests for the POS / Purchasing / Accounting ERP layer (spec §25)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from app import accounting, pos, purchasing
from app.i18n_intents import normalize_intent_text


# ---------- business-type-aware navigation ----------
def test_pos_only_for_restaurant_supermarket():
    assert pos.pos_enabled("restaurant")
    assert pos.pos_enabled("supermarket")
    assert not pos.pos_enabled("trucking")
    assert not pos.pos_enabled("")
    assert pos.navigation_for("clinic") == {"pos": False, "sections": []}


def test_restaurant_vs_supermarket_kinds():
    r = set(pos.kinds_for("restaurant"))
    s = set(pos.kinds_for("supermarket"))
    assert {"option_group", "zone", "table", "structure"} <= r
    assert not {"option_group", "zone", "table", "structure"} & s
    assert {"sub_item", "department"} <= s
    assert not {"sub_item", "department"} & r
    # shared
    for k in ("category", "item", "kiosk", "printer", "drawer", "pos_account", "order"):
        assert k in r and k in s


def test_structure_in_restaurant_navigation():
    nav = pos.navigation_for("restaurant")
    kinds = [i["kind"] for sec in nav["sections"] for i in sec["items"]]
    assert "structure" in kinds
    assert kinds.index("zone") < kinds.index("structure") < kinds.index("table")


def test_drawer_manual_open_requires_reason():
    assert pos.validate_drawer_event({"action": "manual open", "reason": ""}) is not None
    assert pos.validate_drawer_event({"action": "manual open", "reason": "till count"}) is None
    assert pos.validate_drawer_event({"action": "auto open (cash sale)"}) is None


def test_kiosk_token_unique():
    assert pos.new_kiosk_token() != pos.new_kiosk_token()
    assert pos.new_kiosk_token().startswith("kiosk-")


# ---------- accounting: balanced double-entry ----------
def test_journal_validation_balanced():
    assert accounting._validate_lines([
        {"account": "6100 Utilities", "debit": 250, "credit": 0},
        {"account": "1010 Bank", "debit": 0, "credit": 250}]) == (250.0, 250.0)


def test_journal_validation_rejects_unbalanced():
    with pytest.raises(ValueError):
        accounting._validate_lines([
            {"account": "6100", "debit": 250, "credit": 0},
            {"account": "1010", "debit": 0, "credit": 200}])
    with pytest.raises(ValueError):  # debit AND credit on one line
        accounting._validate_lines([
            {"account": "6100", "debit": 10, "credit": 10},
            {"account": "1010", "debit": 0, "credit": 0}])
    with pytest.raises(ValueError):  # single line
        accounting._validate_lines([{"account": "6100", "debit": 10, "credit": 0}])


# ---------- invoice verification is mandatory ----------
class _FakeInv:
    def __init__(self, confirmed, statement):
        self.status = "ai review required"
        self.fields_confirmed = json.dumps(confirmed)
        self.confirm_statement = statement
        self.journal_id = ""


def test_invoice_cannot_post_without_confirmation():
    err = purchasing.can_post(_FakeInv([], ""))
    assert err and "verification incomplete" in err.lower()


def test_invoice_cannot_post_without_statement():
    inv = _FakeInv(purchasing.REQUIRED_FIELDS, "")
    err = purchasing.can_post(inv)
    assert err and "statement" in err.lower()


def test_invoice_posts_only_when_fully_confirmed():
    inv = _FakeInv(purchasing.REQUIRED_FIELDS, purchasing.REQUIRED_STATEMENT)
    assert purchasing.can_post(inv) is None


def test_heuristic_extract_never_invents():
    doc = purchasing._heuristic_extract("")
    f = doc["fields"]
    assert f["invoice_number"]["confidence"] == "missing"
    assert f["total"]["confidence"] == "missing"
    assert doc["warnings"]  # image warning present


def test_heuristic_extract_reads_totals():
    text = "INVOICE No: INV-1001\nDate: 2026/08/01\nSubtotal: $100.00\nTax: $8.25\nTotal: $108.25"
    f = purchasing._heuristic_extract(text)["fields"]
    assert f["invoice_number"]["value"] == "INV-1001"
    assert f["total"]["value"] == "108.25"


# ---------- multilingual chat control ----------
def test_pos_intent_english():
    for t in ("add a new appetizer category", "list tables", "show vendors",
              "profit and loss", "export tax report as xlsx"):
        assert pos.POS_INTENT.search(normalize_intent_text(t)), t


def test_pos_intent_chinese():
    cases = {"新增菜單分類": "category", "列出餐桌": "table", "顯示供應商發票": "vendor invoice",
             "損益表": "profit and loss", "資產負債表": "balance sheet",
             "現金流量表": "cash flow", "现金流量表": "cash flow"}
    for zh, en in cases.items():
        n = normalize_intent_text(zh)
        assert en in n.lower(), f"{zh} -> {n}"
        assert pos.POS_INTENT.search(n), f"{zh} -> {n}"


def test_pos_intent_spanish_cashflow():
    n = normalize_intent_text("muéstrame el flujo de caja")
    assert "cash flow" in n.lower()
    assert pos.POS_INTENT.search(n)


def test_bulk_invoice_approval_blocked_pattern():
    assert pos._BULK_INVOICE.search("approve all invoices")
    assert pos._BULK_INVOICE.search("post invoices")


# ---------- three-way matching (spec §18) ----------
_PO_LINES = [{"sku": "TOM-1", "desc": "Tomatoes", "qty": 10, "unit_cost": 2.00, "received": 10},
             {"sku": "ONI-1", "desc": "Onions", "qty": 5, "unit_cost": 1.00, "received": 3}]


def test_three_way_match_ok():
    inv = {"total": 20.00,
           "lines": [{"sku": "TOM-1", "desc": "Tomatoes", "qty": 10, "unit_cost": 2.00}]}
    r = purchasing.three_way_match(inv, _PO_LINES, po_total=0)
    assert r["matched"], r["issues"]


def test_three_way_match_flags_over_invoicing():
    inv = {"lines": [{"sku": "ONI-1", "qty": 5, "unit_cost": 1.00}]}  # only 3 received
    r = purchasing.three_way_match(inv, _PO_LINES)
    assert not r["matched"]
    assert any("received" in i for i in r["issues"])


def test_three_way_match_flags_price_variance():
    inv = {"lines": [{"sku": "TOM-1", "qty": 10, "unit_cost": 2.50}]}  # PO cost 2.00, tol 2%
    r = purchasing.three_way_match(inv, _PO_LINES)
    assert not r["matched"]
    assert any("cost" in i.lower() for i in r["issues"])


def test_three_way_match_unreadable_blocks():
    inv = {"lines": [{"sku": "TOM-1", "qty": "??", "unit_cost": 2.00}]}
    r = purchasing.three_way_match(inv, _PO_LINES)
    assert not r["matched"]
    assert r["lines"][0]["status"] == "unreadable"


def test_three_way_match_unknown_line():
    inv = {"lines": [{"sku": "XXX-9", "qty": 1, "unit_cost": 1.00}]}
    r = purchasing.three_way_match(inv, _PO_LINES)
    assert not r["matched"]
    assert r["lines"][0]["status"] == "no_po_line"


# ---------- cash flow classification (spec §10.3) ----------
def test_cash_account_detection():
    types = {"1010": "asset", "1010 Bank Checking": "asset", "2000": "liability",
             "2000 Cash Back Liability": "liability"}
    assert accounting.is_cash_account("1010 Bank Checking", types)
    assert not accounting.is_cash_account("2000 Cash Back Liability", types)  # not an asset
    assert not accounting.is_cash_account("1200 Inventory Asset", {"1200": "asset"})


def test_cash_activity_classification():
    types = {"1500": "asset", "3000": "equity", "6100": "expense", "2500": "liability"}
    assert accounting.classify_cash_activity(["1500 Fixed Asset Equipment"], types) == "investing"
    assert accounting.classify_cash_activity(["3000 Owner Equity"], types) == "financing"
    assert accounting.classify_cash_activity(["2500 Bank Loan Payable"], types) == "financing"
    assert accounting.classify_cash_activity(["6100 Utilities"], types) == "operating"
