"""
Authentication API schemas for request and response models.

Defines Pydantic models for authentication-related API endpoints.
"""

from datetime import datetime

from pydantic import BaseModel, Field


class AuthProviderInfo(BaseModel):
    """OAuth provider information."""

    name: str = Field(..., description="Provider name")
    display_name: str = Field(..., description="Human-readable provider name")
    icon_url: str | None = Field(default=None, description="Provider icon URL")


class AuthProvidersResponse(BaseModel):
    """Response model for available OAuth providers."""

    providers: list[AuthProviderInfo] = Field(
        ..., description="List of available OAuth providers"
    )


class AuthorizeRequest(BaseModel):
    """Request model for OAuth authorization."""

    provider: str = Field(..., description="OAuth provider name")
    redirect_url: str | None = Field(
        default=None, description="URL to redirect to after authentication"
    )


class AuthorizeResponse(BaseModel):
    """Response model for OAuth authorization."""

    authorization_url: str = Field(..., description="OAuth authorization URL")
    state: str = Field(..., description="OAuth state parameter")


class UserResponse(BaseModel):
    """Response model for user information."""

    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email address")
    name: str | None = Field(default=None, description="User display name")
    avatar_url: str | None = Field(default=None, description="User avatar URL")
    provider: str = Field(..., description="OAuth provider name")
    authenticated_at: datetime = Field(..., description="Authentication timestamp")


class LogoutResponse(BaseModel):
    """Response model for logout."""

    message: str = Field(
        default="Successfully logged out", description="Logout message"
    )


class AuthStatusResponse(BaseModel):
    """Response model for authentication status."""

    authenticated: bool = Field(..., description="Whether user is authenticated")
    user: UserResponse | None = Field(
        default=None, description="User information if authenticated"
    )


class AuthErrorResponse(BaseModel):
    """Response model for authentication errors."""

    error: str = Field(..., description="Error type")
    error_description: str = Field(..., description="Human-readable error description")
    provider: str | None = Field(
        default=None, description="OAuth provider name if applicable"
    )
