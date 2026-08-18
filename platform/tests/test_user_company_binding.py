"""User ↔ company binding: User Management assigns a worker to a deployed
company (their Operations menu shows only that company); administrators can
act-as any company on the server via /api/business/act-as."""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("NEXACREW_TESTING", "1")

WORKER1 = "bindworker1_" + uuid.uuid4().hex[:8]
WORKER2 = "bindworker2_" + uuid.uuid4().hex[:8]

from fastapi.testclient import TestClient  # noqa: E402

from app.db import BusinessProfile, SessionLocal, User, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.business import biz_owner_id  # noqa: E402

client = TestClient(app)
init_db()


def _ensure_admin():
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "bindadmin").first()
        if not u:
            u = User(username="bindadmin", display_name="Bind Admin",
                     password_hash=hash_password("pass1234"), is_admin=True)
            db.add(u)
            db.commit()
        bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == u.id).first()
        if not bp:
            bp = BusinessProfile(user_id=u.id)
            db.add(bp)
        bp.usage_mode = "commercial"
        bp.company_type = "restaurant"
        bp.company_name = "Bind Co A"
        db.commit()
        return u.id
    finally:
        db.close()


def _login():
    r = client.post("/api/auth/login", json={"username": "bindadmin", "password": "pass1234"})
    assert r.status_code == 200, r.text


def test_create_user_with_company_binding_and_act_as():
    owner_id = _ensure_admin()
    _login()

    # invalid company rejected
    r = client.post("/api/users", json={"username": WORKER1, "password": "workerpass1",
                                        "company_owner_id": "no-such-owner"})
    assert r.status_code == 400

    # bind worker to the deployed company
    r = client.post("/api/users", json={"username": WORKER1, "password": "workerpass1",
                                        "company_owner_id": owner_id})
    assert r.status_code == 200, r.text
    w = r.json()
    assert w["company_owner_id"] == owner_id

    # tenant resolution: worker operates on the bound company workspace
    db = SessionLocal()
    try:
        assert biz_owner_id(db, w["id"]) == owner_id
    finally:
        db.close()

    # unbind via update
    r = client.put(f"/api/users/{w['id']}", json={"company_owner_id": ""})
    assert r.status_code == 200
    assert r.json()["company_owner_id"] == ""

    # admin can act-as any deployed company, then return to own workspace
    r = client.post("/api/business/act-as", json={"owner_id": owner_id})
    assert r.status_code == 200
    assert r.json()["acting_company_owner_id"] == owner_id
    r = client.post("/api/business/act-as", json={"owner_id": ""})
    assert r.status_code == 200
    assert r.json()["acting_company_owner_id"] == ""


def test_bound_worker_sees_employer_virtual_company():
    """Regression: the Companies page (Virtual Company registry) must show
    companies already set up on the server for a worker bound to their
    employer via company_owner_id — not an empty 'no companies' list."""
    owner_id = _ensure_admin()
    _login()

    r = client.post("/api/companies", json={"name": "Bind Co A HQ"})
    assert r.status_code == 200, r.text
    company = r.json()
    assert company["owner_user_id"] == owner_id

    worker = "bindworker3_" + uuid.uuid4().hex[:8]
    r = client.post("/api/users", json={"username": worker, "password": "workerpass1",
                                        "company_owner_id": owner_id})
    assert r.status_code == 200, r.text

    r = client.post("/api/auth/login", json={"username": worker, "password": "workerpass1"})
    assert r.status_code == 200, r.text

    r = client.get("/api/companies")
    assert r.status_code == 200, r.text
    ids = [c["id"] for c in r.json()]
    assert company["id"] in ids


def test_act_as_requires_admin():
    _ensure_admin()
    _login()
    r = client.post("/api/users", json={"username": WORKER2, "password": "workerpass2"})
    assert r.status_code == 200
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": WORKER2, "password": "workerpass2"})
    assert r.status_code == 200
    r = client.post("/api/business/act-as", json={"owner_id": "anything"})
    assert r.status_code == 403
    client.post("/api/auth/logout")
