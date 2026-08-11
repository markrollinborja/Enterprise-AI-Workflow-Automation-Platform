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
    # "json" or "text" (see app/core/logging.py). Defaults to text because
    # the common case for this value is a developer watching `docker compose
    # logs` on their own machine, and JSON is unreadable there. Every
    # deployed/observability path sets json explicitly — docker-compose.yml
    # for the backend and worker services, and the CI job that asserts the
    # JSON shape. Structured logging is the platform default in every context
    # where something machine-reads the output; text is the local-human
    # affordance, not a downgrade.
    log_format: str = "text"

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
    # gpt-4o-mini, not gpt-4.1-nano: observed in a real-mode run that nano
    # is unreliable at this app's bounded agentic tool-calling (it spent
    # both rounds calling lookup_employee instead of answering, tripping
    # the "no parseable response" fallback every time). 4o-mini is still a
    # low-cost model but has much more consistent tool-calling + structured
    # -output behavior — the right "low-cost" tradeoff per the project's
    # cost-conscious-but-reliable requirement, not the cheapest option that
    # technically qualifies.
    openai_model: str = "gpt-4o-mini"
    # The openai SDK's own default is 600s (5s connect + up to 600s total,
    # see openai._constants.DEFAULT_TIMEOUT) — far too generous for a
    # single structured-output completion against a small catalog. A hang
    # that long would sit well outside the engine's own retry/backoff
    # window ([2, 8, 30]s) before the step ever gets a chance to fail and
    # retry. 20s is deliberately tight for this project's call shape, not
    # a general-purpose default (Phase 13, reliability hardening).
    openai_timeout_seconds: float = 20.0

    # Salesforce (V2 Module 2) — see
    # app/services/integrations/providers/salesforce_live.py and
    # docs/architecture/salesforce.md for the org setup this expects.
    #
    # Empty defaults, deliberately: a connection configured for live mode
    # with no credentials must fail as a ProviderConfigurationError with a
    # clear message, not crash at import or silently fall back to the
    # simulator. Absent credentials is a normal state for anyone who cloned
    # this repo without a Salesforce org.
    salesforce_instance_url: str = ""
    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""

    # n8n (V2 Module 3). Shared secret for HMAC-SHA256 over the raw request
    # body on POST /inbound/events. Empty by default and treated as a
    # verification *failure*, never as "verification disabled" — a
    # deployment that forgot to set it must reject traffic loudly rather
    # than quietly accept unauthenticated requests. See
    # app/core/webhook_security.py.
    n8n_webhook_secret: str = ""
    n8n_base_url: str = "http://n8n:5678"
    # No API version setting on purpose — the adapter discovers it from
    # /services/data/. Salesforce ships three releases a year and any
    # pinned version rots into a 404 on a URL that looks correct.

    # MCP — see app/services/integrations/mcp_client.py. The path suffix
    # matters: FastMCP's streamable-http transport mounts the protocol
    # endpoint at /mcp by default (see mcp_server/app/server.py), it isn't
    # served at the bare root.
    mcp_server_url: str = "http://mcp_server:8100/mcp"
    mcp_mock_mode: bool = True
    # The mcp SDK's streamablehttp_client already defaults to timeout=30s,
    # so this isn't closing an unbounded gap — it's replacing an implicit
    # library default with an explicit, intentional one. mcp_server is a
    # same-Docker-network hop returning mock data instantly; 10s is
    # generous for that and still fails fast enough to reach the engine's
    # retry/backoff window instead of stalling a poll cycle (Phase 13).
    mcp_call_timeout_seconds: float = 10.0

    # External integrations — mock mode defaults true, see docs/architecture/integration-strategy.md
    jira_base_url: str = ""
    jira_api_token: str = ""
    jira_email: str = ""
    slack_bot_token: str = ""
    google_calendar_credentials_json: str = ""

    # Shared secret configured on the Jira webhook (ADR-0010) — the
    # webhook route rejects any request whose HMAC-SHA256 signature doesn't
    # match, and refuses to run at all if this is blank (see
    # api/routes/webhooks.py). Blank by default: mock-mode demos never
    # register a real Jira webhook, so this route simply never gets called
    # in that setup.
    jira_webhook_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
