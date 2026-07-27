from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Local-dev default: resolves to <repo_root>/workflows when running the
# backend directly (venv, no Docker) — backend/app/core/config.py's
# parents[3] is the repo root. Docker Compose overrides this via the
# WORKFLOWS_DIR env var to /app/workflows, matching where the ./workflows
# volume gets mounted (see docker-compose.yml) — the container has no
# repo-root sibling structure for a parents[]-based path to find.
_DEFAULT_WORKFLOWS_DIR = str(Path(__file__).resolve().parents[3] / "workflows")


class Settings(BaseSettings):
    """Central application configuration, loaded from environment variables.

    Never hardcode secrets here — every sensitive value must come from the
    environment (see .env.example). This class only defines names, types,
    and safe non-sensitive defaults for local development.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "Meridian Flow"
    environment: str = "local"
    log_level: str = "INFO"

    # Database
    # Host port 5433 (not 5432) — matches docker-compose.yml's db service
    # mapping, chosen to avoid colliding with any other Postgres already
    # running on the host machine. This default only matters when no .env
    # is present at all (e.g. running the backend outside Docker without
    # having created one yet) — see .env.example for the value actually
    # meant to be used.
    database_url: str = "postgresql+psycopg://meridian:meridian@localhost:5433/meridian_flow"

    # Workflow definitions — see app/services/workflows/definition_loader.py
    workflows_dir: str = _DEFAULT_WORKFLOWS_DIR

    # Auth — see docs/architecture/authentication.md
    jwt_secret_key: str = "change-me-in-env"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # 8 hours

    # AI — see docs/architecture/mcp-architecture.md
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-nano"

    # MCP
    mcp_server_url: str = "http://mcp_server:8100"
    mcp_mock_mode: bool = True

    # External integrations — mock mode defaults true, see docs/architecture/integration-strategy.md
    jira_base_url: str = ""
    jira_api_token: str = ""
    jira_email: str = ""
    slack_bot_token: str = ""
    google_calendar_credentials_json: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
