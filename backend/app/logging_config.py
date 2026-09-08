"""
Structured logging configuration using structlog.

Why structlog over stdlib logging?
──────────────────────────────────
1. Logs are emitted as JSON in production → parseable by any log aggregator
   (ELK, Datadog, CloudWatch, etc.)
2. Context variables (request_id, user_id, document_id) can be bound once
   and automatically included in every subsequent log line for that request.
3. In development, the same config renders colourful, human-readable output.

Usage in any module:
    import structlog
    logger = structlog.get_logger()
    logger.info("chunk_embedded", chunk_index=3, tokens=214)
"""

import logging
import sys

import structlog

from app.config import settings


def setup_logging() -> None:
    """Call once at app startup to configure structlog + stdlib logging."""

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,       # picks up request_id etc.
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    is_dev = settings.log_level.upper() == "DEBUG"

    if is_dev:
        # Pretty console output for local development
        renderer = structlog.dev.ConsoleRenderer()
    else:
        # Machine-readable JSON for production / Docker
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    # Quiet down noisy libraries
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
