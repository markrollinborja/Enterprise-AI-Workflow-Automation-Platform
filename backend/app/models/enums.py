import enum


def enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """Pass as `values_callable` to every SQLAlchemy Enum column, always.

    SQLAlchemy's default behavior for a Python str Enum is to persist the
    member's *name* ("HR") instead of its *value* ("hr") — but every Postgres
    enum type in this project's migrations is defined using the lowercase
    values. Skipping this on Phase 3's User.role column caused every insert
    to fail with "invalid input value for enum" until it was found and
    fixed; this helper exists so that bug can't happen again on a new column.
    """
    return [e.value for e in enum_cls]


class UserRole(str, enum.Enum):
    """The six V1 roles — see docs/architecture/authentication.md and
    docs/decisions/ for why these six and not more (no Finance, no CEO/
    Stakeholder role — neither onboarding nor access-request workflows need
    them)."""

    EMPLOYEE = "employee"
    MANAGER = "manager"
    HR = "hr"
    IT = "it"
    SECURITY = "security"
    ADMINISTRATOR = "administrator"


class EmploymentType(str, enum.Enum):
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACTOR = "contractor"


class EmployeeStatus(str, enum.Enum):
    ACTIVE = "active"
    PENDING = "pending"  # reserved for Phase 6+ onboarding-in-progress state
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


class RiskLevel(str, enum.Enum):
    """Directory-level risk classification. Manually set for now (HR
    judgment call); Phase 8's rules engine will read this field when routing
    approvals, but nothing computes it automatically yet."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TriggerType(str, enum.Enum):
    """How a workflow instance gets started. EVENT = the engine reacts to a
    domain event (e.g. `employee.created`) with no human choosing to start
    it. MANUAL = a user explicitly initiates it (e.g. an employee submitting
    a software access request via a form)."""

    EVENT = "event"
    MANUAL = "manual"


class InstanceStatus(str, enum.Enum):
    """See docs/architecture/workflow-state-model.md for the full transition
    diagram. COMPLETED, FAILED, REJECTED, CANCELLED are terminal — enforced
    in services/workflow/state_machine.py, not left to callers to remember."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_EXTERNAL = "waiting_external"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class StepStatus(str, enum.Enum):
    """Per-step counterpart to InstanceStatus — see the second diagram in
    docs/architecture/workflow-state-model.md. A step's FAILED is terminal
    for that step, but whether the *workflow* fails, continues, or retries
    is a per-step `failure_behavior` decision read from definition_json, not
    encoded here.

    WAITING_EXTERNAL (Phase 10 checkpoint 3, ADR-0010): a mcp_tool step
    whose Jira ticket was created successfully but whose real-world
    completion hasn't been confirmed yet — mirrors InstanceStatus's own
    waiting_external, which workflow-state-model.md documented from Phase 1
    as covering both "retry backoff" and "awaiting async result." Only
    reachable when the step's definition sets awaits_fulfillment=true (see
    StepDefinition); every other mcp_tool step still goes straight to
    COMPLETED on success, same as before."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_EXTERNAL = "waiting_external"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    REJECTED = "rejected"


class StepType(str, enum.Enum):
    """What kind of action a step performs. Deliberately no separate
    "conditional" type — any step can carry an optional `condition` in its
    definition (see app/schemas/workflow_definition.py); a condition that
    evaluates false skips that step regardless of its type."""

    VALIDATION = "validation"
    APPROVAL = "approval"
    AI_ACTION = "ai_action"
    MCP_TOOL = "mcp_tool"


class FailureBehavior(str, enum.Enum):
    """Lives inside definition_json per step, not as a DB column — it's
    configuration the engine reads, never a state a row is "in"."""

    RETRY = "retry"
    FAIL_WORKFLOW = "fail_workflow"
    CONTINUE = "continue"


class ApprovalRequestStatus(str, enum.Enum):
    """Distinct from StepStatus.WAITING_APPROVAL/COMPLETED/REJECTED — this
    is the human-facing record ("is there something in my inbox"), not the
    engine's internal step state. The two are updated together (see
    services/workflows/service.py's approval-pause path and
    services/approvals/service.py's decide()), never independently."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class AITaskType(str, enum.Enum):
    """The value of a StepDefinition's `ai_task` field (see
    app/schemas/workflow_definition.py) — names which structured task
    services/ai/service.py should run for a given ai_action step. Matches
    the workflows/*.json string exactly; also the `task_type` column on
    AIExecution."""

    RECOMMEND_ACCESS_PACKAGE = "recommend_access_package"
    SUMMARIZE_JUSTIFICATION = "summarize_justification"


class AIExecutionStatus(str, enum.Enum):
    """Whether a single AIExecution audit row represents a successful OpenAI
    call (structured output parsed and validated) or a failure (missing API
    key, network/timeout, or a response that didn't validate) — see
    services/ai/service.py's graceful-fallback path."""

    COMPLETED = "completed"
    FAILED = "failed"


class MCPToolCaller(str, enum.Enum):
    """Who invoked an MCP tool — the workflow engine dispatching a scripted
    `mcp_tool` step (create_jira_task, send_slack_notification,
    schedule_calendar_event), or the AI service's own tool-calling loop
    deciding mid-reasoning to call lookup_employee (see mcp-architecture.md,
    "How the AI agent discovers and invokes tools"). Both go through the
    same services/integrations/mcp_client.py wrapper and land in the same
    MCPToolExecution table — this column is what disambiguates a row after
    the fact."""

    WORKFLOW_ENGINE = "workflow_engine"
    AI_AGENT = "ai_agent"


class MCPExecutionStatus(str, enum.Enum):
    """Whether a single MCPToolExecution row represents a successful tool
    call (real or mock mode — both count as "completed", MCPToolExecution's
    own mock_mode column is what tells the two apart) or a failure (MCP
    transport error, the tool itself rejected the input, a real-mode
    external API error)."""

    COMPLETED = "completed"
    FAILED = "failed"


class NotificationType(str, enum.Enum):
    """What happened — see services/notifications/service.py for exactly
    which engine events fire each one. Deliberately three, not one per
    workflow: the *reason* a notification exists is the same regardless of
    which of the two V1 workflows triggered it (an approval landed in your
    queue; a workflow you started finished; a workflow you started was
    rejected), so the type doesn't need to name the workflow."""

    APPROVAL_REQUESTED = "approval_requested"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_REJECTED = "workflow_rejected"


class NotificationChannel(str, enum.Enum):
    """IN_APP is always written. SLACK is sent (via the same
    send_slack_notification MCP tool the engine itself uses — see
    services/notifications/service.py) only for APPROVAL_REQUESTED, the one
    notification type where getting someone's attention *now* actually
    matters. EMAIL is simulated only — formatted and logged/written as its
    own row, never actually sent (no SMTP/Gmail integration in V1, matching
    the project's non-goals) — but is a real, first-class channel value,
    not a placeholder, so a future real sender slots in the same way Slack
    already does."""

    IN_APP = "in_app"
    SLACK = "slack"
    EMAIL = "email"


class NotificationStatus(str, enum.Enum):
    """Per-row delivery outcome for that row's own channel — distinct from
    `Notification.read_at`, which tracks whether the *recipient* has seen an
    IN_APP row, not whether it was ever delivered. A SLACK row can be
    FAILED (the MCP call errored) while the IN_APP row for the same event
    is COMPLETED — each channel gets its own row, so one channel's failure
    never hides that the other one succeeded."""

    COMPLETED = "completed"
    FAILED = "failed"
