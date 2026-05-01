"""
Pydantic response schemas for the integration registry API.

These models define the JSON API response format for ``GET /api/integrations``.
"""

from __future__ import annotations

from pydantic import BaseModel


class IntegrationSyncSummaryAttributes(BaseModel):
    """Sync summary nested within an integration entry."""

    last_sync_time: str | None = None
    sync_count: int = 0
    error_count: int = 0


class IntegrationAttributes(BaseModel):
    """Attributes for a single integration entry."""

    name: str
    status: str
    capabilities: list[str]
    sync_summary: IntegrationSyncSummaryAttributes
    needs_reauth: bool = False
    needs_reconsent: bool = False


class IntegrationData(BaseModel):
    """A single integration entry in JSON API format."""

    id: str
    type: str = "integration"
    attributes: IntegrationAttributes


class IntegrationListResponse(BaseModel):
    """JSON API response for GET /api/integrations."""

    data: list[IntegrationData]
