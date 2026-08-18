"""End-to-end tests: auth, multi-company isolation, permissions,
email identity rules, approval-controlled sending, audit chain."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Use a throwaway database for tests
_tmp = tempfile.mkdtemp()
os.environ["PLATFORM_TEST"] = "1"

import app.db as dbmod  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

test_engine = create_engine(f"sqlite:///{_tmp}/test.db", connect_args={"check_same_thread": False})
dbmod.engine = test_engine
dbmod.SessionLocal = sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)
dbmod.Base.metadata.create_all(test_engine)


def _override_get_db():
    db = dbmod.SessionLocal()
    try:
        yield db
    finally:
        db.close()


dbmod.get_db = _override_get_db

# Isolate tests from the user's real config (e.g. their SMTP credentials)
import app.config as cfgmod  # noqa: E402
cfgmod.CONFIG_FILE = Path(_tmp) / "config.json"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db import get_db as app_get_db  # noqa: E402
app.dependency_overrides[app_get_db] = _override_get_db

from app.providers import EchoProvider  # noqa: E402
from app.services import set_agent_provider  # noqa: E402

set_agent_provider(EchoProvider())
client = TestClient(app)


def setup_module():
    r = client.post("/api/auth/setup", json={"username": "tester", "password": "pass1234"})
    assert r.status_code in (200, 400)  # 400 = already set up by another test module
    r = client.post("/api/auth/login", json={"username": "tester", "password": "pass1234"})
    assert r.status_code == 200


def test_requires_auth():
    anon = TestClient(app)
    assert anon.get("/api/companies").status_code == 401


def test_company_isolation():
    a = client.post("/api/companies", json={"name": "Company A"}).json()
    b = client.post("/api/companies", json={"name": "Company B"}).json()
    emp_a = client.post(f"/api/companies/{a['id']}/employees",
                        json={"full_name": "Emp A", "permissions": ["view", "draft_external"]}).json()
    # Cross-company assignment must be blocked (IDOR protection)
    r = client.post(f"/api/companies/{b['id']}/tasks",
                    json={"title": "X", "assignee_id": emp_a["id"]})
    assert r.status_code == 403
    # Cross-company identity connection must be blocked
    r = client.post(f"/api/companies/{b['id']}/identities",
                    json={"employee_id": emp_a["id"], "email_address": "a@example.com"})
    assert r.status_code == 403
    # Employee listing is company-scoped
    assert client.get(f"/api/companies/{b['id']}/employees").json() == []


def test_chat_requires_unambiguous_employee():
    a = client.post("/api/companies", json={"name": "ChatCo"}).json()
    chat = client.post("/api/chats", json={"title": "t", "company_id": a["id"]}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "hello"})
    assert r.status_code == 400  # no active employee -> refuse


def test_email_requires_verified_identity_and_approval():
    a = client.post("/api/companies", json={"name": "MailCo"}).json()
    emp = client.post(f"/api/companies/{a['id']}/employees",
                      json={"full_name": "Mailer", "permissions": ["view", "draft_external"]}).json()
    chat = client.post("/api/chats", json={"title": "mail", "company_id": a["id"],
                                           "active_employee_id": emp["id"]}).json()
    # No identity yet -> refuse, never substitute another mailbox
    r = client.post(f"/api/chats/{chat['id']}/messages",
                    json={"content": "Send an email to client@example.com about the update"}).json()
    assert r["kind"] == "needs_identity"

    # Connect identity, then the email is auto-approved and sent immediately
    client.post(f"/api/companies/{a['id']}/identities",
                json={"employee_id": emp["id"], "email_address": "mailer@example.com",
                      "signature": "Mailer"})
    r = client.post(f"/api/chats/{chat['id']}/messages",
                    json={"content": "Send an email to client@example.com about the update"}).json()
    assert r["kind"] == "email_sent"
    appr_id = r["approval_id"]

    # Approval record kept for the audit trail, already executed
    approvals = client.get("/api/approvals").json()
    mine = next(x for x in approvals if x["id"] == appr_id)
    assert mine["status"] == "executed"
    assert mine["draft"]["status"] == "sent"

    # A second approve attempt is rejected (idempotent workflow)
    assert client.post(f"/api/approvals/{appr_id}/approve").status_code == 400


def test_permission_denied_for_draft():
    a = client.post("/api/companies", json={"name": "NoPermCo"}).json()
    emp = client.post(f"/api/companies/{a['id']}/employees",
                      json={"full_name": "Viewer", "permissions": ["view"]}).json()
    client.post(f"/api/companies/{a['id']}/identities",
                json={"employee_id": emp["id"], "email_address": "viewer@example.com"})
    chat = client.post("/api/chats", json={"title": "np", "company_id": a["id"],
                                           "active_employee_id": emp["id"]}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages",
                    json={"content": "Send an email to someone@example.com now"}).json()
    assert r["kind"] == "error"


def test_agent_answer_and_audit_chain():
    a = client.post("/api/companies", json={"name": "RunCo"}).json()
    emp = client.post(f"/api/companies/{a['id']}/employees",
                      json={"full_name": "Runner", "permissions": ["view", "execute_code"]}).json()
    chat = client.post("/api/chats", json={"title": "run", "company_id": a["id"],
                                           "active_employee_id": emp["id"]}).json()
    r = client.post(f"/api/chats/{chat['id']}/messages", json={"content": "What is 2+2?"}).json()
    assert r["kind"] == "answer" and "[echo-provider]" in r["message"]

    audit = client.get("/api/audit").json()
    assert audit, "audit log must not be empty"
    # hash chain: each prev_hash must equal previous entry's hash (list is desc)
    asc = list(reversed(audit))
    for i in range(1, len(asc)):
        assert asc[i]["prev_hash"] == asc[i - 1]["entry_hash"]


def test_persistence_across_relogin():
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": "tester", "password": "pass1234"})
    assert r.status_code == 200
    assert len(client.get("/api/companies").json()) >= 4


def test_skillscript_basic_framework():
    """SkillScript BASIC: variables, control flow, functions, sandbox, API."""
    from app import skillscript

    code = """
    PROGRAM UnitTest
    ' comment line
    REM another comment
    CONST GREETING = "Hello"
    LET total = 0
    FOR i = 1 TO 5
      total = total + i
    NEXT i
    ASSERT total = 15, "sum wrong"
    IF total > 10 THEN
      PRINT GREETING & ", sum=" & total
    ELSE
      PRINT "small"
    ENDIF
    LET parts = SPLIT("a,b,c", ",")
    PRINT UPPER(JOIN(parts, "-"))
    SELECT CASE total
    CASE 15
      PRINT "fifteen"
    CASE ELSE
      PRINT "other"
    END SELECT
    GOSUB footer
    END
    footer:
      PRINT "bye " & TARGET
    RETURN
    END PROGRAM
    """
    assert skillscript.is_script(code)
    v = skillscript.validate(code)
    assert v["ok"], v
    r = skillscript.run_script(code, context={"target": "codex"}, allow_effects=False)
    assert r["ok"], r
    out = r["output"]
    assert "Hello, sum=15" in out and "A-B-C" in out
    assert "fifteen" in out and "bye codex" in out

    # error handling + sandbox
    bad = skillscript.run_script("PROGRAM X\nTHROW \"boom\"\nEND PROGRAM")
    assert not bad["ok"] and "boom" in bad["error"]
    v2 = skillscript.validate("PROGRAM Y\nFOR i = 1 TO 3\nPRINT i\nEND PROGRAM")
    assert not v2["ok"]  # missing NEXT

    # HTTP API endpoints
    rr = client.post("/api/skillscript/validate", json={"code": code})
    assert rr.status_code == 200 and rr.json()["ok"]
    rr = client.post("/api/skillscript/run", json={"code": "PROGRAM P\nPRINT 2+3\nEND PROGRAM"})
    assert rr.status_code == 200 and rr.json()["output"].strip() == "5"
    rr = client.get("/api/skillscript/reference")
    assert "STATEMENTS" in rr.json()["reference"]


def test_skillscript_ai_and_generation():
    """AI helper statements, GENERATE files and CHART rendering."""
    import zipfile
    from app import skillscript

    calls = []

    def fake_ai(agent, prompt, system=""):
        calls.append(prompt)
        return "MOCKED"

    code = """
    PROGRAM GenTest
    SUMMARIZE s = "long text" WORDS 10
    TRANSLATE t = "hello" TO "German"
    SENTIMENT m = "great product"
    PRINT s & "/" & t & "/" & m
    LET rows = ARRAY(ARRAY("a", "b"), ARRAY(1, 2))
    GENERATE CSV "unittest_gen.csv", rows
    GENERATE XLSX "unittest_gen.xlsx", rows
    GENERATE PDF "unittest_gen.pdf", "# Title" & NL() & "body text"
    GENERATE DOCX "unittest_gen.docx", "# Doc" & NL() & "para"
    GENERATE MD "unittest_gen.md", "# hi"
    CHART "unittest_gen.svg", "pie", ARRAY("x", "y"), ARRAY(30, 70), "Split"
    PRINT "file=" & LAST_FILE
    END PROGRAM
    """
    assert skillscript.validate(code)["ok"]
    it = skillscript.Interpreter(code, context={}, ai_runner=fake_ai)
    r = it.run()
    assert r["ok"], r
    assert "MOCKED/MOCKED/MOCKED" in r["output"]
    assert len(calls) == 3

    base = skillscript.Interpreter("PROGRAM x\nEND PROGRAM")._safe_path("unittest_gen.pdf").parent
    assert (base / "unittest_gen.pdf").read_bytes()[:5] == b"%PDF-"
    assert zipfile.is_zipfile(base / "unittest_gen.xlsx")
    assert zipfile.is_zipfile(base / "unittest_gen.docx")
    assert "<svg" in (base / "unittest_gen.svg").read_text(encoding="utf-8")
    assert "a,b" in (base / "unittest_gen.csv").read_text(encoding="utf-8-sig")
    for f in base.glob("unittest_gen.*"):
        f.unlink()

    # AI-call limit shared by helper statements
    many = "PROGRAM L\n" + "\n".join(f'SENTIMENT a{i} = "x"' for i in range(6)) + "\nEND PROGRAM"
    it2 = skillscript.Interpreter(many, context={}, ai_runner=fake_ai)
    try:
        it2.run()
        raise AssertionError("AI call limit not enforced")
    except skillscript.ScriptError as e:
        assert "limit" in str(e)

