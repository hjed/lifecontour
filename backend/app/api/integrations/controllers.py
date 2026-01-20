"""
Integration API controllers for managing external service integrations.

This module provides REST API endpoints for:
- Google Contacts synchronization
- Integration health monitoring
- Sync job management and status tracking
"""

import urllib.parse
from datetime import UTC, datetime

import structlog
from core_shared.repositories.sync_job_repository import SyncJobRepository
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.integrations.schemas import (
    GoogleContactsStatusAttributes,
    GoogleContactsStatusData,
    GoogleContactsStatusJsonApiResponse,
    HealthResponse,
    OAuthAuthorizeRequest,
    OAuthAuthorizeResponse,
    OAuthCallbackRequest,
    OAuthCallbackResponse,
    OAuthDisconnectResponse,
    SyncJobAttributes,
    SyncJobData,
    SyncJobListMeta,
    SyncJobListResponse,
    SyncJobRequest,
    SyncType,
)
from app.core.integrations.database import IntegrationDatabaseManager
from app.core.integrations.exceptions import JobNotFoundException
from app.core.integrations.health_service import IntegrationHealthService
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.google_token_service import GoogleTokenService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.oauth_service import OAuthService

router = APIRouter(prefix="/integrations", tags=["integrations"])
logger = structlog.get_logger()

# Error message constants
ERROR_INVALID_JOB_ID_FORMAT = "Invalid job ID format"


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
            user_id=user.id,
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


