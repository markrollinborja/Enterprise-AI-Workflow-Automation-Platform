"""The real AI service — replaces execute_ai_action_stub's placeholder
output with an actual OpenAI call, for the two ai_action tasks that exist
in V1 (see AITaskType): recommending an access package during onboarding,
and summarizing an access request's justification.

Design commitments, all deliberate (see the Phase 9 discussion in project
history / docs/architecture/service-boundaries.md's "ai" section):

- Structured outputs only (Pydantic response_format), never free-text
  parsed by hand — an unvalidatable response is treated as a failure, not
  "best effort" parsing.
- recommend_access_package's output is structurally constrained to the
  *current* AccessPackage catalog (a dynamically-built Literal enum, not
  just a prompt instruction) — the model cannot return a package that
  doesn't exist. This is Principle 2 ("AI narrows a catalog, it doesn't
  invent a grant") enforced by the type system, not just asked for nicely.
- Every call, success or failure, writes one AIExecution row (Principle 4).
- Any failure (no API key configured, network error, timeout, a response
  that fails validation) is caught and turned into a StepExecutionResult
  the workflow engine's existing retry/fail/continue machinery already
  knows how to handle — see executors.py. No new failure-handling code
  needed at the engine level; this is the payoff of that seam existing.
- Confidence threshold (0.7) is a named constant, not hidden in a
  conditional, and is explicitly an approximation — an LLM's self-reported
  confidence is not a calibrated probability. Worth saying plainly rather
  than presenting this as more rigorous than it is.
- Does NOT call MCP for employee lookup, despite the original Phase 1
  service-boundaries.md sketch describing that. Standing up the real MCP
  server (Phase 10) a full phase early, to serve one internal read, isn't
  worth it — this calls employee_repo directly. Revisit when Phase 10
  builds lookup_employee for real; swapping this one call over is a
  one-line change, not a redesign.
"""

from dataclasses import dataclass
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, create_model
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import AIExecutionStatus, AITaskType
from app.models.workflow import WorkflowInstance, WorkflowStepInstance
from app.repositories import access_package_repo, ai_execution_repo, employee_repo

# LLM self-reported confidence is not a calibrated probability — this is an
# approximation, chosen and documented as one, not tuned against real data
# (there isn't any yet). Below this, a step whose `requires_review` is
# enabled routes to a human regardless of what the model recommended.
_CONFIDENCE_THRESHOLD = 0.7


@dataclass
class AIActionResult:
    """What services/workflows/executors.py translates into a
    StepExecutionResult — kept separate from that dataclass so this module
    has zero dependency on the workflows package (see the module docstring:
    executors.py depends on ai/service.py, never the other way around)."""

    status: Literal["completed", "failed"]
    output_data: dict[str, Any] | None = None
    error_message: str | None = None


class JustificationSummaryOutput(BaseModel):
    summary: str
    confidence_score: float = Field(ge=0, le=1)
    explanation: str


def _build_recommendation_model(package_names: list[str]) -> type[BaseModel]:
    """Builds a Pydantic model per call, constraining
    `recommended_package_name` to a Literal of exactly the *current*
    AccessPackage catalog. OpenAI's structured-output support turns a
    Literal into a JSON-schema enum, so this isn't merely a prompt
    instruction the model could ignore — a response naming any other value
    fails schema validation before it ever reaches this service's code."""
    # mypy can't verify a Literal built from a runtime tuple (it wants
    # compile-time-literal arguments) — this is correct at runtime, which
    # is what actually matters here; every consumer of the returned model
    # only sees it as `type[BaseModel]`.
    package_name_type = Literal[tuple(package_names)]  # type: ignore[valid-type]
    return create_model(
        "AccessPackageRecommendationOutput",
        recommended_package_name=(package_name_type, ...),
        confidence_score=(float, Field(ge=0, le=1)),
        explanation=(str, ...),
        # Same class of mypy/pydantic limitation as package_name_type above:
        # create_model's field tuples aren't a class body, so the pydantic
        # mypy plugin can't use the surrounding `list[str]` to specialize
        # Field's default_factory overload, and falls back to `Never`.
        # Correct at runtime (an empty list of the declared type).
        missing_information=(list[str], Field(default_factory=list)),  # type: ignore[arg-type]
    )


def _client() -> OpenAI:
    return OpenAI(api_key=get_settings().openai_api_key)


