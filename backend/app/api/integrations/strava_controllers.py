"""
Strava OAuth and Webhook API controllers.

Provides REST API endpoints for Strava OAuth 2.0 authorization,
token exchange (callback), disconnection, webhook event handling,
and activity import sync triggers.
"""

import secrets
from typing import Annotated
from urllib.parse import urlencode, urlparse

import httpx
import structlog
from arq.connections import ArqRedis
from core_shared.exceptions import DomainError
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, field_validator

from app.api.integrations.controllers import _build_sync_job_data
from app.api.integrations.schemas import (
    SyncJobJsonApiResponse,
    SyncJobRequest,
    SyncType,
)
from app.core.integrations.adapters.sql.journal_unmatched_strava_athlete_repository import (
    SqlJournalUnmatchedStravaAthleteRepository,
)
from app.core.integrations.strava.athlete_mapping_service import (
    StravaAthleteMappingService,
)
from app.core.integrations.strava.webhook_service import StravaWebhookService
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.strava_token_service import StravaTokenService
from app.infrastructure.config import Settings

logger = structlog.get_logger()

# Strava OAuth constants
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"
STRAVA_SCOPE = "activity:read_all"

router = APIRouter(prefix="/integrations/strava", tags=["integrations-strava"])


# ---------- Request / Response Schemas ----------


class StravaOAuthAuthorizeRequest(BaseModel):
    """Request body for Strava OAuth authorization initiation."""

    redirect_url: str = "/integrations"

    @field_validator("redirect_url")
    @classmethod
    def validate_safe_redirect(cls, v: str) -> str:
        """Prevent open-redirect by ensuring the URL is a relative path."""
        parsed = urlparse(v)
        if parsed.scheme or parsed.netloc:
            raise ValueError("redirect_url must be a relative path")
        if not v.startswith("/") or v.startswith("//"):
            raise ValueError("redirect_url must be a relative path starting with /")
        return v


class StravaOAuthAuthorizeResponse(BaseModel):
    """Response containing the Strava authorization URL."""

    authorization_url: str
    state: str


class StravaOAuthCallbackRequest(BaseModel):
    """Request body for Strava OAuth callback token exchange."""

    code: str
    state: str


class StravaOAuthCallbackResponse(BaseModel):
    """Response after successful Strava OAuth callback."""

    success: bool
    message: str
    redirect_url: str | None = None


class StravaOAuthDisconnectResponse(BaseModel):
    """Response after Strava disconnection."""

    success: bool
    message: str


class StravaAthleteMappingAttributes(BaseModel):
    strava_athlete_id: str
    strava_athlete_name: str
    contact_id: int


class StravaAthleteMappingResource(BaseModel):
    type: str = "strava-athlete-mapping"
    id: str
    attributes: StravaAthleteMappingAttributes


class StravaAthleteMappingResponse(BaseModel):
    """Response schema for a single Strava athlete mapping."""

    data: StravaAthleteMappingResource


class StravaAthleteMappingListResponse(BaseModel):
    """Response schema for a list of Strava athlete mappings."""

    data: list[StravaAthleteMappingResource]


class StravaAthleteMappingCreateRequest(BaseModel):
    """Request schema for creating a Strava athlete mapping."""

    strava_athlete_id: str
    strava_athlete_name: str
    contact_id: int


class UnmatchedStravaAthleteAttributes(BaseModel):
    strava_athlete_id: str
    strava_athlete_name: str


class UnmatchedStravaAthleteResource(BaseModel):
    type: str = "unmatched-strava-athlete"
    id: str  # Use strava_athlete_id as the ID
    attributes: UnmatchedStravaAthleteAttributes


class UnmatchedStravaAthleteListResponse(BaseModel):
    """Response schema for a list of unmatched Strava athletes."""

    data: list[UnmatchedStravaAthleteResource]


# ---------- Endpoints ----------


