"""
Snipe-IT OAuth API controller.

Provides REST API endpoints for Snipe-IT OAuth 2.0 authorization,
token exchange (callback), and disconnection.

Unlike Strava/Google whose OAuth endpoints are fixed, Snipe-IT's
OAuth URLs are derived from the user's configured Base URL stored
in the ``snipeit_settings`` table.
"""

import secrets
from urllib.parse import urlencode, urlparse

import httpx
import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, field_validator

from app.core.integrations.adapters.sql.snipeit_settings_repository import (
    SqlSnipeItSettingsRepository,
)
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.snipeit_token_service import SnipeItTokenService
from app.infrastructure.config import Settings

logger = structlog.get_logger()

router = APIRouter(prefix="/integrations/snipeit", tags=["integrations-snipeit"])


# ---------- Request / Response Schemas ----------


class SnipeItOAuthAuthorizeRequest(BaseModel):
    """Request body for Snipe-IT OAuth authorization initiation."""

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


class SnipeItOAuthAuthorizeResponse(BaseModel):
    """Response containing the Snipe-IT authorization URL."""

    authorization_url: str
    state: str


class SnipeItOAuthCallbackRequest(BaseModel):
    """Request body for Snipe-IT OAuth callback token exchange."""

    code: str
    state: str


class SnipeItOAuthCallbackResponse(BaseModel):
    """Response after successful Snipe-IT OAuth callback."""

    success: bool
    message: str
    redirect_url: str | None = None


class SnipeItOAuthDisconnectResponse(BaseModel):
    """Response after Snipe-IT disconnection."""

    success: bool
    message: str


# ---------- Endpoints ----------


@router.post(
    "/oauth/authorize",
    responses={
        400: {"description": "Snipe-IT not configured"},
        500: {"description": "Failed to initiate Snipe-IT OAuth authorization"},
    },
)
@inject
async def snipeit_oauth_authorize(
    request_data: SnipeItOAuthAuthorizeRequest,
    request: Request,
    user: FromDishka[SessionUser],
    settings: FromDishka[Settings],
    snipeit_settings_repo: FromDishka[SqlSnipeItSettingsRepository],
) -> SnipeItOAuthAuthorizeResponse:
    """
    Initiate Snipe-IT OAuth authorization flow.

    Looks up the user's Snipe-IT Base URL from ``snipeit_settings``,
    then generates an authorization URL pointing to that instance's
    OAuth server. The frontend should redirect the user to this URL.
    """
    try:
        if not settings.snipeit_client_id:
            raise HTTPException(
                status_code=500,
                detail="Snipe-IT integration is not configured",
            )

        # Look up the user's Snipe-IT Base URL
        snipeit_settings = await snipeit_settings_repo.get_by_user_id(str(user.id))
        if not snipeit_settings or not snipeit_settings.base_url:
            raise HTTPException(
                status_code=400,
                detail="Please configure your Snipe-IT Base URL first",
            )

        base_url = snipeit_settings.base_url.rstrip("/")

        # Generate CSRF state token and store in session
        state = secrets.token_urlsafe(32)
        request.session["snipeit_oauth_state"] = state
        request.session["snipeit_redirect_url"] = request_data.redirect_url

        # Build the callback URL
        callback_url = f"{settings.frontend_url}/auth/snipeit/callback"

        # Build Snipe-IT authorization URL (Passport standard)
        params = {
            "client_id": settings.snipeit_client_id,
            "redirect_uri": callback_url,
            "response_type": "code",
            "scope": "",
            "state": state,
        }
        authorization_url = f"{base_url}/oauth/authorize?{urlencode(params)}"

        logger.info(
            "Snipe-IT OAuth authorization initiated",
            user_id=user.id,
            base_url=base_url,
            redirect_url=request_data.redirect_url,
        )

        return SnipeItOAuthAuthorizeResponse(
            authorization_url=authorization_url,
            state=state,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to initiate Snipe-IT OAuth",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate Snipe-IT OAuth authorization",
        ) from e


