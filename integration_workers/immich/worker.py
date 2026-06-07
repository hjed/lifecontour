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
from datetime import UTC, datetime
from typing import Any

import structlog
from arq import cron
from arq.connections import RedisSettings
from core_shared.integration_constants import IMMICH_ARQ_QUEUE_NAME
from core_shared.logging import set_job_id, set_worker_id
from core_shared.telemetry import trace_arq_job

from immich_api_client import ImmichApiClient
from immich_auth_service import ImmichAuthService
from immich_settings import ImmichWorkerSettings
from immich_sync_service import ImmichSyncService

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
    """ARQ task: orchestrate Immich People sync.

    Lists people pages from Immich and enqueues a `sync_immich_people_batch`
    job for each page. Each batch commits independently.

    Args:
        ctx: ARQ worker context (must contain `session_factory`).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dictionary with sync summary.
    """
    job_id = ctx.get("job_id", "unknown")
    session_factory = ctx["session_factory"]
    started_at = datetime.now(UTC)

    logger.info(
        "sync_immich_people started",
        user_id=user_id,
        sync_type=sync_type,
        job_id=job_id,
    )

    await _update_sync_job_status(
        session_factory, job_id, "running", started_at=started_at, progress=0
    )

    try:
        async with session_factory() as session:
            conn = await session.connection()

            auth_service = ImmichAuthService(settings.encryption_key)
            api_key = await auth_service.get_api_key(user_id, conn)
            server_url = await auth_service.get_server_url(user_id, conn)

            if not api_key or not server_url:
                logger.warning("Immich credentials not found for user", user_id=user_id)
                await _update_sync_job_status(
                    session_factory,
                    job_id,
                    "failed",
                    completed_at=datetime.now(UTC),
                    error_message="Immich credentials not configured",
                )
                return {
                    "status": "error",
                    "message": "Immich credentials not configured",
                    "user_id": user_id,
                }

            batches_enqueued = 0
            api_client = ImmichApiClient.create(server_url, api_key)
            try:
                sync_service = ImmichSyncService(
                    api_client=api_client,
                    connection=conn,
                    user_id=user_id,
                )

                page_number = 0
                batch_jobs = []
                import asyncio

                from arq.jobs import Job

                async for people_batch in sync_service.list_people_batches():
                    page_number += 1
                    batch_job_id = f"immich-batch-{job_id}-p{page_number}"

                    job = await ctx["redis"].enqueue_job(
                        "sync_immich_people_batch",
                        user_id,
                        people_batch,
                        _job_id=batch_job_id,
                        _queue_name=IMMICH_ARQ_QUEUE_NAME,
                    )
                    if job:
                        batches_enqueued += 1
                        batch_jobs.append(job)
                        logger.info(
                            "Enqueued people batch job",
                            job_id=job.job_id,
                            batch_size=len(people_batch),
                            batch_number=page_number,
                        )
                    else:
                        batch_jobs.append(
                            Job(
                                batch_job_id,
                                ctx["redis"],
                                _queue_name=IMMICH_ARQ_QUEUE_NAME,
                            )
                        )
                        logger.info(
                            "People batch job already enqueued",
                            batch_job_id=batch_job_id,
                            batch_number=page_number,
                        )

            finally:
                await api_client.close()

        if batch_jobs:
            logger.info(
                "Waiting for batch jobs to complete",
                job_id=job_id,
                count=len(batch_jobs),
            )
            results = await asyncio.gather(
                *[j.result(timeout=290) for j in batch_jobs], return_exceptions=True
            )
            for res in results:
                if isinstance(res, Exception):
                    raise res

        await _update_sync_job_status(
            session_factory,
            job_id,
            "completed",
            completed_at=datetime.now(UTC),
            progress=100,
        )

        return {
            "status": "enqueued",
            "user_id": user_id,
            "sync_type": sync_type,
            "batches_enqueued": batches_enqueued,
        }

    except Exception as e:
        logger.exception(
            "sync_immich_people failed",
            user_id=user_id,
            error=str(e),
        )
        error_msg = "Immich people sync failed due to an internal error"
        await _update_sync_job_status(
            session_factory,
            job_id,
            "failed",
            completed_at=datetime.now(UTC),
            error_message=error_msg,
        )
        return {
            "status": "error",
            "message": error_msg,
            "user_id": user_id,
        }


