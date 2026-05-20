"""
OAuth user models for authentication.

Defines data models for OAuth user information and session management.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class OAuthUserInfo(BaseModel):
    """OAuth user information from provider."""

    id: str = Field(..., description="User ID from OAuth provider")
    email: str = Field(..., description="User email address")
    name: str | None = Field(default=None, description="User display name")
    avatar_url: str | None = Field(default=None, description="User avatar URL")
    provider: str = Field(..., description="OAuth provider name")
    provider_data: dict[str, Any] = Field(
        default_factory=dict, description="Raw provider data"
    )


class SessionUser(BaseModel):
    """User information stored in session."""

    id: str = Field(..., description="User ID from OAuth provider")
    email: str = Field(..., description="User email address")
    name: str | None = Field(default=None, description="User display name")
    avatar_url: str | None = Field(default=None, description="User avatar URL")
    provider: str = Field(..., description="OAuth provider name")
    authenticated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Authentication timestamp",
    )

    @classmethod
    def from_oauth_user(cls, oauth_user: OAuthUserInfo) -> SessionUser:
        """Create SessionUser from OAuthUserInfo."""
        return cls(
            id=oauth_user.id,
            email=oauth_user.email,
            name=oauth_user.name,
            avatar_url=oauth_user.avatar_url,
            provider=oauth_user.provider,
        )


class OAuthProvider(BaseModel):
    """OAuth provider configuration."""

    name: str = Field(..., description="Provider name")
    client_id: str = Field(..., description="OAuth client ID")
    client_secret: str = Field(..., description="OAuth client secret")
    authorization_url: str | None = Field(
        default=None, description="Authorization URL (for generic providers)"
    )
    token_url: str | None = Field(
        default=None, description="Token URL (for generic providers)"
    )
    userinfo_url: str | None = Field(
        default=None, description="User info URL (for generic providers)"
    )
    scope: str = Field(default="openid email profile", description="OAuth scope")
