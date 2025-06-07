"""Authentication infrastructure components."""

from app.infrastructure.auth.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    OAuthError,
    ProviderNotConfiguredError,
    SessionExpiredError,
    UnauthorizedError,
)
from app.infrastructure.auth.models import OAuthProvider, OAuthUserInfo, SessionUser
from app.infrastructure.auth.oauth_service import OAuthService

__all__ = [
    "AuthenticationError",
    "InvalidCredentialsError",
    "OAuthError",
    "OAuthProvider",
    "OAuthService",
    "OAuthUserInfo",
    "ProviderNotConfiguredError",
    "SessionExpiredError",
    "SessionUser",
    "UnauthorizedError",
]
