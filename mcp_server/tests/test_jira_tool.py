from app.schemas import CreateJiraTaskInput
from app.tools.jira import execute_create_jira_task


def test_mock_mode_returns_a_well_formed_fake_issue() -> None:
    result = execute_create_jira_task(
        CreateJiraTaskInput(
            project_key="ONB",
            summary="Provision laptop for Jamie Rivera",
            description="New hire onboarding task.",
            issue_type="Task",
        )
    )
    assert result.status == "created"
    assert result.issue_key.startswith("ONB-")
    assert result.issue_url.endswith(result.issue_key)


def test_mock_mode_uses_the_given_project_key() -> None:
    result = execute_create_jira_task(
        CreateJiraTaskInput(
            project_key="ACC",
            summary="Grant AWS Console access",
            description="Access request fulfillment task.",
            issue_type="Task",
        )
    )
    assert result.issue_key.startswith("ACC-")


def test_mock_mode_accepts_optional_assignee() -> None:
    result = execute_create_jira_task(
        CreateJiraTaskInput(
            project_key="ONB",
            summary="Order equipment",
            description="Ship a laptop.",
            issue_type="Task",
            assignee_email="it@cordant.io",
        )
    )
    assert result.status == "created"
