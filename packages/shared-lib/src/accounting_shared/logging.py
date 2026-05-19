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
    common_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if log_level.upper() == "DEBUG":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
        shared_processors = common_processors
    else:
        renderer = structlog.processors.JSONRenderer()
        shared_processors = [
            *common_processors,
            structlog.processors.format_exc_info,
        ]
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route standard-library loggers through structlog
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ],
        )
    )
    # Remove any existing handlers to avoid duplicate output
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
