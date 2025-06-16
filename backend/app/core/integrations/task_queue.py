"""
ARQ task queue configuration and setup.

Provides configuration and utilities for the ARQ task queue used by
integration workers for background synchronization tasks.
"""

import logging
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.infrastructure.config import Settings


def get_redis_settings(settings: Settings | None = None) -> RedisSettings:
    """
    Get Redis settings for ARQ from application configuration.

    Args:
        settings: Application settings (will load from env if None)

    Returns:
        RedisSettings: Configured Redis settings for ARQ
    """
    if settings is None:
        settings = Settings()

    # Parse Redis URL to extract components
    redis_url = settings.redis_url
    if redis_url.startswith("redis://"):
        # Simple parsing for redis://host:port format
        url_parts = redis_url.replace("redis://", "").split(":")
        host = url_parts[0]
        port = int(url_parts[1]) if len(url_parts) > 1 else 6379
    else:
        host = "localhost"
        port = 6379

    return RedisSettings(
        host=host,
        port=port,
        database=0,  # Use database 0 for task queue
    )


async def get_redis_pool(settings: Settings | None = None) -> Redis:
    """
    Create a Redis connection pool for ARQ tasks.

    Args:
        settings: Application settings (will load from env if None)

    Returns:
        Redis: Redis connection pool
    """
    redis_settings = get_redis_settings(settings)
    return await create_pool(redis_settings)


class TaskQueueConfig:
    """Configuration for ARQ task queue."""

    # Task queue settings
    QUEUE_NAME = "integration_tasks"
    MAX_JOBS = 10
    JOB_TIMEOUT = 300  # 5 minutes
    KEEP_RESULT = 3600  # Keep results for 1 hour

    # Retry settings
    MAX_TRIES = 3
    RETRY_DELAY = 60  # 1 minute base delay

    # Dead Letter Queue settings
    DLQ_MAX_SIZE = 1000
    DLQ_RETENTION = 86400 * 7  # 7 days


async def startup(ctx: dict[str, Any]) -> None:
    """
    ARQ worker startup function.

    Initializes logging and any required resources for the worker.

    Args:
        ctx: ARQ context dictionary
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("arq.worker")
    logger.info("Integration worker starting up...")

    # Store any shared resources in context
    ctx["logger"] = logger


async def shutdown(ctx: dict[str, Any]) -> None:
    """
    ARQ worker shutdown function.

    Cleans up resources when the worker shuts down.

    Args:
        ctx: ARQ context dictionary
    """
    logger = ctx.get("logger", logging.getLogger("arq.worker"))
    logger.info("Integration worker shutting down...")


# Example task function - will be replaced by actual integration tasks
async def example_integration_task(
    ctx: dict[str, Any], integration_source: str, external_id: str
) -> dict[str, Any]:
    """
    Example integration task for testing the queue setup.

    Args:
        ctx: ARQ context dictionary
        integration_source: Name of the integration source
        external_id: External entity ID to process

    Returns:
        Task result dictionary
    """
    logger = ctx.get("logger", logging.getLogger("arq.worker"))
    logger.info(f"Processing integration task: {integration_source}:{external_id}")

    # Simulate some work
    import asyncio

    await asyncio.sleep(1)

    return {
        "status": "success",
        "integration_source": integration_source,
        "external_id": external_id,
        "processed_at": "2024-01-01T00:00:00Z",  # Would use actual timestamp
    }


class WorkerSettings:
    """
    ARQ worker settings configuration.

    This class defines the configuration for the ARQ worker including
    task functions, Redis settings, and worker behavior.
    """

    # Task functions to register with the worker
    functions = [example_integration_task]

    # Worker lifecycle functions
    on_startup = startup
    on_shutdown = shutdown

    # Redis connection settings (will be set dynamically)
    redis_settings = None

    # Worker configuration
    max_jobs = TaskQueueConfig.MAX_JOBS
    job_timeout = TaskQueueConfig.JOB_TIMEOUT
    keep_result = TaskQueueConfig.KEEP_RESULT

    # Retry configuration
    max_tries = TaskQueueConfig.MAX_TRIES
    retry_delay = TaskQueueConfig.RETRY_DELAY

    @classmethod
    def create_with_settings(
        cls, app_settings: Settings | None = None
    ) -> "WorkerSettings":
        """
        Create worker settings with Redis configuration from app settings.

        Args:
            app_settings: Application settings

        Returns:
            WorkerSettings: Configured worker settings
        """
        settings = cls()
        settings.redis_settings = get_redis_settings(app_settings)
        return settings


def get_worker_settings(app_settings: Settings | None = None) -> WorkerSettings:
    """
    Get configured ARQ worker settings.

    Args:
        app_settings: Application settings

    Returns:
        WorkerSettings: Configured worker settings
    """
    return WorkerSettings.create_with_settings(app_settings)
