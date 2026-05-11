"""
Pydantic schemas for Snipe-IT settings API.

These schemas define the request/response shapes for the
``GET`` and ``PUT /api/integrations/snipeit/settings`` endpoints.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl


class SnipeItSettingsRequest(BaseModel):
    """Request body for creating or updating Snipe-IT settings."""

    base_url: HttpUrl = Field(
        ...,
        description="Base URL of the self-hosted Snipe-IT instance (e.g. https://snipeit.example.com)",
    )
    snipeit_user_id: str | None = Field(
        default=None,
        description="Snipe-IT user ID to map this PMS user to",
    )


class SnipeItSettingsResponse(BaseModel):
    """Response body for Snipe-IT settings."""

    base_url: str = Field(
        ...,
        description="Base URL of the self-hosted Snipe-IT instance",
    )
    snipeit_user_id: str | None = Field(
        default=None,
        description="Snipe-IT user ID mapped to this PMS user",
    )
