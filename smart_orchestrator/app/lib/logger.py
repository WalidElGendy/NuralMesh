from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

from app.config import LOKI_URL

try:
    from logging_loki import LokiHandler
except Exception:  # pragma: no cover - optional transport dependency in disabled mode
    LokiHandler = None  # type: ignore[assignment]


class JsonTraceFormatter(logging.Formatter):
    """Format log records as JSON with OpenTelemetry trace context.

    Args:
        None.

    Returns:
        Formatter that injects timestamp, level, logger, trace_id, span_id, message, and extras.

    Cost/quality target:
        Keeps logs queryable in Loki while avoiding prompt-body logging.
    """

    RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

    def format(self, record: logging.LogRecord) -> str:
        """Format one log record.

        Args:
            record: Python logging record.

        Returns:
            JSON string containing trace context and structured extras.

        Cost/quality target:
            Adds trace IDs with minimal overhead when telemetry is disabled.
        """
        span_context = trace.get_current_span().get_span_context()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "trace_id": f"{span_context.trace_id:032x}" if span_context.is_valid else "",
            "span_id": f"{span_context.span_id:016x}" if span_context.is_valid else "",
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and not key.startswith("_"):
                payload[key] = value
        return json.dumps(payload, default=str)


class StructuredLogger:
    """Small structlog-style wrapper over stdlib logging.

    Args:
        logger: Underlying stdlib logger.

    Returns:
        Logger wrapper that accepts keyword extras.

    Cost/quality target:
        Adds structured fields without pulling prompt bodies or changing logging backends.
    """

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, message: str, *args: Any, **kwargs: Any) -> None:
        explicit_extra = kwargs.pop("extra", {}) or {}
        extra = {**explicit_extra, **kwargs}
        self._logger.log(level, message, *args, extra=extra)

    def debug(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, message, *args, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    """Return a JSON logger with optional Loki shipping.

    Args:
        name: Logger name.

    Returns:
        Configured structlog-style logger wrapper.

    Cost/quality target:
        JSON logs with trace IDs; Loki transport only when explicitly enabled.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        formatter = JsonTraceFormatter()
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

        loki_enabled = os.getenv("LOKI_ENABLED", "false").lower() == "true"
        if loki_enabled and LokiHandler is not None:
            loki_handler = LokiHandler(
                url=os.getenv("LOKI_URL", LOKI_URL),
                tags={"service": "neuralmesh-orchestrator"},
                version="1",
            )
            loki_handler.setFormatter(formatter)
            root.addHandler(loki_handler)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return StructuredLogger(logger)
