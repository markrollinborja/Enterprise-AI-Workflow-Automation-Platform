"""Exercises the real workflows/*.json files through the real loader — not
fixtures standing in for them. If someone edits employee_onboarding.json or
software_access_request.json into something that fails
WorkflowDefinitionSchema, this is what catches it in CI instead of at
`docker compose up` on a contributor's machine.
"""

import json

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.enums import TriggerType
from app.repositories import workflow_definition_repo
from app.schemas.workflow_definition import WorkflowDefinitionSchema
from app.services.workflows.definition_loader import (
    WorkflowDefinitionLoadError,
    _load_file,
    load_all_definitions,
)


def test_load_all_definitions_creates_both_v1_workflows(db_session: Session) -> None:
    counts = load_all_definitions(db_session)
    assert counts["created"] >= 2

    onboarding = workflow_definition_repo.get_active_by_key(db_session, "employee_onboarding")
    assert onboarding is not None
    assert onboarding.trigger_type == TriggerType.EVENT
    assert onboarding.trigger_event == "employee.created"
    assert onboarding.is_active is True
    onboarding_steps = onboarding.definition_json["steps"]
    assert len(onboarding_steps) == 7
    assert {step["key"] for step in onboarding_steps} == {
        "validate_employee",
        "manager_approval",
        "recommend_access",
        "it_review_access",
        "create_it_tasks",
        "schedule_orientation",
        "notify_slack",
    }

    access_request = workflow_definition_repo.get_active_by_key(
        db_session, "software_access_request"
    )
    assert access_request is not None
    assert access_request.trigger_type == TriggerType.MANUAL
    assert access_request.trigger_event is None
    assert len(access_request.definition_json["steps"]) == 7


def test_load_all_definitions_is_idempotent(db_session: Session) -> None:
    first = load_all_definitions(db_session)
    second = load_all_definitions(db_session)
    assert second["created"] == 0
    assert second["unchanged"] == first["created"]


def test_reload_after_deactivation_reactivates_a_fresh_row(db_session: Session) -> None:
    """Simulates the "reseed after a version bump" path: deactivate the
    currently-active row by hand (as if a prior version were active), then
    reload — the loader should insert a new active row rather than erroring
    on a duplicate key."""
    load_all_definitions(db_session)
    existing = workflow_definition_repo.get_active_by_key(db_session, "employee_onboarding")
    assert existing is not None
    workflow_definition_repo.deactivate(db_session, existing)
    assert workflow_definition_repo.get_active_by_key(db_session, "employee_onboarding") is None

    counts = load_all_definitions(db_session)
    assert counts["created"] >= 1
    reactivated = workflow_definition_repo.get_active_by_key(db_session, "employee_onboarding")
    assert reactivated is not None
    assert reactivated.id != existing.id


def test_schema_rejects_approval_step_without_approval_config() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinitionSchema.model_validate(
            {
                "workflow_key": "broken",
                "name": "Broken",
                "description": "missing approval config",
                "trigger_type": "manual",
                "version": 1,
                "input_schema": {},
                "steps": [{"key": "approve", "name": "Approve", "type": "approval"}],
            }
        )


def test_schema_rejects_event_trigger_without_trigger_event() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinitionSchema.model_validate(
            {
                "workflow_key": "broken",
                "name": "Broken",
                "description": "event trigger with no trigger_event",
                "trigger_type": "event",
                "version": 1,
                "input_schema": {},
                "steps": [{"key": "validate", "name": "Validate", "type": "validation"}],
            }
        )


def test_schema_rejects_duplicate_step_keys() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinitionSchema.model_validate(
            {
                "workflow_key": "broken",
                "name": "Broken",
                "description": "duplicate step keys",
                "trigger_type": "manual",
                "version": 1,
                "input_schema": {},
                "steps": [
                    {"key": "dup", "name": "First", "type": "validation"},
                    {"key": "dup", "name": "Second", "type": "validation"},
                ],
            }
        )


def test_schema_rejects_retry_with_max_attempts_of_one() -> None:
    with pytest.raises(ValidationError):
        WorkflowDefinitionSchema.model_validate(
            {
                "workflow_key": "broken",
                "name": "Broken",
                "description": "retry with no retries",
                "trigger_type": "manual",
                "version": 1,
                "input_schema": {},
                "steps": [
                    {
                        "key": "call_tool",
                        "name": "Call tool",
                        "type": "mcp_tool",
                        "mcp_tool": "some_tool",
                        "failure_behavior": "retry",
                        "max_attempts": 1,
                    }
                ],
            }
        )


def test_load_file_raises_on_malformed_json(tmp_path) -> None:
    bad_file = tmp_path / "not_json.json"
    bad_file.write_text("{not valid json")
    with pytest.raises(WorkflowDefinitionLoadError):
        _load_file(bad_file)


def test_load_file_raises_on_schema_violation(tmp_path) -> None:
    bad_file = tmp_path / "bad_schema.json"
    bad_file.write_text(json.dumps({"workflow_key": "incomplete"}))
    with pytest.raises(WorkflowDefinitionLoadError):
        _load_file(bad_file)
