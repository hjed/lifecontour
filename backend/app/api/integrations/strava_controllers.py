"""
Strava OAuth API controllers.

Provides REST API endpoints for Strava OAuth 2.0 authorization,
token exchange (callback), and disconnection.
"""

import secrets
from urllib.parse import urlencode, urlparse

import httpx
import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

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
        athlete = token_data.get("athlete", {})
        athlete_id = athlete.get("id")

        if not all([access_token, refresh_token, expires_at_epoch, athlete_id]):
            raise ValueError("Incomplete token response from Strava")

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
        # Get current tokens to revoke with Strava
        auth_data = await strava_token_service.get_auth(str(user.id))

        if auth_data:
            # Best-effort revoke with Strava API
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        STRAVA_DEAUTHORIZE_URL,
                        data={"access_token": auth_data["access_token"]},
                    )
            except Exception as revoke_err:
                # Don't fail the disconnect if revocation fails
                logger.warning(
                    "Strava token revocation failed (continuing disconnect)",
                    user_id=user.id,
                    error=str(revoke_err),
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
