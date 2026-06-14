"""
Snipe-IT Integration Worker.

ARQ worker process that handles Snipe-IT integration tasks including
gear item sync, maintenance sync, and checkout operations.

This is the entry-point for the worker container. Actual task
implementations will be added in subsequent phases.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from arq.connections import RedisSettings
from core_shared.logging import configure_logging, get_logger
from core_shared.telemetry import setup_telemetry, trace_arq_job

from snipeit_settings import SnipeItWorkerSettings

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

settings = SnipeItWorkerSettings()

configure_logging(
    log_level=settings.log_level,
    service_name=settings.worker_id,
    json_output=True,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# ARQ lifecycle hooks
# ---------------------------------------------------------------------------


async def startup(ctx: dict) -> None:  # type: ignore[type-arg]
    """Initialise shared resources on worker startup."""
    logger.info("snipeit-worker starting", worker_id=settings.worker_id)

    from core_shared.database import create_session_factory

    from stream_consumer_tasks import run_snipeit_stream_consumer

    session_factory = create_session_factory(settings.database_url.get_secret_value())
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
        except Exception as e:  # noqa: BLE001
            logger.error("Stream consumer task failed with an exception", error=str(e))


# ---------------------------------------------------------------------------
# ARQ worker configuration
# ---------------------------------------------------------------------------


async def _get_auth_data(session_factory: Any, user_id: str) -> dict[str, Any] | None:
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT encrypted_api_key
                FROM user_snipe_it_auth
                WHERE user_id = :user_id AND needs_reauth = FALSE
                LIMIT 1
            """),
            {"user_id": user_id},
        )
        row = result.fetchone()
        if row is None:
            return None

        return {
            "encrypted_api_key": row.encrypted_api_key,
        }


def _create_sync_service(
    user_id: str,
    auth_data: dict[str, Any],
    base_url: str,
    snipeit_user_id: str | None,
    worker_settings: SnipeItWorkerSettings,
    session_factory: Any,  # noqa: ARG001
) -> Any:
    from cryptography.fernet import Fernet

    from snipeit_api_client import SnipeItAPIClient
    from snipeit_sync_service import SnipeItSyncService

    fernet = Fernet(worker_settings.encryption_key.get_secret_value().encode())
    api_key = fernet.decrypt(auth_data["encrypted_api_key"]).decode()

    api_client = SnipeItAPIClient.create(
        base_url=base_url,
        api_key=api_key,
    )

    return SnipeItSyncService(
        api_client=api_client,
        user_id=user_id,
        snipeit_user_id=snipeit_user_id,
    )


