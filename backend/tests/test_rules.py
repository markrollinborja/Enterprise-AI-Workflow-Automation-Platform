"""Pure-function tests for services/rules/service.py — no fixtures, no DB,
no app import beyond the enum. If a test here ever needs a Session or a
TestClient, that's a sign business logic leaked out of the rules module,
not a reason to add a fixture.
"""

import pytest

from app.models.enums import RiskLevel
from app.services.rules.service import classify_request_risk, should_auto_approve

LOW, MEDIUM, HIGH = RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH


@pytest.mark.parametrize(
    ("application_risk", "employee_risk", "expected"),
    [
        (LOW, LOW, LOW),
        (LOW, MEDIUM, MEDIUM),
        (LOW, HIGH, HIGH),
        (MEDIUM, LOW, MEDIUM),
        (MEDIUM, MEDIUM, MEDIUM),
        (MEDIUM, HIGH, HIGH),
        (HIGH, LOW, HIGH),
        (HIGH, MEDIUM, HIGH),
        (HIGH, HIGH, HIGH),
    ],
)
def test_classify_request_risk_is_the_max_of_both_inputs(
    application_risk: RiskLevel, employee_risk: RiskLevel, expected: RiskLevel
) -> None:
    assert classify_request_risk(application_risk, employee_risk) == expected


def test_only_low_risk_is_auto_approved() -> None:
    assert should_auto_approve(RiskLevel.LOW) is True
    assert should_auto_approve(RiskLevel.MEDIUM) is False
    assert should_auto_approve(RiskLevel.HIGH) is False
