"""
Strava OAuth and Webhook API controllers.

Provides REST API endpoints for Strava OAuth 2.0 authorization,
token exchange (callback), disconnection, and webhook event handling.
"""

import secrets
from urllib.parse import urlencode, urlparse

import httpx
import structlog
from arq.connections import ArqRedis
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, field_validator

from app.core.integrations.strava.webhook_service import StravaWebhookService
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
                # validation GET handler can look it up during handshake
                await strava_token_service.set_webhook_subscription(
                    user_id=str(user.id),
                    subscription_id=None,  # Not yet known
                    verify_token=verify_token,
                )

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
            except Exception as webhook_err:
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
                    except Exception as unsub_err:
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
                except Exception as revoke_err:
                    logger.warning(
                        "Strava token revocation failed (continuing disconnect)",
                        user_id=user.id,
                        error=str(revoke_err),
                    )
        except Exception as auth_err:
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
)
@inject
async def strava_webhook_validation(
    strava_token_service: FromDishka[StravaTokenService],
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
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
    stored_token = await strava_token_service.get_webhook_verify_token()

    if not stored_token or hub_verify_token != stored_token:
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
) -> Response:
    """
    Receive Strava webhook events.

    Strava sends POST requests when activities are created, updated, or
    deleted. The endpoint must respond with HTTP 200 within 2 seconds.
    Events are enqueued as ARQ tasks for asynchronous processing by the
    Strava worker.

    This endpoint is unauthenticated — Strava calls it directly.
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
        # Log but still return 200 — Strava will retry if we fail
        logger.error(
            "Failed to enqueue Strava webhook event",
            aspect_type=event.aspect_type,
            object_id=event.object_id,
            owner_id=event.owner_id,
            exc_info=True,
        )

    return Response(status_code=200)