@trace_arq_job
async def sync_snipeit_assets(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    sync_type: str = "full",
) -> None:
    """Orchestrator job for full sync of Snipe-IT assets."""
    # TODO: Implement smart sync behavior using sync_type parameter
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    # 1. Fetch settings
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        settings_row = result.fetchone()

    if not settings_row or not settings_row.base_url:
        logger.error("Snipe-IT settings not found", user_id=user_id)
        return

    base_url = settings_row.base_url
    snipeit_user_id = settings_row.snipeit_user_id

    # 2. Fetch auth data
    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        logger.error("Snipe-IT auth not found", user_id=user_id)
        return

    # 3. Create sync service
    sync_service = _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=base_url,
        snipeit_user_id=snipeit_user_id,
        worker_settings=worker_settings,
        session_factory=session_factory,
    )

    try:
        redis = ctx["redis"]

        batch_count = 0
        async for asset_ids in sync_service.list_asset_batches():
            if not asset_ids:
                continue

            job_id = f"snipeit_sync_batch:{user_id}:{batch_count}"
            await redis.enqueue_job(
                "sync_snipeit_asset_batch",
                user_id,
                asset_ids,
                _job_id=job_id,
                _queue_name=worker_settings.queue_name,
            )
            batch_count += 1

        logger.info(
            "Enqueued Snipe-IT sync batches",
            user_id=user_id,
            batch_count=batch_count,
        )

    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def sync_snipeit_asset_batch(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    asset_ids: list[int],
) -> dict[str, int]:
    """Worker job to process a batch of Snipe-IT assets."""
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    # 1. Fetch settings
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        settings_row = result.fetchone()

    if not settings_row or not settings_row.base_url:
        logger.error("Snipe-IT settings not found", user_id=user_id)
        return {"synced": 0, "skipped": 0, "failed": len(asset_ids)}

    base_url = settings_row.base_url
    snipeit_user_id = settings_row.snipeit_user_id

    # 2. Fetch auth data
    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        logger.error("Snipe-IT auth not found", user_id=user_id)
        return {"synced": 0, "skipped": 0, "failed": len(asset_ids)}

    # 3. Create sync service
    sync_service = _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=base_url,
        snipeit_user_id=snipeit_user_id,
        worker_settings=worker_settings,
        session_factory=session_factory,
    )

    try:
        result = await sync_service.sync_asset_batch(
            asset_ids=asset_ids,
            session_factory=session_factory,
        )
        return dict(result)
    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def sync_snipeit_maintenances(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    sync_type: str = "full",
) -> None:
    """Orchestrator job for full sync of Snipe-IT maintenance records."""
    # TODO: Implement smart sync behavior using sync_type parameter
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    # 1. Fetch settings
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        settings_row = result.fetchone()

    if not settings_row or not settings_row.base_url:
        logger.error("Snipe-IT settings not found", user_id=user_id)
        return

    base_url = settings_row.base_url
    snipeit_user_id = settings_row.snipeit_user_id

    # 2. Fetch auth data
    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        logger.error("Snipe-IT auth not found", user_id=user_id)
        return

    # 3. Create sync service
    sync_service = _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=base_url,
        snipeit_user_id=snipeit_user_id,
        worker_settings=worker_settings,
        session_factory=session_factory,
    )

    try:
        redis = ctx["redis"]

        # Fetch all maintenance IDs and enqueue batch jobs
        batch_count = 0
        async for maintenance_ids in sync_service.list_maintenance_batches():
            if not maintenance_ids:
                continue

            job_id = f"snipeit_maint_batch:{user_id}:{batch_count}"
            await redis.enqueue_job(
                "sync_snipeit_maintenance_batch",
                user_id,
                maintenance_ids,
                _job_id=job_id,
                _queue_name=worker_settings.queue_name,
            )
            batch_count += 1

        logger.info(
            "Enqueued Snipe-IT maintenance sync batches",
            user_id=user_id,
            batch_count=batch_count,
        )

    finally:
        await sync_service._api_client.close()


@trace_arq_job
async def sync_snipeit_maintenance_batch(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    maintenance_ids: list[int],
) -> dict[str, int]:
    """Worker job to process a batch of Snipe-IT maintenance records."""
    session_factory = ctx["session_factory"]
    worker_settings: SnipeItWorkerSettings = settings

    from sqlalchemy import text

    # 1. Fetch settings
    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT base_url, snipeit_user_id
                FROM snipeit_settings
                WHERE user_id = :user_id
            """),
            {"user_id": user_id},
        )
        settings_row = result.fetchone()

    if not settings_row or not settings_row.base_url:
        logger.error("Snipe-IT settings not found", user_id=user_id)
        return {"synced": 0, "skipped": 0, "failed": len(maintenance_ids)}

    base_url = settings_row.base_url
    snipeit_user_id = settings_row.snipeit_user_id

    # 2. Fetch auth data
    auth_data = await _get_auth_data(session_factory, user_id)
    if not auth_data:
        logger.error("Snipe-IT auth not found", user_id=user_id)
        return {"synced": 0, "skipped": 0, "failed": len(maintenance_ids)}

    # 3. Create sync service
    sync_service = _create_sync_service(
        user_id=user_id,
        auth_data=auth_data,
        base_url=base_url,
        snipeit_user_id=snipeit_user_id,
        worker_settings=worker_settings,
        session_factory=session_factory,
    )

    try:
        result = await sync_service.sync_maintenance_batch(
            maintenance_ids=maintenance_ids,
            session_factory=session_factory,
        )
        return dict(result)
    finally:
        await sync_service._api_client.close()


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

    queue_name = SnipeItWorkerSettings.model_fields["queue_name"].default

    # Task functions — populated as phases are implemented
    functions: list[Any] = [
        sync_snipeit_assets,
        sync_snipeit_asset_batch,
        sync_snipeit_maintenances,
        sync_snipeit_maintenance_batch,
    ]

    on_startup = startup
    on_shutdown = shutdown

    # Retry / DLQ configuration
    max_tries = 5
    job_timeout = 300
    keep_result = 3600
    health_check_interval = 30

    redis_settings = _parse_redis_url(settings.redis_url)


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from arq import run_worker

    # Setup OpenTelemetry
    setup_telemetry(settings)

    logger.info("Starting Snipe-IT worker process")
    sys.exit(run_worker(WorkerSettings))  # type: ignore[arg-type]
