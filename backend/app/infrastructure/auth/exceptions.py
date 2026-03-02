"""
Authentication exceptions.

Defines custom exceptions for authentication and authorization errors.
"""

from core_shared.exceptions import DomainError


class AuthenticationError(DomainError):
    """Base authentication error."""

    pass


class InvalidCredentialsError(AuthenticationError):
    """Invalid credentials provided."""

    def __init__(self, message: str = "Invalid credentials") -> None:
        super().__init__(message)


class SessionExpiredError(AuthenticationError):
    """User session has expired."""

    def __init__(self, message: str = "Session has expired") -> None:
        super().__init__(message)


class OAuthError(AuthenticationError):
    """OAuth authentication error."""

    def __init__(self, provider: str, message: str) -> None:
        super().__init__(f"OAuth error for {provider}: {message}")
        self.provider = provider


class ProviderNotConfiguredError(AuthenticationError):
    """OAuth provider not configured."""

    def __init__(self, provider: str) -> None:
        super().__init__(f"OAuth provider '{provider}' is not configured")
        self.provider = provider


class UnauthorizedError(AuthenticationError):
    """User is not authorized to access resource."""

    def __init__(self, message: str = "Unauthorized access") -> None:
        super().__init__(message)