@router.post(
    "/oauth/authorize",
    responses={
        500: {"description": "Failed to initiate Strava OAuth authorization"},
    },
)
@inject
async def strava_oauth_authorize(
    request_data: StravaOAuthAuthorizeRequest,
    request: Request,
    user: FromDishka[SessionUser],
    settings: FromDishka[Settings],
) -> StravaOAuthAuthorizeResponse:
    """
    Initiate Strava OAuth authorization flow.

    Generates a Strava authorization URL with the ``activity:read_all`` scope.
    The frontend should redirect the user to this URL to begin the consent flow.
    """
    try:
        if not settings.strava_client_id:
            raise HTTPException(
                status_code=500,
                detail="Strava integration is not configured",
            )

        # Generate CSRF state token and store in session
        state = secrets.token_urlsafe(32)
        request.session["strava_oauth_state"] = state
        request.session["strava_redirect_url"] = request_data.redirect_url

        # Build the callback URL
        callback_url = f"{settings.frontend_url}/auth/strava/callback"

        # Build Strava authorization URL
        params = {
            "client_id": settings.strava_client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": STRAVA_SCOPE,
            "state": state,
            "approval_prompt": "auto",
        }
        authorization_url = f"{STRAVA_AUTHORIZE_URL}?{urlencode(params)}"

        logger.info(
            "Strava OAuth authorization initiated",
            user_id=user.id,
            redirect_url=request_data.redirect_url,
        )

        return StravaOAuthAuthorizeResponse(
            authorization_url=authorization_url,
            state=state,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to initiate Strava OAuth",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate Strava OAuth authorization",
        ) from e