def execute_ai_task(
    db: Session,
    *,
    ai_task: str,
    step_row: WorkflowStepInstance,
    instance: WorkflowInstance,
    context: dict[str, Any],
    requires_review_enabled: bool,
) -> AIActionResult:
    if ai_task == AITaskType.RECOMMEND_ACCESS_PACKAGE.value:
        return _recommend_access_package(
            db,
            step_row=step_row,
            instance=instance,
            requires_review_enabled=requires_review_enabled,
        )
    if ai_task == AITaskType.SUMMARIZE_JUSTIFICATION.value:
        return _summarize_justification(
            db,
            step_row=step_row,
            instance=instance,
            context=context,
            requires_review_enabled=requires_review_enabled,
        )
    raise ValueError(f"unknown ai_task: {ai_task!r}")


def _recommend_access_package(
    db: Session,
    *,
    step_row: WorkflowStepInstance,
    instance: WorkflowInstance,
    requires_review_enabled: bool,
) -> AIActionResult:
    settings = get_settings()
    task_type = AITaskType.RECOMMEND_ACCESS_PACKAGE

    if not settings.openai_api_key:
        return _fail(
            db,
            instance=instance,
            step_row=step_row,
            task_type=task_type,
            input_summary="(not sent — no API key configured)",
            model_used=settings.openai_model,
            error_message="OPENAI_API_KEY is not configured.",
            # Safe default (Phase 6's stub established this pattern): an
            # AI step that couldn't run must never cause a downstream
            # human-review gate to silently skip.
            fallback_output={"requires_human_review": True},
        )

    employee = (
        employee_repo.get_by_id(db, instance.employee_id) if instance.employee_id else None
    )
    if employee is None:
        return _fail(
            db,
            instance=instance,
            step_row=step_row,
            task_type=task_type,
            input_summary="(no employee_id on this workflow instance)",
            model_used=settings.openai_model,
            error_message="No employee record found for this workflow instance.",
            fallback_output={"requires_human_review": True},
        )

    packages = access_package_repo.list_all(db)
    if not packages:
        return _fail(
            db,
            instance=instance,
            step_row=step_row,
            task_type=task_type,
            input_summary="(no AccessPackage catalog rows exist)",
            model_used=settings.openai_model,
            error_message="Access package catalog is empty — nothing to recommend from.",
            fallback_output={"requires_human_review": True},
        )

    input_summary = (
        f"job_title={employee.job_title!r}, department={employee.department.name!r}, "
        f"employment_type={employee.employment_type.value!r}"
    )

    try:
        response_model = _build_recommendation_model([p.name for p in packages])
        catalog_description = "\n".join(
            f"- {p.name} ({p.risk_level.value} risk): {p.description}" for p in packages
        )
        completion = _client().chat.completions.parse(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You recommend exactly one access package from a fixed catalog for a "
                        "newly hired employee, based on their role. You must choose a package "
                        "name that exists in the catalog below — never invent one. Be honest "
                        "about your confidence: a role that maps clearly to one package "
                        "deserves high confidence; an unusual or ambiguous title should get "
                        "lower confidence so a human reviews it.\n\nCatalog:\n"
                        f"{catalog_description}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Employee: {employee.first_name} {employee.last_name}\n"
                        f"Job title: {employee.job_title}\n"
                        f"Department: {employee.department.name}\n"
                        f"Employment type: {employee.employment_type.value}"
                    ),
                },
            ],
            response_format=response_model,
        )
        message = completion.choices[0].message
        if message.refusal or message.parsed is None:
            return _fail(
                db,
                instance=instance,
                step_row=step_row,
                task_type=task_type,
                input_summary=input_summary,
                model_used=settings.openai_model,
                error_message=message.refusal or "Model returned no parseable response.",
                fallback_output={"requires_human_review": True},
            )
        # .model_dump() rather than attribute access: response_model is
        # built dynamically (see _build_recommendation_model), so mypy has
        # no static knowledge of its fields — a dict with known string
        # keys is the honest way to consume a runtime-constructed schema,
        # not a wall of `# type: ignore[attr-defined]`.
        parsed = message.parsed.model_dump()
    except Exception as exc:  # noqa: BLE001 — any failure here must degrade gracefully
        return _fail(
            db,
            instance=instance,
            step_row=step_row,
            task_type=task_type,
            input_summary=input_summary,
            model_used=settings.openai_model,
            error_message=f"{type(exc).__name__}: {exc}",
            fallback_output={"requires_human_review": True},
        )

    recommended_name = parsed["recommended_package_name"]
    confidence_score = float(parsed["confidence_score"])
    recommended_package = next((p for p in packages if p.name == recommended_name), None)
    requires_human_review = requires_review_enabled and confidence_score < _CONFIDENCE_THRESHOLD
    output_data = {
        "recommended_package_id": str(recommended_package.id) if recommended_package else None,
        "recommended_package_name": recommended_name,
        "confidence_score": confidence_score,
        "explanation": parsed["explanation"],
        "missing_information": parsed["missing_information"],
        "requires_human_review": requires_human_review,
    }

    ai_execution_repo.create(
        db,
        workflow_instance_id=instance.id,
        step_instance_id=step_row.id,
        task_type=task_type,
        input_summary=input_summary,
        output_json=output_data,
        confidence_score=confidence_score,
        requires_human_review=requires_human_review,
        model_used=settings.openai_model,
        tokens_used=completion.usage.total_tokens if completion.usage else None,
        status=AIExecutionStatus.COMPLETED,
        error_message=None,
    )
    return AIActionResult(status="completed", output_data=output_data)