@trace_arq_job
async def sync_immich_people_batch(
    ctx: dict[str, Any],
    user_id: str,
    people_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """ARQ task: process a batch of Immich people.

    Args:
        ctx: ARQ worker context.
        user_id: Internal user ID.
        people_data: Serialized ImmichPerson dicts.
    """
    session_factory = ctx["session_factory"]

    logger.info(
        "sync_immich_people_batch started", user_id=user_id, batch_size=len(people_data)
    )

    try:
        async with session_factory() as session:
            conn = await session.connection()

            auth_service = ImmichAuthService(settings.encryption_key)
            api_key = await auth_service.get_api_key(user_id, conn)
            server_url = await auth_service.get_server_url(user_id, conn)

            if not api_key or not server_url:
                raise ValueError("Immich credentials missing")

            api_client = ImmichApiClient.create(server_url, api_key)
            try:
                sync_service = ImmichSyncService(
                    api_client=api_client, connection=conn, user_id=user_id
                )
                result = await sync_service.sync_people_batch(people_data)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await api_client.close()

        return {
            "status": "success",
            "user_id": user_id,
            "created": result.created,
            "linked": result.linked,
            "unchanged": result.unchanged,
            "updated": result.updated,
            "skipped": result.skipped,
            "conflicts": result.conflicts,
        }
    except Exception as e:
        logger.exception(
            "sync_immich_people_batch failed", user_id=user_id, error=str(e)
        )
        raise


@trace_arq_job
async def sync_immich_albums(
    ctx: dict[str, Any],
    user_id: str,
    sync_type: str = "full",
) -> dict[str, Any]:
    """ARQ task: sync Immich albums to PHOTO_ALBUM journals.

    Fetches all albums for the user, derives date ranges, and emits
    ``immich_album.*`` outbox events for the backend to process. Album
    writes happen in a single transaction.

    Args:
        ctx: ARQ worker context (must contain ``session_factory``).
        user_id: Internal user ID.
        sync_type: 'full' or 'smart'.

    Returns:
        Dictionary with album sync summary.
    """
    job_id = ctx.get("job_id", "unknown")
    session_factory = ctx["session_factory"]
    started_at = datetime.now(UTC)

    logger.info(
        "sync_immich_albums started",
        user_id=user_id,
        sync_type=sync_type,
        job_id=job_id,
    )

    await _update_sync_job_status(
        session_factory, job_id, "running", started_at=started_at, progress=0
    )

    try:
        async with session_factory() as session:
            conn = await session.connection()

            auth_service = ImmichAuthService(settings.encryption_key)
            api_key = await auth_service.get_api_key(user_id, conn)
            server_url = await auth_service.get_server_url(user_id, conn)

            if not api_key or not server_url:
                logger.warning("Immich credentials not found for user", user_id=user_id)
                await _update_sync_job_status(
                    session_factory,
                    job_id,
                    "failed",
                    completed_at=datetime.now(UTC),
                    error_message="Immich credentials not configured",
                )
                return {
                    "status": "error",
                    "message": "Immich credentials not configured",
                    "user_id": user_id,
                }

            api_client = ImmichApiClient.create(server_url, api_key)
            try:
                sync_service = ImmichSyncService(
                    api_client=api_client, connection=conn, user_id=user_id
                )
                result = await sync_service.sync_albums()
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await api_client.close()

        await _update_sync_job_status(
            session_factory,
            job_id,
            "completed",
            completed_at=datetime.now(UTC),
            progress=100,
        )

        return {
            "status": "completed",
            "user_id": user_id,
            "sync_type": sync_type,
            "created": result.created,
            "updated": result.updated,
            "unchanged": result.unchanged,
            "errors": result.errors,
        }

    except Exception as e:
        logger.exception("sync_immich_albums failed", user_id=user_id, error=str(e))
        error_msg = "Immich album sync failed due to an internal error"
        await _update_sync_job_status(
            session_factory,
            job_id,
            "failed",
            completed_at=datetime.now(UTC),
            error_message=error_msg,
        )
        return {
            "status": "error",
            "message": error_msg,
            "user_id": user_id,
        }


@trace_arq_job
async def process_contact_event(
    ctx: dict[str, Any], event_type: str, event_data: dict[str, Any]
) -> dict[str, Any]:
    """Process a single contact event for Immich outbound sync.

    Receives domain events (ContactCreated, ContactUpdated, ContactBirthdayChanged)
    and pushes the changes to Immich for all synced accounts.

    Args:
        ctx: ARQ-compatible context dictionary with session_factory
        event_type: The domain event type
        event_data: The event payload containing contact_id

    Returns:
        Task result dictionary with sync status
    """
    job_id = ctx.get("job_id", "unknown")
    set_job_id(job_id)
    set_worker_id(settings.worker_id)

    contact_id = event_data.get("contact_id")
    if not contact_id:
        logger.error(
            "Contact event missing contact_id",
            event_type=event_type,
            job_id=job_id,
        )
        return {"status": "error", "error": "Missing contact_id"}

    logger.info(
        "Processing contact event",
        job_id=job_id,
        event_type=event_type,
        contact_id=contact_id,
    )

    session_factory = ctx["session_factory"]

    async with session_factory() as session:
        # Find all Immich integrations for all users
        auth_service = ImmichAuthService(settings.encryption_key)
        conn = await session.connection()

        event_user_id = event_data.get("user_id")
        if event_user_id is not None:
            user_ids = [str(event_user_id)]
        else:
            user_ids = await auth_service.get_all_user_ids(conn)

        if not user_ids:
            logger.info(
                "No Immich integrations found, skipping contact event",
                contact_id=contact_id,
                event_type=event_type,
            )
            return {"status": "skipped", "reason": "no_immich_integrations"}

        results: list[dict[str, Any]] = []
        # NOTE: This system is single-user by design. We iterate all
        # user_immich_auth rows for forward-compatibility, but in
        # practice there is only one user. The same pattern is used
        # in periodic_sync_all_immich_accounts.
        for user_id in user_ids:
            try:
                conn = await session.connection()
                auth_service = ImmichAuthService(settings.encryption_key)
                api_key = await auth_service.get_api_key(user_id, conn)
                server_url = await auth_service.get_server_url(user_id, conn)

                if not api_key or not server_url:
                    results.append({"user_id": user_id, "status": "skipped"})
                    continue

                api_client = ImmichApiClient.create(server_url, api_key)
                try:
                    sync_service = ImmichSyncService(
                        api_client=api_client, connection=conn, user_id=user_id
                    )
                    result = await sync_service.sync_contact_outbound(contact_id)
                    await session.commit()
                    results.append({"user_id": user_id, "result": result})
                except Exception as inner_e:  # noqa: BLE001
                    await session.rollback()
                    logger.error(
                        "Error syncing contact to Immich",
                        user_id=user_id,
                        contact_id=contact_id,
                        error=str(inner_e),
                    )
                    results.append(
                        {"user_id": user_id, "status": "error", "error": str(inner_e)}
                    )
                finally:
                    await api_client.close()

            except Exception as e:  # noqa: BLE001
                logger.error(
                    "Error processing contact event for user",
                    user_id=user_id,
                    contact_id=contact_id,
                    error=str(e),
                )
                results.append({"user_id": user_id, "status": "error", "error": str(e)})

        return {"status": "success", "results": results}


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

                        from core_shared.repositories.sync_job_repository import (
                            SyncJobRepository,
                        )

                        conn = await session.connection()
                        repo = SyncJobRepository(conn)
                        await repo.create(
                            job_id=job.job_id,
                            user_id=str(user_id),
                            integration_source="immich",
                            sync_type="smart",
                            status="queued",
                        )
                        await session.commit()
                    else:
                        error_msg = f"Failed to enqueue Immich sync for user {user_id}"
                        errors.append(error_msg)
                        logger.warning(
                            "Failed to enqueue periodic Immich sync job",
                            user_id=user_id,
                        )

                except Exception as e:  # noqa: BLE001
                    await session.rollback()
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


def _generate_cron_jobs(
    enable_periodic_sync: bool, sync_interval_hours: int
) -> list[Any]:
    if not enable_periodic_sync:
        return []

    interval = max(1, sync_interval_hours)
    sync_hours = set(range(0, 24, interval))

    logger.info(
        "Periodic Immich sync enabled",
        sync_interval_hours=interval,
        sync_hours=list(sync_hours),
    )

    return [
        cron(
            periodic_sync_all_immich_accounts,
            hour=sync_hours,
            minute=0,  # Run at the top of the hour
            unique=True,  # Only run once even with multiple workers
        )
    ]


class WorkerSettings:
    """ARQ worker settings for the Immich integration worker."""

    queue_name = ImmichWorkerSettings.model_fields["queue_name"].default

    # Task functions — Phase 3 provides placeholder sync tasks
    functions: list[Any] = [
        sync_immich_people,
        sync_immich_people_batch,
        sync_immich_albums,
        periodic_sync_all_immich_accounts,
        process_contact_event,
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
    cron_jobs: list[Any] = _generate_cron_jobs(
        settings.enable_periodic_sync, settings.sync_interval_hours
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from arq import run_worker

    logger.info("Starting Immich worker process")
    sys.exit(run_worker(WorkerSettings))  # type: ignore[arg-type]
