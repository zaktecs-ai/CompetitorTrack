"""Structured JSON logging for both processes (§A12).

One line of JSON per record on stdout, which is what the Docker ``json-file``
driver and every log viewer expect. Two rules the rest of the codebase relies on:

* never ``print()`` — ruff's ``T20`` enforces it;
* never log a response body above DEBUG (§A6.3) — bodies can carry merchant
  data and are useless in an incident anyway.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sys
from typing import Any

_RESERVED = frozenset(
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
        "module",
        "msecs",
        "message",
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
    }
)


class JsonFormatter(logging.Formatter):
    """Render a record as a single JSON object."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_") or key in payload:
                continue
            payload[key] = value if _json_safe(value) else repr(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=repr, ensure_ascii=False)


def _json_safe(value: Any) -> bool:
    return isinstance(value, str | int | float | bool | type(None) | list | dict)


def configure_logging(service: str, level: str = "INFO") -> None:
    """Install the JSON handler as the only handler on the root logger.

    Also re-points uvicorn's loggers at it: uvicorn installs its own handlers
    before the application module is imported, which would otherwise produce two
    formats in one stream.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "apscheduler"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # SQLAlchemy's engine logger is noisy at INFO and echoes SQL; keep it at WARNING
    # unless the whole process is in DEBUG.
    if root.level > logging.DEBUG:
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
