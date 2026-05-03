#!/usr/bin/env python3
"""
Strava Integration Worker.

This worker processes Strava webhook events and activity sync tasks
using ARQ. It runs as a separate process from the main FastAPI
application and also launches a Redis Streams consumer for domain
event fan-out.
"""

import asyncio
from typing import Any

from arq import run_worker
from arq.connections import RedisSettings
from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared.database.engine import create_session_factory
from core_shared.integration_constants import STRAVA_ARQ_QUEUE_NAME
from core_shared.logging import configure_logging, get_logger
from core_shared.telemetry import setup_telemetry

from strava_settings import StravaSettings

# Global settings instance
settings = StravaSettings()  # type: ignore[call-arg]

# Configure structured logging using shared module
configure_logging(
    log_level=settings.log_level,
    service_name=settings.worker_id,
    json_output=True,
)

logger = get_logger(__name__)


def _on_consumer_task_done(task: asyncio.Task[None]) -> None:
    """Log unhandled exceptions from the stream consumer background task.

    Without this callback, if the consumer task raises, the exception
    goes un-retrieved and the worker silently runs in a degraded state.
    """
    if task.cancelled():
        logger.info("Stream consumer task was cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Stream consumer task failed unexpectedly",
            error=str(exc),
            error_type=type(exc).__name__,
            exc_info=exc,
        )


async def startup(ctx: dict[str, Any]) -> None:
    """
    Worker startup function.

    Initializes database session factory, stream consumer, and other resources.
    """
    logger.info("Strava worker starting up", worker_id=settings.worker_id)

    # Create database session factory
    session_factory = create_session_factory(settings.database_url.get_secret_value())
    ctx["session_factory"] = session_factory
    ctx["settings"] = settings

    # Launch stream consumer for domain event fan-out
    from stream_consumer_tasks import run_strava_stream_consumer

    consumer_task = asyncio.create_task(
        run_strava_stream_consumer(
            session_factory=session_factory,
            redis_url=settings.redis_url,
        )
    )
    consumer_task.add_done_callback(_on_consumer_task_done)
    ctx["stream_consumer_task"] = consumer_task

    logger.info("Strava worker startup complete", worker_id=settings.worker_id)


async def shutdown(ctx: dict[str, Any]) -> None:
    """
    Worker shutdown function.

    Cancels background tasks and cleans up resources.
    """
    logger.info("Strava worker shutting down", worker_id=settings.worker_id)

    # Cancel the stream consumer task
    consumer_task: asyncio.Task[None] | None = ctx.get("stream_consumer_task")
    if consumer_task and not consumer_task.done():
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

    logger.info("Strava worker shutdown complete")


async def process_strava_webhook_event(
    ctx: dict[str, Any],
    event_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Process a Strava webhook event.

    Dispatches to the appropriate handler based on the event's
    ``aspect_type`` (create, update, delete) and ``object_type``.

    Args:
        ctx: ARQ worker context (contains session_factory, settings).
        event_data: Webhook event payload with keys:
            - aspect_type: "create", "update", or "delete"
            - object_type: "activity" or "athlete"
            - object_id: Strava object ID
            - owner_id: Strava athlete ID
            - subscription_id: Webhook subscription ID
            - event_time: Unix timestamp
            - updates: Optional dict of updated fields

    Returns:
        Dict with processing result status.
    """
    aspect_type = event_data.get("aspect_type", "unknown")
    object_type = event_data.get("object_type", "unknown")
    object_id = event_data.get("object_id")
    owner_id = event_data.get("owner_id")

    if object_type != "activity":
        logger.debug(
            "Ignoring non-activity webhook event in worker",
            object_type=object_type,
            aspect_type=aspect_type,
            owner_id=owner_id,
        )
        return {"status": "ignored", "reason": f"object_type={object_type}"}

    logger.info(
        "Processing Strava webhook event",
        aspect_type=aspect_type,
        object_type=object_type,
        object_id=object_id,
        owner_id=owner_id,
    )

    # Dispatch based on aspect_type
    # NOTE: Actual activity sync implementation will be added in ITER5-004.
    # For now, we log the event and return a placeholder result.
    if aspect_type == "create":
        logger.info(
            "Activity created — sync will be implemented in ITER5-004",
            object_id=object_id,
            owner_id=owner_id,
        )
        return {"status": "processed", "aspect_type": "create", "object_id": object_id}

    elif aspect_type == "update":
        logger.info(
            "Activity updated — sync will be implemented in ITER5-004",
            object_id=object_id,
            owner_id=owner_id,
        )
        return {"status": "processed", "aspect_type": "update", "object_id": object_id}

    elif aspect_type == "delete":
        logger.info(
            "Activity deleted — sync will be implemented in ITER5-004",
            object_id=object_id,
            owner_id=owner_id,
        )
        return {"status": "processed", "aspect_type": "delete", "object_id": object_id}

    else:
        logger.warning(
            "Unknown Strava webhook aspect_type",
            aspect_type=aspect_type,
            object_id=object_id,
        )
        return {"status": "ignored", "reason": f"unknown aspect_type={aspect_type}"}


# ARQ Worker Settings
class StravaWorkerSettings(WorkerSettingsBase):
    """ARQ worker configuration."""

    # Task functions
    functions = [process_strava_webhook_event]

    # Worker lifecycle
    on_startup: StartupShutdown = startup
    on_shutdown: StartupShutdown = shutdown

    # Redis settings
    redis_settings = RedisSettings.from_dsn(settings.redis_url)

    # Worker configuration
    max_jobs = 5
    job_timeout = 300  # 5 minutes
    keep_result = 3600  # Keep results for 1 hour

    # Retry configuration
    max_tries = 3

    # Queue name
    queue_name = STRAVA_ARQ_QUEUE_NAME


if __name__ == "__main__":
    # Setup OpenTelemetry
    setup_telemetry(settings)

    # Run the worker
    logger.info("Starting Strava ARQ worker", worker_id=settings.worker_id)
    run_worker(StravaWorkerSettings)
