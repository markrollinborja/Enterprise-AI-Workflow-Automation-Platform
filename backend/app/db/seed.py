"""Seed reference and demo data for local development and interview demos.

Fictional company: Cordant Industries. Order matters and is enforced by
run_all_seeds(): departments before employees (FK dependency), employees
before demo users (users are linked to employees by matching email), and
the employee<->user link pass runs last, once both sides exist.

Idempotent throughout — every step checks for an existing row (by name or
email) before creating one, so this is safe to run on every container
startup, not just the first one.

Demo password is intentionally simple and documented here in plain sight —
this is a local-dev-only credential, never a real one, never used outside
`docker compose up` / a portfolio demo.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.department import Department
from app.models.employee import Employee
from app.models.enums import EmployeeStatus, EmploymentType, RiskLevel, UserRole
from app.repositories import (
    access_package_repo,
    application_repo,
    department_repo,
    employee_repo,
    user_repo,
)
from app.services.rules.service import classify_request_risk, should_auto_approve
from app.services.workflows.definition_loader import load_all_definitions
from app.services.workflows.service import start_workflow

DEMO_PASSWORD = "MeridianDemo123!"

DEPARTMENT_NAMES = [
    "Human Resources",
    "Information Technology",
    "Engineering",
    "Security",
    "Finance",
    "Operations",
]

# work_email doubles as the login email for the subset of employees who also
# get a demo User account (see DEMO_USER_ROLES below).
EMPLOYEES: list[dict] = [
    {
        "first_name": "Marcus",
        "last_name": "Webb",
        "work_email": "marcus.webb@cordant.io",
        "job_title": "Chief Technology Officer",
        "department": "Engineering",
        "manager_email": None,
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2021, 3, 1),
        "location": "Austin, TX",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "first_name": "Daniel",
        "last_name": "Osei",
        "work_email": "daniel.osei@cordant.io",
        "job_title": "Engineering Manager",
        "department": "Engineering",
        "manager_email": "marcus.webb@cordant.io",
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2022, 1, 10),
        "location": "Austin, TX",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "first_name": "Jordan",
        "last_name": "Lee",
        "work_email": "jordan.lee@cordant.io",
        "job_title": "Software Engineer",
        "department": "Engineering",
        "manager_email": "daniel.osei@cordant.io",
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2026, 7, 6),
        "location": "Remote - US",
        "risk_level": RiskLevel.LOW,
    },
    {
        "first_name": "Priya",
        "last_name": "Anand",
        "work_email": "priya.anand@cordant.io",
        "job_title": "HR Coordinator",
        "department": "Human Resources",
        "manager_email": None,
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2020, 6, 15),
        "location": "Austin, TX",
        "risk_level": RiskLevel.LOW,
    },
    {
        "first_name": "Sam",
        "last_name": "Whitfield",
        "work_email": "sam.whitfield@cordant.io",
        "job_title": "IT Administrator",
        "department": "Information Technology",
        "manager_email": None,
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2019, 9, 2),
        "location": "Austin, TX",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "first_name": "Noah",
        "last_name": "Kim",
        "work_email": "noah.kim@cordant.io",
        "job_title": "IT Support Specialist",
        "department": "Information Technology",
        "manager_email": "sam.whitfield@cordant.io",
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2023, 4, 18),
        "location": "Austin, TX",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "first_name": "Renee",
        "last_name": "Castillo",
        "work_email": "renee.castillo@cordant.io",
        "job_title": "Security Analyst",
        "department": "Security",
        "manager_email": None,
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2021, 11, 8),
        "location": "Remote - US",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "first_name": "Elena",
        "last_name": "Vasquez",
        "work_email": "elena.vasquez@cordant.io",
        "job_title": "Finance Director",
        "department": "Finance",
        "manager_email": None,
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2020, 2, 3),
        "location": "Austin, TX",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "first_name": "Ava",
        "last_name": "Thompson",
        "work_email": "ava.thompson@cordant.io",
        "job_title": "Platform Administrator",
        "department": "Operations",
        "manager_email": None,
        "employment_type": EmploymentType.FULL_TIME,
        "start_date": date(2018, 5, 21),
        "location": "Austin, TX",
        "risk_level": RiskLevel.HIGH,
    },
]

# Only these six of the nine employees get a demo login — matches the six
# V1 roles. Marcus, Noah, and Elena exist in the directory (to make the
# manager hierarchy and department spread feel like a real company) but
# don't need system access for any V1 demo scenario.
DEMO_USER_ROLES: dict[str, UserRole] = {
    "priya.anand@cordant.io": UserRole.HR,
    "daniel.osei@cordant.io": UserRole.MANAGER,
    "sam.whitfield@cordant.io": UserRole.IT,
    "renee.castillo@cordant.io": UserRole.SECURITY,
    "jordan.lee@cordant.io": UserRole.EMPLOYEE,
    "ava.thompson@cordant.io": UserRole.ADMINISTRATOR,
}


# Spans all three risk levels so the demo can show every branch of the
# access-request workflow: auto-approve (low), manager-only (medium, when
# paired with a low-risk employee), and the full manager+IT+security chain
# (high). See services/rules/service.py for how an application's risk_level
# combines with the requesting employee's risk_level.
APPLICATIONS: list[dict] = [
    {
        "name": "Confluence",
        "description": "Internal wiki and documentation.",
        "risk_level": RiskLevel.LOW,
    },
    {
        "name": "Zoom",
        "description": "Video conferencing.",
        "risk_level": RiskLevel.LOW,
    },
    {
        "name": "Salesforce",
        "description": "Customer relationship management (CRM).",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "name": "GitHub",
        "description": "Source code hosting and CI/CD.",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "name": "Slack Admin Console",
        "description": "Workspace administration for Slack.",
        "risk_level": RiskLevel.MEDIUM,
    },
    {
        "name": "AWS Console",
        "description": "Production cloud infrastructure.",
        "risk_level": RiskLevel.HIGH,
    },
    {
        "name": "NetSuite Finance",
        "description": "Finance and payroll system.",
        "risk_level": RiskLevel.HIGH,
    },
]


# The catalog recommend_access_package picks from (see
# services/ai/service.py) — never free text, never invented. Spans risk
# levels and departments so the AI has a genuine choice to make, not one
# obviously-correct row every time.
ACCESS_PACKAGES: list[dict] = [
    {
        "name": "Engineering - Standard",
        "department": "Engineering",
        "risk_level": RiskLevel.LOW,
        "included_systems": ["GitHub", "Slack", "AWS Console (dev)"],
        "description": "Baseline access for individual-contributor engineers.",
    },
    {
        "name": "Engineering - Elevated",
        "department": "Engineering",
        "risk_level": RiskLevel.MEDIUM,
        "included_systems": ["GitHub (admin)", "AWS Console (prod)", "CI/CD"],
        "description": "For engineers who own production infrastructure or CI/CD pipelines.",
    },
    {
        "name": "IT - Standard",
        "department": "Information Technology",
        "risk_level": RiskLevel.LOW,
        "included_systems": ["Slack", "Zoom", "Confluence"],
        "description": "Baseline access for IT support staff.",
    },
    {
        "name": "IT - Elevated",
        "department": "Information Technology",
        "risk_level": RiskLevel.HIGH,
        "included_systems": ["AWS Console", "Slack Admin Console", "Okta Admin"],
        "description": "For IT administrators who manage infrastructure and identity systems.",
    },
    {
        "name": "HR - Standard",
        "department": "Human Resources",
        "risk_level": RiskLevel.LOW,
        "included_systems": ["Slack", "Confluence"],
        "description": "Baseline access for HR coordinators.",
    },
    {
        "name": "Finance - Standard",
        "department": "Finance",
        "risk_level": RiskLevel.MEDIUM,
        "included_systems": ["NetSuite Finance", "Salesforce"],
        "description": "Baseline access for finance team members.",
    },
    {
        "name": "Security - Standard",
        "department": "Security",
        "risk_level": RiskLevel.HIGH,
        "included_systems": ["AWS Console", "Okta Admin", "Slack Admin Console"],
        "description": "For security analysts who need broad visibility across systems.",
    },
    {
        "name": "Operations - Standard",
        "department": "Operations",
        "risk_level": RiskLevel.LOW,
        "included_systems": ["Slack", "Zoom", "Confluence"],
        "description": "Baseline access for operations staff.",
    },
]


def seed_access_packages(db: Session, departments: dict[str, Department]) -> None:
    created = 0
    for data in ACCESS_PACKAGES:
        if access_package_repo.get_by_name(db, data["name"]) is None:
            access_package_repo.create(
                db,
                name=data["name"],
                department_id=departments[data["department"]].id,
                risk_level=data["risk_level"],
                included_systems=data["included_systems"],
                description=data["description"],
            )
            created += 1
    print(f"Access packages: {created} created, {len(ACCESS_PACKAGES) - created} already existed.")


def seed_departments(db: Session) -> dict[str, Department]:
    result: dict[str, Department] = {}
    created = 0
    for name in DEPARTMENT_NAMES:
        dept = department_repo.get_by_name(db, name)
        if dept is None:
            dept = department_repo.create(db, name=name)
            created += 1
        result[name] = dept
    print(f"Departments: {created} created, {len(DEPARTMENT_NAMES) - created} already existed.")
    return result


def seed_employees(db: Session, departments: dict[str, Department]) -> dict[str, Employee]:
    by_email: dict[str, Employee] = {}
    created = 0

    # Pass 1: create everyone with manager_id unset — avoids having to hand-
    # order EMPLOYEES by hierarchy depth (a manager must exist before a
    # report can reference it, but not every employee has a manager).
    for data in EMPLOYEES:
        existing = employee_repo.get_by_work_email(db, data["work_email"])
        if existing is None:
            existing = employee_repo.create(
                db,
                first_name=data["first_name"],
                last_name=data["last_name"],
                work_email=data["work_email"],
                job_title=data["job_title"],
                department_id=departments[data["department"]].id,
                manager_id=None,
                employment_type=data["employment_type"],
                start_date=data["start_date"],
                status=EmployeeStatus.ACTIVE,
                location=data["location"],
                risk_level=data["risk_level"],
            )
            created += 1
        by_email[data["work_email"]] = existing

    # Pass 2: wire up manager_id now that every employee row exists.
    for data in EMPLOYEES:
        manager_email = data["manager_email"]
        if manager_email is None:
            continue
        employee = by_email[data["work_email"]]
        if employee.manager_id is None:
            employee_repo.update(db, employee, manager_id=by_email[manager_email].id)

    print(f"Employees: {created} created, {len(EMPLOYEES) - created} already existed.")
    return by_email


def seed_applications(db: Session) -> None:
    created = 0
    for data in APPLICATIONS:
        if application_repo.get_by_name(db, data["name"]) is None:
            application_repo.create(db, **data)
            created += 1
    print(f"Applications: {created} created, {len(APPLICATIONS) - created} already existed.")


def seed_demo_users() -> None:
    db = SessionLocal()
    try:
        created = 0
        for email, role in DEMO_USER_ROLES.items():
            if user_repo.get_by_email(db, email) is not None:
                continue
            full_name = next(
                f"{e['first_name']} {e['last_name']}" for e in EMPLOYEES if e["work_email"] == email
            )
            user_repo.create(
                db,
                email=email,
                hashed_password=hash_password(DEMO_PASSWORD),
                full_name=full_name,
                role=role,
            )
            created += 1
        print(f"Users: {created} created, {len(DEMO_USER_ROLES) - created} already existed.")
    finally:
        db.close()


def link_users_to_employees(db: Session) -> None:
    linked = 0
    for email in DEMO_USER_ROLES:
        user = user_repo.get_by_email(db, email)
        employee = employee_repo.get_by_work_email(db, email)
        if user is not None and employee is not None and user.employee_id != employee.id:
            user.employee_id = employee.id
            db.add(user)
            linked += 1
    if linked:
        db.commit()
    print(f"Linked {linked} user(s) to their employee record.")


def seed_demo_workflow_instance(db: Session) -> None:
    """Starts one real onboarding WorkflowInstance for the demo "new hire"
    (Jordan Lee) so Phase 6's engine is visible in the database the moment
    `docker compose up` finishes — a demoable artifact without needing a
    route or UI yet. Safe to call on every startup: start_workflow's own
    dedup_key check (keyed on this employee's id) means re-running this
    never creates a second instance for the same demo employee.

    Left paused mid-workflow on purpose (stops at manager_approval) rather
    than auto-approving through to completion — that pause *is* the point:
    it's what proves the engine can actually wait on a human, not just run
    a script front to back. Phase 7's approval inbox is what will resolve
    it for real.

    Since Phase 9, approving past manager_approval triggers a real AI call
    (recommend_access) — with no OPENAI_API_KEY configured, that call fails
    gracefully (see services/ai/service.py) and still safely pauses at
    it_review_access, just via the fallback path instead of a real
    recommendation. Both are legitimate things to demo.
    """
    employee = employee_repo.get_by_work_email(db, "jordan.lee@cordant.io")
    hr_user = user_repo.get_by_email(db, "priya.anand@cordant.io")
    if employee is None or hr_user is None:
        print("Skipping demo workflow instance: Jordan Lee / Priya Anand not found yet.")
        return

    instance = start_workflow(
        db,
        workflow_key="employee_onboarding",
        input_data={"employee_id": str(employee.id)},
        dedup_key=f"employee_onboarding:{employee.id}",
        initiated_by_user_id=hr_user.id,
        employee_id=employee.id,
    )
    print(
        f"Demo workflow instance: employee_onboarding for {employee.first_name} "
        f"{employee.last_name} is '{instance.status.value}' "
        f"(current step: {instance.current_step_key})."
    )


def seed_demo_access_request(db: Session) -> None:
    """A second demo WorkflowInstance, deliberately pairing a LOW-risk
    employee (Jordan Lee) with a HIGH-risk application (AWS Console) —
    classify_request_risk's "highest wins" rule means the overall request is
    still HIGH, so this demo shows the full manager+IT+security approval
    chain, distinct from the single-approval onboarding demo. Left paused at
    manager_approval for the same reason as seed_demo_workflow_instance:
    proving the engine waits on a human rather than just running start to
    finish.

    Uses a fixed dedup_key (unlike the real /access-requests route, which
    generates a random one per submission — see
    services/access_requests/service.py) because this seed must resolve to
    the same single instance on every `docker compose up`, not create a new
    one on every restart.
    """
    employee = employee_repo.get_by_work_email(db, "jordan.lee@cordant.io")
    requester = user_repo.get_by_email(db, "jordan.lee@cordant.io")
    application = application_repo.get_by_name(db, "AWS Console")
    if employee is None or requester is None or application is None:
        print("Skipping demo access request: seed data not found yet.")
        return

    risk = classify_request_risk(application.risk_level, employee.risk_level)
    auto_approved = should_auto_approve(risk)
    instance = start_workflow(
        db,
        workflow_key="software_access_request",
        input_data={
            "employee_id": str(employee.id),
            "application_id": str(application.id),
            "justification": (
                "Need production AWS access to investigate a customer-reported outage."
            ),
            "application_risk_level": risk.value,
            "auto_approved": auto_approved,
        },
        dedup_key=f"software_access_request:demo:{employee.id}:{application.id}",
        initiated_by_user_id=requester.id,
        employee_id=employee.id,
    )
    print(
        f"Demo access request: {application.name} for {employee.first_name} "
        f"{employee.last_name} is '{instance.status.value}' "
        f"(risk: {risk.value}, current step: {instance.current_step_key})."
    )


def run_all_seeds() -> None:
    db = SessionLocal()
    try:
        departments = seed_departments(db)
        seed_employees(db, departments)
        seed_applications(db)
        seed_access_packages(db, departments)
    finally:
        db.close()

    seed_demo_users()

    db = SessionLocal()
    try:
        link_users_to_employees(db)
    finally:
        db.close()

    db = SessionLocal()
    try:
        counts = load_all_definitions(db)
        print(
            f"Workflow definitions: {counts['created']} created/updated, "
            f"{counts['unchanged']} already up to date."
        )
    finally:
        db.close()

    db = SessionLocal()
    try:
        seed_demo_workflow_instance(db)
        seed_demo_access_request(db)
    finally:
        db.close()


if __name__ == "__main__":
    run_all_seeds()
