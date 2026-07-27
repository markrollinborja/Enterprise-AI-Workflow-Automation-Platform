"""Deterministic business rules — the "rules before AI" leaf module (see
docs/architecture/service-boundaries.md and ADR-0004). No DB session, no
I/O, nothing here can fail except on bad input: every function is plain
input-in/decision-out and trivially unit-testable (tests/test_rules.py)
with nothing more than enum values.

What this module decides vs. what it doesn't: it computes WHAT the overall
risk of a request is and WHETHER that risk clears the bar for automatic
approval. It does NOT decide which specific approval steps run for a given
risk level — that routing already lives in
workflows/software_access_request.json's own step `condition` strings,
evaluated by services/workflows/conditions.py. Keeping that split (rules
decide the risk, workflow JSON routes on it) means there's exactly one
place that encodes "medium risk needs IT, high risk needs IT and security,"
not two definitions that could quietly drift apart.
"""

from app.models.enums import RiskLevel

_RISK_ORDER: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
}


def classify_request_risk(application_risk: RiskLevel, employee_risk: RiskLevel) -> RiskLevel:
    """An access request's overall risk is the higher of the two inputs —
    "highest wins," not an average or a weighted score. A low-risk
    application requested by a high-risk employee (someone in a sensitive
    role) is still a request worth scrutinizing, and a high-risk
    application requested by a low-risk employee is still high-risk on the
    strength of the application alone. This is the simplest rule that's
    still defensible to a security reviewer, which is the actual bar for a
    V1 rules engine — not maximum sophistication.
    """
    return max(application_risk, employee_risk, key=lambda risk: _RISK_ORDER[risk])


def should_auto_approve(risk: RiskLevel) -> bool:
    """Only a LOW overall risk request skips human approval entirely.
    Medium and high always require at least a manager's sign-off — see
    `manager_approval`'s condition in workflows/software_access_request.json,
    which reads this decision back out of the workflow's own input_data
    rather than re-deriving it."""
    return risk == RiskLevel.LOW
