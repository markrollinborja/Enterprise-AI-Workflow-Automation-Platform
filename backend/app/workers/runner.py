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
from app.services.workflows.service import advance_workflow

logger = logging.getLogger(__name__)

# See background-jobs.md — 2-5s is an accepted latency tradeoff for a
# system gated on human approvals, not sub-second-critical execution.
POLL_INTERVAL_SECONDS = 3


def poll_once() -> int:
    """Runs one poll cycle: find every instance that's ready to advance and
    call advance_workflow on each. Returns the count processed — a plain
    int return (not the instances themselves) because the worker only
    cares that this ran, not what came back; tests call this directly to
    assert on DB state afterward instead of on this return value."""
    db = SessionLocal()
    try:
        instances = workflow_instance_repo.list_ready_to_advance(db)
        for instance in instances:
            try:
                advance_workflow(db, instance)
            except Exception:
                # One instance's bug must not take down the poll loop for
                # every other instance — log and move on. A real production
                # version would also write an AuditLog row here (Phase 13);
                # V1's worker isn't wired to the audit service yet.
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
