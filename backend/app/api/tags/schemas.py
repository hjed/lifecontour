"""
Tag API schemas.

Defines request/response models for tag endpoints following JSON API specification.
"""

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.api.common.schemas import JsonApiResponse
from app.api.contacts.schemas import TagResource


# Tag Creation Schemas
class TagCreateAttributes(BaseModel):
    """Attributes for creating a tag."""

    name: str = Field(..., description="Tag name", min_length=1, max_length=100)
    color: str | None = Field(default=None, description="Tag color (hex code)")
    description: str | None = Field(default=None, description="Tag description")
    parent_id: int | None = Field(
        default=None, description="Parent tag ID for hierarchical tags"
    )


class TagCreateData(BaseModel):
    """Data for creating a tag."""

    type: str = Field(default="tags", description="Resource type")
    attributes: TagCreateAttributes = Field(..., description="Tag attributes")


class TagCreateRequest(BaseModel):
    """Request model for creating a tag."""

    data: TagCreateData = Field(..., description="Tag creation data")


# Tag Update Schemas
class TagUpdateAttributes(BaseModel):
    """Attributes for updating a tag."""

    name: str | None = Field(
        default=None, description="Tag name", min_length=1, max_length=100
    )
    color: str | None = Field(default=None, description="Tag color (hex code)")
    description: str | None = Field(default=None, description="Tag description")
    parent_id: int | None = Field(
        default=None,
        description="Parent tag ID for hierarchical tags. Provide explicit None to clear parent.",
    )

    @model_validator(mode="before")
    @classmethod
    def validate_non_nulls(cls, data: Any) -> Any:
        """Reject explicit nulls for required string fields."""
        if isinstance(data, dict):
            for field in ["name", "color", "description"]:
                if field in data and data[field] is None:
                    raise ValueError(f"Explicit null is not allowed for '{field}'")
        return data


class TagUpdateData(BaseModel):
    """Data for updating a tag."""

    type: str = Field(default="tags", description="Resource type")
    id: str = Field(..., description="Tag ID")
    attributes: TagUpdateAttributes = Field(..., description="Tag update attributes")


class TagUpdateRequest(BaseModel):
    """Request model for updating a tag."""

    data: TagUpdateData = Field(..., description="Tag update data")


class TagResponse(JsonApiResponse[TagResource]):
    """Response model for a single tag."""

    pass
