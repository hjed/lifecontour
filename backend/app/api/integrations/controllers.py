"""
Integration API controllers for managing external service integrations.

This module provides REST API endpoints for:
- Google Contacts synchronization
- Integration health monitoring
- Sync job management and status tracking
"""

import urllib.parse
from typing import Any

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.integrations.schemas import (
    GoogleContactsStatusAttributes,
    GoogleContactsStatusData,
    GoogleContactsStatusJsonApiResponse,
    OAuthAuthorizeRequest,
    OAuthAuthorizeResponse,
    OAuthCallbackRequest,
    OAuthCallbackResponse,
    OAuthDisconnectResponse,
    SyncJobRequest,
    SyncType,
)
from app.core.integrations.health_service import IntegrationHealthService
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.oauth_service import OAuthService

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
    request: SyncJobRequest,
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

        # Determine sync type from request or force_full_sync flag
        sync_type = request.sync_type.value
        if request.force_full_sync:
            sync_type = SyncType.FULL.value

        # Enqueue the sync job
        job_id = await task_queue_service.enqueue_google_contacts_sync(
            google_account_email=google_account_email,
            user_id=int(user.id),  # Convert string ID to int for security
            sync_type=sync_type,
        )

        return SyncJobResponse(
            job_id=job_id,
            status="queued",
            message="Google Contacts sync job has been queued",
        )

    except ValueError as e:
        logger.error("Invalid sync parameters", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sync parameters: {str(e)}",
        ) from e
    except ConnectionError as e:
        logger.error("Task queue connection failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Task queue service is temporarily unavailable",
        ) from e
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

    except ValueError as e:
        logger.error(
            "Invalid job ID format", job_id=job_id, error=str(e), exc_info=True
        )
        raise HTTPException(status_code=400, detail="Invalid job ID format") from e
    except PermissionError as e:
        logger.error(
            "Job access denied",
            job_id=job_id,
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=403, detail="Access denied to this job") from e
    except ConnectionError as e:
        logger.error(
            "Task queue connection failed", job_id=job_id, error=str(e), exc_info=True
        )
        raise HTTPException(
            status_code=503,
            detail="Task queue service is temporarily unavailable",
        ) from e
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


