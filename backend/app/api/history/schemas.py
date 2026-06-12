"""Shared JSON:API schemas for entity-agnostic field-level history."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HistoryAttributes(BaseModel):
    """Attributes for a field-level history entry (any entity type)."""

    entity_type: str = Field(..., description="Type of entity that was changed")
    entity_id: int = Field(..., description="ID of the entity that was changed")
    field_name: str = Field(..., description="Name of the field that was changed")
    old_value: str | None = Field(
        default=None, description="Previous value of the field"
    )
    new_value: str | None = Field(default=None, description="New value of the field")
    changed_by: str | None = Field(
        default=None, description="User or system that made the change"
    )
    source: str = Field(default="system", description="Provenance source of the change")
    created_at: datetime | None = Field(
        default=None, description="Timestamp when the change occurred"
    )


class HistoryResource(BaseModel):
    """JSON:API resource for a field-level history entry."""

    type: str = Field(default="history", description="Resource type")
    id: str = Field(..., description="History entry ID")
    attributes: HistoryAttributes = Field(..., description="History entry attributes")


class HistoryListResponse(BaseModel):
    """JSON:API list response for field-level history."""

    data: list[HistoryResource] = Field(..., description="List of history entries")
    meta: Any = Field(default=None, description="Response metadata")
    links: Any = Field(default=None, description="Response links")
