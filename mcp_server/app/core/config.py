"""mcp_server's own configuration. This is a genuinely separate process from
backend/ (ADR-0005) — it gets its own Settings class rather than importing
backend's, and its own .env read. It happens to share the repo-root .env
file in Docker Compose (both services get `env_file: - .env`) purely for
Mark's convenience running one file locally; nothing here imports anything
from backend/.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Meridian Flow MCP Server"
    log_level: str = "INFO"

    # Mock mode — default true everywhere (ADR-0005). A demo or an
    # interview screen-share must never depend on live Jira/Slack/Google
    # credentials being valid at that exact moment.
    mcp_mock_mode: bool = True

    # Database — read-only access to the same Postgres backend/ owns
    # migrations for (lookup_employee only). mcp_server never migrates,
    # never writes, and does not import backend's SQLAlchemy models — see
    # app/db.py for why a raw query is the right amount of machinery here.
    database_url: str = "postgresql://meridian:meridian@localhost:5433/meridian_flow"

    # Jira Cloud REST API
    jira_base_url: str = ""
    jira_api_token: str = ""
    jira_email: str = ""

    # Slack Web API
    slack_bot_token: str = ""

    # Google Calendar API v3 — service account, one shared demo calendar
    # (see docs/architecture/integration-strategy.md for why not per-user
    # OAuth).
    google_calendar_credentials_json: str = ""
    google_calendar_id: str = "primary"


@lru_cache
def get_settings() -> Settings:
    return Settings()