@router.post(
    "/oauth/callback",
    responses={
        400: {"description": "Invalid OAuth callback data"},
        500: {"description": "Failed to complete Snipe-IT OAuth"},
    },
)
@inject
async def snipeit_oauth_callback(
    callback_data: SnipeItOAuthCallbackRequest,
    request: Request,
    user: FromDishka[SessionUser],
    snipeit_token_service: FromDishka[SnipeItTokenService],
    snipeit_settings_repo: FromDishka[SqlSnipeItSettingsRepository],
    settings: FromDishka[Settings],
) -> SnipeItOAuthCallbackResponse:
    """
    Handle Snipe-IT OAuth callback and exchange authorization code for tokens.

    Validates the CSRF state, exchanges the authorization code with the
    Snipe-IT instance's token endpoint, and stores encrypted tokens in
    the database.
    """
    try:
        # Validate CSRF state
        stored_state = request.session.pop("snipeit_oauth_state", None)
        if not stored_state or stored_state != callback_data.state:
            raise HTTPException(
                status_code=400,
                detail="Invalid OAuth state parameter",
            )

        if (
            not settings.snipeit_client_id
            or not settings.snipeit_client_secret
            or not settings.snipeit_encryption_key
        ):
            raise HTTPException(
                status_code=500,
                detail="Snipe-IT integration is not fully configured",
            )

        # Look up the user's Snipe-IT Base URL for token exchange
        snipeit_settings = await snipeit_settings_repo.get_by_user_id(str(user.id))
        if not snipeit_settings or not snipeit_settings.base_url:
            raise HTTPException(
                status_code=400,
                detail="Snipe-IT settings not found",
            )

        base_url = snipeit_settings.base_url.rstrip("/")
        token_url = f"{base_url}/oauth/token"
        callback_url = f"{settings.frontend_url}/auth/snipeit/callback"

        # Exchange code for tokens with Snipe-IT
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.snipeit_client_id,
                    "client_secret": settings.snipeit_client_secret,
                    "redirect_uri": callback_url,
                    "code": callback_data.code,
                },
            )
            response.raise_for_status()
            token_data = response.json()

        # Extract token fields
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")

        if not all([access_token, refresh_token, expires_in]):
            raise ValueError("Incomplete token response from Snipe-IT")

        from datetime import UTC, datetime, timedelta

        token_expires_at = datetime.now(UTC) + timedelta(seconds=int(expires_in))

        # Store encrypted tokens
        await snipeit_token_service.store_tokens(
            user_id=str(user.id),
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_at,
        )

        # Get redirect URL from session
        redirect_url = request.session.pop("snipeit_redirect_url", "/integrations")

        logger.info(
            "Snipe-IT OAuth callback successful",
            user_id=user.id,
        )

        return SnipeItOAuthCallbackResponse(
            success=True,
            message="Snipe-IT connected successfully",
            redirect_url=redirect_url,
        )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        logger.error(
            "Snipe-IT token exchange failed",
            user_id=user.id,
            status_code=e.response.status_code,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail="Failed to exchange authorization code with Snipe-IT",
        ) from e
    except ValueError as e:
        logger.error(
            "Invalid Snipe-IT OAuth callback data",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(
            "Failed to handle Snipe-IT OAuth callback",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to complete Snipe-IT OAuth authorization",
        ) from e


@router.delete(
    "/oauth/disconnect",
    responses={
        500: {"description": "Failed to disconnect Snipe-IT"},
    },
)
@inject
async def snipeit_oauth_disconnect(
    user: FromDishka[SessionUser],
    snipeit_token_service: FromDishka[SnipeItTokenService],
) -> SnipeItOAuthDisconnectResponse:
    """
    Disconnect Snipe-IT integration for the authenticated user.

    Removes the stored OAuth credentials. Imported data remains.
    """
    try:
        deleted = await snipeit_token_service.delete_tokens(str(user.id))

        if deleted:
            logger.info(
                "Snipe-IT OAuth disconnected successfully",
                user_id=user.id,
            )
            return SnipeItOAuthDisconnectResponse(
                success=True,
                message="Snipe-IT disconnected successfully",
            )
        else:
            logger.info(
                "No Snipe-IT connection found to disconnect",
                user_id=user.id,
            )
            return SnipeItOAuthDisconnectResponse(
                success=True,
                message="No Snipe-IT connection found",
            )

    except Exception as e:
        logger.error(
            "Failed to disconnect Snipe-IT",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to disconnect Snipe-IT integration",
        ) from e
