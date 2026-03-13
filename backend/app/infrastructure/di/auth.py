"""
Authentication providers for Dishka dependency injection.

Provides authentication-related services and user session management.
"""

import pydantic
import structlog
from dishka import Provider, Scope, provide
from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.infrastructure.auth.google_token_service import GoogleTokenService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.oauth_service import OAuthService
from app.infrastructure.config import Settings

logger = structlog.get_logger()


class AuthProvider(Provider):
    """Provider for authentication-related dependencies."""

    @provide(scope=Scope.REQUEST)
    def get_oauth_service(self, settings: Settings) -> OAuthService:
        """Get OAuth service instance for request scope."""
        return OAuthService(settings)

    @provide(scope=Scope.REQUEST)
    def get_google_token_service(
        self, connection: AsyncConnection, settings: Settings
    ) -> GoogleTokenService:
        """Get Google Token service instance for request scope."""
        return GoogleTokenService(
            connection=connection,
            encryption_key=settings.google_encryption_key,
        )

    @provide(scope=Scope.REQUEST)
    def get_current_user(self, request: Request, settings: Settings) -> SessionUser:
        """
        Get current authenticated user from session.

        Raises HTTPException if user is not authenticated.
        """
        # If authentication is disabled, return a mock user
        if settings.disable_auth:
            return SessionUser(
                id="dev-user",
                email="dev@example.com",
                name="Development User",
                provider="development",
            )

        user_data = request.session.get("user")

        if not user_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            return SessionUser.model_validate(user_data)
        except pydantic.ValidationError as e:
            logger.warning("Invalid user session data", error=str(e))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid session data",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    @provide(scope=Scope.REQUEST)
    def get_optional_user(
        self, request: Request, settings: Settings
    ) -> SessionUser | None:
        """
        Get current authenticated user from session if available.

        Returns None if user is not authenticated instead of raising an exception.
        """
        # If authentication is disabled, return a mock user
        if settings.disable_auth:
            return SessionUser(
                id="dev-user",
                email="dev@example.com",
                name="Development User",
                provider="development",
            )

        user_data = request.session.get("user")

        if not user_data:
            return None

        try:
            return SessionUser.model_validate(user_data)
        except pydantic.ValidationError as e:
            logger.warning("Invalid user session data", error=e, user_data=user_data)
            return None
