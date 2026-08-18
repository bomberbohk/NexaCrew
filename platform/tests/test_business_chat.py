# SPDX-License-Identifier: MIT
"""Regression tests for the chat ERP handler value extraction
(bug: full request sentence was saved as the worker's name)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from test_platform import client, dbmod  # noqa: E402 — shared throwaway DB

from app import business  # noqa: E402
from app.db import BusinessProfile, BusinessRecord, User  # noqa: E402


def _session_user():
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


def _worker_names(db, user_id):
    rows = (db.query(BusinessRecord)
            .filter(BusinessRecord.user_id == user_id, BusinessRecord.module == "workers").all())
    return [json.loads(r.data or "{}").get("name") for r in rows]


def test_quoted_name_is_extracted_not_full_sentence():
    db, user = _session_user()
    r = business.handle_business_prompt(
        db, 'please add the worker of "Peter Chiu" now,and please ask me the question about Peter Chiu',
        user.id)
    assert r and "RECORD COMMITTED" in r
    assert "Peter Chiu" in _worker_names(db, user.id)
    # the polluted sentence must NOT be stored
    assert not any(n and "please" in n.lower() for n in _worker_names(db, user.id))
    # follow-up question for missing fields is asked
    assert "Outstanding fields" in r
    db.close()


def test_unquoted_clean_name_still_works():
    db, user = _session_user()
    r = business.handle_business_prompt(db, "add worker Maria Lopez", user.id)
    assert r and "RECORD COMMITTED" in r
    assert "Maria Lopez" in _worker_names(db, user.id)
    db.close()


def test_messy_request_without_extractable_value_asks_instead_of_saving_junk():
    db, user = _session_user()
    before = len(_worker_names(db, user.id))
    r = business.handle_business_prompt(
        db, "add a worker and then ask me about what you need to know", user.id)
    assert r is not None
    assert len(_worker_names(db, user.id)) == before  # nothing junk saved
    assert "RECORD SPECIFICATION REQUIRED" in r
    db.close()


def test_revise_intent_matches_fast_path():
    # "revise ... workers" must be handled by the ERP handler, not the slow AI pipeline
    assert business.BUSINESS_INTENT.search("please revise peter chiu in workers: position: Manager")
    assert business.BUSINESS_INTENT.search("update worker: phone=123")
    assert business.BUSINESS_INTENT.search("edit workers #2: email=a@b.c")


def test_update_worker_by_name_with_field_synonyms():
    db, user = _session_user()
    business.handle_business_prompt(db, 'add worker "Peter Chiu"', user.id)
    r = business.handle_business_prompt(
        db,
        "please revise peter chiu in workers:\n"
        "position : Assistant Manager\n"
        "Telephone :949-331-6528\n"
        "email :apictrrading.peter@gmail.com\n"
        "address :21513 lost river dr, diamond bar, ca 91765\n"
        "DOB : 8/6/1982\n"
        "Gender : male",
        user.id)
    assert r and "RECORD AMENDED" in r
    import json as _json
    from app.db import BusinessRecord
    rec = (db.query(BusinessRecord)
           .filter(BusinessRecord.user_id == user.id, BusinessRecord.module == "workers")
           .order_by(BusinessRecord.created_at.desc()).first())
    d = _json.loads(rec.data)
    assert d["name"] == "Peter Chiu"
    assert d["role"] == "Assistant Manager"          # position → role
    assert d["phone"] == "949-331-6528"              # Telephone → phone
    assert d["email"] == "apictrrading.peter@gmail.com"
    assert d["dob"] == "8/6/1982"
    assert d["gender"] == "male"
    db.close()


def test_update_unknown_record_asks_instead_of_guessing():
    db, user = _session_user()
    r = business.handle_business_prompt(
        db, "update worker nobody-here: phone=123", user.id)
    assert r and "TARGET RESOLUTION FAILED" in r
    db.close()


def test_restaurant_workers_have_hr_and_tips_fields():
    mods = business.modules_for("restaurant")
    w = next(m for m in mods if m["key"] == "workers")
    keys = [f[0] for f in w["fields"]]
    for k in ("ssn", "hired", "wage", "tips_ratio", "address", "dob", "gender"):
        assert k in keys, f"missing {k}"
    # tips_ratio is restaurant-only
    w2 = next(m for m in business.modules_for("insurance") if m["key"] == "workers")
    assert "tips_ratio" not in [f[0] for f in w2["fields"]]
    # base ERP_MODULES must not be mutated by the injection
    base = next(m for m in business.ERP_MODULES if m["key"] == "workers")
    assert "tips_ratio" not in [f[0] for f in base["fields"]]


def test_semicolon_typo_accepted_as_separator():
    db, user = _session_user()
    business.handle_business_prompt(db, 'add worker "Semi Colon"', user.id)
    r = business.handle_business_prompt(
        db,
        "update semi colon in workers:\n"
        "Emergency contact ;9899412169\n"
        "phone : 111-222-3333",
        user.id)
    assert r and "RECORD AMENDED" in r
    import json as _json
    from app.db import BusinessRecord
    rec = (db.query(BusinessRecord)
           .filter(BusinessRecord.user_id == user.id, BusinessRecord.module == "workers")
           .order_by(BusinessRecord.created_at.desc()).first())
    d = _json.loads(rec.data)
    assert d["emergency"] == "9899412169"
    assert d["phone"] == "111-222-3333"
    db.close()


def test_update_worker_tips_ssn_hire_salary():
    db, user = _session_user()
    business.handle_business_prompt(db, 'add worker "Tip Tester"', user.id)
    r = business.handle_business_prompt(
        db,
        "update tip tester in workers:\n"
        "SSN : 123-45-6789\n"
        "hire date : 2026-01-15\n"
        "salary : 4200\n"
        "tips ratio : 15",
        user.id)
    assert r and "RECORD AMENDED" in r
    import json as _json
    from app.db import BusinessRecord
    rec = (db.query(BusinessRecord)
           .filter(BusinessRecord.user_id == user.id, BusinessRecord.module == "workers")
           .order_by(BusinessRecord.created_at.desc()).first())
    d = _json.loads(rec.data)
    assert d["ssn"] == "123-45-6789"
    assert d["hired"] == "2026-01-15"
    assert d["wage"] == "4200"
    assert d["tips_ratio"] == "15"
    db.close()