@router.get(
    "/google/contacts/status", response_model=GoogleContactsStatusJsonApiResponse
)
@inject
async def get_google_contacts_status(
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
) -> GoogleContactsStatusJsonApiResponse:
    """
    Get the current status of Google Contacts integration.

    Returns JSON API formatted response with connection status,
    last sync time, and sync count.
    """
    try:
        # Check if user has Google Contacts connected
        is_connected = await oauth_service.is_google_contacts_connected(user.id)

        # Build status based on connection state
        status = "active" if is_connected else "disconnected"

        # TODO: Get actual sync stats from database when implemented
        # For now, return mock sync data if connected
        last_sync = "2024-01-01T12:00:00Z" if is_connected else None
        sync_count = 150 if is_connected else 0

        return GoogleContactsStatusJsonApiResponse(
            data=GoogleContactsStatusData(
                id="google-contacts",
                type="integration-status",
                attributes=GoogleContactsStatusAttributes(
                    connected=is_connected,
                    last_sync=last_sync,
                    sync_count=sync_count,
                    status=status,
                ),
            )
        )
    except Exception as e:
        logger.error(
            "Failed to get Google Contacts status",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        # Return disconnected status on error
        return GoogleContactsStatusJsonApiResponse(
            data=GoogleContactsStatusData(
                id="google-contacts",
                type="integration-status",
                attributes=GoogleContactsStatusAttributes(
                    connected=False,
                    status="error",
                    error_message=str(e),
                ),
            )
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


# OAuth Integration Endpoints


@router.post("/google/contacts/oauth/authorize", response_model=OAuthAuthorizeResponse)
@inject
async def google_contacts_oauth_authorize(
    request_data: OAuthAuthorizeRequest,
    request: Request,
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
) -> OAuthAuthorizeResponse:
    """
    Initiate OAuth authorization flow for Google Contacts integration.

    This endpoint generates an OAuth authorization URL that the frontend
    can redirect to for connecting a Google account for contacts sync.
    """
    try:
        # Store the redirect URL in session for after OAuth completion
        request.session["integration_redirect_url"] = request_data.redirect_url

        # Generate OAuth authorization URL for Google Contacts
        # Use frontend callback URL for OAuth redirect
        callback_url = urllib.parse.urljoin(str(request.base_url), "auth/callback")

        authorization_url = await oauth_service.get_google_contacts_authorization_url(
            request, callback_url
        )

        # Extract state from the authorization URL
        # The state is embedded in the URL by the oauth_service
        parsed_url = urllib.parse.urlparse(authorization_url)
        query_params = urllib.parse.parse_qs(parsed_url.query)
        state_list = query_params.get("state")

        if not state_list or not state_list[0]:
            logger.error(
                "OAuth authorization URL missing state parameter",
                user_id=user.id,
                authorization_url=authorization_url,
            )
            raise HTTPException(
                status_code=500,
                detail="OAuth authorization URL missing state parameter",
            )

        state = state_list[0]

        logger.info(
            "Google Contacts OAuth authorization initiated",
            user_id=user.id,
            redirect_url=request_data.redirect_url,
            has_state=True,
        )

        return OAuthAuthorizeResponse(
            authorization_url=authorization_url,
            state=state,
        )

    except HTTPException:
        # Re-raise HTTP exceptions (like provider not configured)
        raise
    except Exception as e:
        logger.error(
            "Failed to initiate Google Contacts OAuth",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate OAuth authorization",
        ) from e


@router.post("/google/contacts/oauth/callback", response_model=OAuthCallbackResponse)
@inject
async def google_contacts_oauth_callback(
    callback_data: OAuthCallbackRequest,
    request: Request,
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
) -> OAuthCallbackResponse:
    """
    Handle OAuth callback for Google Contacts integration.

    This endpoint processes the OAuth callback and stores the tokens
    for the authenticated user's Google Contacts integration.
    """
    try:
        # Handle the OAuth callback and store tokens
        # Use the frontend callback URL for OAuth redirect
        callback_url = urllib.parse.urljoin(str(request.base_url), "auth/callback")

        token_data = await oauth_service.handle_google_contacts_callback(
            request, callback_data.code, callback_data.state, callback_url
        )

        # Get redirect URL from session
        redirect_url = request.session.pop("integration_redirect_url", "/integrations")

        logger.info(
            "Google Contacts OAuth callback successful",
            user_id=user.id,
            has_access_token=bool(token_data.get("access_token")),
            has_refresh_token=bool(token_data.get("refresh_token")),
        )

        return OAuthCallbackResponse(
            success=True,
            message="Google Contacts connected successfully",
            redirect_url=redirect_url,
        )

    except ValueError as e:
        logger.error(
            "Invalid OAuth callback data",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(
            "Failed to handle Google Contacts OAuth callback",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to complete OAuth authorization",
        ) from e


@router.delete(
    "/google/contacts/oauth/disconnect", response_model=OAuthDisconnectResponse
)
@inject
async def google_contacts_oauth_disconnect(
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
) -> OAuthDisconnectResponse:
    """
    Disconnect Google Contacts integration for the authenticated user.

    This endpoint removes the stored OAuth tokens and disconnects
    the Google Contacts integration.
    """
    try:
        # Disconnect the Google Contacts integration
        success = await oauth_service.disconnect_google_contacts(user.id)

        if success:
            logger.info(
                "Google Contacts OAuth disconnected successfully",
                user_id=user.id,
            )
            return OAuthDisconnectResponse(
                success=True,
                message="Google Contacts disconnected successfully",
            )
        else:
            logger.warning(
                "Google Contacts OAuth disconnect not implemented",
                user_id=user.id,
            )
            return OAuthDisconnectResponse(
                success=False,
                message="Google Contacts disconnect feature not yet implemented",
            )

    except ValueError as e:
        logger.error(
            "Google Contacts disconnect validation error",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(
            "Failed to disconnect Google Contacts",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to disconnect Google Contacts",
        ) from e
