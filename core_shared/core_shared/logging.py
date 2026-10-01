"""
Shared structured logging configuration for Lifecontour.

Provides consistent, structured logging across all services (backend, workers)
with support for trace/job/worker IDs and JSON output for production.
"""

import logging
from contextvars import ContextVar
from typing import Any

import structlog
from structlog.types import EventDict

# Context variables for request/job tracing
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
job_id_var: ContextVar[str] = ContextVar("job_id", default="")
worker_id_var: ContextVar[str] = ContextVar("worker_id", default="")


def add_trace_context(
    _logger: Any, _method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Add tracing context to every log entry.

    Includes trace_id, job_id, and worker_id from context variables.
    Empty strings are used when context is not set.
    """
    trace_id = trace_id_var.get()
    job_id = job_id_var.get()
    worker_id = worker_id_var.get()

    # Only add non-empty values to avoid cluttering logs
    if trace_id:
        event_dict["trace_id"] = trace_id
    if job_id:
        event_dict["job_id"] = job_id
    if worker_id:
        event_dict["worker_id"] = worker_id

    return event_dict


def configure_logging(
    log_level: str = "INFO",
    service_name: str = "personal-management",
    json_output: bool = True,
) -> None:
    """
    Configure structured logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        service_name: Name of the service for log identification
        json_output: Whether to output JSON (True) or console-friendly format (False)
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, log_level.upper()),
    )

    # Build processor chain
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        add_trace_context,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Add final renderer based on output format
    if json_output:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Add service name to all logs
    structlog.contextvars.bind_contextvars(service=service_name)


def get_logger(name: str = __name__) -> Any:
    """
    Get a structured logger instance.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Structured logger instance
    """
    return structlog.get_logger(name)


def set_trace_id(trace_id: str) -> None:
    """Set the trace ID for the current context."""
    trace_id_var.set(trace_id)


def set_job_id(job_id: str) -> None:
    """Set the job ID for the current context."""
    job_id_var.set(job_id)


def set_worker_id(worker_id: str) -> None:
    """Set the worker ID for the current context."""
    worker_id_var.set(worker_id)


def clear_context() -> None:
    """Clear all context variables."""
    trace_id_var.set("")
    job_id_var.set("")
    worker_id_var.set("")


__all__ = [
    "configure_logging",
    "get_logger",
    "set_trace_id",
    "set_job_id",
    "set_worker_id",
    "clear_context",
    "trace_id_var",
    "job_id_var",
    "worker_id_var",
]
