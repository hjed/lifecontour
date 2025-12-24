"""
Pydantic schemas for integration API endpoints.

This module defines the request and response models used by the integration
API controllers for data validation and serialization.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SyncType(str, Enum):
    """Enumeration of available sync types."""

    FULL = "full"
    INCREMENTAL = "incremental"
    SMART = "smart"


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


class GoogleContactsStatusAttributes(BaseModel):
    """Attributes for Google Contacts integration status (JSON API format)."""

    connected: bool = Field(description="Whether the integration is connected")
    last_sync: str | None = Field(
        default=None,
        description="ISO timestamp of the last successful sync",
        serialization_alias="lastSync",
    )
    sync_count: int = Field(
        default=0,
        description="Total number of contacts synced",
        serialization_alias="syncCount",
    )
    status: str = Field(
        default="disconnected",
        description="Current integration status (active, inactive, error, disconnected)",
    )
    error_message: str | None = Field(
        default=None,
        description="Error message if status is error",
        serialization_alias="errorMessage",
    )

    model_config = {"populate_by_name": True}


class GoogleContactsStatusData(BaseModel):
    """JSON API data wrapper for Google Contacts status."""

    id: str = Field(default="google-contacts", description="Resource identifier")
    type: str = Field(
        default="integration-status", description="Resource type for JSON API"
    )
    attributes: GoogleContactsStatusAttributes = Field(
        description="Integration status attributes"
    )


class GoogleContactsStatusJsonApiResponse(BaseModel):
    """JSON API response for Google Contacts integration status."""

    data: GoogleContactsStatusData = Field(description="JSON API data object")


class HealthResponse(BaseModel):
    """Response model for integration health checks."""

    status: str = Field(description="Overall health status")
    timestamp: str = Field(description="ISO timestamp of the health check")
    services: dict[str, Any] = Field(description="Health status of individual services")
    version: str = Field(default="1.0.0", description="API version")


class OAuthAuthorizeRequest(BaseModel):
    """Request model for OAuth authorization."""

    redirect_url: str = Field(
        default="/integrations", description="URL to redirect to after OAuth completion"
    )


class OAuthAuthorizeResponse(BaseModel):
    """Response model for OAuth authorization."""

    authorization_url: str = Field(description="OAuth authorization URL to redirect to")
    state: str = Field(description="OAuth state parameter for security")


class OAuthCallbackRequest(BaseModel):
    """Request model for OAuth callback."""

    code: str = Field(description="OAuth authorization code")
    state: str = Field(description="OAuth state parameter")


class OAuthCallbackResponse(BaseModel):
    """Response model for OAuth callback."""

    success: bool = Field(description="Whether OAuth was successful")
    message: str = Field(description="Human-readable status message")
    redirect_url: str = Field(description="URL to redirect to after completion")


class OAuthDisconnectResponse(BaseModel):
    """Response model for OAuth disconnect."""

    success: bool = Field(description="Whether disconnect was successful")
    message: str = Field(description="Human-readable status message")


class ErrorResponse(BaseModel):
    """Response model for API errors."""

    error: str = Field(description="Error type")
    message: str = Field(description="Human-readable error message")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional error details"
    )
    timestamp: str = Field(description="ISO timestamp of the error")
