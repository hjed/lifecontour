"""
Health check endpoints for monitoring and load balancer integration.

Provides basic health status and detailed system health information
including database connectivity and external service status.
"""

import time
from datetime import UTC, datetime
from typing import Any

import structlog
from core_shared.stream_client import StreamClient
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.orm import Session

from app.infrastructure.config import Settings
from app.infrastructure.database import check_database_connection
from app.infrastructure.events.dead_letter_repository import DeadLetterRepository

logger = structlog.get_logger()
router = APIRouter()

# Track application startup time
_startup_time = time.time()


def _get_uptime() -> str:
    """Calculate application uptime."""
    uptime_seconds = int(time.time() - _startup_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    timestamp: datetime
    version: str
    uptime: str


class DetailedHealthResponse(BaseModel):
    """Detailed health check response model."""

    status: str
    timestamp: datetime
    version: str
    uptime: str
    services: dict[str, Any]


@router.get("/health")
async def health_check() -> HealthResponse:
    """
    Basic health check endpoint.

    Returns basic application health status for load balancers
    and monitoring systems.
    """
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(UTC),
        version="0.1.0",
        uptime=_get_uptime(),
    )


@router.get("/health/detailed")
@inject
async def detailed_health_check(
    _db: FromDishka[Session],
    settings: FromDishka[Settings],
) -> DetailedHealthResponse:
    """
    Detailed health check endpoint.

    Returns comprehensive health information including database
    connectivity and external service status.
    """
    services = {}
    overall_status = "healthy"

    # Check database connectivity
    try:
        db_healthy = check_database_connection()
        services["database"] = {
            "status": "healthy" if db_healthy else "unhealthy",
            "type": "postgresql",
        }
        if not db_healthy:
            overall_status = "degraded"
    except Exception as e:  # noqa: BLE001
        logger.error("Database health check failed", error=str(e))
        services["database"] = {
            "status": "unhealthy",
            "type": "postgresql",
            "error": str(e),
        }
        overall_status = "unhealthy"

    # Check MCP server status
    if settings.mcp_enabled:
        try:
            # MCP server health check - just verify it's enabled and configured
            services["mcp_server"] = {
                "status": "healthy",
                "type": "fastmcp",
                "mount_path": settings.mcp_mount_path,
                "enabled": "true",
            }
        except Exception as e:  # noqa: BLE001
            logger.error("MCP server health check failed", error=str(e))
            services["mcp_server"] = {
                "status": "unhealthy",
                "type": "fastmcp",
                "error": str(e),
                "enabled": "true",
            }
            overall_status = "degraded"
    else:
        services["mcp_server"] = {
            "status": "disabled",
            "type": "fastmcp",
            "enabled": "false",
        }

    # External service checks can be added here in the future
    # Examples: Google Calendar API, Google Contacts API, Immich API

    return DetailedHealthResponse(
        status=overall_status,
        timestamp=datetime.now(UTC),
        version="0.1.0",
        uptime=_get_uptime(),
        services=services,
    )


@router.get("/health/ready")
@inject
async def readiness_check(
    _db: FromDishka[Session],
) -> dict[str, str]:
    """
    Kubernetes readiness probe endpoint.

    Returns 200 if the application is ready to serve traffic,
    503 if not ready.
    """
    try:
        if not check_database_connection():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Database connection not available",
            )

        return {"status": "ready"}

    except Exception as e:
        logger.error("Readiness check failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Service not ready"
        ) from e


@router.get("/health/live")
async def liveness_check() -> dict[str, str]:
    """
    Kubernetes liveness probe endpoint.

    Returns 200 if the application is alive, 503 if it should be restarted.
    """
    return {"status": "alive"}


