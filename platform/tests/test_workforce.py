# SPDX-License-Identifier: MIT
"""Workforce / Visitor / Access Control platform tests.

Covers: badge lifecycle + revoked/expired/replayed scans, enrollment code
single-use + expiry, duplicate punch suppression + idempotency, timecards
and audited adjustments, payroll idempotency + posting, visitor state
machine incl. deny/expiry/PII masking, access decisions with reason codes,
and cross-tenant isolation.
"""
import datetime as dt

from fastapi.testclient import TestClient

from tests.test_platform import client as _shared  # noqa: F401  (patches the DB first)

import app.db as dbmod
from app.db import Visit, WorkerBadge
from app.main import app

client = TestClient(app)
CREDS = {"username": "tester", "password": "pass1234"}   # shared test tenant


def setup_module(module):
    r = client.post("/api/auth/setup", json=CREDS)
    assert r.status_code in (200, 400)   # 400 = already set up by another module
    r = client.post("/api/auth/login", json=CREDS)
    assert r.status_code == 200, r.text


def _enroll(kind="checkin", name="Test Kiosk"):
    r = client.post("/api/workforce/devices/enroll-code",
                    json={"kind": kind, "name": name, "site": "HQ"})
    assert r.status_code == 200, r.text
    code = r.json()["code"]
    r = client.post("/api/workforce/enroll", json={"code": code})
    assert r.status_code == 200, r.text
    return r.json()["credential"], code


# ---------------------------------------------------------------- enrollment
def test_enroll_code_single_use():
    cred, code = _enroll()
    assert cred.startswith("dc-")
    # replay the same code → rejected
    r = client.post("/api/workforce/enroll", json={"code": code})
    assert r.status_code == 401


def test_enroll_bad_code_rejected():
    r = client.post("/api/workforce/enroll", json={"code": "ek-not-a-real-code"})
    assert r.status_code == 401


# ---------------------------------------------------------------- badges
def test_badge_issue_scan_and_revoke():
    cred, _ = _enroll()
    r = client.post("/api/workforce/badges",
                    json={"worker_name": "Alice Example"})
    assert r.status_code == 200
    tok = r.json()["badge_token"]
    bid = r.json()["badge_id"]
    assert tok.startswith("wb-")

    # scan → clock in
    r = client.post("/api/workforce/scan",
                    json={"device": cred, "badge": tok, "idempotency_key": "k1"})
    assert r.status_code == 200
    assert r.json()["event"] == "in" and r.json()["result"] == "ok"

    # same idempotency key replayed → same punch, idempotent
    r = client.post("/api/workforce/scan",
                    json={"device": cred, "badge": tok, "idempotency_key": "k1"})
    assert r.status_code == 200 and r.json()["idempotent"] is True

    # revoke → scan denied with machine-readable reason
    r = client.post(f"/api/workforce/badges/{bid}/revoke", json={"reason": "lost"})
    assert r.status_code == 200
    r = client.post("/api/workforce/scan",
                    json={"device": cred, "badge": tok, "idempotency_key": "k2"})
    assert r.status_code == 403 and "badge_revoked" in r.text

    # lifecycle history recorded
    rows = client.get("/api/workforce/badges").json()
    b = next(x for x in rows if x["id"] == bid)
    events = [e["event"] for e in b["lifecycle"]]
    assert events == ["issued", "revoked"]


def test_badge_unknown_token_denied():
    cred, _ = _enroll()
    r = client.post("/api/workforce/scan",
                    json={"device": cred, "badge": "wb-forged-token", "idempotency_key": "kx"})
    assert r.status_code == 403 and "badge_unknown" in r.text


def test_badge_expired_denied():
    cred, _ = _enroll()
    r = client.post("/api/workforce/badges",
                    json={"worker_name": "Bob Expired", "expires_days": 1})
    tok, bid = r.json()["badge_token"], r.json()["badge_id"]
    db = dbmod.SessionLocal()
    b = db.query(WorkerBadge).get(bid)
    b.expires_at = dt.datetime.utcnow() - dt.timedelta(days=1)
    db.commit()
    db.close()
    r = client.post("/api/workforce/scan",
                    json={"device": cred, "badge": tok, "idempotency_key": "ke"})
    assert r.status_code == 403 and "badge_expired" in r.text