@router.get("/google/contacts/sync-history", response_model=SyncJobListResponse)
@inject
async def list_sync_jobs(
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],
    status: str | None = Query(None, description="Filter by status"),
    sync_type: str | None = Query(None, description="Filter by sync type"),
    date_from: str | None = Query(
        None, description="Filter by created_at >= date_from (ISO format)"
    ),
    date_to: str | None = Query(
        None, description="Filter by created_at <= date_to (ISO format)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of results"),
    offset: int = Query(0, ge=0, description="Number of results to skip"),
) -> SyncJobListResponse:
    """
    List sync job history for the authenticated user.

    Returns a paginated list of sync jobs with optional filtering by status,
    sync type, and date range.
    """
    try:
        # Parse date filters if provided
        date_from_dt = None
        date_to_dt = None

        if date_from:
            try:
                date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date_from format: {str(e)}",
                ) from e

        if date_to:
            try:
                date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid date_to format: {str(e)}",
                ) from e

        # Get sync jobs from the task queue service
        # Filter by google_contacts integration source since this endpoint is specific to Google Contacts
        jobs, total = await task_queue_service.list_sync_jobs(
            user_id=user.id,
            status=status,
            sync_type=sync_type,
            integration_source="google_contacts",
            date_from=date_from_dt,
            date_to=date_to_dt,
            limit=limit,
            offset=offset,
        )

        # Convert to JSON API format
        data = []
        for job in jobs:
            # created_at should never be None since it's set when job is created
            # If it is None, this indicates a data integrity issue
            if job["created_at"] is None:
                logger.error(
                    "Sync job has missing created_at",
                    job_id=job.get("job_id"),
                    user_id=user.id,
                )
                raise HTTPException(
                    status_code=500,
                    detail="Sync job has missing created_at; data integrity issue detected.",
                )

            data.append(
                SyncJobData(
                    id=job["job_id"],
                    type="sync-job",
                    attributes=SyncJobAttributes(
                        status=job["status"],
                        sync_type=job["sync_type"],
                        created_at=job["created_at"],
                        started_at=job["started_at"],
                        completed_at=job["completed_at"],
                        error_message=job["error_message"],
                        contacts_processed=job["contacts_processed"],
                        contacts_created=job["contacts_created"],
                        contacts_updated=job["contacts_updated"],
                        contacts_deleted=job["contacts_deleted"],
                        progress=job["progress"],
                    ),
                )
            )

        # Calculate page number
        page = (offset // limit) + 1 if limit > 0 else 1

        return SyncJobListResponse(
            data=data,
            meta=SyncJobListMeta(
                total=total,
                page=page,
                page_size=limit,
            ),
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(
            "Failed to list sync jobs",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while retrieving sync history",
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
        job_status = await task_queue_service.get_job_status(job_id, user.id)

        return SyncJobResponse(
            job_id=job_id,
            status=job_status["status"],
            message=job_status["message"],
        )

    except ValueError as e:
        logger.error(
            ERROR_INVALID_JOB_ID_FORMAT, job_id=job_id, error=str(e), exc_info=True
        )
        raise HTTPException(status_code=400, detail=ERROR_INVALID_JOB_ID_FORMAT) from e
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


@router.post("/google/contacts/sync/{job_id}/cancel", response_model=SyncJobResponse)
@inject
async def cancel_sync_job(
    job_id: str,
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobResponse:
    """
    Cancel a running or queued sync job.

    Marks the job as cancelled in the database. The worker will check this status
    and stop processing at the next opportunity.
    """
    try:
        # Cancel the job
        result = await task_queue_service.cancel_job(job_id, user.id)

        return SyncJobResponse(
            job_id=job_id,
            status=result["status"],
            message=result["message"],
        )

    except JobNotFoundException as e:
        logger.error(
            "Sync job not found",
            job_id=job_id,
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=404, detail="Job not found") from e
    except PermissionError as e:
        logger.error(
            "Job cancellation access denied",
            job_id=job_id,
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=403, detail="Access denied to cancel this job"
        ) from e
    except Exception as e:
        logger.error(
            "Failed to cancel job",
            job_id=job_id,
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while cancelling job",
        ) from e


@router.get(
    "/google/contacts/status", response_model=GoogleContactsStatusJsonApiResponse
)
@inject
async def get_google_contacts_status(
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
    db_manager: FromDishka[IntegrationDatabaseManager],
) -> GoogleContactsStatusJsonApiResponse:
    """
    Get the current status of Google Contacts integration.

    Returns JSON API formatted response with connection status,
    last sync time, and sync count.
    """
    try:
        # Get actual sync stats from database
        last_sync = None
        sync_count = 0
        is_connected = False

        async with db_manager.get_session() as session:
            conn = await session.connection()

            # Check if user has Google Contacts connected
            is_connected = await oauth_service.is_google_contacts_connected(
                user.id, conn
            )

            # Build status based on connection state
            status = "active" if is_connected else "disconnected"

            if is_connected:
                repo = SyncJobRepository(conn)

                # Get the most recent completed sync
                completed_syncs, total_count = await repo.list_by_user(
                    user_id=str(user.id),
                    status="completed",
                    integration_source="google_contacts",
                    limit=1,
                    offset=0,
                )

                if completed_syncs:
                    last_sync_job = completed_syncs[0]
                    if last_sync_job.completed_at:
                        last_sync = last_sync_job.completed_at.isoformat()

                # Get total count of completed syncs
                sync_count = total_count

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
    - Queue metrics (depth, queued jobs, running jobs)
    - Job statistics (failures, retries, completion rates)
    - Recent failures for troubleshooting
    """
    try:
        # Get comprehensive health status
        health_status = await health_service.get_overall_health()

        return HealthResponse(
            status=health_status["status"],
            timestamp=health_status["timestamp"],
            services=health_status["services"],
            queue_metrics=health_status.get("queue_metrics", {}),
            job_statistics=health_status.get("job_statistics", {}),
            recent_failures=health_status.get("recent_failures", []),
            version=health_status.get("version", "1.0.0"),
        )

    except Exception as e:
        logger.error("Health check failed", error=str(e), exc_info=True)
        # Return unhealthy status if health check fails
        return HealthResponse(
            status="unhealthy",
            timestamp=datetime.now(UTC).isoformat(),
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
        base_url = str(request.base_url).rstrip("/")
        callback_url = f"{base_url}/auth/callback"

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
    google_token_service: FromDishka[GoogleTokenService],
) -> OAuthCallbackResponse:
    """
    Handle OAuth callback for Google Contacts integration.

    This endpoint processes the OAuth callback and stores the tokens
    for the authenticated user's Google Contacts integration.
    """
    try:
        # Handle the OAuth callback and store tokens
        # Use the frontend callback URL for OAuth redirect
        base_url = str(request.base_url).rstrip("/")
        callback_url = f"{base_url}/auth/callback"

        token_data = await oauth_service.handle_google_contacts_callback(
            request, callback_data.code, callback_data.state, callback_url
        )

        # Get Google user email from access token
        access_token = token_data.get("access_token")
        if not access_token:
            raise ValueError("No access token in OAuth response")

        google_email = await oauth_service.get_google_user_email(access_token)

        # Store tokens in database
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            raise ValueError("No refresh token in OAuth response")

        expires_in = token_data.get("expires_in", 3600)

        await google_token_service.store_tokens(
            user_id=user.id,
            google_email=google_email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

        # Get redirect URL from session
        redirect_url = request.session.pop("integration_redirect_url", "/integrations")

        logger.info(
            "Google Contacts OAuth callback successful and tokens stored",
            user_id=user.id,
            google_email=google_email,
            has_access_token=bool(access_token),
            has_refresh_token=bool(refresh_token),
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
    db_manager: FromDishka[IntegrationDatabaseManager],
) -> OAuthDisconnectResponse:
    """
    Disconnect Google Contacts integration for the authenticated user.

    This endpoint removes the stored OAuth tokens and disconnects
    the Google Contacts integration.
    """
    try:
        # Get database connection
        async with db_manager.get_session() as session:
            connection = await session.connection()

            # Disconnect the Google Contacts integration
            success = await oauth_service.disconnect_google_contacts(
                user.id, connection
            )

            # Commit the transaction
            await session.commit()

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
            logger.info(
                "No Google Contacts connection found to disconnect",
                user_id=user.id,
            )
            return OAuthDisconnectResponse(
                success=False,
                message="No Google Contacts connection found",
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
