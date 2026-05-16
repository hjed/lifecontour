"""
Snipe-IT Integration Worker.

ARQ worker process that handles Snipe-IT integration tasks including
gear item sync, maintenance sync, and checkout operations.

This is the entry-point for the worker container. Actual task
implementations will be added in subsequent phases.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import structlog
from arq.connections import RedisSettings

from snipeit_settings import SnipeItWorkerSettings

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

settings = SnipeItWorkerSettings()  # type: ignore[call-arg]

log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(log_level),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# ARQ lifecycle hooks
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:  # type: ignore[type-arg]
    """Initialise shared resources on worker startup."""
    logger.info("snipeit-worker starting", worker_id=settings.worker_id)

    from core_shared.database import create_session_factory

    from stream_consumer_tasks import run_snipeit_stream_consumer

    session_factory = create_session_factory(settings.database_url)
    ctx["session_factory"] = session_factory

    # Start stream consumer for webhooks and domain events
    consumer_task = asyncio.create_task(
        run_snipeit_stream_consumer(
            session_factory=session_factory,
            redis_url=settings.redis_url,
            stream_name=settings.stream_name,
        )
    )
    ctx["stream_consumer_task"] = consumer_task


async def shutdown(ctx: dict) -> None:  # type: ignore[type-arg]
    """Clean up shared resources on worker shutdown."""
    logger.info("snipeit-worker shutting down", worker_id=settings.worker_id)

    # Stop the stream consumer
    consumer_task = ctx.get("stream_consumer_task")
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Stream consumer task failed with an exception", error=str(e))


# ---------------------------------------------------------------------------
# ARQ worker configuration
# ---------------------------------------------------------------------------


def _parse_redis_url(url: str) -> RedisSettings:
    """Convert a ``redis://`` URL into ARQ ``RedisSettings``."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


class WorkerSettings:
    """ARQ worker settings for the Snipe-IT integration worker."""

    # Task functions — populated as phases are implemented
    functions: list = []  # type: ignore[type-arg]

    on_startup = startup
    on_shutdown = shutdown

    # Retry / DLQ configuration
    max_tries = 5
    job_timeout = 300
    keep_result = 3600
    health_check_interval = 30

    # Queue name scoped to this worker
    queue_name = "arq:snipeit"

    redis_settings = _parse_redis_url(settings.redis_url)


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from arq import run_worker

    logger.info("Starting Snipe-IT worker process")
    sys.exit(run_worker(WorkerSettings))  # type: ignore[arg-type]
