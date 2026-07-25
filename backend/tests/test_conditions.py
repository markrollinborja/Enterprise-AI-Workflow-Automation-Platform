"""No DB fixtures — the evaluator only ever touches the dict it's given,
matching conditions.py's "pure function" design. Includes explicit
security-boundary tests: a condition string containing a function call or
anything else outside the whitelist must raise, never execute.
"""

import pytest

from app.services.workflows.conditions import ConditionEvaluationError, evaluate_condition


def test_evaluates_attribute_equality_against_step_output() -> None:
    context = {"recommend_access": {"requires_human_review": True}}
    assert evaluate_condition("recommend_access.requires_human_review == true", context) is True


def test_evaluates_not_equal_against_input() -> None:
    context = {"input": {"application_risk_level": "medium"}}
    assert evaluate_condition("input.application_risk_level != 'low'", context) is True
    assert evaluate_condition("input.application_risk_level != 'medium'", context) is False


def test_evaluates_in_and_not_in() -> None:
    context = {"input": {"application_risk_level": "high"}}
    assert evaluate_condition("input.application_risk_level in ['medium', 'high']", context) is True
    assert evaluate_condition("input.application_risk_level not in ['low']", context) is True
    assert evaluate_condition("input.application_risk_level in ['low']", context) is False


def test_json_style_literals_true_false_null() -> None:
    context = {"step": {"flag": True, "missing": None}}
    assert evaluate_condition("step.flag == true", context) is True
    assert evaluate_condition("step.flag == false", context) is False
    assert evaluate_condition("step.missing == null", context) is True


def test_bool_and_or() -> None:
    context = {"input": {"a": "x", "b": "y"}}
    assert evaluate_condition("input.a == 'x' and input.b == 'y'", context) is True
    assert evaluate_condition("input.a == 'x' and input.b == 'z'", context) is False
    assert evaluate_condition("input.a == 'z' or input.b == 'y'", context) is True


def test_unknown_name_raises() -> None:
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("nonexistent_step.field == 'x'", {"input": {}})


def test_unknown_attribute_raises() -> None:
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("input.nonexistent_field == 'x'", {"input": {}})


def test_invalid_syntax_raises() -> None:
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition("input.a ===", {"input": {"a": 1}})


@pytest.mark.parametrize(
    "malicious_expression",
    [
        "__import__('os').system('echo pwned')",
        "[1, 2, 3].append(4)",
        "(lambda: 1)()",
        "open('/etc/passwd').read()",
        "input.__class__",
    ],
)
def test_disallowed_constructs_never_execute(malicious_expression: str) -> None:
    """The whole point of parsing with ast instead of eval(): a function
    call, lambda, or dunder-attribute access must be rejected by the
    whitelist, not silently run."""
    with pytest.raises(ConditionEvaluationError):
        evaluate_condition(malicious_expression, {"input": {"a": 1}})
