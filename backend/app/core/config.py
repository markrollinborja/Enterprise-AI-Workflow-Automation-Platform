from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    database_url: str = "postgresql+psycopg://meridian:meridian@localhost:5432/meridian_flow"

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
