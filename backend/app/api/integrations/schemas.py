"""
Pydantic schemas for integration API endpoints.

This module defines the request and response models used by the integration
API controllers for data validation and serialization.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# Shared field description constants (avoids literal duplication)
STATUS_MESSAGE_DESCRIPTION = "Human-readable status message"


class SyncType(StrEnum):
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
    message: str = Field(description=STATUS_MESSAGE_DESCRIPTION)
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


class GoogleStatusAttributes(BaseModel):
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
        description="Current integration status (active, inactive, error, disconnected, token_expired)",
    )
    error_message: str | None = Field(
        default=None,
        description="Error message if status is error",
        serialization_alias="errorMessage",
    )
    needs_reconsent: bool = Field(
        default=False,
        description="Whether the user needs to re-consent to grant required scopes",
        serialization_alias="needsReconsent",
    )
    needs_reauth: bool = Field(
        default=False,
        description="Whether the refresh token has been revoked and the user needs to re-authenticate",
        serialization_alias="needsReauth",
    )

    model_config = {"populate_by_name": True}


class GoogleStatusData(BaseModel):
    """JSON API data wrapper for Google Contacts status."""

    id: str = Field(default="google", description="Resource identifier")
    type: str = Field(
        default="integration-status", description="Resource type for JSON API"
    )
    attributes: GoogleStatusAttributes = Field(
        description="Integration status attributes"
    )


class GoogleStatusJsonApiResponse(BaseModel):
    """JSON API response for Google Contacts integration status."""

    data: GoogleStatusData = Field(description="JSON API data object")


class HealthResponse(BaseModel):
    """Response model for integration health checks."""

    status: str = Field(description="Overall health status")
    timestamp: str = Field(description="ISO timestamp of the health check")
    services: dict[str, Any] = Field(description="Health status of individual services")
    queue_metrics: dict[str, Any] = Field(
        default_factory=dict, description="Queue depth and statistics"
    )
    job_statistics: dict[str, Any] = Field(
        default_factory=dict, description="Job statistics (failures, retries, etc.)"
    )
    recent_failures: list[dict[str, Any]] = Field(
        default_factory=list, description="List of recent failed jobs"
    )
    version: str = Field(default="1.0.0", description="API version")


# Integration Health Response Models (JSON API format)
class ComponentHealthAttributes(BaseModel):
    """Health attributes for a single component (JSON API format)."""

    status: str = Field(description="Component health status")
    latency: float | None = Field(
        default=None,
        description="Component latency in milliseconds",
    )
    last_seen: str | None = Field(
        default=None,
        description="ISO timestamp when the component was last checked/seen",
        serialization_alias="lastSeen",
    )
    error_message: str | None = Field(
        default=None,
        description="Error message if the component is unhealthy",
        serialization_alias="errorMessage",
    )

    model_config = {"populate_by_name": True}


class IntegrationHealthAttributes(BaseModel):
    """Integration health attributes returned to the frontend (JSON API format)."""

    redis: ComponentHealthAttributes = Field(description="Redis component health")
    worker: ComponentHealthAttributes = Field(description="Worker component health")
    overall: str = Field(description="Overall health status")
    last_checked: str = Field(
        description="ISO timestamp of the health check",
        serialization_alias="lastChecked",
    )

    model_config = {"populate_by_name": True}


class IntegrationHealthData(BaseModel):
    """JSON API data wrapper for integration health."""

    id: str = Field(default="health", description="Resource identifier")
    type: str = Field(default="integration-health", description="Resource type")
    attributes: IntegrationHealthAttributes = Field(
        description="Integration health attributes"
    )


class IntegrationHealthJsonApiResponse(BaseModel):
    """JSON API response for integration health."""

    data: IntegrationHealthData = Field(description="JSON API data object")


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
    message: str = Field(description=STATUS_MESSAGE_DESCRIPTION)
    redirect_url: str = Field(description="URL to redirect to after completion")


class OAuthDisconnectResponse(BaseModel):
    """Response model for OAuth disconnect."""

    success: bool = Field(description="Whether disconnect was successful")
    message: str = Field(description=STATUS_MESSAGE_DESCRIPTION)


class ErrorResponse(BaseModel):
    """Response model for API errors."""

    error: str = Field(description="Error type")
    message: str = Field(description="Human-readable error message")
    details: dict[str, Any] = Field(
        default_factory=dict, description="Additional error details"
    )
    timestamp: str = Field(description="ISO timestamp of the error")


# Sync Job List Response Models (JSON API format)
class SyncJobAttributes(BaseModel):
    """Attributes for a sync job (JSON API format)."""

    status: str = Field(description="Job status")
    sync_type: str = Field(description="Type of sync", serialization_alias="syncType")
    created_at: str = Field(
        description="ISO timestamp when job was created",
        serialization_alias="createdAt",
    )
    started_at: str | None = Field(
        default=None,
        description="ISO timestamp when job started",
        serialization_alias="startedAt",
    )
    completed_at: str | None = Field(
        default=None,
        description="ISO timestamp when job completed",
        serialization_alias="completedAt",
    )
    error_message: str | None = Field(
        default=None,
        description="Error message if failed",
        serialization_alias="errorMessage",
    )
    contacts_processed: int | None = Field(
        default=None,
        description="Number of contacts processed",
        serialization_alias="contactsProcessed",
    )
    contacts_created: int | None = Field(
        default=None,
        description="Number of contacts created",
        serialization_alias="contactsCreated",
    )
    contacts_updated: int | None = Field(
        default=None,
        description="Number of contacts updated",
        serialization_alias="contactsUpdated",
    )
    contacts_deleted: int | None = Field(
        default=None,
        description="Number of contacts deleted",
        serialization_alias="contactsDeleted",
    )
    progress: int | None = Field(
        default=None, description="Progress percentage (0-100)"
    )

    model_config = {"populate_by_name": True}


class SyncJobData(BaseModel):
    """Data wrapper for a sync job (JSON API format)."""

    id: str = Field(description="Job ID")
    type: str = Field(default="sync-job", description="Resource type")
    attributes: SyncJobAttributes = Field(description="Job attributes")


class SyncJobListMeta(BaseModel):
    """Metadata for sync job list response."""

    total: int = Field(description="Total number of jobs matching filters")
    page: int = Field(description="Current page number")
    page_size: int = Field(
        description="Number of items per page",
        serialization_alias="pageSize",
    )

    model_config = {"populate_by_name": True}


class SyncJobListResponse(BaseModel):
    """Response model for sync job list (JSON API format)."""

    data: list[SyncJobData] = Field(description="List of sync jobs")
    meta: SyncJobListMeta = Field(description="Response metadata")


class SyncJobJsonApiResponse(BaseModel):
    """Response model for a single sync job (JSON API format)."""

    data: SyncJobData = Field(description="Sync job resource")


# Google Calendar List Response Models (JSON API format)
class GoogleCalendarAttributes(BaseModel):
    """Attributes for a Google Calendar item."""

    summary: str = Field(description="Calendar name/summary")
    description: str | None = Field(default=None, description="Calendar description")
    background_color: str | None = Field(
        default=None,
        description="Calendar background colour",
        serialization_alias="backgroundColor",
    )
    primary: bool = Field(
        default=False, description="Whether this is the primary calendar"
    )
    access_role: str | None = Field(
        default=None,
        description="User's access role (owner, writer, reader, freeBusyReader)",
        serialization_alias="accessRole",
    )

    model_config = {"populate_by_name": True}


class GoogleCalendarData(BaseModel):
    """JSON API data wrapper for a Google Calendar."""

    id: str = Field(description="Google Calendar ID")
    type: str = Field(default="google-calendar", description="Resource type")
    attributes: GoogleCalendarAttributes = Field(description="Calendar attributes")


class GoogleCalendarListResponse(BaseModel):
    """JSON API response for listing Google Calendars."""

    data: list[GoogleCalendarData] = Field(description="List of Google Calendars")


# Webhook Re-register Response Models
class WebhookReregisterAttributes(BaseModel):
    """Attributes for a webhook re-register response."""

    webhooks_queued: int = Field(
        description="Number of webhook re-registration jobs queued"
    )
    message: str = Field(description="Human-readable status message")


class WebhookReregisterData(BaseModel):
    """JSON API data wrapper for webhook re-register response."""

    id: str = Field(description="Resource identifier")
    type: str = Field(default="webhook-reregister", description="Resource type")
    attributes: WebhookReregisterAttributes = Field(
        description="Re-register result attributes"
    )


class WebhookReregisterResponse(BaseModel):
    """JSON API response for webhook re-registration."""

    data: WebhookReregisterData = Field(description="Re-register result")


class WebhookUrlAttributes(BaseModel):
    """Attributes for a webhook URL response."""

    webhook_url: str = Field(description="The webhook URL to configure")
    message: str = Field(description="Human-readable instructions")


class WebhookUrlData(BaseModel):
    """JSON API data wrapper for webhook URL response."""

    id: str = Field(description="Resource identifier")
    type: str = Field(default="webhook-url", description="Resource type")
    attributes: WebhookUrlAttributes = Field(description="Webhook URL attributes")


class WebhookUrlResponse(BaseModel):
    """JSON API response for webhook URL retrieval."""

    data: WebhookUrlData = Field(description="Webhook URL data")


# Conflict Resolution Models (JSON API format)
class ConflictResolutionAction(StrEnum):
    """Action to take when resolving a conflict."""

    LINK = "link"
    CREATE = "create"


class ConflictResolutionRequest(BaseModel):
    """Request model for resolving a sync conflict."""

    action: ConflictResolutionAction = Field(
        description="Action to take (link to existing or create new)"
    )
    contact_id: int | None = Field(
        default=None,
        description="ID of the local contact to link (required if action is 'link')",
    )


class ImmichConflictAttributes(BaseModel):
    """Attributes for a sync conflict (JSON API format)."""

    external_entity_id: str = Field(
        description="Immich person ID", serialization_alias="externalEntityId"
    )
    external_entity_name: str | None = Field(
        default=None,
        description="Name of the Immich person",
        serialization_alias="externalEntityName",
    )
    candidate_contact_ids: list[int] = Field(
        default_factory=list,
        description="List of candidate local contact IDs",
        serialization_alias="candidateContactIds",
    )
    status: str = Field(description="Conflict status (unresolved, resolved)")
    created_at: str = Field(
        description="ISO timestamp when the conflict was recorded",
        serialization_alias="createdAt",
    )

    model_config = {"populate_by_name": True}


class ImmichConflictData(BaseModel):
    """Data wrapper for a sync conflict (JSON API format)."""

    id: str = Field(description="Conflict ID")
    type: str = Field(default="immich-conflict", description="Resource type")
    attributes: ImmichConflictAttributes = Field(description="Conflict attributes")


class ImmichConflictListResponse(BaseModel):
    """JSON API response for a list of conflicts."""

    data: list[ImmichConflictData] = Field(description="List of conflicts")


class ImmichConflictResponse(BaseModel):
    """JSON API response for a single conflict."""

    data: ImmichConflictData = Field(description="Conflict data")


# Album Creation Models (ITER11-006, JSON API format)
class ImmichSearchPhotosRequest(BaseModel):
    """Request to search Immich photos for a journal's date range."""

    journal_id: int = Field(description="ID of the journal to search photos for")


