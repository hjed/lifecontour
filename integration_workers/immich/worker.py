"""
Immich Integration Worker.

ARQ worker process that handles Immich integration tasks including
contact/album sync with face-based matching.

This is the entry-point for the worker container. Phase 3 provides
periodic sync scheduling, manual sync triggers, and placeholder
sync tasks. Actual sync logic will be implemented in ITER11-002+.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any

import structlog
from arq import cron
from arq.connections import RedisSettings
from core_shared.integration_constants import IMMICH_ARQ_QUEUE_NAME
from core_shared.telemetry import trace_arq_job

from immich_settings import ImmichWorkerSettings

__version__ = "0.2.0"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

settings = ImmichWorkerSettings()

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
    logger.info("immich-worker starting", worker_id=settings.worker_id)

    from core_shared.database import create_session_factory

    from stream_consumer_tasks import run_immich_stream_consumer

    session_factory = create_session_factory(settings.database_url)
    ctx["session_factory"] = session_factory

    # Start stream consumer for domain events
    consumer_task = asyncio.create_task(
        run_immich_stream_consumer(
            session_factory=session_factory,
            redis_url=settings.redis_url,
            stream_name=settings.stream_name,
        )
    )
    ctx["stream_consumer_task"] = consumer_task


async def shutdown(ctx: dict) -> None:  # type: ignore[type-arg]
    """Clean up shared resources on worker shutdown."""
    logger.info("immich-worker shutting down", worker_id=settings.worker_id)

    # Stop the stream consumer
    consumer_task = ctx.get("stream_consumer_task")
    if consumer_task:
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.error("Stream consumer task failed with an exception", error=str(e))


# ---------------------------------------------------------------------------
# ARQ sync tasks
# ---------------------------------------------------------------------------


async def _update_sync_job_status(
    session_factory: Any,
    job_id: str,
    status: str,
    **kwargs: Any,
) -> None:
    """Update a sync_jobs row via SyncJobRepository."""
    from core_shared.repositories.sync_job_repository import SyncJobRepository

    async with session_factory() as session:
        conn = await session.connection()
        repo = SyncJobRepository(conn)
        result = await repo.update_status(job_id=job_id, status=status, **kwargs)
        await session.commit()
        if result is None:
            logger.warning(
                "Failed to update sync job status - job not found",
                job_id=job_id,
                status=status,
            )


@trace_arq_job
async def sync_immich_people(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """ARQ task: sync Immich People for a user.

    Phase 3 placeholder — logs the request and returns success.
    Full implementation will be added in ITER11-002 (Contact Sync).

    Args:
        ctx: ARQ worker context (must contain ``session_factory``).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dictionary with sync summary.
    """
    from datetime import UTC, datetime

    job_id = ctx.get("job_id", "unknown")
    session_factory = ctx["session_factory"]
    started_at = datetime.now(UTC)

    logger.info(
        "sync_immich_people called (placeholder)",
        user_id=user_id,
        sync_type=sync_type,
        job_id=job_id,
    )

    # Mark job as running
    await _update_sync_job_status(
        session_factory, job_id, "running", started_at=started_at, progress=0
    )

    # Mark job as completed (placeholder — no real work yet)
    await _update_sync_job_status(
        session_factory,
        job_id,
        "completed",
        completed_at=datetime.now(UTC),
        progress=100,
    )

    return {
        "status": "success",
        "message": "People sync not yet implemented — placeholder for ITER11-002",
        "user_id": user_id,
        "sync_type": sync_type,
    }


async def periodic_sync_all_immich_accounts(
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Periodic sync wrapper that syncs all active Immich accounts.

    This function is called by ARQ cron jobs and enqueues individual
    ``sync_immich_people`` tasks for each connected Immich
    integration using 'smart' sync type.

    Args:
        ctx: ARQ context dictionary containing Redis pool and session_factory.

    Returns:
        Dictionary with sync summary (accounts_found, jobs_enqueued, errors).
    """
    logger.info("Starting periodic sync for all Immich accounts")

    session_factory = ctx["session_factory"]

    accounts_found = 0
    jobs_enqueued = 0
    errors: list[str] = []

    try:
        async with session_factory() as session:
            from sqlalchemy import text

            stmt = text("""
                SELECT user_id
                FROM user_immich_auth
                ORDER BY user_id
            """)
            result = await session.execute(stmt)
            accounts = result.fetchall()

            accounts_found = len(accounts)
            logger.info(
                "Found active Immich accounts for periodic sync",
                accounts_count=accounts_found,
            )

            for row in accounts:
                user_id = row.user_id

                try:
                    job = await ctx["redis"].enqueue_job(
                        "sync_immich_people",
                        str(user_id),
                        "smart",
                        _queue_name=IMMICH_ARQ_QUEUE_NAME,
                    )

                    if job:
                        jobs_enqueued += 1
                        logger.info(
                            "Enqueued periodic Immich sync job",
                            job_id=job.job_id,
                            user_id=user_id,
                        )
                    else:
                        error_msg = f"Failed to enqueue Immich sync for user {user_id}"
                        errors.append(error_msg)
                        logger.warning(
                            "Failed to enqueue periodic Immich sync job",
                            user_id=user_id,
                        )

                except Exception as e:  # noqa: BLE001
                    error_msg = (
                        f"Error enqueueing Immich sync for user {user_id}: {e!s}"
                    )
                    errors.append(error_msg)
                    logger.error(
                        "Error enqueueing periodic Immich sync job",
                        user_id=user_id,
                        error=str(e),
                        error_type=type(e).__name__,
                    )

        logger.info(
            "Periodic Immich sync scheduling complete",
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
            "Fatal error during periodic Immich sync",
            accounts_found=accounts_found,
            jobs_enqueued=jobs_enqueued,
            exc_info=True,
        )
        raise


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
    """ARQ worker settings for the Immich integration worker."""

    queue_name = ImmichWorkerSettings.model_fields["queue_name"].default

    # Task functions — Phase 3 provides placeholder sync tasks
    functions: list[Any] = [
        sync_immich_people,
        periodic_sync_all_immich_accounts,
    ]

    on_startup = startup
    on_shutdown = shutdown

    # Retry / DLQ configuration
    max_tries = 5
    job_timeout = 300
    keep_result = 3600
    health_check_interval = 30

    redis_settings = _parse_redis_url(settings.redis_url)

    # Periodic sync configuration (cron jobs)
    # Only configure cron_jobs if periodic sync is enabled
    cron_jobs: list[Any] = []
    if settings.enable_periodic_sync:
        # Generate cron schedule based on sync_interval_hours
        # For example: sync_interval_hours=6 -> hours={0, 6, 12, 18}
        interval = max(1, settings.sync_interval_hours)
        sync_hours = set(range(0, 24, interval))

        cron_jobs = [
            cron(
                periodic_sync_all_immich_accounts,
                hour=sync_hours,
                minute=0,  # Run at the top of the hour
                unique=True,  # Only run once even with multiple workers
            )
        ]

        logger.info(
            "Periodic Immich sync enabled",
            sync_interval_hours=interval,
            sync_hours=list(sync_hours),
        )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from arq import run_worker

    logger.info("Starting Immich worker process")
    sys.exit(run_worker(WorkerSettings))  # type: ignore[arg-type]
