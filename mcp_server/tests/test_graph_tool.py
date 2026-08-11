"""Mock-mode only, same convention as test_jira_tool.py / test_slack_tool.py
/ test_calendar_tool.py — see conftest.py's docstring for why real mode
isn't unit-tested here."""

import uuid

from app.schemas import ProvisionM365AccountInput
from app.tools.graph import execute_provision_m365_account


def _input(**overrides: str) -> ProvisionM365AccountInput:
    defaults = {
        "display_name": "Jamie Rivera",
        "user_principal_name": "jamie.rivera@cordant.io",
        "job_title": "Software Engineer",
        "department": "Engineering",
    }
    defaults.update(overrides)
    return ProvisionM365AccountInput(**defaults)


def test_mock_mode_returns_created_with_a_real_looking_id() -> None:
    result = execute_provision_m365_account(_input())
    assert result.status == "created"
    assert result.user_principal_name == "jamie.rivera@cordant.io"
    # A real GUID, not "MOCK-1" — same reasoning as create_jira_task's
    # fake issue key: downstream code should see the same shape it would
    # in real mode.
    assert uuid.UUID(result.m365_user_id)


def test_mock_mode_still_generates_the_powershell_script() -> None:
    """The PowerShell artifact is not a real-mode-only feature — it's
    generated identically regardless of which mode created the account
    (see ProvisionM365AccountOutput.powershell_script's docstring), so a
    mock-mode workflow instance still has something real for IT to
    review."""
    result = execute_provision_m365_account(_input())
    assert "New-MgUser" in result.powershell_script
    assert "jamie.rivera@cordant.io" in result.powershell_script
    assert "Jamie Rivera" in result.powershell_script


def test_powershell_script_uses_the_mail_nickname_not_the_full_upn() -> None:
    result = execute_provision_m365_account(
        _input(user_principal_name="priya.nair@cordant.io")
    )
    assert '-MailNickname "priya.nair"' in result.powershell_script


def test_powershell_script_never_contains_a_real_looking_password() -> None:
    """Same reasoning as scim.md's provisioned-user passwords: this text
    is stored as workflow output and shown on the dashboard, so it must
    never contain anything that looks like a real credential — only a
    prompt for the admin to set one."""
    result = execute_provision_m365_account(_input())
    assert "Read-Host" in result.powershell_script
    assert "ConvertFrom-SecureString" in result.powershell_script


def test_mock_mode_reflects_job_title_and_department() -> None:
    result = execute_provision_m365_account(
        _input(job_title="Security Analyst", department="Security")
    )
    assert '-JobTitle "Security Analyst"' in result.powershell_script
    assert '-Department "Security"' in result.powershell_script
