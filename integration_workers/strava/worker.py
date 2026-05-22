#!/usr/bin/env python3
"""
Strava Integration Worker.

This worker processes Strava webhook events and activity sync tasks
using ARQ. It runs as a separate process from the main FastAPI
application and also launches a Redis Streams consumer for domain
event fan-out.
"""

import asyncio
import random
from typing import Any

from arq import Retry, run_worker
from arq.connections import RedisSettings
from arq.cron import cron
from arq.typing import StartupShutdown, WorkerSettingsBase
from core_shared.database.engine import create_session_factory
from core_shared.integration_constants import STRAVA_ARQ_QUEUE_NAME
from core_shared.logging import configure_logging, get_logger
from core_shared.telemetry import setup_telemetry, trace_arq_job

from strava_rate_limiter import StravaRateLimitError
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

# Default deferral when Strava provides no retry_after hint (daily limit).
# 1 hour ensures 20 max_tries covers ~20 hours, enough to reach midnight UTC.
_DEFAULT_RATE_LIMIT_DEFER = 60 * 60  # 1 hour


def _rate_limit_defer(exc: StravaRateLimitError) -> int:
    """Calculate a deferral duration for a rate-limited ARQ retry.

    Uses the server-provided ``retry_after`` when available (e.g. remaining
    time in the 15-minute window) plus random jitter to avoid thundering
    herd.  When ``retry_after`` is ``None`` (daily limit), falls back to
    a conservative 15-minute default.
    """
    base = (
        int(exc.retry_after)
        if exc.retry_after is not None
        else _DEFAULT_RATE_LIMIT_DEFER
    )
    jitter = random.randint(10, 120)
    return base + jitter


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


async def _update_user_tokens(
    session_factory: Any,
    user_id: str,
    tokens: Any,
    auth_service: Any,
) -> None:
    from sqlalchemy import text

    encrypted_access = auth_service.encrypt(tokens.access_token)
    encrypted_refresh = auth_service.encrypt(tokens.refresh_token)

    async with session_factory() as session:
        await session.execute(
            text("""
                UPDATE user_strava_auth
                SET encrypted_access_token = :access,
                    encrypted_refresh_token = :refresh,
                    expires_at = :expires_at,
                    updated_at = NOW()
                WHERE user_id = :user_id
            """),
            {
                "access": encrypted_access,
                "refresh": encrypted_refresh,
                "expires_at": tokens.expires_at,
                "user_id": user_id,
            },
        )
        await session.commit()


