"""Reads workflows/*.json, validates each against WorkflowDefinitionSchema,
and upserts the result into WorkflowDefinition. Called from seed.py's
run_all_seeds() — same "safe to run on every container startup" idempotency
requirement as the rest of that module (see seed.py's module docstring).

Where the directory comes from: Settings.workflows_dir (see
app/core/config.py) — a repo-root-relative default for local/venv runs,
overridden to /app/workflows by Docker Compose's volume mount. Not derived
from this file's own path, because that breaks the moment this file's
location inside the container (/app/app/services/workflows/...) stops
lining up with the repo's on-disk layout.
"""

import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories import workflow_definition_repo
from app.schemas.workflow_definition import WorkflowDefinitionSchema


class WorkflowDefinitionLoadError(Exception):
    """Raised when a workflows/*.json file fails to parse or fails schema
    validation. Deliberately not an AppError — this happens at
    startup/seed time, outside any HTTP request, so there's no response to
    shape. It should fail loudly and stop the container from starting with
    a broken workflow definition rather than silently skip it."""


def _load_file(path: Path) -> WorkflowDefinitionSchema:
    try:
        raw = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise WorkflowDefinitionLoadError(f"{path.name}: invalid JSON — {exc}") from exc
    try:
        return WorkflowDefinitionSchema.model_validate(raw)
    except ValidationError as exc:
        raise WorkflowDefinitionLoadError(
            f"{path.name}: schema validation failed — {exc}"
        ) from exc


def load_all_definitions(db: Session) -> dict[str, int]:
    """Loads every workflows/*.json file, validates it, and upserts it as a
    WorkflowDefinition row. Returns counts for the caller to log (matches
    the pattern every seed_* function in seed.py follows).

    Upsert logic: if the currently-active row for a given key already
    matches this file's version, do nothing (idempotent — running this on
    every container start doesn't create duplicate rows). If a file's
    version differs from what's active, the old row is deactivated and a
    new one inserted — see WorkflowDefinition's docstring for why "one
    active row per key" is an application-level rule, not a DB constraint.
    """
    workflows_dir = Path(get_settings().workflows_dir)
    if not workflows_dir.is_dir():
        raise WorkflowDefinitionLoadError(
            f"workflows directory not found: {workflows_dir} "
            "(check WORKFLOWS_DIR / the docker-compose volume mount)"
        )

    created = 0
    unchanged = 0
    for path in sorted(workflows_dir.glob("*.json")):
        schema = _load_file(path)
        existing = workflow_definition_repo.get_active_by_key(db, schema.workflow_key)
        if existing is not None and existing.version == schema.version:
            unchanged += 1
            continue
        if existing is not None:
            workflow_definition_repo.deactivate(db, existing)
        workflow_definition_repo.create(
            db,
            key=schema.workflow_key,
            name=schema.name,
            version=schema.version,
            trigger_type=schema.trigger_type,
            trigger_event=schema.trigger_event,
            definition_json=schema.model_dump(mode="json"),
            is_active=True,
        )
        created += 1
    return {"created": created, "unchanged": unchanged}
