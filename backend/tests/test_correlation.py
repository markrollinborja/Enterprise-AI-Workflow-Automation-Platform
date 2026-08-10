"""Correlation ID plumbing — see app/core/correlation.py.

The point of these tests is not that a UUID gets generated; it is that the
three properties the support console depends on actually hold: an inbound ID
survives the round trip, a missing one is manufactured rather than left
empty, and a hostile one cannot reach a log line or a database column.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.correlation import (
    CORRELATION_ID_HEADER,
    MAX_CORRELATION_ID_LENGTH,
    ensure_correlation_id,
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
)
from app.core.logging import CorrelationIdFilter, JsonFormatter


def test_generated_ids_are_unique_and_prefixed() -> None:
    first, second = new_correlation_id(), new_correlation_id()
    assert first != second
    assert first.startswith("mf-")


def test_context_var_round_trip() -> None:
    set_correlation_id("mf-test-round-trip")
    assert get_correlation_id() == "mf-test-round-trip"


def test_inbound_header_is_preserved(client: TestClient) -> None:
    """The whole point: an ID minted by n8n must be the one this app uses,
    otherwise the two systems' logs can't be joined."""
    response = client.get("/health", headers={CORRELATION_ID_HEADER: "n8n-exec-4417"})
    assert response.headers[CORRELATION_ID_HEADER] == "n8n-exec-4417"


def test_missing_header_gets_a_generated_id(client: TestClient) -> None:
    response = client.get("/health")
    assert response.headers[CORRELATION_ID_HEADER].startswith("mf-")


def test_error_responses_carry_the_correlation_id(client: TestClient) -> None:
    """A user quoting the ID from a failed request is how support finds the
    transaction — so it has to survive the AppError handler, not just the
    happy path."""
    response = client.post(
        "/auth/login", json={"email": "nobody@cordant.io", "password": "wrong"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["correlation_id"] == response.headers[CORRELATION_ID_HEADER]


@pytest.mark.parametrize(
    "hostile",
    [
        "line-one\nINFO fake log entry",  # log injection
        "has spaces",
        "semi;colon",
        "",
        "   ",
        "x" * (MAX_CORRELATION_ID_LENGTH + 1),
    ],
)
def test_hostile_inbound_ids_are_replaced(hostile: str) -> None:
    """Rejected values are *replaced*, never propagated and never fatal — a
    malformed correlation ID is not a reason to fail a valid business
    request."""
    result = ensure_correlation_id(hostile)
    assert result != hostile
    assert result.startswith("mf-")


@pytest.mark.parametrize(
    "acceptable",
    ["mf-abc123", "n8n-exec-4417", "0068d00000AbCdEfGHI", "trace:1234.5678_x"],
)
def test_legitimate_inbound_ids_pass_through(acceptable: str) -> None:
    assert ensure_correlation_id(acceptable) == acceptable


def test_none_produces_a_new_id() -> None:
    assert ensure_correlation_id(None).startswith("mf-")


def test_json_log_line_includes_correlation_id_and_extras() -> None:
    """`extra={...}` must land as top-level JSON keys, not be swallowed or
    stringified into the message — that is what makes them queryable in Loki
    rather than something you regex out of message text."""
    set_correlation_id("mf-log-test")
    record = logging.LogRecord(
        name="app.services.integrations",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="provider call failed",
        args=(),
        exc_info=None,
    )
    CorrelationIdFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert payload["correlation_id"] == "mf-log-test"
    assert payload["level"] == "ERROR"
    assert payload["message"] == "provider call failed"
    assert payload["logger"] == "app.services.integrations"


def test_json_formatter_promotes_extra_fields() -> None:
    set_correlation_id("mf-extra-test")
    record = logging.LogRecord(
        name="app.services.integrations",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="rate limited",
        args=(),
        exc_info=None,
    )
    record.provider = "salesforce"  # type: ignore[attr-defined]
    record.operation = "sync_account"  # type: ignore[attr-defined]
    CorrelationIdFilter().filter(record)
    payload = json.loads(JsonFormatter().format(record))

    assert payload["provider"] == "salesforce"
    assert payload["operation"] == "sync_account"


def test_json_formatter_survives_unserializable_extras() -> None:
    """Losing exact typing in a log line is strictly better than losing the
    log line — a stray UUID or datetime in `extra` must not raise."""
    import uuid

    record = logging.LogRecord(
        name="app",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ok",
        args=(),
        exc_info=None,
    )
    record.workflow_instance_id = uuid.uuid4()  # type: ignore[attr-defined]
    CorrelationIdFilter().filter(record)

    payload = json.loads(JsonFormatter().format(record))
    assert isinstance(payload["workflow_instance_id"], str)
