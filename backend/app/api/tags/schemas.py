"""
Tag API schemas.

Defines request/response models for tag endpoints following JSON API specification.
"""

from pydantic import BaseModel, Field

from app.api.common.schemas import JsonApiResponse
from app.api.contacts.schemas import TagResource


# Tag Creation Schemas
class TagCreateAttributes(BaseModel):
    """Attributes for creating a tag."""

    name: str = Field(..., description="Tag name", min_length=1, max_length=100)
    color: str | None = Field(default=None, description="Tag color (hex code)")
    description: str | None = Field(default=None, description="Tag description")


class TagCreateData(BaseModel):
    """Data for creating a tag."""

    type: str = Field(default="tags", description="Resource type")
    attributes: TagCreateAttributes = Field(..., description="Tag attributes")


class TagCreateRequest(BaseModel):
    """Request model for creating a tag."""

    data: TagCreateData = Field(..., description="Tag creation data")


class TagResponse(JsonApiResponse[TagResource]):
    """Response model for a single tag."""

    pass
