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
from typing import Any

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


async def _get_auth_data(session_factory: Any, user_id: str) -> dict[str, Any] | None:
    from sqlalchemy import text

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT encrypted_access_token, encrypted_refresh_token
                FROM user_snipe_it_auth
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
    access_token: str,
    refresh_token: str,
    auth_service: Any,
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import text

    # Rough estimate since SnipeIT token refresh returns expires_in
    # This might need adjustment if SnipeIT requires precise expires_at
    expires_at = datetime.now(UTC) + timedelta(seconds=31536000)

    encrypted_access = auth_service.encrypt(access_token)
    encrypted_refresh = auth_service.encrypt(refresh_token)

    async with session_factory() as session:
        await session.execute(
            text("""
                UPDATE user_snipe_it_auth
                SET encrypted_access_token = :access,
                    encrypted_refresh_token = :refresh,
                    token_expires_at = :expires_at,
                    updated_at = NOW()
                WHERE user_id = :user_id
            """),
            {
                "access": encrypted_access,
                "refresh": encrypted_refresh,
                "expires_at": expires_at,
                "user_id": user_id,
            },
        )
        await session.commit()


def _create_sync_service(
    user_id: str,
    auth_data: dict[str, Any],
    base_url: str,
    snipeit_user_id: str | None,
    worker_settings: SnipeItWorkerSettings,
    session_factory: Any,
) -> Any:
    # Simple Fernet decrypter for tokens
    from cryptography.fernet import Fernet

    from snipeit_api_client import SnipeItAPIClient
    from snipeit_sync_service import SnipeItSyncService

    fernet = Fernet(worker_settings.encryption_key.encode())

    access_token = fernet.decrypt(auth_data["encrypted_access_token"]).decode()
    refresh_token = fernet.decrypt(auth_data["encrypted_refresh_token"]).decode()

    async def on_token_refresh() -> str:
        # Simplistic token refresh logic
        import httpx

        token_url = f"{base_url.rstrip('/')}/oauth/token"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": getattr(worker_settings, "snipeit_client_id", ""),
                    "client_secret": getattr(
                        worker_settings, "snipeit_client_secret", ""
                    ),
                },
            )
            response.raise_for_status()
            token_data = response.json()
            new_access = token_data["access_token"]
            new_refresh = token_data.get("refresh_token", refresh_token)

            # Simple wrapper to match the signature
            class DummyAuth:
                def encrypt(self, txt: str) -> bytes:
                    return fernet.encrypt(txt.encode())

            await _update_user_tokens(
                session_factory, user_id, new_access, new_refresh, DummyAuth()
            )
            return str(new_access)

    api_client = SnipeItAPIClient.create(
        base_url=base_url,
        access_token=access_token,
        on_token_refresh=on_token_refresh,
    )

    return SnipeItSyncService(
        api_client=api_client,
        user_id=user_id,
        snipeit_user_id=snipeit_user_id,
    )


async def sync_snipeit_assets(
    ctx: dict,  # type: ignore[type-arg]
    user_id: str,
    sync_type: str = "full",
) -> None:
    """Orchestrator job for full sync of Snipe-IT assets."""
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
            )
            batch_count += 1

        logger.info(
            "Enqueued Snipe-IT sync batches",
            user_id=user_id,
            batch_count=batch_count,
        )

    finally:
        await sync_service._api_client.close()


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
    functions: list[Any] = [
        "worker.sync_snipeit_assets",
        "worker.sync_snipeit_asset_batch",
    ]

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
