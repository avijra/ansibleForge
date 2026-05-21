"""Structured logging configuration using structlog.

Uses QueueHandler + QueueListener so that log I/O (writing to stderr)
happens in a background thread.  The asyncio event loop only ever puts
a record into an in-memory queue — it never blocks on a pipe write.
This prevents the Tauri sidecar pipe back-pressure from stalling the
event loop when log output is heavy.
"""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import queue
import sys

import structlog

_listener: logging.handlers.QueueListener | None = None


def setup_logging(log_level: str = "info") -> None:
    """Configure structlog with non-blocking queue-based log delivery."""
    global _listener

    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    is_tty = hasattr(sys.stderr, "isatty") and sys.stderr.isatty()

    if is_tty:
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
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
        foreign_pre_chain=shared_processors,
    )

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)

    log_queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=10_000)
    queue_handler = logging.handlers.QueueHandler(log_queue)

    if _listener is not None:
        _listener.stop()
    _listener = logging.handlers.QueueListener(
        log_queue, stderr_handler, respect_handler_level=True,
    )
    _listener.start()
    atexit.register(_listener.stop)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(queue_handler)
    root.setLevel(level)

    for noisy in ("httpcore", "httpx", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
