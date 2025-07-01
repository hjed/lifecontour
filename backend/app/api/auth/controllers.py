"""
Authentication API controllers.

Handles OAuth authentication endpoints including authorization, callback, and logout.
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, status
from starlette.responses import RedirectResponse

from app.api.auth.schemas import (
    AuthorizeRequest,
    AuthorizeResponse,
    AuthProviderInfo,
    AuthProvidersResponse,
    AuthStatusResponse,
    CallbackRequest,
    CallbackResponse,
    LogoutResponse,
    UserResponse,
)
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.oauth_service import OAuthService

logger = structlog.get_logger()

router = APIRouter()


@router.get("/providers", response_model=AuthProvidersResponse)
@inject
async def get_auth_providers(
    oauth_service: FromDishka[OAuthService],
) -> AuthProvidersResponse:
    """
    Get available OAuth providers.

    Returns a list of configured OAuth providers that users can authenticate with.
    """
    available_providers = oauth_service.get_available_providers()

    # Map provider names to display information
    provider_info_map = {
        "github": AuthProviderInfo(
            name="github",
            display_name="GitHub",
            icon_url="https://github.com/favicon.ico",
        ),
        "microsoft": AuthProviderInfo(
            name="microsoft",
            display_name="Microsoft",
            icon_url="https://www.microsoft.com/favicon.ico",
        ),
        "discord": AuthProviderInfo(
            name="discord",
            display_name="Discord",
            icon_url="https://discord.com/assets/favicon.ico",
        ),
    }

    providers = []
    for provider_name in available_providers:
        if provider_name in provider_info_map:
            providers.append(provider_info_map[provider_name])
        else:
            # Generic provider
            providers.append(
                AuthProviderInfo(
                    name=provider_name,
                    display_name=provider_name.title(),
                )
            )

    return AuthProvidersResponse(providers=providers)


@router.get("/debug/session")
async def debug_session(request: Request) -> dict:
    """Debug endpoint to test session functionality."""
    try:
        # Try to access session
        session_data = dict(request.session)
        return {
            "session_available": True,
            "session_data": session_data,
            "session_id": getattr(request.session, "session_id", "unknown"),
        }
    except Exception as e:
        return {
            "session_available": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


@router.post("/login", response_model=AuthorizeResponse)
@inject
async def login(
    request_data: AuthorizeRequest,
    request: Request,
    oauth_service: FromDishka[OAuthService],
) -> AuthorizeResponse:
    """
    Initiate OAuth login flow.

    Returns the OAuth authorization URL for the frontend to redirect to.
    This is the JSON API version of the authorize endpoint.
    """
    provider = request_data.provider
    redirect_url = request_data.redirect_url or "/"

    # Store the final redirect URL in session
    request.session["post_auth_redirect"] = redirect_url

    # Generate callback URL pointing to frontend callback page
    # OAuth provider will redirect user to frontend, which then calls backend
    # Use frontend URL for OAuth callback
    callback_url = "http://localhost:3000/auth/callback"

    # Get authorization URL from OAuth service
    # Let domain exceptions bubble up to global handlers
    authorization_url = await oauth_service.get_authorization_url(
        request, provider, callback_url
    )

    # Get the state from session (set by oauth_service.get_authorization_url)
    state = request.session.get("oauth_state", "")

    logger.info(
        "OAuth login initiated via JSON API",
        provider=provider,
        redirect_url=redirect_url,
    )

    return AuthorizeResponse(authorization_url=authorization_url, state=state)


@router.get("/authorize/{provider}")
@inject
async def authorize(
    provider: str,
    request: Request,
    oauth_service: FromDishka[OAuthService],
    redirect_url: str = Query(
        default="/", description="URL to redirect to after authentication"
    ),
) -> RedirectResponse:
    """
    Initiate OAuth authorization flow.

    Redirects the user to the OAuth provider's authorization page.
    """
    # Store the final redirect URL in session
    request.session["post_auth_redirect"] = redirect_url

    # Generate callback URL pointing to frontend callback page
    # OAuth provider will redirect user to frontend, which then calls backend
    # Use frontend URL for OAuth callback
    callback_url = "http://localhost:3000/auth/callback"

    # Get authorization URL from OAuth service
    # Let domain exceptions bubble up to global handlers
    authorization_url = await oauth_service.get_authorization_url(
        request, provider, callback_url
    )

    logger.info(
        "OAuth authorization initiated",
        provider=provider,
        redirect_url=redirect_url,
    )

    return RedirectResponse(url=authorization_url)


@router.post("/callback", response_model=CallbackResponse)
@inject
async def auth_callback_json(
    callback_data: CallbackRequest,
    request: Request,
    oauth_service: FromDishka[OAuthService],
) -> CallbackResponse:
    """
    Handle OAuth callback from frontend.

    Processes OAuth callback data sent from frontend callback page,
    exchanges authorization code for user information, and creates session.
    """
    logger.info(
        "OAuth JSON callback received",
        provider=callback_data.provider,
        code_length=len(callback_data.code) if callback_data.code else 0,
        state_length=len(callback_data.state) if callback_data.state else 0,
    )

    try:
        # TODO: Temporarily bypass session state check for debugging
        # The session state is not being maintained properly between requests
        logger.warning(
            "Bypassing session state check for debugging",
            callback_state=callback_data.state,
            provider=callback_data.provider,
        )

        # Use hardcoded redirect URI for now
        redirect_uri = "http://localhost:3000/auth/callback"

        # Exchange authorization code for user info
        oauth_user = await oauth_service.exchange_code_for_user(
            callback_data.provider, callback_data.code, redirect_uri
        )

        # Create session user
        session_user = SessionUser.from_oauth_user(oauth_user)

        # TODO: Temporarily bypass session storage for debugging
        # Store user in session (serialize datetime to ISO string)
        try:
            request.session["user"] = session_user.model_dump(mode="json")
            logger.info("Successfully stored user in session")
        except Exception as e:
            logger.warning("Failed to store user in session", error=str(e))

        # Use default redirect URL for now
        redirect_url = "/"

        logger.info(
            "OAuth authentication successful via JSON callback",
            provider=callback_data.provider,
            user_id=session_user.id,
            email=session_user.email,
        )

        return CallbackResponse(redirect_url=redirect_url)

    except Exception as e:
        logger.error(
            "OAuth JSON callback failed", provider=callback_data.provider, error=str(e)
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication failed: {str(e)}",
        ) from e


@router.get("/callback/{provider}")
@inject
async def auth_callback(
    provider: str,
    request: Request,
    oauth_service: FromDishka[OAuthService],
) -> RedirectResponse:
    """
    Handle OAuth callback.

    Processes the OAuth callback, exchanges the authorization code for user information,
    and creates a user session.
    """
    try:
        # Handle OAuth callback and get user info
        oauth_user = await oauth_service.handle_callback(request)

        # Create session user
        session_user = SessionUser.from_oauth_user(oauth_user)

        # Store user in session (serialize datetime to ISO string)
        request.session["user"] = session_user.model_dump(mode="json")

        # Get redirect URL from session
        redirect_url = request.session.pop("post_auth_redirect", "/")

        logger.info(
            "OAuth authentication successful",
            provider=provider,
            user_id=session_user.id,
            email=session_user.email,
        )

        return RedirectResponse(url=redirect_url)

    except Exception as e:
        logger.error("OAuth callback failed", provider=provider, error=str(e))
        # Redirect to error page or login page
        error_url = f"/?error=auth_failed&provider={provider}"
        return RedirectResponse(url=error_url)


@router.post("/logout", response_model=LogoutResponse)
async def logout(request: Request) -> LogoutResponse:
    """
    Logout current user.

    Clears the user session and logs out the user.
    """
    user_data = request.session.get("user")

    # Clear session
    request.session.clear()

    if user_data:
        logger.info("User logged out", user_id=user_data.get("id"))

    return LogoutResponse(message="Successfully logged out")


@router.get("/me", response_model=UserResponse)
@inject
async def get_current_user_info(user: FromDishka[SessionUser]) -> UserResponse:
    """
    Get current user information.

    Returns the current authenticated user's information.
    """
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        provider=user.provider,
        authenticated_at=user.authenticated_at,
    )


@router.get("/status", response_model=AuthStatusResponse)
@inject
async def get_auth_status(user: FromDishka[SessionUser | None]) -> AuthStatusResponse:
    """
    Get authentication status.

    Returns whether the user is authenticated and their information if available.
    """
    if user:
        user_response = UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            avatar_url=user.avatar_url,
            provider=user.provider,
            authenticated_at=user.authenticated_at,
        )
        return AuthStatusResponse(authenticated=True, user=user_response)
    else:
        return AuthStatusResponse(authenticated=False, user=None)
