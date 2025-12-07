"""
Pydantic schemas for integration API endpoints.

This module defines the request and response models used by the integration
API controllers for data validation and serialization.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SyncType(str, Enum):
    """Enumeration of available sync types."""

    FULL = "full"
    INCREMENTAL = "incremental"
    SMART = "smart"


# OAuth Schemas
class GoogleOAuthConnectRequest(BaseModel):
    """Request to initiate Google OAuth connection."""

    redirect_url: str | None = Field(
        default=None, description="URL to redirect after OAuth completion"
    )
    scopes: list[str] | None = Field(
        default=None, description="OAuth scopes to request"
    )


class GoogleOAuthConnectResponse(BaseModel):
    """Response with OAuth authorization URL."""

    authorization_url: str = Field(description="URL to redirect user for OAuth")


class GoogleOAuthCallbackRequest(BaseModel):
    """Request from OAuth callback."""

    code: str = Field(description="Authorization code from Google")
    state: str = Field(description="State parameter for CSRF validation")


class GoogleOAuthCallbackResponse(BaseModel):
    """Response after successful OAuth callback."""

    email: str = Field(description="Connected Google account email")
    message: str = Field(description="Success message")


class GoogleAccountResponse(BaseModel):
    """Response with Google account details."""

    id: int = Field(description="Account ID")
    email: str = Field(description="Google account email")
    created_at: datetime = Field(description="When account was connected")
    is_token_expired: bool = Field(description="Whether access token has expired")


class GoogleAccountsListResponse(BaseModel):
    """Response with list of connected Google accounts."""

    accounts: list[GoogleAccountResponse] = Field(
        description="List of connected accounts"
    )


class SyncJobRequest(BaseModel):
    """Request model for triggering sync jobs."""

    sync_type: SyncType = Field(
        default=SyncType.SMART, description="Type of sync to perform"
    )
    force_full_sync: bool = Field(
        default=False, description="Force a full sync instead of incremental"
    )
    sync_options: dict[str, Any] = Field(
        default_factory=dict, description="Additional sync options"
    )


class SyncJobResponse(BaseModel):
    """Response model for sync job operations."""

    job_id: str = Field(description="Unique identifier for the sync job")
    status: str = Field(description="Current status of the job")
    message: str = Field(description="Human-readable status message")
    created_at: str | None = Field(
        default=None, description="ISO timestamp when the job was created"
    )
    started_at: str | None = Field(
        default=None, description="ISO timestamp when the job started processing"
    )
    completed_at: str | None = Field(
        default=None, description="ISO timestamp when the job completed"
    )
    progress: dict[str, Any] = Field(
        default_factory=dict, description="Job progress information"
    )


class IntegrationStatusResponse(BaseModel):
    """Response model for integration status."""

    integration: str = Field(description="Name of the integration")
    status: str = Field(description="Current integration status")
    enabled: bool = Field(description="Whether the integration is enabled")
    last_sync: str | None = Field(
        default=None, description="ISO timestamp of the last successful sync"
    )
    next_sync: str | None = Field(
        default=None, description="ISO timestamp of the next scheduled sync"
    )
    sync_count: int = Field(default=0, description="Total number of successful syncs")
    error_count: int = Field(
        default=0, description="Number of sync errors in the last 24 hours"
    )
    configuration: dict[str, Any] = Field(
        default_factory=dict, description="Integration configuration details"
    )


class HealthResponse(BaseModel):
    """Response model for integration health checks."""

    status: str = Field(description="Overall health status")
    timestamp: str = Field(description="ISO timestamp of the health check")
    services: dict[str, Any] = Field(description="Health status of individual services")
    version: str = Field(default="1.0.0", description="API version")


class ErrorResponse(BaseModel):
    """Response model for API errors."""

    error: str = Field(description="Error type")
    message: str = Field(description="Human-readable error message")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional error details"
    )
    timestamp: str = Field(description="ISO timestamp of the error")
