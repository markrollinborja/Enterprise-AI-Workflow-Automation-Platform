"""Composes the rules engine's risk decision with the workflow engine's
`start_workflow` — the second workflow proving the engine built for
onboarding (Phase 6/7) is genuinely reusable, not onboarding-shaped code
with a second JSON file bolted on. See services/rules/service.py for why
the risk computation itself lives in a separate, dependency-free module
rather than inline here.
"""

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.user import User
from app.repositories import application_repo, employee_repo
from app.schemas.access_request import AccessRequestCreate, AccessRequestResponse
from app.services.rules.service import classify_request_risk, should_auto_approve
from app.services.workflows.service import start_workflow


def submit_access_request(
    db: Session, payload: AccessRequestCreate, *, current_user: User
) -> AccessRequestResponse:
    if current_user.employee_id is None:
        raise ConflictError(
            "Your account is not linked to an employee record, so it can't submit "
            "an access request."
        )
    employee = employee_repo.get_by_id(db, current_user.employee_id)
    if employee is None:
        raise NotFoundError("Linked employee record not found")

    application = application_repo.get_by_id(db, payload.application_id)
    if application is None:
        raise NotFoundError("Application not found")

    risk = classify_request_risk(application.risk_level, employee.risk_level)
    auto_approved = should_auto_approve(risk)

    instance = start_workflow(
        db,
        workflow_key="software_access_request",
        input_data={
            "employee_id": str(employee.id),
            "application_id": str(application.id),
            "justification": payload.justification,
            "application_risk_level": risk.value,
            "auto_approved": auto_approved,
        },
        # Random, not derived from employee/application — unlike onboarding's
        # one-dedup-key-per-employee (an event that should only ever start
        # one instance), the same employee legitimately requesting the same
        # application twice (e.g. re-requesting after an earlier rejection)
        # is a second, independent event, not a retry to collapse into the
        # first. See WorkflowEvent's docstring on what dedup_key protects
        # against.
        dedup_key=f"software_access_request:{uuid.uuid4()}",
        initiated_by_user_id=current_user.id,
        employee_id=employee.id,
    )

    return AccessRequestResponse(
        workflow_instance_id=instance.id,
        application_id=application.id,
        application_name=application.name,
        justification=payload.justification,
        computed_risk_level=risk,
        auto_approved=auto_approved,
        status=instance.status,
        current_step_key=instance.current_step_key,
    )