def _summarize_justification(
    db: Session,
    *,
    step_row: WorkflowStepInstance,
    instance: WorkflowInstance,
    context: dict[str, Any],
    requires_review_enabled: bool,
) -> AIActionResult:
    settings = get_settings()
    task_type = AITaskType.SUMMARIZE_JUSTIFICATION
    justification = context["input"].get("justification", "")
    risk_level = context["input"].get("application_risk_level", "unknown")
    input_summary = f"risk_level={risk_level!r}, justification={justification[:200]!r}"

    if not settings.openai_api_key:
        return _fail(
            db,
            instance=instance,
            step_row=step_row,
            task_type=task_type,
            input_summary="(not sent — no API key configured)",
            model_used=settings.openai_model,
            error_message="OPENAI_API_KEY is not configured.",
            fallback_output=None,  # nothing downstream reads this step's output
        )

    try:
        completion = _client().chat.completions.parse(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You summarize a software access request's justification in one or "
                        "two sentences for an approver who has not read the original request. "
                        "Be neutral and factual — do not recommend approval or rejection."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Risk level: {risk_level}\nJustification: {justification}",
                },
            ],
            response_format=JustificationSummaryOutput,
        )
        message = completion.choices[0].message
        if message.refusal or message.parsed is None:
            return _fail(
                db,
                instance=instance,
                step_row=step_row,
                task_type=task_type,
                input_summary=input_summary,
                model_used=settings.openai_model,
                error_message=message.refusal or "Model returned no parseable response.",
                fallback_output=None,
            )
        parsed = message.parsed
    except Exception as exc:  # noqa: BLE001
        return _fail(
            db,
            instance=instance,
            step_row=step_row,
            task_type=task_type,
            input_summary=input_summary,
            model_used=settings.openai_model,
            error_message=f"{type(exc).__name__}: {exc}",
            fallback_output=None,
        )

    # This task never gates on review (requires_review is false in both
    # workflows/*.json steps that use it) — requires_review_enabled is
    # accepted for a consistent function signature, not used here.
    del requires_review_enabled
    output_data = {
        "summary": parsed.summary,
        "confidence_score": parsed.confidence_score,
        "explanation": parsed.explanation,
        "requires_human_review": False,
    }
    ai_execution_repo.create(
        db,
        workflow_instance_id=instance.id,
        step_instance_id=step_row.id,
        task_type=task_type,
        input_summary=input_summary,
        output_json=output_data,
        confidence_score=parsed.confidence_score,
        requires_human_review=False,
        model_used=settings.openai_model,
        tokens_used=completion.usage.total_tokens if completion.usage else None,
        status=AIExecutionStatus.COMPLETED,
        error_message=None,
    )
    return AIActionResult(status="completed", output_data=output_data)


def _fail(
    db: Session,
    *,
    instance: WorkflowInstance,
    step_row: WorkflowStepInstance,
    task_type: AITaskType,
    input_summary: str,
    model_used: str,
    error_message: str,
    fallback_output: dict[str, Any] | None,
) -> AIActionResult:
    """Writes the FAILED audit row and returns the AIActionResult
    executors.py turns into a failed StepExecutionResult. `fallback_output`
    is only non-None for recommend_access_package, whose
    requires_human_review a downstream step's condition reads even when
    this step never completed — see _apply_step_result in
    services/workflows/service.py, which now carries output_data forward
    on a failed-with-continue step precisely for this case."""
    ai_execution_repo.create(
        db,
        workflow_instance_id=instance.id,
        step_instance_id=step_row.id,
        task_type=task_type,
        input_summary=input_summary,
        output_json=None,
        confidence_score=None,
        requires_human_review=None,
        model_used=model_used,
        tokens_used=None,
        status=AIExecutionStatus.FAILED,
        error_message=error_message,
    )
    return AIActionResult(
        status="failed", output_data=fallback_output, error_message=error_message
    )
