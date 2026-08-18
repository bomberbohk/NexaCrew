"""Seed example data: two isolated companies with departments, employees,
projects, tasks and one verified email identity. Safe example config only —
no real credentials or real email addresses (example.com reserved domain).

Run:  python -m app.seed   (from platform/ dir)
"""

from app.db import (Chat, Department, EmailIdentity, Project, SessionLocal, Task,
                    User, VirtualCompany, VirtualEmployee, Workspace, init_db)
from app.security import hash_password
import json

init_db()
db = SessionLocal()

if db.query(User).count():
    print("Database already initialized — skipping seed.")
    raise SystemExit(0)

user = User(username="admin", display_name="Admin", password_hash=hash_password("admin1234"))
db.add(user); db.commit()
ws = Workspace(name="Default Workspace", owner_id=user.id)
db.add(ws); db.commit()

def make_company(name, logo, industry, mission):
    c = VirtualCompany(workspace_id=ws.id, name=name, logo=logo, industry=industry, mission=mission)
    db.add(c); db.commit()
    return c

acme = make_company("Acme Software", "🚀", "Software", "Ship delightful software, fast.")
nova = make_company("Nova Consulting", "🌟", "Consulting", "Practical advice, measurable results.")

eng = Department(company_id=acme.id, name="Engineering")
ops = Department(company_id=nova.id, name="Operations")
db.add_all([eng, ops]); db.commit()

alice = VirtualEmployee(
    company_id=acme.id, department_id=eng.id, full_name="Alice Chen", avatar="👩‍💻",
    job_title="Software Engineer",
    responsibilities="Design, implement, review, and debug software.",
    working_style="Precise, pragmatic, friendly.",
    permissions=json.dumps(["view", "create", "edit", "execute_code", "draft_external"]))
bob = VirtualEmployee(
    company_id=acme.id, full_name="Bob Rivera", avatar="🧑‍💼",
    job_title="Project Manager",
    responsibilities="Plan projects, manage tasks and status reporting.",
    permissions=json.dumps(["view", "create", "edit", "draft_external"]))
carol = VirtualEmployee(
    company_id=nova.id, department_id=ops.id, full_name="Carol Diaz", avatar="👩‍💼",
    job_title="Operations Manager",
    responsibilities="Run daily operations and client communication.",
    permissions=json.dumps(["view", "create", "edit", "draft_external", "send_external"]))
db.add_all([alice, bob, carol]); db.commit()

db.add(EmailIdentity(company_id=acme.id, employee_id=alice.id, provider="local-dev",
                     email_address="alice.chen@acme.example.com", display_name="Alice Chen",
                     signature="Best regards,\nAlice Chen\nSoftware Engineer, Acme Software",
                     verified=True, connection_status="connected"))
db.add(Project(company_id=acme.id, name="Website Redesign", priority="High",
               description="Redesign the marketing site.", instructions="Use the company brand voice."))
db.add(Project(company_id=nova.id, name="Client Onboarding", priority="Medium",
               description="Streamline onboarding for new clients."))
db.commit()
p = db.query(Project).filter(Project.company_id == acme.id).first()
db.add_all([
    Task(company_id=acme.id, project_id=p.id, title="Draft homepage copy", status="Ready", assignee_id=alice.id),
    Task(company_id=acme.id, project_id=p.id, title="Set up CI pipeline", status="Backlog", assignee_id=alice.id, priority="High"),
    Task(company_id=nova.id, title="Prepare onboarding checklist", status="In Progress", assignee_id=carol.id),
])
db.add(Chat(company_id=acme.id, project_id=p.id, title="Website kickoff", active_employee_id=alice.id))
db.commit()
print("Seeded. Sign in with  admin / admin1234")