def _create_sync_service(
    user_id: str,
    auth_data: dict[str, Any],
    worker_settings: StravaSettings,
    session_factory: Any,
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

    async def on_token_refresh(tokens: Any) -> None:
        await _update_user_tokens(session_factory, user_id, tokens, auth_service)

    api_client = StravaAPIClient(
        access_token=access_token,
        refresh_token_value=refresh_token,
        auth_service=auth_service,
        on_token_refresh=on_token_refresh,
    )

    return StravaSyncService(
        api_client=api_client,
        user_id=user_id,
    )


@trace_arq_job
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
        sync_service = _create_sync_service(
            user_id, auth_data, worker_settings, session_factory
        )
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
        except StravaRateLimitError as exc:
            defer = _rate_limit_defer(exc)
            logger.warning(
                "Rate limit reached in webhook event, retrying",
                retry_after=exc.retry_after,
                defer_seconds=defer,
            )
            raise Retry(defer=defer) from exc
        finally:
            await sync_service._api_client.close()

    elif aspect_type == "delete":
        sync_service = _create_sync_service(
            user_id, auth_data, worker_settings, session_factory
        )
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
        except StravaRateLimitError as exc:
            defer = _rate_limit_defer(exc)
            logger.warning(
                "Rate limit reached in webhook delete, retrying",
                retry_after=exc.retry_after,
                defer_seconds=defer,
            )
            raise Retry(defer=defer) from exc
        finally:
            await sync_service._api_client.close()

    else:
        logger.warning(
            "Unknown Strava webhook aspect_type",
            aspect_type=aspect_type,
            object_id=object_id,
        )
        return {"status": "ignored", "reason": f"unknown aspect_type={aspect_type}"}


@trace_arq_job
async def sync_strava_activities(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """
    ARQ task: orchestrate Strava activity sync for a user.

    Lists activity pages from Strava and enqueues a
    ``sync_strava_activity_batch`` job for each page. Each batch
    commits independently, so progress is preserved even if later
    batches fail. ARQ's ``max_tries`` provides automatic retries
    per batch.

    Called when the user clicks "Import Activities" in the UI or
    when a full sync is triggered programmatically.

    Args:
        ctx: ARQ worker context (must contain ``redis`` ARQ pool).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dict with orchestration summary.
    """
    worker_settings: StravaSettings = ctx["settings"]
    session_factory = ctx["session_factory"]

    logger.info(
        "Starting Strava activity sync orchestrator",
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

    sync_service = _create_sync_service(
        user_id, auth_data, worker_settings, session_factory
    )

    try:
        # For smart sync, we could use after_timestamp from last sync
        # For now, full sync imports everything
        after_ts = None
        batches_enqueued = 0
        page_number = 0

        async for activity_ids in sync_service.list_activity_batches(
            after_timestamp=after_ts,
        ):
            page_number += 1

            # Deterministic job ID prevents duplicate enqueues if the
            # orchestrator is retried by ARQ after a partial run.
            batch_job_id = f"strava-batch-{user_id}-p{page_number}"

            job = await ctx["redis"].enqueue_job(
                "sync_strava_activity_batch",
                user_id,
                activity_ids,
                _job_id=batch_job_id,
                _queue_name=STRAVA_ARQ_QUEUE_NAME,
            )
            if job:
                batches_enqueued += 1
                logger.info(
                    "Enqueued activity batch job",
                    job_id=job.job_id,
                    batch_size=len(activity_ids),
                    batch_number=page_number,
                )
            else:
                # enqueue_job returns None when a job with the same
                # _job_id already exists — this is expected on retries.
                logger.info(
                    "Activity batch job already enqueued (idempotent)",
                    batch_job_id=batch_job_id,
                    batch_number=page_number,
                )

        logger.info(
            "Strava sync orchestrator completed",
            user_id=user_id,
            batches_enqueued=batches_enqueued,
            total_pages=page_number,
        )
        return {
            "status": "enqueued",
            "sync_type": sync_type,
            "batches_enqueued": batches_enqueued,
        }
    except StravaRateLimitError as exc:
        defer = _rate_limit_defer(exc)
        logger.warning(
            "Rate limit reached in orchestrator, retrying",
            retry_after=exc.retry_after,
            defer_seconds=defer,
        )
        raise Retry(defer=defer) from exc
    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def sync_strava_activity_batch(
    ctx: dict[str, Any],
    user_id: str,
    activity_ids: list[int],
) -> dict[str, Any]:
    """
    ARQ task: process a batch of Strava activity IDs.

    Fetches full activity details + streams from Strava and creates
    outbox events. Each activity is processed independently so one
    failure doesn't block others. ARQ's ``max_tries`` handles
    automatic retries on job-level failures (e.g. timeout).

    Args:
        ctx: ARQ worker context.
        user_id: Internal user ID.
        activity_ids: Strava activity IDs to process.

    Returns:
        Dict with batch processing result.
    """
    session_factory = ctx["session_factory"]
    worker_settings: StravaSettings = ctx["settings"]

    logger.info(
        "Processing Strava activity batch",
        user_id=user_id,
        batch_size=len(activity_ids),
    )

    auth_data = await _resolve_user_by_id(session_factory, user_id)
    if auth_data is None:
        logger.error(
            "No Strava auth found for user",
            user_id=user_id,
        )
        return {"status": "error", "reason": "no_auth"}

    sync_service = _create_sync_service(
        user_id, auth_data, worker_settings, session_factory
    )

    try:
        result = await sync_service.sync_activity_batch(
            activity_ids=activity_ids,
            session_factory=session_factory,
        )

        logger.info(
            "Strava activity batch completed",
            user_id=user_id,
            **result,
        )
        return {
            "status": "completed",
            **result,
        }
    except StravaRateLimitError as exc:
        defer = _rate_limit_defer(exc)
        logger.warning(
            "Rate limit reached in batch sync, retrying",
            retry_after=exc.retry_after,
            defer_seconds=defer,
        )
        raise Retry(defer=defer) from exc
    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def periodic_sync_all_strava_accounts(
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Periodic sync wrapper that syncs all active Strava accounts.

    This function is called by ARQ cron jobs and enqueues individual
    ``sync_strava_activities`` tasks for each connected Strava
    integration using 'smart' sync type.

    Args:
        ctx: ARQ context dictionary containing Redis pool and session_factory.

    Returns:
        Dictionary with sync summary (accounts_found, jobs_enqueued, errors).
    """
    logger.info("Starting periodic sync for all Strava accounts")

    session_factory = ctx["session_factory"]

    accounts_found = 0
    jobs_enqueued = 0
    errors: list[str] = []

    try:
        async with session_factory() as session:
            from sqlalchemy import text

            stmt = text("""
                SELECT user_id, strava_athlete_id
                FROM user_strava_auth
                ORDER BY user_id
            """)
            result = await session.execute(stmt)
            accounts = result.fetchall()

            accounts_found = len(accounts)
            logger.info(
                "Found active Strava accounts for periodic sync",
                accounts_count=accounts_found,
            )

            for row in accounts:
                user_id = row.user_id

                try:
                    job = await ctx["redis"].enqueue_job(
                        "sync_strava_activities",
                        str(user_id),
                        "smart",
                        _job_timeout=600,
                        _queue_name=STRAVA_ARQ_QUEUE_NAME,
                    )

                    if job:
                        jobs_enqueued += 1
                        logger.info(
                            "Enqueued periodic Strava sync job",
                            job_id=job.job_id,
                            user_id=user_id,
                        )
                    else:
                        error_msg = f"Failed to enqueue Strava sync for user {user_id}"
                        errors.append(error_msg)
                        logger.warning(
                            "Failed to enqueue periodic Strava sync job",
                            user_id=user_id,
                        )

                except Exception as e:  # noqa: BLE001
                    error_msg = (
                        f"Error enqueueing Strava sync for user {user_id}: {e!s}"
                    )
                    errors.append(error_msg)
                    logger.error(
                        "Error enqueueing periodic Strava sync job",
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

        logger.info(
            "Periodic Strava sync scheduling complete",
            accounts_found=accounts_found,
            jobs_enqueued=jobs_enqueued,
            errors_count=len(errors),
        )

        return {
            "status": "success",
            "accounts_found": accounts_found,
            "jobs_enqueued": jobs_enqueued,
            "errors": errors,
        }

    except Exception:
        logger.error(
            "Fatal error during periodic Strava sync",
            accounts_found=accounts_found,
            jobs_enqueued=jobs_enqueued,
            exc_info=True,
        )
        raise


# ARQ Worker Settings
class StravaWorkerSettings(WorkerSettingsBase):
    """ARQ worker configuration."""

    # Task functions
    functions = [
        process_strava_webhook_event,
        sync_strava_activities,
        sync_strava_activity_batch,
        periodic_sync_all_strava_accounts,
    ]

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
    max_tries = 20

    # Queue name
    queue_name = STRAVA_ARQ_QUEUE_NAME

    # Periodic sync configuration (cron jobs)
    # Only configure cron_jobs if periodic sync is enabled
    cron_jobs = []
    if settings.enable_periodic_sync:
        # Generate cron schedule based on sync_interval_hours
        # For example: sync_interval_hours=6 -> hours={0, 6, 12, 18}
        sync_hours = set(range(0, 24, settings.sync_interval_hours))

        cron_jobs = [
            cron(
                periodic_sync_all_strava_accounts,
                hour=sync_hours,
                minute=0,  # Run at the top of the hour
                unique=True,  # Only run once even with multiple workers
            )
        ]

        logger.info(
            "Periodic Strava sync enabled",
            sync_interval_hours=settings.sync_interval_hours,
            sync_hours=list(sync_hours),
        )


if __name__ == "__main__":
    # Setup OpenTelemetry
    setup_telemetry(settings)

    # Run the worker
    logger.info("Starting Strava ARQ worker", worker_id=settings.worker_id)
    run_worker(StravaWorkerSettings)
