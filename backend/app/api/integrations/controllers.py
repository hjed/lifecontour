"""
Integration API controllers for managing external service integrations.

This module provides REST API endpoints for:
- Google Contacts synchronization
- Google OAuth account linking
- Integration health monitoring
- Sync job management and status tracking
"""

from typing import Any

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.api.integrations.schemas import (
    GoogleAccountResponse,
    GoogleAccountsListResponse,
    GoogleOAuthCallbackRequest,
    GoogleOAuthCallbackResponse,
    GoogleOAuthConnectRequest,
    GoogleOAuthConnectResponse,
    SyncJobRequest,
    SyncType,
)
from app.core.integrations.google_oauth import (
    GoogleAccountNotFoundError,
    GoogleOAuthConfigurationError,
    GoogleOAuthService,
    GoogleOAuthStateError,
    GoogleOAuthTokenError,
)
from app.core.integrations.health_service import IntegrationHealthService
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.config import Settings

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


@router.get("/google/contacts/status", response_model=IntegrationStatusResponse)
@inject
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


# Google OAuth Endpoints
@router.post("/google/oauth/connect", response_model=GoogleOAuthConnectResponse)
@inject
async def initiate_google_oauth(
    request: GoogleOAuthConnectRequest,
    http_request: Request,
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[GoogleOAuthService],
    settings: FromDishka[Settings],
) -> GoogleOAuthConnectResponse:
    """
    Initiate Google OAuth connection flow.

    Returns an authorization URL to redirect the user to Google's OAuth
    consent page. After user authorization, Google will redirect back
    to the callback endpoint.
    """
    try:
        # Create OAuth state for CSRF protection
        state = oauth_service.create_oauth_state(
            user_id=user.id,
            redirect_url=request.redirect_url,
        )

        # Build callback URL
        callback_url = f"{settings.frontend_url}/integrations/callback"

        # Get authorization URL
        authorization_url = oauth_service.get_authorization_url(
            state=state,
            callback_url=callback_url,
            scopes=request.scopes,
        )

        logger.info(
            "Initiated Google OAuth flow",
            user_id=user.id,
        )

        return GoogleOAuthConnectResponse(authorization_url=authorization_url)

    except GoogleOAuthConfigurationError as e:
        logger.error("Google OAuth not configured", error=str(e))
        raise HTTPException(
            status_code=501,
            detail="Google OAuth is not configured on this server",
        ) from e


@router.post("/google/oauth/callback", response_model=GoogleOAuthCallbackResponse)
@inject
async def handle_google_oauth_callback(
    request: GoogleOAuthCallbackRequest,
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[GoogleOAuthService],
    settings: FromDishka[Settings],
) -> GoogleOAuthCallbackResponse:
    """
    Handle Google OAuth callback.

    Exchanges the authorization code for access tokens and stores
    the encrypted tokens for the connected Google account.
    """
    try:
        # Decode and validate OAuth state
        state = oauth_service.decode_state(request.state)

        # Verify user matches the state
        if state.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="OAuth state does not match current user",
            )

        # Build callback URL (must match the one used in authorization)
        callback_url = f"{settings.frontend_url}/integrations/callback"

        # Exchange authorization code for tokens
        tokens = await oauth_service.exchange_code_for_tokens(
            code=request.code,
            callback_url=callback_url,
        )

        # Get user's Google email
        email = await oauth_service.get_user_email(tokens.access_token)

        # Save the account with encrypted tokens
        await oauth_service.save_account(
            user_id=user.id,
            tokens=tokens,
            email=email,
        )

        logger.info(
            "Google OAuth connection successful",
            user_id=user.id,
            google_email=email,
        )

        return GoogleOAuthCallbackResponse(
            email=email,
            message="Google account connected successfully",
        )

    except GoogleOAuthStateError as e:
        logger.error("OAuth state validation failed", error=str(e))
        raise HTTPException(
            status_code=400,
            detail="Invalid or expired OAuth state",
        ) from e
    except GoogleOAuthTokenError as e:
        logger.error("OAuth token exchange failed", error=str(e))
        raise HTTPException(
            status_code=400,
            detail=f"Failed to exchange authorization code: {str(e)}",
        ) from e


@router.get("/google/accounts", response_model=GoogleAccountsListResponse)
@inject
async def list_google_accounts(
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[GoogleOAuthService],
) -> GoogleAccountsListResponse:
    """
    List all connected Google accounts for the current user.

    Returns account information including email and connection status.
    """
    accounts = await oauth_service.get_accounts(user_id=user.id)

    return GoogleAccountsListResponse(
        accounts=[
            GoogleAccountResponse(
                id=account.id,
                email=account.email,
                created_at=account.created_at,
                is_token_expired=account.is_token_expired,
            )
            for account in accounts
        ]
    )


@router.delete("/google/accounts/{email}")
@inject
async def disconnect_google_account(
    email: str,
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[GoogleOAuthService],
) -> dict[str, str]:
    """
    Disconnect a Google account.

    Removes the stored OAuth tokens for the specified Google account.
    """
    try:
        await oauth_service.disconnect_account(
            user_id=user.id,
            email=email,
        )

        logger.info(
            "Google account disconnected",
            user_id=user.id,
            email=email,
        )

        return {"message": f"Google account {email} disconnected successfully"}

    except GoogleAccountNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Google account {email} not found",
        ) from None
