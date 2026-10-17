"""
Integration domain MCP response schemas.

Each tool returns one of these, which fastmcp publishes as the tool's
``outputSchema`` and sends as ``structuredContent``.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.core.integrations.immich.conflict_resolution_service import (
    ConflictResolutionAction,
)
from app.core.integrations.registry.models import (
    IntegrationCapability,
    IntegrationStatus,
)


class SyncSummaryMCP(BaseModel):
    """How an integration's syncs have gone."""

    last_sync_time: str | None = Field(
        description="ISO 8601 time of the last sync, or null if it never synced"
    )
    sync_count: int = Field(description="Total number of syncs run")
    error_count: int = Field(description="Number of syncs that failed")


class IntegrationStatusMCP(BaseModel):
    """One registered integration and its health."""

    id: str = Field(description="Integration id, e.g. 'strava' or 'immich'")
    name: str = Field(description="Display name")
    status: IntegrationStatus = Field(description="Connection status")
    capabilities: list[IntegrationCapability] = Field(
        description="What the integration can sync"
    )
    sync_summary: SyncSummaryMCP
    needs_reauth: bool = Field(description="The user must sign in to it again")
    needs_reconsent: bool = Field(
        description="The user must grant newly required permissions"
    )


class IntegrationListResponse(BaseModel):
    """Every registered integration, with an AI-friendly summary."""

    integrations: list[IntegrationStatusMCP]
    total_count: int
    summary: str = Field(
        description="e.g. '1/2 integrations connected. Action required for: Strava.'"
    )


class SyncTriggeredResponse(BaseModel):
    """A sync job that was enqueued."""

    integration_id: str
    job_id: str | None = Field(description="The queued job's id")
    status: Literal["queued"]


class StravaAthleteMappingMCP(BaseModel):
    """A Strava athlete linked to a contact."""

    strava_athlete_id: str
    strava_athlete_name: str
    contact_id: int


class StravaAthleteMappingListResponse(BaseModel):
    """The Strava athlete-to-contact mappings that matched the filters."""

    mappings: list[StravaAthleteMappingMCP]
    total_count: int


class ImmichConflictMCP(BaseModel):
    """An Immich person that matched more than one local contact."""

    id: int = Field(description="Conflict id, for resolve_immich_conflict")
    external_entity_id: str = Field(description="The Immich person UUID")
    external_entity_name: str | None = Field(description="The person's name in Immich")
    candidate_contact_ids: list[int] = Field(
        description="Local contacts the person may be"
    )
    status: str = Field(description="Always 'unresolved' for a pending conflict")
    created_at: str | None = Field(description="ISO 8601 time the conflict arose")


class ImmichConflictListResponse(BaseModel):
    """The unresolved Immich conflicts that need a person to decide."""

    conflicts: list[ImmichConflictMCP]
    total_count: int


class ImmichConflictResolvedResponse(BaseModel):
    """The outcome of resolving an Immich conflict."""

    conflict_id: int
    action: ConflictResolutionAction
    contact_id: int | None = Field(
        description="The contact the Immich person is now linked to"
    )
    status: Literal["resolved"]


class ImmichPhotoMCP(BaseModel):
    """A photo in Immich."""

    asset_id: str = Field(description="Immich asset id, for exclude_asset_ids")
    original_file_name: str
    taken_at: str | None = Field(description="ISO 8601 capture time")


class ImmichPhotoSearchResponse(BaseModel):
    """The Immich photos taken within a journal's date range."""

    journal_id: int
    photos: list[ImmichPhotoMCP]
    total_count: int


class ImmichAlbumCreatedResponse(BaseModel):
    """An Immich album created from a journal and linked back to it."""

    journal_id: int
    album_id: str
    asset_count: int = Field(description="Number of photos in the album")
    shared_link_url: str | None = Field(
        description="Public link, when create_shared_link was set"
    )
    status: Literal["created"]
