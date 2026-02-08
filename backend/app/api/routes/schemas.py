"""
Route API schemas for request and response models.

Defines Pydantic models for route-related API endpoints following
the JSON API specification.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.api.common.schemas import (
    JsonApiCollectionResponse,
    JsonApiCreateRequest,
    JsonApiLinks,
    JsonApiResponse,
    JsonApiUpdateRequest,
)


class RouteRequestAttributes(BaseModel):
    """Route attributes for create/update requests (client-provided fields only)."""

    name: str = Field(..., description="Route name", max_length=200)
    description: str | None = Field(default=None, description="Route description")
    gpx_data: str | None = Field(
        default=None, description="GPX track data in XML format"
    )


class RouteResponseAttributes(BaseModel):
    """Route attributes for responses (includes server-managed fields)."""

    name: str = Field(..., description="Route name", max_length=200)
    description: str | None = Field(default=None, description="Route description")
    gpx_data: str | None = Field(
        default=None, description="GPX track data in XML format"
    )
    created_at: datetime = Field(..., description="Route creation timestamp")
    updated_at: datetime = Field(..., description="Route last update timestamp")


class RouteResource(BaseModel):
    """Route resource following JSON API specification."""

    type: str = Field(default="routes", description="Resource type")
    id: str = Field(..., description="Resource identifier (UUID)")
    attributes: RouteResponseAttributes = Field(..., description="Route attributes")
    links: JsonApiLinks | None = Field(default=None, description="Resource links")
    meta: dict[str, Any] | None = Field(default=None, description="Resource metadata")


class RouteCreateData(BaseModel):
    """Data for creating a route (no ID)."""

    type: str = Field(default="routes", description="Resource type")
    attributes: RouteRequestAttributes = Field(..., description="Route attributes")


class RouteUpdateData(BaseModel):
    """Data for updating a route (requires ID)."""

    type: str = Field(default="routes", description="Resource type")
    id: str = Field(..., description="Resource identifier (UUID)")
    attributes: RouteRequestAttributes = Field(..., description="Route attributes")


# Request/Response wrappers
class RouteCreateRequest(JsonApiCreateRequest[RouteCreateData]):
    """Request for creating a route."""

    pass


class RouteUpdateRequest(JsonApiUpdateRequest[RouteUpdateData]):
    """Request for updating a route."""

    pass


class RouteResponse(JsonApiResponse[RouteResource]):
    """Response containing a single route resource."""

    pass


class RouteListResponse(JsonApiCollectionResponse[RouteResource]):
    """Response containing a list of route resources."""

    pass
