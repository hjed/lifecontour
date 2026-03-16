"""
Integration API controllers for managing external service integrations.

This module provides REST API endpoints for:
- Google Contacts synchronization
- Integration health monitoring
- Sync job management and status tracking
"""

import urllib.parse
from datetime import UTC, datetime
from typing import Any, cast

import aiohttp
import structlog
from core_shared.repositories.sync_job_repository import SyncJobRepository
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.integrations.schemas import (
    ComponentHealthAttributes,
    GoogleCalendarAttributes,
    GoogleCalendarData,
    GoogleCalendarListResponse,
    GoogleStatusAttributes,
    GoogleStatusData,
    GoogleStatusJsonApiResponse,
    IntegrationHealthAttributes,
    IntegrationHealthData,
    IntegrationHealthJsonApiResponse,
    OAuthAuthorizeRequest,
    OAuthAuthorizeResponse,
    OAuthCallbackRequest,
    OAuthCallbackResponse,
    OAuthDisconnectResponse,
    SyncJobAttributes,
    SyncJobData,
    SyncJobJsonApiResponse,
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


def _build_sync_job_data(job: dict[str, Any]) -> SyncJobData:
    """Build a SyncJobData instance from a raw job dictionary."""
    return SyncJobData(
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


class IntegrationStatusResponse(BaseModel):
    """Response model for integration status."""

    integration: str
    status: str
    last_sync: str | None = None
    next_sync: str | None = None


@router.post(
    "/google/contacts/sync",
    responses={
        400: {"description": "Invalid sync parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def trigger_google_sync(
    request: SyncJobRequest,
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
    db_manager: FromDishka[IntegrationDatabaseManager],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """
    Trigger a Google Contacts synchronization job.

    This endpoint queues a background sync job for the authenticated user's
    Google Contacts. The job will run asynchronously in the worker.
    """
    try:
        async with db_manager.get_session() as session:
            connection = await session.connection()
            google_account_email = (
                await oauth_service.get_connected_google_account_email(
                    user.id, connection
                )
            )

        # Determine sync type from request or force_full_sync flag
        sync_type = request.sync_type.value
        if request.force_full_sync:
            sync_type = SyncType.FULL.value

        # Enqueue the sync job
        job_id = await task_queue_service.enqueue_google_sync(
            google_account_email=google_account_email,
            user_id=user.id,
            sync_type=sync_type,
        )

        job = await task_queue_service.get_sync_job_details(
            job_id=job_id, user_id=user.id
        )

        return SyncJobJsonApiResponse(data=_build_sync_job_data(job))

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


@router.get(
    "/google/contacts/sync-history",
    responses={
        400: {"description": "Invalid date filter format"},
        500: {"description": "An unexpected error occurred"},
    },
)
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
        # Filter by google integration source since this endpoint is specific to Google Contacts
        jobs, total = await task_queue_service.list_sync_jobs(
            user_id=user.id,
            status=status,
            sync_type=sync_type,
            integration_source="google",
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

            data.append(_build_sync_job_data(job))

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


@router.get(
    "/google/contacts/sync/{job_id}",
    responses={
        400: {"description": "Invalid job ID format"},
        403: {"description": "Access denied"},
        404: {"description": "Job not found"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def get_sync_job_status(
    job_id: str,
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """
    Get the status of a specific sync job.

    Returns the current status and progress of a sync job.
    """
    try:
        job = await task_queue_service.get_sync_job_details(
            job_id=job_id, user_id=user.id
        )

        return SyncJobJsonApiResponse(data=_build_sync_job_data(job))

    except ValueError as e:
        logger.error(
            ERROR_INVALID_JOB_ID_FORMAT, job_id=job_id, error=str(e), exc_info=True
        )
        raise HTTPException(status_code=400, detail=ERROR_INVALID_JOB_ID_FORMAT) from e
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
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while retrieving job status",
        ) from e


@router.post(
    "/google/contacts/sync/{job_id}/cancel",
    responses={
        403: {"description": "Access denied"},
        404: {"description": "Job not found"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def cancel_sync_job(
    job_id: str,
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """
    Cancel a running or queued sync job.

    Marks the job as cancelled in the database. The worker will check this status
    and stop processing at the next opportunity.
    """
    try:
        await task_queue_service.cancel_job(job_id, user.id)
        job = await task_queue_service.get_sync_job_details(
            job_id=job_id, user_id=user.id
        )

        return SyncJobJsonApiResponse(data=_build_sync_job_data(job))

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


@router.get("/google/contacts/status")
@inject
async def get_google_status(
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
    db_manager: FromDishka[IntegrationDatabaseManager],
) -> GoogleStatusJsonApiResponse:
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
        needs_reconsent = False

        async with db_manager.get_session() as session:
            conn = await session.connection()

            # Check if user has Google Contacts connected
            is_connected = await oauth_service.is_google_connected(user.id, conn)

            # Build status based on connection state
            status = "active" if is_connected else "disconnected"

            if is_connected:
                # Check for calendar scopes to determine if re-consent is needed
                from sqlalchemy import text

                stmt = text("""
                    SELECT granted_scopes
                    FROM user_google_auth
                    WHERE user_id = :user_id
                """)
                result = await conn.execute(stmt, {"user_id": str(user.id)})
                rows = result.fetchall()
                for row in rows:
                    scopes = row.granted_scopes or ""
                    # If any connected account doesn't have calendar scopes, they need to re-consent
                    if (
                        "calendar.events" not in scopes
                        or "calendar.readonly" not in scopes
                    ):
                        needs_reconsent = True
                        break

                repo = SyncJobRepository(conn)

                # Get the most recent completed sync
                completed_syncs, total_count = await repo.list_by_user(
                    user_id=str(user.id),
                    status="completed",
                    integration_source="google",
                    limit=1,
                    offset=0,
                )

                if completed_syncs:
                    last_sync_job = completed_syncs[0]
                    if last_sync_job.completed_at:
                        last_sync = last_sync_job.completed_at.isoformat()

                # Get total count of completed syncs
                sync_count = total_count

        return GoogleStatusJsonApiResponse(
            data=GoogleStatusData(
                id="google",
                type="integration-status",
                attributes=GoogleStatusAttributes(
                    connected=is_connected,
                    last_sync=last_sync,
                    sync_count=sync_count,
                    status=status,
                    needs_reconsent=needs_reconsent,
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
        return GoogleStatusJsonApiResponse(
            data=GoogleStatusData(
                id="google",
                type="integration-status",
                attributes=GoogleStatusAttributes(
                    connected=False,
                    status="error",
                    error_message=str(e),
                ),
            )
        )


@router.get("/health")
@inject
async def get_integrations_health(
    health_service: FromDishka[IntegrationHealthService],
) -> IntegrationHealthJsonApiResponse:
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

        services = health_status.get("services", {})
        redis_service = services.get("redis", {})
        worker_service = services.get("google_worker", {})

        return IntegrationHealthJsonApiResponse(
            data=IntegrationHealthData(
                attributes=IntegrationHealthAttributes(
                    overall=health_status["status"],
                    last_checked=health_status["timestamp"],
                    redis=ComponentHealthAttributes(
                        status=redis_service.get("status", "unknown"),
                        latency=redis_service.get("response_time_ms"),
                        last_seen=redis_service.get("last_checked"),
                        error_message=redis_service.get("error"),
                    ),
                    worker=ComponentHealthAttributes(
                        status=worker_service.get("status", "unknown"),
                        latency=None,
                        last_seen=worker_service.get("last_checked"),
                        error_message=worker_service.get("error"),
                    ),
                ),
            )
        )

    except Exception as e:
        logger.error("Health check failed", error=str(e), exc_info=True)
        # Return unhealthy status if health check fails
        now = datetime.now(UTC).isoformat()
        unhealthy_component = ComponentHealthAttributes(
            status="unhealthy",
            latency=None,
            last_seen=now,
            error_message=str(e),
        )
        return IntegrationHealthJsonApiResponse(
            data=IntegrationHealthData(
                attributes=IntegrationHealthAttributes(
                    overall="unhealthy",
                    last_checked=now,
                    redis=unhealthy_component,
                    worker=unhealthy_component,
                ),
            )
        )


# OAuth Integration Endpoints


@router.post(
    "/google/contacts/oauth/authorize",
    responses={
        500: {"description": "Failed to initiate OAuth authorization"},
    },
)
@inject
async def google_oauth_authorize(
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

        authorization_url = await oauth_service.get_google_authorization_url(
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


@router.post(
    "/google/contacts/oauth/callback",
    responses={
        400: {"description": "Invalid OAuth callback data"},
        500: {"description": "Failed to complete OAuth authorization"},
    },
)
@inject
async def google_oauth_callback(
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

        token_data = await oauth_service.handle_google_callback(
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
        granted_scopes = token_data.get("scope")
        if not granted_scopes:
            from app.infrastructure.auth.oauth_service import GOOGLE_SCOPE

            granted_scopes = " ".join(GOOGLE_SCOPE)

        await google_token_service.store_tokens(
            user_id=user.id,
            google_email=google_email,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
            granted_scopes=granted_scopes,
        )

        # Get redirect URL from session
        redirect_url = request.session.pop("integration_redirect_url", "/integrations")

        logger.info(
            "Google OAuth callback successful and tokens stored",
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
    "/google/contacts/oauth/disconnect",
    responses={
        400: {"description": "Validation error"},
        500: {"description": "Failed to disconnect"},
    },
)
@inject
async def google_oauth_disconnect(
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
            success = await oauth_service.disconnect_google(user.id, connection)

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


GOOGLE_CALENDAR_LIST_URL = (
    "https://www.googleapis.com/calendar/v3/users/me/calendarList"
)


@router.get(
    "/google/calendars",
    response_model=GoogleCalendarListResponse,
    responses={
        401: {"description": "Not authenticated or Google not connected"},
        502: {"description": "Google Calendar API error"},
    },
)
@inject
async def list_google_calendars(
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
    google_token_service: FromDishka[GoogleTokenService],
    db_manager: FromDishka[IntegrationDatabaseManager],
) -> GoogleCalendarListResponse:
    """
    List the authenticated user's Google Calendars.

    Fetches the calendar list from the Google Calendar API using stored
    OAuth tokens. Requires the user to be connected with calendar scopes.
    """
    from app.infrastructure.auth.google_token_service import GoogleTokenNotFoundError

    # --- Resolve credentials (local failures → 401) ---
    try:
        async with db_manager.get_session() as session:
            conn = await session.connection()
            google_email = await oauth_service.get_connected_google_account_email(
                user.id, conn
            )
    except ValueError as e:
        logger.warning(
            "Google account not connected",
            user_id=user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=401,
            detail="Google account not connected",
        ) from e

    try:
        tokens = await google_token_service.get_tokens(
            user_id=str(user.id), google_email=google_email
        )
    except GoogleTokenNotFoundError as e:
        logger.warning(
            "Google tokens not found",
            user_id=user.id,
            error=str(e),
        )
        raise HTTPException(
            status_code=401,
            detail="Google tokens not found – please reconnect your account",
        ) from e

    access_token = tokens["access_token"]

    # --- Fetch calendars from Google Calendar API (paginated) ---
    try:
        headers = {"Authorization": f"Bearer {access_token}"}
        calendars: list[GoogleCalendarData] = []
        page_token: str | None = None

        async with aiohttp.ClientSession() as http_session:
            while True:
                params: dict[str, str] = {"maxResults": "250"}
                if page_token:
                    params["pageToken"] = page_token

                async with http_session.get(
                    GOOGLE_CALENDAR_LIST_URL,
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(
                            "Google Calendar API error",
                            status=response.status,
                            error=error_text,
                        )
                        raise HTTPException(
                            status_code=502,
                            detail="Failed to fetch Google Calendars",
                        )

                    data = await response.json()

                for item in data.get("items", []):
                    calendars.append(
                        GoogleCalendarData(
                            id=item["id"],
                            attributes=GoogleCalendarAttributes(
                                summary=item.get("summary", "Untitled"),
                                description=item.get("description"),
                                background_color=item.get("backgroundColor"),
                                primary=item.get("primary", False),
                            ),
                        )
                    )

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

        return GoogleCalendarListResponse(data=calendars)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to list Google Calendars",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch Google Calendars",
        ) from e


# Calendar Sync Endpoints


@router.post(
    "/google/calendar/sync",
    responses={
        400: {"description": "Invalid sync parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def trigger_calendar_sync(
    request: SyncJobRequest,
    user: FromDishka[SessionUser],
    oauth_service: FromDishka[OAuthService],
    db_manager: FromDishka[IntegrationDatabaseManager],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """
    Trigger a Google Calendar synchronization job.

    This endpoint queues a background sync job for the authenticated user's
    Google Calendar events. The job will run asynchronously in the worker.
    """
    try:
        async with db_manager.get_session() as session:
            connection = await session.connection()
            google_account_email = (
                await oauth_service.get_connected_google_account_email(
                    user.id, connection
                )
            )

        sync_type = request.sync_type.value
        if request.force_full_sync:
            sync_type = SyncType.FULL.value

        job_id = await task_queue_service.enqueue_calendar_sync(
            google_account_email=google_account_email,
            user_id=user.id,
            sync_type=sync_type,
        )

        job = await task_queue_service.get_sync_job_details(
            job_id=job_id, user_id=user.id
        )

        return SyncJobJsonApiResponse(data=_build_sync_job_data(job))

    except ValueError as e:
        logger.error("Invalid calendar sync parameters", error=str(e), exc_info=True)
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
        logger.error("Failed to enqueue calendar sync job", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while queueing the calendar sync job",
        ) from e


def _validate_webhook_headers(
    channel_id: str | None,
    resource_id: str | None,
) -> None:
    """Validate required Google webhook headers are present.

    Raises HTTPException(404) if either header is missing.
    """
    if not channel_id or not resource_id:
        raise HTTPException(status_code=404, detail="Missing channel or resource ID")


async def _lookup_webhook_channel(
    session: Any,
    channel_id: str,
    resource_id: str,
) -> Any:
    """Look up a webhook channel in the database.

    Returns the matching row or raises HTTPException(404) if not found.
    """
    from sqlalchemy import text

    stmt = text("""
        SELECT user_id, google_account_email
        FROM calendar_sync_tokens
        WHERE channel_id = :channel_id
        AND channel_resource_id = :resource_id
    """)
    result = await session.execute(
        stmt,
        {"channel_id": channel_id, "resource_id": resource_id},
    )
    row = result.fetchone()

    if not row:
        logger.warning(
            "Unknown webhook channel",
            channel_id=channel_id,
            resource_id=resource_id,
        )
        raise HTTPException(status_code=404, detail="Unknown channel")

    return row


# Google push notification resource states that indicate actual data changes.
_ENQUEUE_STATES = frozenset({"exists", "update", "not_exists"})


def _should_enqueue_sync(resource_state: str) -> bool:
    """Determine if a webhook resource_state should trigger a sync.

    Only the known Google states that indicate data changes trigger a sync.
    The 'sync' state (channel confirmation) and unknown/empty values are
    ignored to avoid spurious syncs from malformed requests.
    """
    return resource_state in _ENQUEUE_STATES


@router.post(
    "/google/calendar/webhook",
    responses={
        200: {"description": "Notification acknowledged"},
        404: {"description": "Unknown channel"},
    },
    include_in_schema=False,  # Hide from OpenAPI docs — not a user-facing endpoint
)
@inject
async def receive_calendar_webhook(
    request: Request,
    db_manager: FromDishka[IntegrationDatabaseManager],
    task_queue_service: FromDishka[TaskQueueService],
) -> dict[str, str]:
    """
    Receive Google Calendar push notification.

    This is an unauthenticated endpoint — Google push notifications don't carry
    auth tokens. Validation is performed by checking the channel_id and
    resource_id against the calendar_sync_tokens table.
    """
    channel_id = request.headers.get("X-Goog-Channel-ID")
    resource_id = request.headers.get("X-Goog-Resource-ID")
    resource_state = request.headers.get("X-Goog-Resource-State", "")

    _validate_webhook_headers(channel_id, resource_id)
    # After validation, both are guaranteed non-None strings
    channel_id = cast(str, channel_id)
    resource_id = cast(str, resource_id)

    try:
        async with db_manager.get_session() as session:
            row = await _lookup_webhook_channel(
                session,
                channel_id,
                resource_id,
            )
            user_id = row.user_id
            google_account_email = row.google_account_email

        if not _should_enqueue_sync(resource_state):
            logger.info(
                "Webhook channel sync confirmation received",
                channel_id=channel_id,
            )
            return {"status": "ok"}

        # Enqueue calendar sync for the user
        logger.info(
            "Webhook triggered calendar sync",
            channel_id=channel_id,
            resource_state=resource_state,
            google_account_email=google_account_email,
            user_id=user_id,
        )

        await task_queue_service.enqueue_calendar_sync(
            google_account_email=google_account_email,
            user_id=user_id,
            sync_type="smart",
        )

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Error processing calendar webhook",
            channel_id=channel_id,
            error=str(e),
            exc_info=True,
        )
        # Return 200 for unexpected internal errors to avoid Google retrying.
        # (HTTPExceptions for missing headers/unknown channels are re-raised above.)
        return {"status": "error", "detail": "Internal processing error"}
