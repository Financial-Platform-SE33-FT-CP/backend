"""Structured logging configuration via ``structlog``."""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(log_level: str = "DEBUG") -> None:
    """Configure structlog with sensible defaults.

    Uses ``structlog.dev.ConsoleRenderer`` when *log_level* is ``DEBUG``
    (human-friendly output), and ``structlog.processors.JSONRenderer`` for
    higher log levels (machine-parseable JSON).
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    if log_level.upper() == "DEBUG":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            renderer,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route standard-library loggers through structlog
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processors=shared_processors + [renderer],
    ))
    # Remove any existing handlers to avoid duplicate output
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
