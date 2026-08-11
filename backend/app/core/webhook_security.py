"""HMAC verification for inbound webhooks.

Extracted from api/routes/webhooks.py (V1's Jira handler) when the n8n
ingestion endpoint became the second caller. One implementation, so a fix or
a hardening applies everywhere rather than to whichever copy someone
remembered.

The V1 Jira route is deliberately left calling its own local helper for now:
changing a working, tested security control at the same time as adding a new
caller means a regression there would be indistinguishable from a bug here.
It moves over in Phase 7's hardening pass, with its tests as the safety net.
"""

import hashlib
import hmac

from app.core.exceptions import InvalidWebhookSignatureError


def verify_hmac_signature(
    *,
    raw_body: bytes,
    provided_signature: str | None,
    secret: str,
    caller: str,
) -> None:
    """Raise unless `provided_signature` is a valid HMAC-SHA256 of `raw_body`.

    Verifies against the *raw bytes*, never a re-serialized dict. JSON
    round-tripping changes key order and whitespace, so a signature computed
    over `json.dumps(parsed)` would fail for a legitimate sender roughly
    whenever their formatting differed from ours — an intermittent auth
    failure with no useful error message.

    An unconfigured secret is treated as a signature failure, not as
    "verification disabled". A deployment that forgot to set the secret must
    reject traffic loudly rather than silently accept unauthenticated
    requests, which is the failure mode that turns a config mistake into an
    open endpoint.
    """
    if not secret:
        raise InvalidWebhookSignatureError(f"Webhook signature verification failed for {caller}")

    if not provided_signature:
        raise InvalidWebhookSignatureError(f"Webhook signature verification failed for {caller}")

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    # Senders differ on whether they prefix the digest. Accepting both
    # avoids an integration that fails for a purely cosmetic reason.
    candidate = provided_signature.strip()
    if candidate.lower().startswith("sha256="):
        candidate = candidate[7:]

    # compare_digest, not ==: string equality short-circuits on the first
    # differing byte, which leaks how much of a guess was correct through
    # response timing.
    if not hmac.compare_digest(expected, candidate):
        # Identical message for every failure mode — missing secret, missing
        # header, wrong digest. An attacker probing the endpoint should not
        # be able to tell "not configured" from "wrong signature".
        raise InvalidWebhookSignatureError(f"Webhook signature verification failed for {caller}")
