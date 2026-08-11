"""provision_m365_account — creates (or simulates creating) a Microsoft 365
account during onboarding. See docs/architecture/microsoft-graph.md and
ADR-0020 for why this is one MCP tool rather than a new provider-adapter
integration, and why it always returns a PowerShell script alongside
whatever it actually did.

execute_provision_m365_account is the plain, directly-testable function —
server.py wraps it with @mcp.tool(), the same split every other tool here
uses.
"""

import uuid

import httpx

from app.core.config import Settings, get_settings
from app.schemas import ProvisionM365AccountInput, ProvisionM365AccountOutput

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def execute_provision_m365_account(
    input_data: ProvisionM365AccountInput,
) -> ProvisionM365AccountOutput:
    settings = get_settings()
    if settings.mcp_mock_mode:
        return _mock_provision_m365_account(input_data)
    return _real_provision_m365_account(input_data, settings)


def _mail_nickname(user_principal_name: str) -> str:
    return user_principal_name.split("@", 1)[0]


def _render_powershell_script(input_data: ProvisionM365AccountInput) -> str:
    """The generated audit artifact — what an IT admin would run by hand to
    reproduce this exact account creation using the Microsoft Graph
    PowerShell SDK (the current, non-deprecated module; MSOnline/AzureAD
    are retired). A temporary password placeholder, never a real one: this
    text is stored as workflow output and shown in the dashboard, so a
    real generated secret has no business appearing in it (see ADR-0020's
    note on why this platform never invents a placeholder-shaped real
    credential — the same reasoning as V1's provisioned-user password
    handling in scim.md).
    """
    nickname = _mail_nickname(input_data.user_principal_name)
    return (
        "# Run interactively — Connect-MgGraph will prompt for sign-in.\n"
        "Connect-MgGraph -Scopes \"User.ReadWrite.All\"\n\n"
        "$passwordProfile = @{\n"
        "    Password = Read-Host \"Temporary password for the new account\" -AsSecureString "
        "| ConvertFrom-SecureString -AsPlainText\n"
        "    ForceChangePasswordNextSignIn = $true\n"
        "}\n\n"
        "New-MgUser `\n"
        f'    -DisplayName "{input_data.display_name}" `\n'
        f'    -UserPrincipalName "{input_data.user_principal_name}" `\n'
        f'    -MailNickname "{nickname}" `\n'
        "    -AccountEnabled `\n"
        "    -PasswordProfile $passwordProfile `\n"
        f'    -JobTitle "{input_data.job_title}" `\n'
        f'    -Department "{input_data.department}"'
    )


def _mock_provision_m365_account(
    input_data: ProvisionM365AccountInput,
) -> ProvisionM365AccountOutput:
    return ProvisionM365AccountOutput(
        m365_user_id=str(uuid.uuid4()),
        user_principal_name=input_data.user_principal_name,
        status="created",
        powershell_script=_render_powershell_script(input_data),
    )


def _fetch_graph_token(settings: Settings) -> str:
    """App-only (client-credentials) grant — the only mode that makes sense
    for a backend service provisioning accounts with no signed-in user in
    the loop. Requests the `.default` scope, which is Microsoft's
    convention for "whatever application permissions this app registration
    was actually granted", read from the app registration itself rather
    than requested per-call."""
    response = httpx.post(
        GRAPH_TOKEN_URL_TEMPLATE.format(tenant_id=settings.graph_tenant_id),
        data={
            "grant_type": "client_credentials",
            "client_id": settings.graph_client_id,
            "client_secret": settings.graph_client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Microsoft Graph token request failed {exc.response.status_code}: "
            f"{exc.response.text}"
        ) from exc
    return str(response.json()["access_token"])


def _real_provision_m365_account(
    input_data: ProvisionM365AccountInput, settings: Settings
) -> ProvisionM365AccountOutput:
    """Real mode: Microsoft Graph `POST /users`. Raises on any failure —
    same contract as every other tool's real-mode function; the caller
    (services/integrations/mcp_client.py) turns an exception into a failed
    MCPToolExecution row, not this function."""
    token = _fetch_graph_token(settings)
    payload = {
        "accountEnabled": True,
        "displayName": input_data.display_name,
        "userPrincipalName": input_data.user_principal_name,
        "mailNickname": _mail_nickname(input_data.user_principal_name),
        "jobTitle": input_data.job_title,
        "department": input_data.department,
        "passwordProfile": {
            # Discarded immediately, same as SCIM-provisioned local users
            # (see docs/architecture/scim.md) — this call's job is to
            # create the account, not to hand back a credential anyone
            # should use. The real admin sets a real temporary password by
            # hand, using the generated PowerShell above or the Entra
            # admin center.
            "password": str(uuid.uuid4()),
            "forceChangePasswordNextSignIn": True,
        },
    }
    response = httpx.post(
        f"{GRAPH_BASE_URL}/users",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Microsoft Graph API error {exc.response.status_code}: {exc.response.text}"
        ) from exc
    body = response.json()
    return ProvisionM365AccountOutput(
        m365_user_id=body["id"],
        user_principal_name=body["userPrincipalName"],
        status="created",
        powershell_script=_render_powershell_script(input_data),
    )
