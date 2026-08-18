# SPDX-License-Identifier: MIT
"""Multi-company licensing & tenant isolation.

When a server hosts MORE THAN ONE commercial company, each company must be
bound to its own license key before its Operations workspace unlocks.
HR Employee Enrollment binds each worker to a specific company; the worker's
login only sees that company's operations and data.

Single-company servers are grandfathered — no key required (regression
guarded implicitly by every other test file running unlicensed)."""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_platform import client, dbmod  # noqa: E402 — shared throwaway DB

from app.db import BusinessProfile, LicenseKey, User  # noqa: E402
from app.security import hash_password  # noqa: E402


def _login(u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text


def _mk_admin_company(db, username, company_name):
    u = db.query(User).filter(User.username == username).first()
    if not u:
        u = User(username=username, display_name=username,
                 password_hash=hash_password("pass1234"), is_admin=True)
        db.add(u)
        db.commit()
    bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == u.id).first()
    if not bp:
        bp = BusinessProfile(user_id=u.id)
        db.add(bp)
    bp.usage_mode = "commercial"
    bp.company_type = "restaurant"
    bp.company_name = company_name
    db.commit()
    return u, bp


def _mk_key(db, note):
    key = "LIC-" + uuid.uuid4().hex[:20].upper()
    db.add(LicenseKey(key=key, note=note))
    db.commit()
    return key


def test_multicompany_license_enforcement_and_worker_isolation():
    db = dbmod.SessionLocal()
    client.post("/api/auth/setup", json={"username": "tester", "password": "pass1234"})
    _login("tester", "pass1234")
    owner_a, bp_a = _mk_admin_company(db, "tester", "Alpha Corp")
    owner_b, bp_b = _mk_admin_company(db, "licadmin2", "Beta Corp")
    try:
        # --- two commercial companies → license enforcement kicks in ---
        ws = client.get("/api/business/workspace").json()
        assert ws["active"] is False and ws.get("license_required") is True
        assert ws["is_owner"] is True
        r = client.post("/api/business/records",
                        json={"module": "supplier", "data": {"name": "X"}})
        assert r.status_code == 403

        # --- bind key A → Alpha unlocks; duplicate bind by Beta → 409 ---
        key_a = _mk_key(db, "alpha")
        assert client.post("/api/business/license",
                           json={"key": "NOPE"}).status_code == 400
        assert client.post("/api/business/license",
                           json={"key": key_a}).status_code == 200
        ws = client.get("/api/business/workspace").json()
        assert ws["active"] is True and ws["license"]["valid"] is True
        assert ws["license"]["enforced"] is True

        _login("licadmin2", "pass1234")
        assert client.post("/api/business/license",
                           json={"key": key_a}).status_code == 409
        key_b = _mk_key(db, "beta")
        assert client.post("/api/business/license",
                           json={"key": key_b}).status_code == 200
        assert client.get("/api/business/workspace").json()["active"] is True

        # --- company list for the HR picker ---
        cos = client.get("/api/business/companies").json()
        names = {c["company_name"]: c for c in cos}
        assert "Alpha Corp" in names and "Beta Corp" in names
        assert names["Beta Corp"]["mine"] is True
        assert names["Alpha Corp"]["licensed"] is True

        # --- Alpha owner writes a record; then enrolls a worker INTO Beta ---
        _login("tester", "pass1234")
        r = client.post("/api/business/records",
                        json={"module": "supplier",
                              "data": {"name": "Alpha Farms"}})
        assert r.status_code == 200, r.text
        r = client.post("/api/business/records",
                        json={"module": "workers",
                              "data": {"name": "Beta Worker",
                                       "company_owner": owner_b.id,
                                       "login_username": "bworker1",
                                       "login_password": "workerpass1",
                                       "face_photo": "face_test.jpg"}})
        assert r.status_code == 200, r.text
        assert r.json()["user_created"] == "bworker1"

        # worker record landed in BETA's register, not Alpha's
        db.expire_all()
        w = db.query(User).filter(User.username == "bworker1").first()
        assert w is not None and w.company_owner_id == owner_b.id

        # --- worker login sees ONLY Beta's workspace/data ---
        _login("bworker1", "workerpass1")
        ws = client.get("/api/business/workspace").json()
        assert ws["active"] is True and ws["company_name"] == "Beta Corp"
        rows = client.get("/api/business/records?module=supplier").json()
        assert not any(r0["data"].get("name") == "Alpha Farms" for r0 in rows)

        # enrolling into a nonexistent company is rejected
        _login("tester", "pass1234")
        r = client.post("/api/business/records",
                        json={"module": "workers",
                              "data": {"name": "Ghost",
                                       "company_owner": "no-such-owner",
                                       "login_username": "ghost1",
                                       "login_password": "workerpass1",
                                       "face_photo": "face_test.jpg"}})
        assert r.status_code == 422
    finally:
        # restore single-company world so later test files stay unlicensed
        _login("tester", "pass1234")
        db.expire_all()
        bp_b = db.query(BusinessProfile).filter(
            BusinessProfile.user_id == owner_b.id).first()
        if bp_b:
            bp_b.usage_mode = "personal"
            bp_b.license_key = ""
        bp_a = db.query(BusinessProfile).filter(
            BusinessProfile.user_id == owner_a.id).first()
        if bp_a:
            bp_a.license_key = ""
        db.commit()
        db.close()