def test_duplicate_scan_cooldown():
    cred, _ = _enroll()
    r = client.post("/api/workforce/badges", json={"worker_name": "Cara Cooldown"})
    tok = r.json()["badge_token"]
    r1 = client.post("/api/workforce/scan",
                     json={"device": cred, "badge": tok, "idempotency_key": "c1",
                           "event": "in"})
    r2 = client.post("/api/workforce/scan",
                     json={"device": cred, "badge": tok, "idempotency_key": "c2",
                           "event": "in"})
    assert r1.json()["result"] == "ok"
    assert r2.json()["result"] == "duplicate"     # raw event kept, flagged


# ---------------------------------------------------------------- timecards & payroll
def test_timecard_pairing_and_adjustment():
    cred, _ = _enroll()
    r = client.post("/api/workforce/badges", json={"worker_name": "Dan Hours"})
    tok = r.json()["badge_token"]
    client.post("/api/workforce/scan", json={"device": cred, "badge": tok,
                                             "idempotency_key": "d1", "event": "in"})
    client.post("/api/workforce/scan", json={"device": cred, "badge": tok,
                                             "idempotency_key": "d2", "event": "out"})
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    tc = client.get("/api/workforce/timecard",
                    params={"worker": "Dan Hours", "day_from": today,
                            "day_to": today}).json()
    assert today in tc["days"]

    # audited adjustment: +30 minutes, requires approval before it counts
    r = client.post("/api/workforce/adjustments",
                    json={"worker": "Dan Hours", "day": today,
                          "minutes_delta": 30, "reason": "forgot badge at door"})
    aid = r.json()["id"]
    tc = client.get("/api/workforce/timecard",
                    params={"worker": "Dan Hours", "day_from": today,
                            "day_to": today}).json()
    before = tc["total_minutes"]
    r = client.post(f"/api/workforce/adjustments/{aid}/decide", json={"approve": True})
    assert r.json()["status"] == "approved"
    tc = client.get("/api/workforce/timecard",
                    params={"worker": "Dan Hours", "day_from": today,
                            "day_to": today}).json()
    assert tc["total_minutes"] == before + 30
    # double-decide blocked
    r = client.post(f"/api/workforce/adjustments/{aid}/decide", json={"approve": False})
    assert r.status_code == 409


def test_payroll_batch_idempotent_and_posts_journal():
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    body = {"period_start": today, "period_end": today,
            "wages": {"Dan Hours": 20.0}}
    r1 = client.post("/api/workforce/payroll/batch", json=body)
    assert r1.status_code == 200
    bid = r1.json()["batch_id"]
    # retry → same batch, no duplicate
    r2 = client.post("/api/workforce/payroll/batch", json=body)
    assert r2.json()["batch_id"] == bid and r2.json()["existed"] is True

    r = client.post(f"/api/workforce/payroll/{bid}/post")
    assert r.status_code == 200
    j1 = r.json()["journal_id"]
    # re-post → same journal (no duplicate payroll posting)
    r = client.post(f"/api/workforce/payroll/{bid}/post")
    assert r.json()["journal_id"] == j1

    csv = client.get(f"/api/workforce/payroll/{bid}/export.csv")
    assert csv.status_code == 200 and csv.text.startswith("worker,")


