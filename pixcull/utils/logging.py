import logging
import os
import sys

import structlog


def setup_logging(level: str | None = None) -> None:
    level = level or os.environ.get("PIXCULL_LOG_LEVEL", "INFO")
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def get_logger(name: str = "pixcull"):
    return structlog.get_logger(name)
