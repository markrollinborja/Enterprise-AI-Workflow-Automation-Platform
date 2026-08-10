"""Provider failure classification and redaction — see
app/core/provider_errors.py.

Two things are being defended here. First, that `is_retryable` says what the
workflow engine needs it to say, because retrying a permanent failure burns
the retry budget and delays the real escalation. Second, that no credential
can reach a log line, a database column, or the support console — which is
tested by throwing realistic provider error bodies at it, not toy strings.
"""

import pytest

from app.core.provider_errors import (
    MAX_ERROR_SUMMARY_LENGTH,
    PermanentProviderError,
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    TransientProviderError,
    classify_status,
    redact_mapping,
    redact_text,
    summarize,
)


class TestRetryClassification:
    def test_transient_is_retryable(self) -> None:
        assert TransientProviderError("upstream 503").is_retryable is True

    def test_permanent_is_not_retryable(self) -> None:
        assert PermanentProviderError("unknown field Foo__c").is_retryable is False

    def test_rate_limit_is_transient_and_carries_provider_guidance(self) -> None:
        exc = ProviderRateLimitError("429 Too Many Requests", retry_after_seconds=30)
        assert exc.is_retryable is True
        assert exc.retry_after_seconds == 30

    def test_configuration_error_is_permanent(self) -> None:
        """"Never set up correctly" is a different remedy from "provider
        broke", and neither retrying nor escalating to the provider helps."""
        assert ProviderConfigurationError("no base URL configured").is_retryable is False

    def test_expired_token_is_retryable_but_revoked_grant_is_not(self) -> None:
        """The one case where the same HTTP status means opposite things: a
        refresh fixes an expired token, nothing fixes a revoked grant."""
        assert ProviderAuthError("token expired", refreshable=True).is_retryable is True
        assert ProviderAuthError("grant revoked", refreshable=False).is_retryable is False

    def test_timeout_is_transient(self) -> None:
        assert ProviderTimeoutError("read timeout after 20s").is_retryable is True


class TestStatusMapping:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (400, PermanentProviderError),
            (404, PermanentProviderError),
            (409, PermanentProviderError),
            (422, PermanentProviderError),
            (408, ProviderTimeoutError),
            (429, ProviderRateLimitError),
            (500, TransientProviderError),
            (503, TransientProviderError),
            (504, ProviderTimeoutError),
            (401, ProviderAuthError),
            (403, ProviderAuthError),
        ],
    )
    def test_known_statuses(self, status: int, expected: type[ProviderError]) -> None:
        assert classify_status(status) is expected

    def test_unknown_server_error_gets_one_more_attempt(self) -> None:
        assert classify_status(599) is TransientProviderError

    def test_unknown_client_error_is_permanent(self) -> None:
        """An unrecognized 4xx is our bug and will not fix itself on retry."""
        assert classify_status(418) is PermanentProviderError


class TestRedaction:
    @pytest.mark.parametrize(
        "raw",
        [
            "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payloadpart.sigpart",
            "request failed with access_token=00D5g000004abcXYZ!ArIAQD",
            'body: {"client_secret": "s3cr3t-value-here"}',
            "slack rejected xoxb-FIXTURE-NOT-A-REAL-TOKEN-VALUE",
            "refresh_token: not-a-real-refresh-token-fixture",
        ],
    )
    def test_secrets_are_stripped_from_free_text(self, raw: str) -> None:
        assert "[REDACTED]" in redact_text(raw)

    def test_bare_jwt_in_an_error_body_is_stripped(self) -> None:
        body = "invalid token eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NX0.dBjftJeZ4CVPmB92K"
        assert "eyJhbGciOiJSUzI1NiJ9" not in redact_text(body)

    def test_ordinary_error_text_is_left_readable(self) -> None:
        """Over-redaction is the safe direction, but an error nobody can read
        is its own failure — the common case must survive intact."""
        message = "INVALID_FIELD: No such column 'Foo__c' on entity 'Account'"
        assert redact_text(message) == message

    def test_secret_keys_are_redacted_wholesale(self) -> None:
        payload = {
            "client_id": "meridian-flow",
            "client_secret": "abcdef123456",
            "authorization": "Bearer abc.def.ghi",
            "account_name": "Cordant Industries",
        }
        result = redact_mapping(payload)
        assert result["client_secret"] == "[REDACTED]"
        assert result["authorization"] == "[REDACTED]"
        assert result["account_name"] == "Cordant Industries"

    def test_redaction_recurses_into_nested_structures(self) -> None:
        """Provider error bodies nest. A secret two levels down is still a
        secret."""
        payload = {
            "request": {
                "headers": {"Authorization": "Bearer eyJab.cdef.ghij"},
                "records": [{"api_key": "k-123456789"}, {"name": "safe"}],
            }
        }
        result = redact_mapping(payload)
        assert result["request"]["headers"]["Authorization"] == "[REDACTED]"
        assert result["request"]["records"][0]["api_key"] == "[REDACTED]"
        assert result["request"]["records"][1]["name"] == "safe"

    def test_non_string_values_pass_through_unharmed(self) -> None:
        result = redact_mapping({"attempt": 3, "ok": False, "ratio": 0.5, "nothing": None})
        assert result == {"attempt": 3, "ok": False, "ratio": 0.5, "nothing": None}


class TestConstructionTimeSafety:
    def test_message_is_redacted_at_construction(self) -> None:
        """There must be no path to the unredacted string once the exception
        exists — call sites cannot leak what they cannot reach."""
        exc = ProviderError("failed: Authorization: Bearer eyJab.cdef.ghij")
        assert "eyJab" not in exc.message
        assert "[REDACTED]" in exc.message

    def test_message_is_length_bounded(self) -> None:
        """One pathological HTML error page must not bloat every row of the
        connections table."""
        exc = ProviderError("x" * 5000)
        assert len(exc.message) == MAX_ERROR_SUMMARY_LENGTH

    def test_log_context_is_uniformly_shaped(self) -> None:
        """Identical shape across every provider failure is what makes
        "error rate by provider" a query instead of a regex."""
        exc = ProviderRateLimitError(
            "429", provider="salesforce", operation="sync_account", status_code_from_provider=429
        )
        assert exc.log_context() == {
            "provider": "salesforce",
            "operation": "sync_account",
            "error_type": "ProviderRateLimitError",
            "retryable": True,
            "provider_status": 429,
        }

    def test_provider_errors_surface_as_502_not_500(self) -> None:
        """A spike of 502s points at a provider; a spike of 500s points at
        us. That distinction is worth preserving at the HTTP edge."""
        assert ProviderError.status_code == 502


class TestSummarize:
    def test_summarizes_arbitrary_exceptions(self) -> None:
        """The thing that killed a provider call is frequently not one of
        ours — an httpx timeout, a JSON decode error — and the console still
        has to render something honest."""
        assert summarize(ValueError("bad json at line 1")) == "ValueError: bad json at line 1"

    def test_summary_is_redacted(self) -> None:
        assert "eyJab" not in summarize(RuntimeError("Bearer eyJab.cdef.ghij rejected"))

    def test_summary_is_length_bounded(self) -> None:
        assert len(summarize(RuntimeError("y" * 5000))) == MAX_ERROR_SUMMARY_LENGTH
