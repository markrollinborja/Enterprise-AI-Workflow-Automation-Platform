"""Logging configuration — one place, so every module gets consistent output.

v1 shipped a plain formatted stream handler and this docstring promised that
"swapping in JSON structured logging later only means changing this
function". Phase 1 of v2 collects on that promise: `LOG_FORMAT=json` emits
one JSON object per line with the correlation ID attached to every record,
which is what makes logs joinable against traces and against the support
console (Module 7/8). `LOG_FORMAT=text` keeps v1's human-readable output for
local debugging, because reading JSON in a terminal is miserable.

The correlation ID is injected by a logging *filter*, not by asking call
sites to pass it. Call sites keep doing `logging.getLogger(__name__).info(...)`
exactly as they do today — no existing log statement in the codebase needs to
change for correlation to start working. See app/core/correlation.py.
"""

import json
import logging
import sys
from typing import Any

from app.core.config import get_settings
from app.core.correlation import get_correlation_id

# LogRecord attributes that are part of the logging machinery itself. Anything
# on a record that isn't in here was attached by a caller via `extra={...}`
# and is therefore application context worth emitting — that's how a service
# adds provider/operation/organization fields to a line without this module
# needing to know they exist.
_STANDARD_RECORD_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        # Added by CorrelationIdFilter below; emitted explicitly, so it must
        # not also be picked up as a caller-supplied extra.
        "correlation_id",
    }
)


class CorrelationIdFilter(logging.Filter):
    """Attaches the current correlation ID to every record.

    A filter rather than a formatter concern because both formatters need it
    and because `record.correlation_id` then exists for any future handler
    (an OTel log exporter, a file handler) without further plumbing.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Hand-rolled rather than pulling in structlog or python-json-logger: the
    requirement is a flat object with a fixed core set of keys plus whatever
    `extra` the caller passed, which is ~30 lines. A logging dependency that
    every module transitively imports is worth avoiding when the thing it
    replaces is this small (and it's one less pin to keep current).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "-"),
        }

        # Caller-supplied `extra={...}` fields — provider, operation,
        # organization_id, workflow_instance_id, and so on. Emitted as
        # top-level keys so they are directly queryable in Loki rather than
        # buried inside a stringified message.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # default=str so a stray UUID, datetime, or Enum in an `extra` can
        # never turn a log call into a TypeError. Losing exact typing in the
        # log output is strictly better than losing the log line.
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    """Configure root logging from settings. Safe to call more than once."""
    settings = get_settings()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.addFilter(CorrelationIdFilter())

    if settings.log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | [%(correlation_id)s] | %(message)s"
            )
        )

    root = logging.getLogger()
    root.setLevel(settings.log_level)
    # Replace rather than append. configure_logging() runs at import of
    # app.main, and again in the worker entrypoint; without this, running
    # both in one process (or importing app.main twice under pytest) would
    # duplicate every log line once per extra handler.
    root.handlers = [handler]
