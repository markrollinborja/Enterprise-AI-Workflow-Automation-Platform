"""Evaluates a step's `condition` string (see StepDefinition.condition)
against the workflow's runtime context, e.g.
`"recommend_access.requires_human_review == true"` or
`"input.application_risk_level in ['medium', 'high']"`.

This is NOT Python's eval()/exec() — arbitrary code execution is an
explicit non-goal (see spec section 23). Instead, the expression is parsed
with the standard library `ast` module and walked by hand, allowing only a
small whitelist of node types: comparisons (==, !=, in, not in), boolean
and/or, attribute access, list literals, and constants. A condition string
containing a function call, an import, a lambda, or anything else outside
that whitelist raises ConditionEvaluationError instead of ever being
executed — the parser sees the full syntax tree before anything runs, so
there's no path from "workflow author writes a condition" to "arbitrary
code runs on the server."

Condition authors write JSON-style literals (`true`/`false`/`null`) rather
than Python's (`True`/`False`/`None`) since workflows/*.json is the
authoring surface and JSON is what its authors think in — see
_LITERAL_NAMES below for how that's reconciled with ast.parse(), which
otherwise treats `true` as a bare (undefined) name.
"""

import ast
from collections.abc import Iterable
from typing import Any

from app.models.workflow import WorkflowInstance, WorkflowStepInstance

_LITERAL_NAMES: dict[str, Any] = {"true": True, "false": False, "null": None}


class ConditionEvaluationError(Exception):
    """Raised for invalid syntax, a disallowed construct, or a reference to
    a name/attribute the context doesn't have (e.g. a condition referencing
    a step that hasn't run yet — see the module docstring in service.py for
    why step ordering makes this a workflow-authoring bug, not a runtime
    race)."""


def build_condition_context(
    instance: WorkflowInstance, steps: Iterable[WorkflowStepInstance]
) -> dict[str, Any]:
    """`input` is the workflow's own input_data; every other top-level name
    is a step_key, mapped to that step's output_data once it has one. A
    step with no output yet (not run, or ran with no output) simply isn't a
    key in this dict — referencing it in a condition raises rather than
    silently evaluating to None, so a workflow author gets a clear error
    instead of a condition that's quietly always false.
    """
    context: dict[str, Any] = {"input": instance.input_data}
    for step in steps:
        if step.output_data is not None:
            context[step.step_key] = step.output_data
    return context


def evaluate_condition(expression: str, context: dict[str, Any]) -> bool:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ConditionEvaluationError(f"invalid condition syntax: {expression!r}") from exc
    return bool(_eval_node(tree.body, expression, context))


def _eval_node(node: ast.AST, expression: str, context: dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.Name):
        if node.id in _LITERAL_NAMES:
            return _LITERAL_NAMES[node.id]
        if node.id not in context:
            raise ConditionEvaluationError(
                f"condition {expression!r} references unknown name {node.id!r}"
            )
        return context[node.id]

    if isinstance(node, ast.Attribute):
        base = _eval_node(node.value, expression, context)
        if not isinstance(base, dict) or node.attr not in base:
            raise ConditionEvaluationError(
                f"condition {expression!r} references unknown attribute {node.attr!r}"
            )
        return base[node.attr]

    if isinstance(node, ast.List):
        return [_eval_node(el, expression, context) for el in node.elts]

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, expression, context)
        result = True
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval_node(comparator, expression, context)
            if isinstance(op, ast.Eq):
                result = result and left == right
            elif isinstance(op, ast.NotEq):
                result = result and left != right
            elif isinstance(op, ast.In):
                result = result and left in right
            elif isinstance(op, ast.NotIn):
                result = result and left not in right
            else:
                raise ConditionEvaluationError(
                    f"condition {expression!r} uses an unsupported comparison operator"
                )
            left = right
        return result

    if isinstance(node, ast.BoolOp):
        values = [_eval_node(value, expression, context) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ConditionEvaluationError(
            f"condition {expression!r} uses an unsupported boolean operator"
        )

    raise ConditionEvaluationError(
        f"condition {expression!r} uses an unsupported expression: {type(node).__name__}"
    )
