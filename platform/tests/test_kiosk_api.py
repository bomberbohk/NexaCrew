# SPDX-License-Identifier: MIT
"""End-to-end tests: POS Kiosk Client device-token API (spec §3.2/§7),
three-way matching endpoint (§18) and Cash Flow report (§10.3).
Reuses the isolated test database bootstrapped by test_platform."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# bootstrap the shared throwaway DB / TestClient exactly like test_platform
from test_platform import client  # noqa: E402  (import side effects set up the app)


def setup_module():
    # login (idempotent — setup may already have run in this session)
    client.post("/api/auth/setup", json={"username": "tester", "password": "pass1234"})
    r = client.post("/api/auth/login", json={"username": "tester", "password": "pass1234"})
    assert r.status_code == 200
    # commercial restaurant → POS enabled
    r = client.put("/api/business/profile",
                   json={"usage_mode": "commercial", "company_type": "restaurant",
                         "company_name": "Testaurant"})
    assert r.status_code == 200


def _mk_kiosk():
    r = client.post("/api/pos/objects/kiosk",
                    json={"name": "Front Kiosk", "data": {"name": "Front Kiosk",
                                                          "location": "Main"}})
    assert r.status_code == 200
    out = r.json()
    assert out["device_token"].startswith("kiosk-")
    return out


def test_kiosk_handshake_and_isolation():
    k = _mk_kiosk()
    # valid token → configuration limited to this business
    r = client.post("/api/kiosk/handshake", json={"token": k["device_token"]})
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["business"]["type"] == "restaurant"
    assert cfg["kiosk"]["id"] == k["id"]
    assert "zones" in cfg and "sub_items" not in cfg  # restaurant-scoped config
    # bad token → 401, no data leak
    assert client.post("/api/kiosk/handshake", json={"token": "kiosk-forged"}).status_code == 401
    assert client.post("/api/kiosk/handshake", json={"token": ""}).status_code == 401


def test_kiosk_token_revocation_blocks_access():
    k = _mk_kiosk()
    old = k["device_token"]
    r = client.put(f"/api/pos/objects/{k['id']}", json={"revoke_token": True})
    assert r.status_code == 200
    assert client.post("/api/kiosk/handshake", json={"token": old}).status_code == 401


def test_kiosk_deactivation_blocks_access():
    k = _mk_kiosk()
    client.put(f"/api/pos/objects/{k['id']}", json={"active": False})
    assert client.post("/api/kiosk/handshake",
                       json={"token": k["device_token"]}).status_code == 401


def test_kiosk_order_idempotency():
    k = _mk_kiosk()
    order = {"token": k["device_token"], "idempotency_key": "abc-123",
             "order_type": "dine-in",
             "lines": [{"name": "Burger", "qty": 2, "price": 9.50}]}
    r1 = client.post("/api/kiosk/orders", json=order).json()
    r2 = client.post("/api/kiosk/orders", json=order).json()  # network retry
    assert r1["order_id"] == r2["order_id"]
    assert r2["idempotent"] is True
    assert r1["total"] == 19.0
    # missing idempotency key is rejected
    bad = dict(order)
    bad.pop("idempotency_key")
    assert client.post("/api/kiosk/orders", json=bad).status_code == 422
    # forged token cannot order
    assert client.post("/api/kiosk/orders",
                       json={**order, "token": "kiosk-x"}).status_code == 401


def test_cashflow_report_endpoint():
    # post one cash expense: Debit Utilities / Credit Bank
    r = client.post("/api/accounting/journals",
                    json={"memo": "Power bill", "post": True,
                          "lines": [{"account": "6100 Utilities", "debit": 120, "credit": 0},
                                    {"account": "1010 Bank Account", "debit": 0, "credit": 120}]})
    assert r.status_code == 200
    import datetime as dt
    cf = client.get(f"/api/accounting/reports/cashflow?year={dt.date.today().year}").json()
    assert cf["operating"] <= -120.0
    assert cf["ending_cash"] == cf["beginning_cash"] + cf["net_change"]
    assert any(d["activity"] == "operating" for d in cf["detail"])


def test_invoice_match_endpoint_requires_po():
    # upload a simple text invoice, then request three-way match without a PO
    files = {"file": ("inv.txt", b"Invoice No: T-1\nTotal: $10.00", "text/plain")}
    inv = client.post("/api/purchasing/invoices", files=files).json()
    r = client.get(f"/api/purchasing/invoices/{inv['id']}/match")
    assert r.status_code == 200
    out = r.json()
    assert out["matched"] is False
    assert any("purchase order" in i.lower() for i in out["issues"])


def test_kiosk_heartbeat_and_status_board():
    k = _mk_kiosk()
    # before any heartbeat/handshake data → never (unless handshake set last_online)
    st = client.get("/api/pos/kiosks/status").json()
    mine = next(x for x in st["kiosks"] if x["id"] == k["id"])
    assert mine["status"] in ("never", "online")
    # heartbeat → online with client metadata
    r = client.post("/api/kiosk/heartbeat",
                    json={"token": k["device_token"], "version": "kiosk-client/1.0"})
    assert r.status_code == 200
    st = client.get("/api/pos/kiosks/status").json()
    mine = next(x for x in st["kiosks"] if x["id"] == k["id"])
    assert mine["status"] == "online"
    assert mine["age_seconds"] <= 60
    assert mine["client_version"] == "kiosk-client/1.0"
    assert st["online"] >= 1
    # forged token heartbeat rejected
    assert client.post("/api/kiosk/heartbeat", json={"token": "kiosk-x"}).status_code == 401


def test_kiosk_status_counts_todays_orders():
    k = _mk_kiosk()
    client.post("/api/kiosk/orders",
                json={"token": k["device_token"], "idempotency_key": "st-1",
                      "lines": [{"name": "Tea", "qty": 1, "price": 3.0}]})
    st = client.get("/api/pos/kiosks/status").json()
    mine = next(x for x in st["kiosks"] if x["id"] == k["id"])
    assert mine["orders_today"] == 1


def test_kiosk_client_page_served():
    r = client.get("/kiosk")
    assert r.status_code == 200
    assert "POS Kiosk Client" in r.text
    assert "/api/kiosk/handshake" in r.text


def test_kiosk_token_visible_in_admin_list():
    k = _mk_kiosk()
    rows = client.get("/api/pos/objects/kiosk").json()
    mine = next(x for x in rows if x["id"] == k["id"])
    # owner requested the token be visible to the authenticated POS admin
    assert mine["device_token"] == k["device_token"]
    # but never to an unauthenticated caller
    from fastapi.testclient import TestClient
    from app.main import app as _app
    anon = TestClient(_app)
    assert anon.get("/api/pos/objects/kiosk").status_code == 401
