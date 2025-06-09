"""
Health check endpoints for monitoring and load balancer integration.

Provides basic health status and detailed system health information
including database connectivity and external service status.
"""

import time
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.infrastructure.config import get_settings
from app.infrastructure.database import check_database_connection, get_database_session

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


@router.get("/health", response_model=HealthResponse)
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


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def detailed_health_check(
    _db: Session = Depends(get_database_session),
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
    except Exception as e:
        logger.error("Database health check failed", error=str(e))
        services["database"] = {
            "status": "unhealthy",
            "type": "postgresql",
            "error": str(e),
        }
        overall_status = "unhealthy"

    # Check MCP server status
    settings = get_settings()
    if settings.mcp_enabled:
        try:
            # MCP server health check - just verify it's enabled and configured
            services["mcp_server"] = {
                "status": "healthy",
                "type": "fastmcp",
                "mount_path": settings.mcp_mount_path,
                "enabled": "true",
            }
        except Exception as e:
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
async def readiness_check(
    _db: Session = Depends(get_database_session),
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
