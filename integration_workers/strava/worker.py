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


async def _resolve_user_for_athlete(
    session_factory: Any, athlete_id: int
) -> tuple[str, dict[str, Any]] | None:
    """Look up user_id and auth data for a Strava athlete_id.

    Args:
        session_factory: SQLAlchemy async session factory.
        athlete_id: Strava numeric athlete ID.

    Returns:
        Tuple of (user_id, auth_dict) or None if not found.
    """
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT user_id, encrypted_access_token, encrypted_refresh_token
                FROM user_strava_auth
                WHERE athlete_id = :athlete_id
                LIMIT 1
            """),
            {"athlete_id": athlete_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return str(row.user_id), {
            "encrypted_access_token": row.encrypted_access_token,
            "encrypted_refresh_token": row.encrypted_refresh_token,
        }


async def _resolve_user_by_id(
    session_factory: Any, user_id: str
) -> dict[str, Any] | None:
    """Look up auth data for a given user_id.

    Args:
        session_factory: SQLAlchemy async session factory.
        user_id: Internal user ID string.

    Returns:
        Auth dict with encrypted tokens, or None if not found.
    """
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT encrypted_access_token, encrypted_refresh_token
                FROM user_strava_auth
                WHERE user_id = :user_id
                LIMIT 1
            """),
            {"user_id": user_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return {
            "encrypted_access_token": row.encrypted_access_token,
            "encrypted_refresh_token": row.encrypted_refresh_token,
        }


def _create_sync_service(
    user_id: str,
    auth_data: dict[str, Any],
    worker_settings: StravaSettings,
) -> Any:
    """Create a StravaSyncService with an authenticated API client.

    Args:
        user_id: Internal user ID.
        auth_data: Dict with encrypted_access_token and encrypted_refresh_token.
        worker_settings: Strava worker settings (contains encryption key, client creds).

    Returns:
        Ready-to-use StravaSyncService.
    """
    from strava_api_client import StravaAPIClient
    from strava_auth_service import StravaAuthService
    from strava_sync_service import StravaSyncService

    auth_service = StravaAuthService(
        encryption_key=worker_settings.encryption_key.get_secret_value(),
        client_id=worker_settings.strava_client_id,
        client_secret=worker_settings.strava_client_secret.get_secret_value(),
    )

    access_token = auth_service.decrypt(auth_data["encrypted_access_token"])
    refresh_token = auth_service.decrypt(auth_data["encrypted_refresh_token"])

    api_client = StravaAPIClient(
        access_token=access_token,
        refresh_token_value=refresh_token,
        auth_service=auth_service,
    )

    return StravaSyncService(
        api_client=api_client,
        user_id=user_id,
    )


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

    session_factory = ctx["session_factory"]
    worker_settings: StravaSettings = ctx["settings"]

    if owner_id is None:
        logger.warning(
            "Webhook event missing owner_id",
            object_id=object_id,
            aspect_type=aspect_type,
        )
        return {"status": "skipped", "reason": "missing_owner_id"}

    if object_id is None or not isinstance(object_id, int):
        logger.warning(
            "Webhook event missing or invalid object_id",
            object_id=object_id,
            aspect_type=aspect_type,
            owner_id=owner_id,
        )
        return {"status": "skipped", "reason": "invalid_object_id"}

    # Resolve the user from the athlete_id
    user_info = await _resolve_user_for_athlete(session_factory, int(owner_id))
    if user_info is None:
        logger.warning(
            "No user found for Strava athlete_id",
            owner_id=owner_id,
            object_id=object_id,
        )
        return {"status": "skipped", "reason": "unknown_athlete"}

    user_id, auth_data = user_info

    if aspect_type in ("create", "update"):
        sync_service = _create_sync_service(user_id, auth_data, worker_settings)
        try:
            async with session_factory() as session:
                async with session.begin():
                    events = await sync_service.sync_single_activity(
                        activity_id=object_id, session=session
                    )
                    logger.info(
                        "Webhook activity sync complete",
                        aspect_type=aspect_type,
                        object_id=object_id,
                        events_created=len(events),
                    )
                    return {
                        "status": "processed",
                        "aspect_type": aspect_type,
                        "object_id": object_id,
                        "events_created": len(events),
                    }
        finally:
            await sync_service._api_client.close()

    elif aspect_type == "delete":
        sync_service = _create_sync_service(user_id, auth_data, worker_settings)
        try:
            async with session_factory() as session:
                async with session.begin():
                    event = await sync_service.handle_delete(
                        activity_id=object_id, session=session
                    )
                    logger.info(
                        "Webhook delete handled",
                        object_id=object_id,
                        event_created=event is not None,
                    )
                    return {
                        "status": "processed",
                        "aspect_type": "delete",
                        "object_id": object_id,
                        "event_created": event is not None,
                    }
        finally:
            await sync_service._api_client.close()

    else:
        logger.warning(
            "Unknown Strava webhook aspect_type",
            aspect_type=aspect_type,
            object_id=object_id,
        )
        return {"status": "ignored", "reason": f"unknown aspect_type={aspect_type}"}


async def sync_strava_activities(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """
    ARQ task: sync Strava activities for a user.

    Called when the user clicks "Import Activities" in the UI or
    when a full sync is triggered programmatically.

    Args:
        ctx: ARQ worker context.
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dict with sync result summary.
    """
    session_factory = ctx["session_factory"]
    worker_settings: StravaSettings = ctx["settings"]

    logger.info(
        "Starting Strava activity sync",
        user_id=user_id,
        sync_type=sync_type,
    )

    auth_data = await _resolve_user_by_id(session_factory, user_id)
    if auth_data is None:
        logger.error(
            "No Strava auth found for user",
            user_id=user_id,
        )
        return {"status": "error", "reason": "no_auth"}

    sync_service = _create_sync_service(user_id, auth_data, worker_settings)

    try:
        async with session_factory() as session:
            async with session.begin():
                # For smart sync, we could use after_timestamp from last sync
                # For now, full sync imports everything
                after_ts = None
                events = await sync_service.sync_full(
                    session=session,
                    after_timestamp=after_ts,
                )

                logger.info(
                    "Strava activity sync completed",
                    user_id=user_id,
                    sync_type=sync_type,
                    activities_synced=len(events),
                )
                return {
                    "status": "completed",
                    "sync_type": sync_type,
                    "activities_synced": len(events),
                }
    finally:
        await sync_service._api_client.close()


# ARQ Worker Settings
class StravaWorkerSettings(WorkerSettingsBase):
    """ARQ worker configuration."""

    # Task functions
    functions = [process_strava_webhook_event, sync_strava_activities]

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
