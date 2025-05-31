"""
Health check endpoints for monitoring and load balancer integration.

Provides basic health status and detailed system health information
including database connectivity and external service status.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.infrastructure.database import check_database_connection, get_database_session

logger = structlog.get_logger()
router = APIRouter()


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
        uptime="unknown",  # TODO: Calculate actual uptime
    )


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def detailed_health_check(
    db: Session = Depends(get_database_session),
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

    # TODO: Add checks for external services (Google APIs, Immich)

    return DetailedHealthResponse(
        status=overall_status,
        timestamp=datetime.now(UTC),
        version="0.1.0",
        uptime="unknown",  # TODO: Calculate actual uptime
        services=services,
    )


@router.get("/health/ready")
async def readiness_check(
    db: Session = Depends(get_database_session),
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
