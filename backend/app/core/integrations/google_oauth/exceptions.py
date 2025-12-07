"""
Google OAuth specific exceptions.

Provides custom exceptions for Google OAuth operations including
authentication failures, state validation errors, and token issues.
"""

from app.core.integrations.exceptions import AuthenticationError


class GoogleOAuthError(AuthenticationError):
    """Base exception for Google OAuth errors."""

    def __init__(self, message: str):
        """
        Initialize Google OAuth error.

        Args:
            message: Error message
        """
        super().__init__(
            message=message,
            integration_source="google",
            auth_type="oauth2",
        )


class GoogleOAuthStateError(GoogleOAuthError):
    """Exception raised when OAuth state validation fails."""

    def __init__(self, message: str = "Invalid or expired OAuth state"):
        """
        Initialize OAuth state error.

        Args:
            message: Error message
        """
        super().__init__(message)


class GoogleOAuthTokenError(GoogleOAuthError):
    """Exception raised when token exchange or refresh fails."""

    def __init__(
        self,
        message: str = "Failed to obtain access token",
        error_code: str | None = None,
    ):
        """
        Initialize OAuth token error.

        Args:
            message: Error message
            error_code: Error code from Google OAuth API
        """
        super().__init__(message)
        self.error_code = error_code


class GoogleAccountNotFoundError(GoogleOAuthError):
    """Exception raised when Google account is not found."""

    def __init__(self, email: str):
        """
        Initialize account not found error.

        Args:
            email: Google account email that was not found
        """
        super().__init__(f"Google account not found: {email}")
        self.email = email


class GoogleOAuthConfigurationError(GoogleOAuthError):
    """Exception raised when OAuth is not properly configured."""

    def __init__(self, message: str = "Google OAuth is not configured"):
        """
        Initialize configuration error.

        Args:
            message: Error message describing configuration issue
        """
        super().__init__(message)


class GoogleOAuthTokenSaveError(GoogleOAuthError):
    """Exception raised when token save operation fails."""

    def __init__(self, user_id: str, email: str):
        """
        Initialize token save error.

        Args:
            user_id: User ID that the save was attempted for
            email: Google account email that was being saved
        """
        super().__init__(
            f"Failed to save Google OAuth tokens for user {user_id}, email {email}"
        )
        self.user_id = user_id
        self.email = email
