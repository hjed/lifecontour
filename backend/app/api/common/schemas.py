"""
Common JSON API schemas for all domains.

Provides reusable Pydantic models that follow the JSON API specification
for consistent API responses across all domains.
"""

from typing import Any, TypeVar
from urllib.parse import urlencode
from uuid import uuid4

from pydantic import BaseModel, Field

# Generic type for resource data
T = TypeVar("T")


class JsonApiMeta(BaseModel):
    """JSON API meta object for additional information."""

    total_count: int | None = Field(
        default=None, description="Total number of resources"
    )
    page_count: int | None = Field(default=None, description="Total number of pages")
    current_page: int | None = Field(default=None, description="Current page number")
    per_page: int | None = Field(default=None, description="Resources per page")


class JsonApiLinks(BaseModel):
    """JSON API links object for navigation."""

    self: str | None = Field(default=None, description="Link to the resource itself")
    first: str | None = Field(default=None, description="Link to the first page")
    last: str | None = Field(default=None, description="Link to the last page")
    prev: str | None = Field(default=None, description="Link to the previous page")
    next: str | None = Field(default=None, description="Link to the next page")
    related: str | None = Field(default=None, description="Link to related resources")


class JsonApiErrorSource(BaseModel):
    """JSON API error source information."""

    pointer: str | None = Field(
        default=None, description="JSON Pointer to the error location"
    )
    parameter: str | None = Field(
        default=None, description="Query parameter that caused the error"
    )
    header: str | None = Field(default=None, description="Header that caused the error")


class JsonApiError(BaseModel):
    """JSON API error object."""

    id: str = Field(
        default_factory=lambda: str(uuid4()), description="Unique error identifier"
    )
    status: str = Field(..., description="HTTP status code as string")
    code: str | None = Field(
        default=None, description="Application-specific error code"
    )
    title: str = Field(..., description="Short, human-readable summary")
    detail: str | None = Field(default=None, description="Human-readable explanation")
    source: JsonApiErrorSource | None = Field(
        default=None, description="Error source information"
    )
    meta: dict[str, Any] | None = Field(
        default=None, description="Additional error metadata"
    )


class JsonApiErrorResponse(BaseModel):
    """JSON API error response."""

    errors: list[JsonApiError] = Field(..., description="Array of error objects")
    meta: JsonApiMeta | None = Field(default=None, description="Response metadata")
    links: JsonApiLinks | None = Field(default=None, description="Response links")


class JsonApiResource(BaseModel):
    """Base JSON API resource object."""

    type: str = Field(..., description="Resource type")
    id: str = Field(..., description="Resource identifier")
    attributes: dict[str, Any] | None = Field(
        default=None, description="Resource attributes"
    )
    relationships: dict[str, Any] | None = Field(
        default=None, description="Resource relationships"
    )
    links: JsonApiLinks | None = Field(default=None, description="Resource links")
    meta: dict[str, Any] | None = Field(default=None, description="Resource metadata")


class JsonApiResponse[T](BaseModel):
    """Generic JSON API response for single resources."""

    data: T = Field(..., description="Primary resource data")
    meta: JsonApiMeta | None = Field(default=None, description="Response metadata")
    links: JsonApiLinks | None = Field(default=None, description="Response links")
    included: list[JsonApiResource] | None = Field(
        default=None, description="Included resources"
    )


class JsonApiCollectionResponse[T](BaseModel):
    """Generic JSON API response for resource collections."""

    data: list[T] = Field(..., description="Array of primary resource data")
    meta: JsonApiMeta | None = Field(default=None, description="Response metadata")
    links: JsonApiLinks | None = Field(default=None, description="Response links")
    included: list[JsonApiResource] | None = Field(
        default=None, description="Included resources"
    )


class JsonApiCreateRequest[T](BaseModel):
    """Generic JSON API request for creating resources."""

    data: T = Field(..., description="Resource data to create")


class JsonApiUpdateRequest[T](BaseModel):
    """Generic JSON API request for updating resources."""

    data: T = Field(..., description="Resource data to update")


# External System Link Schemas
class ExternalLinkAttributes(BaseModel):
    """Attributes of an external system link."""

    source: str = Field(
        ...,
        description="Integration source identifier (e.g. 'strava', 'google_calendar')",
    )
    url: str | None = Field(
        default=None,
        description="Clickable URL to the external record, or null if not constructable",
    )
    external_id: str = Field(
        ..., description="The external system's identifier for the entity"
    )


class ExternalLinkResource(BaseModel):
    """JSON:API resource representing an external link."""

    type: str = Field(default="external_links", description="Resource type")
    id: str = Field(..., description="Unique identifier for this link")
    attributes: ExternalLinkAttributes


class ExternalLinksResponse(BaseModel):
    """Response model for external system links."""

    data: list[ExternalLinkResource] = Field(
        ..., description="List of external system links"
    )


# Pagination helpers
class PaginationParams(BaseModel):
    """Standard pagination parameters."""

    page: int = Field(default=1, description="Page number", ge=1)
    limit: int = Field(default=20, description="Items per page", ge=1, le=100)

    @property
    def offset(self) -> int:
        """Calculate offset from page and limit."""
        return (self.page - 1) * self.limit


def create_pagination_meta(
    total_count: int,
    page: int,
    limit: int,
) -> JsonApiMeta:
    """Create pagination metadata."""
    page_count = (total_count + limit - 1) // limit if total_count > 0 else 0

    return JsonApiMeta(
        total_count=total_count,
        page_count=page_count,
        current_page=page,
        per_page=limit,
    )


def get_request_base_url(request: Any) -> str:
    """Extract and normalize base URL from FastAPI request."""
    return str(request.base_url).rstrip("/")


def create_pagination_links(
    base_url: str,
    page: int,
    limit: int,
    total_count: int,
    additional_params: dict[str, str | list[str]] | None = None,
) -> JsonApiLinks:
    """
    Create pagination links with optional additional query parameters.

    Args:
        base_url: Base URL for the links
        page: Current page number
        limit: Items per page
        total_count: Total number of items
        additional_params: Additional query parameters to include in links
    """
    page_count = (total_count + limit - 1) // limit if total_count > 0 else 0

    def build_url(target_page: int) -> str:
        """Build URL with page, limit, and additional parameters."""
        query_params: dict[str, int | str | list[str]] = {
            "page": target_page,
            "limit": limit,
        }
        if additional_params:
            query_params.update(additional_params)

        return f"{base_url}?{urlencode(query_params, doseq=True)}"

    links = JsonApiLinks(
        self=build_url(page),
        first=build_url(1) if page_count > 0 else None,
        last=build_url(page_count) if page_count > 0 else None,
    )

    if page > 1:
        links.prev = build_url(page - 1)

    if page < page_count:
        links.next = build_url(page + 1)

    return links
