"""
Search API schemas for request and response models.

Defines Pydantic models for search-related API endpoints using JSON API format.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.api.common.schemas import JsonApiLinks, JsonApiMeta
from app.api.contacts.schemas import ContactData


class SearchRequest(BaseModel):
    """Request model for search operations."""

    query: str = Field(
        ..., description="Search query string", min_length=1, max_length=500
    )
    limit: int = Field(
        default=20, description="Maximum number of results", ge=1, le=100
    )
    offset: int = Field(default=0, description="Offset for pagination", ge=0)
    filters: dict[str, Any] | None = Field(
        default=None, description="Optional search filters"
    )
    sort: list[str] | None = Field(default=None, description="Sort criteria")


class ContactSearchRequest(SearchRequest):
    """Request model for contact search operations."""

    include_tags: list[str] | None = Field(default=None, description="Filter by tags")
    exclude_tags: list[str] | None = Field(default=None, description="Exclude tags")


class GlobalSearchRequest(SearchRequest):
    """Request model for global search operations."""

    entity_types: list[str] | None = Field(
        default=None, description="Entity types to search (e.g., 'contact', 'journal')"
    )


# JSON API compliant search response schemas
class SearchMeta(JsonApiMeta):
    """Search-specific meta information."""

    query: str = Field(..., description="Original search query")
    processing_time_ms: int = Field(
        ..., description="Search processing time in milliseconds"
    )
    facets: dict[str, Any] | None = Field(default=None, description="Facet information")
    available_tags: list[str] | None = Field(
        default=None, description="Available tags for filtering"
    )
    searched_entity_types: list[str] | None = Field(
        default=None, description="Entity types that were searched"
    )
    available_entity_types: list[str] | None = Field(
        default=None, description="All available entity types"
    )
    results_by_type: dict[str, int] | None = Field(
        default=None, description="Number of results by entity type"
    )


class ContactSearchResponse(BaseModel):
    """JSON API compliant response for contact search operations."""

    data: list[ContactData] = Field(..., description="Search results")
    meta: SearchMeta = Field(..., description="Search metadata")
    links: JsonApiLinks | None = Field(default=None, description="Pagination links")


class GlobalSearchResponse(BaseModel):
    """JSON API compliant response for global search operations."""

    data: list[ContactData] = Field(..., description="Search results (contacts only for now)")
    meta: SearchMeta = Field(..., description="Search metadata")
    links: JsonApiLinks | None = Field(default=None, description="Pagination links")


class SearchSuggestionsRequest(BaseModel):
    """Request model for search suggestions."""

    query: str = Field(
        ..., description="Partial query for suggestions", min_length=1, max_length=100
    )
    entity_type: str = Field(
        default="contacts", description="Entity type for suggestions"
    )
    limit: int = Field(
        default=5, description="Maximum number of suggestions", ge=1, le=20
    )


class SearchSuggestionsResponse(BaseModel):
    """Response model for search suggestions."""

    suggestions: list[str] = Field(..., description="List of search suggestions")
    query: str = Field(..., description="Original query")


class SearchHealthResponse(BaseModel):
    """Response model for search health check."""

    status: str = Field(..., description="Overall search system status")
    meilisearch_status: str | None = Field(
        default=None, description="MeiliSearch status"
    )
    indices: list[dict[str, Any]] = Field(
        default_factory=list, description="Index information"
    )
    error: str | None = Field(default=None, description="Error message if any")
