"""Structured logging configuration for auditable API and worker events."""

from __future__ import annotations

import logging
import sys

import structlog


def configureLogging() -> None:
    """Configure JSON logs without leaking raw document or query content."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def getLogger(componentName: str) -> structlog.stdlib.BoundLogger:
    """Return a logger bound to a stable component identifier."""
    if not componentName.strip():
        raise ValueError("componentName cannot be empty")
    return structlog.get_logger(component=componentName)
