"""
Google OAuth domain models.

Provides domain entities for Google OAuth flow including
OAuth state management and connected account representation.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class GoogleOAuthState:
    """
    Represents OAuth state for CSRF protection.

    The state is encrypted and stored in session to validate
    the OAuth callback and prevent CSRF attacks.
    """

    user_id: str
    nonce: str
    created_at: datetime
    redirect_url: str | None = None

    def is_expired(self, max_age_seconds: int = 600) -> bool:
        """
        Check if the OAuth state has expired.

        Args:
            max_age_seconds: Maximum age in seconds (default 10 minutes)

        Returns:
            True if state has expired
        """
        from datetime import UTC

        age = (datetime.now(UTC) - self.created_at).total_seconds()
        return age > max_age_seconds


@dataclass(frozen=True)
class GoogleAccount:
    """
    Represents a connected Google account.

    Contains non-sensitive information about a linked Google account
    that can be safely displayed in the UI.
    """

    id: int
    user_id: str
    email: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @property
    def is_token_expired(self) -> bool:
        """Check if the access token has expired."""
        from datetime import UTC

        return datetime.now(UTC) >= self.expires_at


@dataclass
class GoogleOAuthTokens:
    """
    Holds OAuth tokens returned from Google.

    This is a transient object used during token exchange
    and is not persisted directly (tokens are encrypted first).
    """

    access_token: str
    refresh_token: str | None
    expires_in: int
    token_type: str
    scope: str


# Constants
GOOGLE_OAUTH_STATE_MAX_AGE_SECONDS = 600  # 10 minutes
GOOGLE_CONTACTS_READONLY_SCOPE = "https://www.googleapis.com/auth/contacts.readonly"
GOOGLE_CONTACTS_FULL_SCOPE = "https://www.googleapis.com/auth/contacts"
GOOGLE_USERINFO_EMAIL_SCOPE = "https://www.googleapis.com/auth/userinfo.email"
GOOGLE_OAUTH_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
