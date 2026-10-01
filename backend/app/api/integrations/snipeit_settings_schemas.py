"""
Pydantic schemas for Snipe-IT settings API.

These schemas define the request/response shapes for the
``GET`` and ``PUT /api/integrations/snipeit/settings`` endpoints.
"""

from core_shared.product import PRODUCT_NAME
from pydantic import BaseModel, Field, HttpUrl


class SnipeItSettingsRequest(BaseModel):
    """Request body for creating or updating Snipe-IT settings."""

    base_url: HttpUrl = Field(
        ...,
        description="Base URL of the self-hosted Snipe-IT instance (e.g. https://snipeit.example.com)",
    )
    snipeit_user_id: str | None = Field(
        default=None,
        description=f"Snipe-IT user ID to map this {PRODUCT_NAME} user to",
    )


class SnipeItSettingsAttributes(BaseModel):
    """Attributes for Snipe-IT settings."""

    base_url: str = Field(
        ...,
        description="Base URL of the self-hosted Snipe-IT instance",
    )
    snipeit_user_id: str | None = Field(
        default=None,
        description=f"Snipe-IT user ID mapped to this {PRODUCT_NAME} user",
    )


class SnipeItSettingsData(BaseModel):
    """A single Snipe-IT settings entry in JSON API format."""

    id: str
    type: str = "snipeit_settings"
    attributes: SnipeItSettingsAttributes


class SnipeItSettingsResponse(BaseModel):
    """JSON API response for Snipe-IT settings."""

    data: SnipeItSettingsData


SnipeItSettingsResponse.model_rebuild()
