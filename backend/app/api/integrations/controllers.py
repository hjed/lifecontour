"""
Integration API controllers for managing external service integrations.

This module provides REST API endpoints for:
- Google Contacts synchronization
- Integration health monitoring
- Sync job management and status tracking
"""

from typing import Any

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.integrations.health_service import IntegrationHealthService
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(prefix="/integrations", tags=["integrations"])
logger = structlog.get_logger()


class SyncJobResponse(BaseModel):
    """Response model for sync job operations."""

    job_id: str
    status: str
    message: str


class IntegrationStatusResponse(BaseModel):
    """Response model for integration status."""

    integration: str
    status: str
    last_sync: str | None = None
    next_sync: str | None = None


class HealthResponse(BaseModel):
    """Response model for integration health checks."""

    status: str
    services: dict[str, Any]


@router.post("/google/contacts/sync", response_model=SyncJobResponse)
@inject
async def trigger_google_contacts_sync(
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobResponse:
    """
    Trigger a Google Contacts synchronization job.

    This endpoint queues a background sync job for the authenticated user's
    Google Contacts. The job will run asynchronously in the worker.
    """
    try:
        # For now, use the user's email as the Google account email
        # In a real implementation, you'd look up the user's connected Google account
        google_account_email = user.email

        # Enqueue the sync job
        job_id = await task_queue_service.enqueue_google_contacts_sync(
            google_account_email=google_account_email,
            user_id=int(user.id),  # Convert string ID to int for security
            sync_type="smart",
        )

        return SyncJobResponse(
            job_id=job_id,
            status="queued",
            message="Google Contacts sync job has been queued",
        )

    except Exception as e:
        logger.error("Failed to enqueue sync job", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while queueing the sync job",
        ) from e


@router.get("/google/contacts/sync/{job_id}", response_model=SyncJobResponse)
@inject
async def get_sync_job_status(
    job_id: str,
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobResponse:
    """
    Get the status of a specific sync job.

    Returns the current status and progress of a sync job.
    """
    try:
        # Get job status from the task queue
        job_status = await task_queue_service.get_job_status(job_id, int(user.id))

        return SyncJobResponse(
            job_id=job_id,
            status=job_status["status"],
            message=job_status["message"],
        )

    except Exception as e:
        logger.error(
            "Failed to get job status", job_id=job_id, error=str(e), exc_info=True
        )
        # Check if it's an access denied error
        if "access denied" in str(e).lower() or "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail="Job not found") from e
        else:
            raise HTTPException(
                status_code=500,
                detail="An unexpected error occurred while retrieving job status",
            ) from e


@router.get("/google/contacts/status", response_model=IntegrationStatusResponse)
async def get_google_contacts_status(
    user: FromDishka[SessionUser],
) -> IntegrationStatusResponse:
    """
    Get the current status of Google Contacts integration.

    Returns information about the last sync, next scheduled sync,
    and overall integration health.
    """
    # TODO: Implement actual status checking
    # For now, return a mock response
    return IntegrationStatusResponse(
        integration="google_contacts",
        status="active",
        last_sync="2024-01-01T12:00:00Z",
        next_sync="2024-01-01T18:00:00Z",
    )


@router.get("/health", response_model=HealthResponse)
@inject
async def get_integrations_health(
    health_service: FromDishka[IntegrationHealthService],
) -> HealthResponse:
    """
    Get the health status of all integration services.

    This endpoint checks the health of:
    - Redis task queue
    - Integration workers
    - External API connectivity
    """
    try:
        # Get comprehensive health status
        health_status = await health_service.get_overall_health()

        return HealthResponse(
            status=health_status["status"],
            services=health_status["services"],
        )

    except Exception as e:
        # Return unhealthy status if health check fails
        return HealthResponse(
            status="unhealthy",
            services={
                "error": {"status": "unhealthy", "message": str(e)},
            },
        )