@router.post(
    "/oauth/callback",
    responses={
        400: {"description": "Invalid OAuth callback data"},
        500: {"description": "Failed to complete Strava OAuth"},
    },
)
@inject
async def strava_oauth_callback(
    callback_data: StravaOAuthCallbackRequest,
    request: Request,
    user: FromDishka[SessionUser],
    strava_token_service: FromDishka[StravaTokenService],
    settings: FromDishka[Settings],
) -> StravaOAuthCallbackResponse:
    """
    Handle Strava OAuth callback and exchange authorization code for tokens.

    Validates the CSRF state, exchanges the authorization code with Strava's
    token endpoint, and stores encrypted tokens in the database.
    """
    try:
        # Validate CSRF state
        stored_state = request.session.pop("strava_oauth_state", None)
        if not stored_state or stored_state != callback_data.state:
            raise HTTPException(
                status_code=400,
                detail="Invalid OAuth state parameter",
            )

        # Exchange code for tokens with Strava
        async with httpx.AsyncClient() as client:
            response = await client.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": settings.strava_client_id,
                    "client_secret": settings.strava_client_secret,
                    "code": callback_data.code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            token_data = response.json()

        # Extract token fields
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_at_epoch = token_data.get("expires_at")
        athlete = token_data.get("athlete")
        if not isinstance(athlete, dict):
            raise ValueError("Missing or invalid athlete data in Strava token response")
        athlete_id = athlete.get("id")

        if not all([access_token, refresh_token, expires_at_epoch, athlete_id]):
            raise ValueError("Incomplete token response from Strava")

        # Type narrowing — all() above ensures these are non-None
        assert athlete_id is not None  # noqa: S101

        from datetime import UTC, datetime

        expires_at = datetime.fromtimestamp(float(expires_at_epoch), tz=UTC)

        # Store encrypted tokens
        await strava_token_service.store_tokens(
            user_id=str(user.id),
            athlete_id=int(athlete_id),
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )

        # Create webhook subscription (best-effort — connection succeeds
        # even if subscription fails; it can be re-created later)
        if settings.webhook_base_url:
            try:
                verify_token = secrets.token_urlsafe(32)
                callback_url = (
                    f"{settings.webhook_base_url}/api/integrations/strava/webhook"
                )

                # Store the verify token BEFORE calling Strava so the
                # validation GET handler can look it up during handshake.
                # Only update the verify_token — preserve any existing
                # subscription_id to avoid losing a valid ID if subscribe()
                # fails (e.g. Strava 409 for an existing app subscription).
                await strava_token_service.set_webhook_verify_token(
                    user_id=str(user.id),
                    verify_token=verify_token,
                )

                # Explicitly commit so the Strava handshake GET — which
                # arrives as a separate HTTP request/transaction — can see
                # the verify token we just stored.
                await strava_token_service.commit()

                webhook_service = StravaWebhookService(
                    client_id=settings.strava_client_id,
                    client_secret=settings.strava_client_secret,
                )
                subscription_id = await webhook_service.subscribe(
                    callback_url=callback_url,
                    verify_token=verify_token,
                )

                # Store the returned subscription ID alongside the token
                await strava_token_service.set_webhook_subscription(
                    user_id=str(user.id),
                    subscription_id=subscription_id,
                    verify_token=verify_token,
                )

                logger.info(
                    "Strava webhook subscription created during OAuth",
                    user_id=user.id,
                    subscription_id=subscription_id,
                )
            except Exception as webhook_err:  # noqa: BLE001
                logger.warning(
                    "Strava webhook subscription failed during OAuth "
                    "(connection still active)",
                    user_id=user.id,
                    error=str(webhook_err),
                )

        # Get redirect URL from session
        redirect_url = request.session.pop("strava_redirect_url", "/integrations")

        logger.info(
            "Strava OAuth callback successful",
            user_id=user.id,
            athlete_id=athlete_id,
        )

        return StravaOAuthCallbackResponse(
            success=True,
            message="Strava connected successfully",
            redirect_url=redirect_url,
        )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error(
            "Strava token exchange failed",
            user_id=user.id,
            status_code=e.response.status_code,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail="Failed to exchange authorization code with Strava",
        ) from e
    except ValueError as e:
        logger.error(
            "Invalid Strava OAuth callback data",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(
            "Failed to handle Strava OAuth callback",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to complete Strava OAuth authorization",
        ) from e


@router.delete(
    "/oauth/disconnect",
    responses={
        500: {"description": "Failed to disconnect Strava"},
    },
)
@inject
async def strava_oauth_disconnect(
    user: FromDishka[SessionUser],
    strava_token_service: FromDishka[StravaTokenService],
    settings: FromDishka[Settings],
) -> StravaOAuthDisconnectResponse:
    """
    Disconnect Strava integration for the authenticated user.

    Revokes the OAuth token with Strava, then removes stored credentials.
    Imported journals and their data remain.
    """
    try:
        # Best-effort revocation: try to decrypt and revoke with Strava API
        try:
            auth_data = await strava_token_service.get_auth(str(user.id))
            if auth_data:
                # Best-effort webhook unsubscribe
                sub_id = auth_data.get("strava_webhook_subscription_id")
                if sub_id and settings.strava_client_id:
                    try:
                        webhook_service = StravaWebhookService(
                            client_id=settings.strava_client_id,
                            client_secret=settings.strava_client_secret,
                        )
                        await webhook_service.unsubscribe(int(sub_id))
                    except Exception as unsub_err:  # noqa: BLE001
                        logger.warning(
                            "Strava webhook unsubscribe failed (continuing disconnect)",
                            user_id=user.id,
                            subscription_id=sub_id,
                            error=str(unsub_err),
                        )

                # Best-effort token revocation
                try:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            STRAVA_DEAUTHORIZE_URL,
                            data={"access_token": auth_data["access_token"]},
                        )
                except Exception as revoke_err:  # noqa: BLE001
                    logger.warning(
                        "Strava token revocation failed (continuing disconnect)",
                        user_id=user.id,
                        error=str(revoke_err),
                    )
        except Exception as auth_err:  # noqa: BLE001
            # Decryption/retrieval failed — still proceed with DB cleanup
            logger.warning(
                "Could not retrieve Strava tokens for revocation "
                "(continuing with DB cleanup)",
                user_id=user.id,
                error=str(auth_err),
            )

        # Delete stored tokens regardless of revocation result
        deleted = await strava_token_service.delete_tokens(str(user.id))

        if deleted:
            logger.info(
                "Strava OAuth disconnected successfully",
                user_id=user.id,
            )
            return StravaOAuthDisconnectResponse(
                success=True,
                message="Strava disconnected successfully",
            )
        else:
            logger.info(
                "No Strava connection found to disconnect",
                user_id=user.id,
            )
            return StravaOAuthDisconnectResponse(
                success=True,
                message="No Strava connection found",
            )

    except Exception as e:
        logger.error(
            "Failed to disconnect Strava",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to disconnect Strava integration",
        ) from e