@router.get("/health/integrations")
@inject
async def integration_health_check(
    redis_pool: FromDishka[Redis],
    settings: FromDishka[Settings],
) -> DetailedHealthResponse:
    """
    Health check specifically for integration infrastructure.

    Verifies that the integration foundation components are working:
    - Redis connection for ARQ task queue
    - Core shared package accessibility
    - Integration domain configuration

    Returns comprehensive health information for integration components.
    """
    services: dict[str, Any] = {}
    overall_status = "healthy"

    # Check Redis connection for ARQ task queue
    try:
        # Test Redis connection with a simple ping
        pong = await redis_pool.ping()
        if pong:
            services["redis"] = {
                "status": "healthy",
                "type": "redis",
                "purpose": "ARQ task queue",
                "url": settings.redis_url,
            }
        else:
            services["redis"] = {
                "status": "unhealthy",
                "type": "redis",
                "purpose": "ARQ task queue",
                "error": "Redis ping failed",
            }
            overall_status = "unhealthy"
    except Exception as e:  # noqa: BLE001
        logger.error("Redis health check failed", error=str(e))
        services["redis"] = {
            "status": "unhealthy",
            "type": "redis",
            "purpose": "ARQ task queue",
            "error": f"Redis connection failed: {str(e)}",
        }
        overall_status = "unhealthy"

    # Check core_shared package accessibility
    try:
        # Import and verify core_shared models are accessible
        # These imports are intentionally tested to verify package accessibility
        from core_shared.base_service import BaseIntegrationService, SyncResult
        from core_shared.models.sync_metadata import SyncMetadata, SyncStatus

        # Verify enums work correctly (test that they can be accessed)
        _ = SyncStatus.SUCCESS
        _ = SyncResult.SUCCESS

        # Test that we can reference the classes (for health check verification)
        available_models = [
            SyncMetadata.__name__,
            BaseIntegrationService.__name__,
        ]

        services["core_shared"] = {
            "status": "healthy",
            "type": "python_package",
            "purpose": "Shared integration models",
            "models": available_models,
            "enums_working": True,
        }
    except Exception as e:  # noqa: BLE001
        logger.error("Core shared package health check failed", error=str(e))
        services["core_shared"] = {
            "status": "unhealthy",
            "type": "python_package",
            "purpose": "Shared integration models",
            "error": f"Core shared package error: {str(e)}",
        }
        overall_status = "unhealthy"

    # Check integration domain configuration
    try:
        # These imports are intentionally tested to verify domain accessibility
        from app.core.integrations.database import IntegrationDatabaseManager
        from app.core.integrations.exceptions import IntegrationError
        from app.core.integrations.task_queue import TaskQueueConfig, get_redis_settings

        # Verify configuration is accessible
        config = TaskQueueConfig()
        _ = get_redis_settings(settings)  # Test that it can be called

        # Test that we can reference the classes (for health check verification)
        available_components = [
            IntegrationError.__name__,
            IntegrationDatabaseManager.__name__,
        ]

        services["integration_domain"] = {
            "status": "healthy",
            "type": "domain_configuration",
            "purpose": "Integration architecture foundation",
            "task_queue_config": {
                "queue_name": config.QUEUE_NAME,
                "max_jobs": config.MAX_JOBS,
                "job_timeout": config.JOB_TIMEOUT,
                "max_tries": config.MAX_TRIES,
            },
            "redis_settings_configured": True,
            "available_components": available_components,
        }
    except Exception as e:  # noqa: BLE001
        logger.error("Integration domain health check failed", error=str(e))
        services["integration_domain"] = {
            "status": "unhealthy",
            "type": "domain_configuration",
            "purpose": "Integration architecture foundation",
            "error": f"Integration domain error: {str(e)}",
        }
        overall_status = "unhealthy"

    return DetailedHealthResponse(
        status=overall_status,
        timestamp=datetime.now(UTC),
        version="0.1.0",
        uptime=_get_uptime(),
        services=services,
    )


@router.get("/health/consumer-lag")
@inject
async def get_consumer_lag(
    stream_client: FromDishka[StreamClient],
    settings: FromDishka[Settings],
) -> list[dict[str, Any]]:
    """Get consumer lag for the application's domain events stream."""
    try:
        info = await stream_client.get_consumer_group_info(settings.stream_name)
        return info
    except Exception as e:
        logger.error("Failed to get consumer lag", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve consumer lag"
        ) from e


@router.get("/health/dead-letters")
@inject
async def get_dead_letters(
    connection: FromDishka[AsyncConnection],
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Get dead letter events from the repository.

    Returns event metadata without raw event_data to avoid
    leaking potentially sensitive payloads.
    """
    # Clamp pagination parameters to safe bounds
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    try:
        repo = DeadLetterRepository(connection)
        events = await repo.list_events(limit=limit, offset=offset)
        total = await repo.count()
        return {
            "items": [
                {
                    "id": event.id,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "aggregate_id": event.aggregate_id,
                    "consumer_group": event.consumer_group,
                    "delivery_count": event.delivery_count,
                    "last_error": event.last_error,
                    "created_at": event.created_at.isoformat()
                    if event.created_at
                    else None,
                }
                for event in events
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    except Exception as e:
        logger.error("Failed to get dead letters", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500, detail="Failed to retrieve dead letters"
        ) from e


@router.get("/metrics")
async def metrics() -> Response:
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text format for scraping by monitoring systems.
    Includes:
    - Worker job metrics (duration, total, queue depth)
    - Sync metrics (items processed, errors, conflicts)
    - API metrics (requests, duration)
    - Python runtime metrics (GC, memory, etc.)

    This endpoint is typically scraped by Prometheus or compatible monitoring systems.
    """
    # Generate Prometheus metrics in text format
    metrics_data = generate_latest()

    return Response(
        content=metrics_data,
        media_type=CONTENT_TYPE_LATEST,
    )
