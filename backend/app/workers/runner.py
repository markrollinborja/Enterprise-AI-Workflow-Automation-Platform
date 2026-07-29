"""Polling worker entrypoint: `python -m app.workers.runner`.

Same codebase, same DB, same service-layer code as the API (see
docs/architecture/background-jobs.md and ADR-0002) — this process is a
scheduler, not a second implementation of workflow execution. Every line
that actually runs a step lives in services/workflows/service.py and
behaves identically whether it's called from here or from
start_workflow/resume_workflow_step.
"""

import logging
import time

from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.repositories import workflow_instance_repo
from app.services.workflows.service import try_advance_workflow

logger = logging.getLogger(__name__)

# See background-jobs.md — 2-5s is an accepted latency tradeoff for a
# system gated on human approvals, not sub-second-critical execution.
POLL_INTERVAL_SECONDS = 3


def poll_once() -> int:
    """Runs one poll cycle: find every instance that's ready to advance and
    call try_advance_workflow on each. Returns the count of instances the
    query matched — not the count actually advanced, since
    try_advance_workflow (Phase 13) skips any instance whose advisory lock
    is already held by a concurrent API request's own inline
    advance_workflow call, deliberately, rather than racing it (see
    services/workflows/service.py's advance_workflow docstring for why a
    lock was needed at all). A skipped instance just gets picked up on the
    next 3-second tick instead. Tests call this directly to assert on DB
    state afterward instead of on this return value."""
    db = SessionLocal()
    try:
        instances = workflow_instance_repo.list_ready_to_advance(db)
        for instance in instances:
            try:
                try_advance_workflow(db, instance)
            except Exception:
                # One instance's bug must not take down the poll loop for
                # every other instance — log and move on. This is a crash
                # in advance_workflow itself (e.g. an unhandled exception
                # before it could cleanly transition the step to FAILED),
                # distinct from a normal step failure — those already get
                # recorded via the step's own FAILED transition and show up
                # in the Audit Log page (Phase 12) through the ordinary
                # WorkflowEvent/AIExecution/MCPToolExecution rows. This
                # log-and-continue behavior is the actual crash-isolation
                # feature for the poll loop, not a placeholder for one.
                logger.exception("advance_workflow failed for instance %s", instance.id)
        return len(instances)
    finally:
        db.close()


def run_forever() -> None:
    configure_logging()
    logger.info("workflow worker started, polling every %ss", POLL_INTERVAL_SECONDS)
    while True:
        poll_once()
        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_forever()