# ---------- Sync Trigger Endpoints ----------


@router.post(
    "/activity_import/sync",
    responses={
        400: {"description": "Strava not connected or invalid parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def trigger_strava_sync(
    request: SyncJobRequest,
    user: FromDishka[SessionUser],
    strava_token_service: FromDishka[StravaTokenService],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """
    Trigger a Strava activity import sync job.

    Enqueues a background sync job that fetches activities from Strava
    and creates journal entries for each. The sync type may be ``full``
    (all historical activities) or ``smart`` (only changes since last sync).
    """
    try:
        # Verify Strava is connected
        is_connected = await strava_token_service.is_connected(str(user.id))
        if not is_connected:
            raise HTTPException(
                status_code=400,
                detail="Strava is not connected. Please connect Strava first.",
            )

        # Determine sync type
        sync_type = request.sync_type.value
        if request.force_full_sync:
            sync_type = SyncType.FULL.value

        # Enqueue the sync job
        job_id = await task_queue_service.enqueue_strava_sync(
            user_id=user.id,
            sync_type=sync_type,
        )

        job = await task_queue_service.get_sync_job_details(
            job_id=job_id, user_id=user.id
        )

        return SyncJobJsonApiResponse(data=_build_sync_job_data(job))

    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Invalid Strava sync parameters", error=str(e), exc_info=True)
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
        logger.error(
            "Failed to enqueue Strava sync job",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while queueing the sync job",
        ) from e


# ---------- Webhook Endpoints ----------


class StravaWebhookEvent(BaseModel):
    """Strava webhook event payload."""

    aspect_type: str  # "create", "update", or "delete"
    object_type: str  # "activity" or "athlete"
    object_id: int
    owner_id: int  # Strava athlete ID
    subscription_id: int
    event_time: int  # Unix timestamp
    updates: dict[str, str | int | float | bool] | None = None


@router.get(
    "/webhook",
    include_in_schema=False,
    responses={400: {"description": "Bad Request"}, 403: {"description": "Forbidden"}},
)
@inject
async def strava_webhook_validation(
    strava_token_service: FromDishka[StravaTokenService],
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
) -> dict[str, str]:
    """
    Handle Strava webhook validation handshake.

    Strava sends a GET request with ``hub.mode``, ``hub.challenge``, and
    ``hub.verify_token`` when creating a push subscription. The endpoint
    must echo ``hub.challenge`` if the verify token matches.

    This endpoint is unauthenticated — Strava calls it directly.
    """
    if hub_mode != "subscribe" or not hub_challenge:
        raise HTTPException(
            status_code=400,
            detail="Missing or invalid hub.mode / hub.challenge parameters",
        )

    if not hub_verify_token:
        raise HTTPException(
            status_code=400,
            detail="Missing hub.verify_token parameter",
        )

    # Look up the stored verify token from the database
    is_valid = await strava_token_service.is_valid_webhook_verify_token(
        hub_verify_token
    )

    if not is_valid:
        logger.warning(
            "Strava webhook validation failed: token mismatch",
            received_token_prefix=hub_verify_token[:8] + "..."
            if hub_verify_token
            else None,
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid verify token",
        )

    logger.info("Strava webhook validation handshake successful")
    return {"hub.challenge": hub_challenge}


@router.post(
    "/webhook",
    include_in_schema=False,
    status_code=200,
)
@inject
async def strava_webhook_event(
    event: StravaWebhookEvent,
    redis_pool: FromDishka[ArqRedis],
    strava_token_service: FromDishka[StravaTokenService],
) -> Response:
    """
    Receive Strava webhook events.

    Strava sends POST requests when activities are created, updated, or
    deleted. The endpoint must respond with HTTP 200 within 2 seconds.
    Events are enqueued as ARQ tasks for asynchronous processing by the
    Strava worker.

    This endpoint is unauthenticated — Strava calls it directly.
    The ``subscription_id`` is validated against stored subscriptions to
    reject unsolicited events.
    """
    from core_shared.integration_constants import STRAVA_ARQ_QUEUE_NAME

    if event.object_type != "activity":
        logger.debug(
            "Ignoring non-activity Strava webhook event",
            object_type=event.object_type,
            aspect_type=event.aspect_type,
            owner_id=event.owner_id,
        )
        return Response(status_code=200)

    # Validate that the subscription_id is known — reject unknown events
    # silently (return 200 to avoid leaking info, but skip enqueue)
    is_known = await strava_token_service.has_subscription_id(
        event.subscription_id,
    )
    if not is_known:
        logger.warning(
            "Strava webhook event from unknown subscription_id — skipping",
            subscription_id=event.subscription_id,
            owner_id=event.owner_id,
        )
        return Response(status_code=200)

    # Enqueue ARQ task for the Strava worker
    try:
        job = await redis_pool.enqueue_job(
            "process_strava_webhook_event",
            {
                "aspect_type": event.aspect_type,
                "object_type": event.object_type,
                "object_id": event.object_id,
                "owner_id": event.owner_id,
                "subscription_id": event.subscription_id,
                "event_time": event.event_time,
                "updates": event.updates,
            },
            _queue_name=STRAVA_ARQ_QUEUE_NAME,
        )
        logger.info(
            "Enqueued Strava webhook event for processing",
            job_id=job.job_id if job else None,
            aspect_type=event.aspect_type,
            object_id=event.object_id,
            owner_id=event.owner_id,
        )
    except Exception:
        # Return 500 so Strava treats delivery as failed and retries
        logger.error(
            "Failed to enqueue Strava webhook event",
            aspect_type=event.aspect_type,
            object_id=event.object_id,
            owner_id=event.owner_id,
            exc_info=True,
        )
        return Response(status_code=500)

    return Response(status_code=200)


@router.get(
    "/athlete-mappings",
    description="Get all Strava athlete mappings for the authenticated user",
)
@inject
async def get_athlete_mappings(
    user: FromDishka[SessionUser],
    mapping_service: FromDishka[StravaAthleteMappingService],
) -> StravaAthleteMappingListResponse:
    mappings = await mapping_service.get_all_mappings(str(user.id))
    return StravaAthleteMappingListResponse(
        data=[
            StravaAthleteMappingResource(
                id=str(m.id),
                attributes=StravaAthleteMappingAttributes(
                    strava_athlete_id=m.strava_athlete_id,
                    strava_athlete_name=m.strava_athlete_name,
                    contact_id=m.contact_id,
                ),
            )
            for m in mappings
        ]
    )


@router.post(
    "/athlete-mappings",
    description="Create or update a Strava athlete mapping and process retroactively",
)
@inject
async def create_athlete_mapping(
    request_data: StravaAthleteMappingCreateRequest,
    user: FromDishka[SessionUser],
    mapping_service: FromDishka[StravaAthleteMappingService],
) -> StravaAthleteMappingResponse:

    # The ContactNotFoundError inherits from DomainError, so the global
    # domain_error_handler will convert it to a JSON:API formatted error
    mapping = await mapping_service.create_mapping(
        user_id=str(user.id),
        strava_athlete_id=request_data.strava_athlete_id,
        strava_athlete_name=request_data.strava_athlete_name,
        contact_id=request_data.contact_id,
    )

    return StravaAthleteMappingResponse(
        data=StravaAthleteMappingResource(
            id=str(mapping.id),
            attributes=StravaAthleteMappingAttributes(
                strava_athlete_id=mapping.strava_athlete_id,
                strava_athlete_name=mapping.strava_athlete_name,
                contact_id=mapping.contact_id,
            ),
        )
    )


@router.delete(
    "/athlete-mappings/{strava_athlete_id}",
    status_code=204,
    description="Delete a Strava athlete mapping",
    responses={404: {"description": "Mapping not found"}},
)
@inject
async def delete_athlete_mapping(
    strava_athlete_id: str,
    user: FromDishka[SessionUser],
    mapping_service: FromDishka[StravaAthleteMappingService],
) -> None:
    deleted = await mapping_service.delete_mapping(str(user.id), strava_athlete_id)
    if not deleted:
        raise DomainError("Mapping not found", status_code=404)


@router.get(
    "/journals/{journal_id}/unmatched-athletes",
    description="Get unmatched Strava athletes for a specific journal",
)
@inject
async def get_journal_unmatched_athletes(
    journal_id: int,
    user: FromDishka[SessionUser],
    unmatched_repo: FromDishka[SqlJournalUnmatchedStravaAthleteRepository],
) -> UnmatchedStravaAthleteListResponse:
    # Enforce ownership check via the query scope
    athletes = await unmatched_repo.get_by_journal_id(str(user.id), journal_id)
    return UnmatchedStravaAthleteListResponse(
        data=[
            UnmatchedStravaAthleteResource(
                id=a["strava_athlete_id"],
                attributes=UnmatchedStravaAthleteAttributes(
                    strava_athlete_id=a["strava_athlete_id"],
                    strava_athlete_name=a["strava_athlete_name"],
                ),
            )
            for a in athletes
        ]
    )


# ---------- Webhook Re-register ----------


@router.post(
    "/webhooks/reregister",
    responses={
        200: {"description": "Webhook re-registration completed"},
        400: {"description": "Strava integration not configured"},
        404: {"description": "Strava not connected"},
        500: {"description": "Webhook re-registration failed"},
    },
)
@inject
async def reregister_strava_webhook(
    user: FromDishka[SessionUser],
    strava_token_service: FromDishka[StravaTokenService],
    settings: FromDishka[Settings],
) -> dict[str, object]:
    """Re-register the Strava webhook subscription.

    Deletes the existing Strava push subscription (if any) and creates a
    new one with a fresh verify token. This is useful when the webhook URL
    has changed or the subscription has become stale.
    """
    from app.api.integrations.schemas import (
        WebhookReregisterAttributes,
        WebhookReregisterData,
        WebhookReregisterResponse,
    )

    if not settings.strava_client_id or not settings.strava_client_secret:
        raise HTTPException(
            status_code=400,
            detail="Strava integration is not configured",
        )

    if not settings.webhook_base_url:
        raise HTTPException(
            status_code=400,
            detail="Webhook base URL is not configured",
        )

    # Verify Strava is connected
    is_connected = await strava_token_service.is_connected(str(user.id))
    if not is_connected:
        raise HTTPException(
            status_code=404,
            detail="Strava is not connected",
        )

    # Get existing subscription ID
    auth_data = await strava_token_service.get_auth(str(user.id))
    existing_sub_id = (
        int(auth_data["strava_webhook_subscription_id"])
        if auth_data and auth_data.get("strava_webhook_subscription_id")
        else None
    )

    # Generate new verify token and store it
    verify_token = secrets.token_urlsafe(32)
    await strava_token_service.set_webhook_verify_token(
        user_id=str(user.id),
        verify_token=verify_token,
    )
    await strava_token_service.commit()

    # Force resubscribe
    callback_url = f"{settings.webhook_base_url}/api/integrations/strava/webhook"

    try:
        webhook_service = StravaWebhookService(
            client_id=settings.strava_client_id,
            client_secret=settings.strava_client_secret,
        )
        new_sub_id = await webhook_service.force_resubscribe(
            callback_url=callback_url,
            verify_token=verify_token,
            existing_subscription_id=existing_sub_id,
        )

        # Store the new subscription ID
        await strava_token_service.set_webhook_subscription(
            user_id=str(user.id),
            subscription_id=new_sub_id,
            verify_token=verify_token,
        )
        await strava_token_service.commit()

        logger.info(
            "Strava webhook re-registered",
            user_id=user.id,
            old_subscription_id=existing_sub_id,
            new_subscription_id=new_sub_id,
        )

        return WebhookReregisterResponse(
            data=WebhookReregisterData(
                attributes=WebhookReregisterAttributes(
                    webhooks_queued=1,
                    message="Strava webhook re-registered successfully",
                )
            )
        ).model_dump()

    except Exception as e:
        logger.error(
            "Failed to re-register Strava webhook",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to re-register Strava webhook",
        ) from e