class ImmichPhotoAttributes(BaseModel):
    """Attributes for a candidate Immich photo (JSON API format)."""

    thumbnail_url: str = Field(
        description="Backend proxy URL for the photo thumbnail",
        serialization_alias="thumbnailUrl",
    )
    original_file_name: str = Field(
        default="",
        description="Original filename of the photo",
        serialization_alias="originalFileName",
    )
    taken_at: str | None = Field(
        default=None,
        description="ISO timestamp when the photo was taken",
        serialization_alias="takenAt",
    )

    model_config = {"populate_by_name": True}


class ImmichPhotoData(BaseModel):
    """Data wrapper for a candidate Immich photo (JSON API format)."""

    id: str = Field(description="Immich asset ID")
    type: str = Field(default="immich-photo", description="Resource type")
    attributes: ImmichPhotoAttributes = Field(description="Photo attributes")


class ImmichPhotoListMeta(BaseModel):
    """Metadata for a photo search response."""

    count: int = Field(description="Number of matching photos")


class ImmichSearchPhotosResponse(BaseModel):
    """JSON API response for an Immich photo search."""

    data: list[ImmichPhotoData] = Field(description="Matching photos")
    meta: ImmichPhotoListMeta = Field(description="Response metadata")


class ImmichCreateAlbumRequest(BaseModel):
    """Request to create an Immich album from a journal's selected photos."""

    journal_id: int = Field(description="ID of the journal to create an album for")
    asset_ids: list[str] = Field(description="Immich asset IDs to include in the album")
    create_shared_link: bool = Field(
        default=False,
        description="Whether to create a public shared link for the album",
    )


class ImmichCreatedAlbumAttributes(BaseModel):
    """Attributes for a newly created Immich album (JSON API format)."""

    journal_id: int = Field(
        description="ID of the linked journal", serialization_alias="journalId"
    )
    asset_count: int = Field(
        description="Number of photos in the album", serialization_alias="assetCount"
    )
    shared_link_url: str | None = Field(
        default=None,
        description="Public shared link URL, if one was created",
        serialization_alias="sharedLinkUrl",
    )

    model_config = {"populate_by_name": True}


class ImmichCreatedAlbumData(BaseModel):
    """Data wrapper for a created Immich album (JSON API format)."""

    id: str = Field(description="Immich album ID")
    type: str = Field(default="immich-album", description="Resource type")
    attributes: ImmichCreatedAlbumAttributes = Field(description="Album attributes")


class ImmichCreateAlbumResponse(BaseModel):
    """JSON API response for a created Immich album."""

    data: ImmichCreatedAlbumData = Field(description="Created album data")
