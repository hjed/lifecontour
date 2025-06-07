"""
Authentication dependencies for FastAPI.

Provides dependency injection for authentication and authorization.
"""

from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request, status

from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.oauth_service import OAuthService
from app.infrastructure.config import Settings, get_settings

logger = structlog.get_logger()


def get_oauth_service(settings: Settings = Depends(get_settings)) -> OAuthService:
    """Get OAuth service instance."""
    return OAuthService(settings)


def get_current_user(request: Request) -> SessionUser:
    """
    Get current authenticated user from session.

    Raises HTTPException if user is not authenticated.
    """
    user_data = request.session.get("user")

    if not user_data:
        logger.warning("No user session found")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user = SessionUser.model_validate(user_data)
        logger.debug("User authenticated", user_id=user.id, provider=user.provider)
        return user
    except Exception as e:
        logger.error("Invalid user session data", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def get_optional_user(request: Request) -> SessionUser | None:
    """
    Get current authenticated user from session if available.

    Returns None if user is not authenticated instead of raising an exception.
    """
    user_data = request.session.get("user")

    if not user_data:
        return None

    try:
        return SessionUser.model_validate(user_data)
    except Exception as e:
        logger.warning("Invalid user session data", error=str(e))
        return None


def require_authentication(
    user: SessionUser = Depends(get_current_user),
) -> SessionUser:
    """
    Dependency that requires authentication.

    Use this as a dependency for endpoints that require authentication.
    """
    return user


# Type aliases for dependency injection
OAuthServiceDep = Annotated[OAuthService, Depends(get_oauth_service)]
CurrentUserDep = Annotated[SessionUser, Depends(get_current_user)]
OptionalUserDep = Annotated[SessionUser | None, Depends(get_optional_user)]
RequireAuthDep = Annotated[SessionUser, Depends(require_authentication)]