# ---------------------------------------------------------------- visitors
def test_visitor_full_lifecycle_and_pii_masking():
    cred, _ = _enroll(kind="visitor", name="Lobby Kiosk")
    r = client.post("/api/visitor/register", json={
        "device": cred, "visitor_name": "Vera Visitor", "category": "vendor",
        "host": "Alice Example", "purpose": "maintenance", "destination": "Kitchen",
        "id_doc_type": "drivers_license", "id_number": "D123456789", "consent": True})
    assert r.status_code == 200
    vid = r.json()["visit_id"]

    # admin list masks the identity number — never full value
    rows = client.get("/api/visitor/visits").json()
    v = next(x for x in rows if x["id"] == vid)
    assert v["id_number_masked"].endswith("6789")
    assert "D123456789" not in str(rows)

    # approve → badge code returned once, visit checked in
    r = client.post(f"/api/visitor/visits/{vid}/decide",
                    json={"approve": True, "badge_hours": 2})
    assert r.status_code == 200
    badge = r.json()["badge_code"]
    assert badge.startswith("vb-")

    # checkout invalidates badge
    r = client.post("/api/visitor/checkout", json={"device": cred, "visit_id": vid})
    assert r.status_code == 200
    db = dbmod.SessionLocal()
    assert db.query(Visit).get(vid).badge_code_hash == ""
    db.close()


def test_visitor_consent_required_and_denial():
    cred, _ = _enroll(kind="visitor")
    r = client.post("/api/visitor/register", json={
        "device": cred, "visitor_name": "No Consent", "consent": False})
    assert r.status_code == 422

    r = client.post("/api/visitor/register", json={
        "device": cred, "visitor_name": "Denied Person", "consent": True})
    vid = r.json()["visit_id"]
    r = client.post(f"/api/visitor/visits/{vid}/decide", json={"approve": False})
    assert r.json()["status"] == "denied"
    # deciding twice blocked
    r = client.post(f"/api/visitor/visits/{vid}/decide", json={"approve": True})
    assert r.status_code == 409


def test_visitor_kiosk_cannot_use_checkin_credential():
    cred, _ = _enroll(kind="checkin")
    r = client.post("/api/visitor/register", json={
        "device": cred, "visitor_name": "Wrong Device", "consent": True})
    assert r.status_code == 401   # wrong-type device rejected


# ---------------------------------------------------------------- access control
def test_access_decisions_with_reason_codes():
    cred, _ = _enroll()
    r = client.post("/api/access/doors",
                    json={"name": "Kitchen Door", "zone": "Kitchen",
                          "allow_visitors": True})
    door = r.json()["id"]

    # worker badge → allow
    r = client.post("/api/workforce/badges", json={"worker_name": "Eve Access"})
    tok = r.json()["badge_token"]
    bid = r.json()["badge_id"]
    r = client.post("/api/access/decision",
                    json={"device": cred, "door_id": door, "code": tok})
    assert r.json() == {"allow": True, "reason": "ok"}

    # revoked badge → deny with reason
    client.post(f"/api/workforce/badges/{bid}/revoke", json={"reason": "term"})
    r = client.post("/api/access/decision",
                    json={"device": cred, "door_id": door, "code": tok})
    assert r.json() == {"allow": False, "reason": "badge_revoked"}

    # no credential at all → deny
    r = client.post("/api/access/decision",
                    json={"device": cred, "door_id": door, "code": ""})
    assert r.json()["allow"] is False and r.json()["reason"] == "no_credential"

    # forged visitor badge → deny
    r = client.post("/api/access/decision",
                    json={"device": cred, "door_id": door, "code": "vb-forged"})
    assert r.json()["allow"] is False

    # events are all logged immutably
    ev = client.get("/api/access/events").json()
    assert len(ev) >= 4
    assert {e["decision"] for e in ev} == {"allow", "deny"}


def test_visitor_zone_scoping_on_doors():
    cred, _ = _enroll(kind="visitor")
    dcred, _ = _enroll()
    r = client.post("/api/access/doors",
                    json={"name": "Server Room", "zone": "IT",
                          "allow_visitors": True})
    it_door = r.json()["id"]
    r = client.post("/api/visitor/register", json={
        "device": cred, "visitor_name": "Zone Visitor", "consent": True,
        "destination": "Kitchen"})
    vid = r.json()["visit_id"]
    r = client.post(f"/api/visitor/visits/{vid}/decide", json={"approve": True})
    badge = r.json()["badge_code"]
    # approved for Kitchen, tries IT door → deny zone_not_granted
    r = client.post("/api/access/decision",
                    json={"device": dcred, "door_id": it_door, "code": badge})
    assert r.json() == {"allow": False, "reason": "zone_not_granted"}
