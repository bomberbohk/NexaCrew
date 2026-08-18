# SPDX-License-Identifier: MIT
"""Operations Package — externalized company operations.

Covers: schema validation (happy + failure paths), atomic install /
export / revert via the API, module override in the workspace, and
record creation against a custom module."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_platform import client, dbmod  # noqa: E402 — shared throwaway DB

from app import ops_package  # noqa: E402
from app.db import BusinessProfile, User  # noqa: E402

VALID_PKG = {
    "schema": 1, "name": "Acme Ops", "version": "1.0.0",
    "modules": [
        {"key": "widget_qc", "name": "Widget QC Register", "iso": "9001 §8.6",
         "icon": "🔍", "grp": "A · QUALITY",
         "fields": [["serial", "Serial #", "text"],
                    ["result", "Result", "select:pass,fail"],
                    ["at", "Date", "date"]]},
    ],
}


def _admin_commercial():
    db = dbmod.SessionLocal()
    client.post("/api/auth/setup", json={"username": "tester", "password": "pass1234"})
    client.post("/api/auth/login", json={"username": "tester", "password": "pass1234"})
    user = db.query(User).filter(User.username == "tester").first()
    bp = db.query(BusinessProfile).filter(BusinessProfile.user_id == user.id).first()
    if not bp:
        bp = BusinessProfile(user_id=user.id)
        db.add(bp)
    bp.usage_mode = "commercial"
    bp.company_type = "restaurant"
    db.commit()
    return db, user


# ---------------- validation (no I/O) ----------------
def test_validate_accepts_good_package():
    assert ops_package.validate_package(VALID_PKG) == []


def test_validate_rejects_bad_packages():
    assert ops_package.validate_package("nope")
    assert ops_package.validate_package({"schema": 1, "name": "x", "modules": []})
    bad_key = {**VALID_PKG, "modules": [{**VALID_PKG["modules"][0], "key": "Bad-Key!"}]}
    assert any("key" in e for e in ops_package.validate_package(bad_key))
    bad_type = {**VALID_PKG, "modules": [
        {**VALID_PKG["modules"][0], "fields": [["a", "A", "wibble"]]}]}
    assert any("wibble" in e for e in ops_package.validate_package(bad_type))
    dup = {**VALID_PKG, "modules": [VALID_PKG["modules"][0], VALID_PKG["modules"][0]]}
    assert any("duplicate" in e for e in ops_package.validate_package(dup))


# ---------------- API lifecycle ----------------
def test_install_overrides_operations_and_revert_restores():
    db, user = _admin_commercial()
    try:
        # starter shown before install
        r = client.get("/api/business/ops-package")
        assert r.status_code == 200 and r.json()["installed"] is False

        r = client.post("/api/business/ops-package", json={"package": VALID_PKG})
        assert r.status_code == 200, r.text
        assert r.json()["package"]["name"] == "Acme Ops"

        ws = client.get("/api/business/workspace").json()
        keys = {m["key"] for m in ws["modules"]}
        assert "widget_qc" in keys              # custom operations active
        assert "haccp_temp" not in keys         # built-in restaurant ops replaced
        assert "workers" in keys and "ledger" in keys   # universal core kept
        assert ws["ops_package"]["name"] == "Acme Ops"

        # records can be created in the custom module
        r = client.post("/api/business/records",
                        json={"module": "widget_qc",
                              "data": {"serial": "SN-1", "result": "pass"}})
        assert r.status_code == 200, r.text

        # invalid packages are rejected atomically (422, old package kept)
        r = client.post("/api/business/ops-package",
                        json={"package": {"schema": 1, "name": "", "modules": []}})
        assert r.status_code == 422
        assert client.get("/api/business/ops-package").json()["installed"] is True

        r = client.delete("/api/business/ops-package")
        assert r.status_code == 200 and r.json()["removed"] is True
        ws = client.get("/api/business/workspace").json()
        keys = {m["key"] for m in ws["modules"]}
        assert "haccp_temp" in keys and "widget_qc" not in keys
        assert ws["ops_package"] is None
    finally:
        ops_package.delete_package(user.id)
        db.close()


def test_builtin_starter_export():
    pkg = ops_package.builtin_as_package("restaurant")
    assert pkg and ops_package.validate_package(pkg) == []
    assert any(m["key"] == "haccp_temp" for m in pkg["modules"])
    assert ops_package.builtin_as_package("no_such_type") is None


def test_worker_account_shares_company_workspace():
    """Non-admin worker accounts (HR-provisioned) must see and operate the
    company owner's Operations workspace — not an empty personal one."""
    db, owner = _admin_commercial()
    try:
        # owner creates a record in a shared register
        r = client.post("/api/business/records",
                        json={"module": "supplier",
                              "data": {"name": "Fresh Farms", "category": "produce"}})
        assert r.status_code == 200, r.text
        # provision a non-admin worker directly (as HR enrollment does)
        from app.security import hash_password
        from app.db import User
        w = db.query(User).filter(User.username == "worker1").first()
        if not w:
            w = User(username="worker1", display_name="Worker One",
                     password_hash=hash_password("workerpass1"), is_admin=False)
            db.add(w)
            db.commit()
        client.post("/api/auth/login", json={"username": "worker1",
                                             "password": "workerpass1"})
        ws = client.get("/api/business/workspace").json()
        assert ws["active"] is True                  # sees the company workspace
        assert any(m["key"] == "supplier" for m in ws["modules"])
        rows = client.get("/api/business/records?module=supplier").json()
        assert any(r0["data"].get("name") == "Fresh Farms" for r0 in rows)
        # worker can create a record into the SHARED tenant
        r = client.post("/api/business/records",
                        json={"module": "supplier",
                              "data": {"name": "Vista Foods", "category": "dry"}})
        assert r.status_code == 200, r.text
        # …and the owner sees it
        client.post("/api/auth/login", json={"username": "tester",
                                             "password": "pass1234"})
        rows = client.get("/api/business/records?module=supplier").json()
        assert any(r0["data"].get("name") == "Vista Foods" for r0 in rows)
        # ops studio remains admin-only
        client.post("/api/auth/login", json={"username": "worker1",
                                             "password": "workerpass1"})
        assert client.get("/api/business/ops-package").status_code == 403
        client.post("/api/auth/login", json={"username": "tester",
                                             "password": "pass1234"})
    finally:
        db.close()


def test_starter_is_single_company_build_package():
    pkg = ops_package.builtin_as_package("restaurant", "Acme Supplies",
                                         "Custom ops doctrine.")
    assert pkg["name"] == "ACME SUPPLIES BUILD"
    assert pkg["chat_prompt"] == "Custom ops doctrine."


def test_package_chat_prompt_governs_chat_injection():
    from app import services
    db, user = _admin_commercial()
    try:
        pkg = {**VALID_PKG, "chat_prompt": "SPEAK AS ACME OPS DOCTRINE."}
        r = client.post("/api/business/ops-package", json={"package": pkg})
        assert r.status_code == 200, r.text
        block = services._business_block(db, user.id)
        assert "SPEAK AS ACME OPS DOCTRINE." in block
        assert "Operations Package 'Acme Ops'" in block
        # oversized / wrong-typed chat_prompt rejected
        bad = {**VALID_PKG, "chat_prompt": "x" * 20001}
        assert client.post("/api/business/ops-package",
                           json={"package": bad}).status_code == 422
    finally:
        ops_package.delete_package(user.id)
        db.close()
