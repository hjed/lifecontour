"""
Search API schemas for request and response models.

Defines Pydantic models for search-related API endpoints following
the JSON API specification.
"""

from typing import Any

from pydantic import BaseModel, Field

from app.api.common.schemas import (
    JsonApiCollectionResponse,
    JsonApiLinks,
    JsonApiMeta,
)
from app.api.contacts.schemas import ContactResource


# Search Result Resources (JSON API compliant)
class SearchResultAttributes(BaseModel):
    """Base attributes for search result resources."""

    entity_type: str = Field(..., description="Type of the source entity")
    title: str | None = Field(default=None, description="Display title")
    content: str | None = Field(default=None, description="Content snippet")
    highlighted: dict[str, Any] | None = Field(
        default=None, description="Highlighted fields from search"
    )


class SearchResultMeta(BaseModel):
    """Meta information for search result resources."""

    score: float | None = Field(default=None, description="Search relevance score")
    original_id: int = Field(..., description="Original entity ID")
    search_metadata: dict[str, Any] | None = Field(
        default=None, description="Additional search-specific metadata"
    )


class SearchResultResource(BaseModel):
    """Search result resource following JSON API specification."""

    type: str = Field(default="search-results", description="Resource type")
    id: str = Field(..., description="Composite resource identifier (entity_type-id)")
    attributes: SearchResultAttributes = Field(
        ..., description="Search result attributes"
    )
    meta: SearchResultMeta | None = Field(
        default=None, description="Search result metadata"
    )
    links: JsonApiLinks | None = Field(default=None, description="Resource links")


# Search Response Meta
class SearchMeta(JsonApiMeta):
    """Extended meta information for search responses."""

    query: str = Field(..., description="Original search query")
    processing_time_ms: int = Field(
        ..., description="Search processing time in milliseconds"
    )
    facets: dict[str, Any] | None = Field(default=None, description="Facet information")


class ContactSearchMeta(SearchMeta):
    """Meta information for contact search responses."""

    available_tags: list[str] | None = Field(
        default=None, description="Available tags for filtering"
    )


class GlobalSearchMeta(SearchMeta):
    """Meta information for global search responses."""

    searched_entity_types: list[str] = Field(
        ..., description="Entity types that were searched"
    )
    available_entity_types: list[str] = Field(
        ..., description="All available entity types"
    )
    results_by_type: dict[str, int] | None = Field(
        default=None, description="Number of results by entity type"
    )


# Response Models (JSON API compliant)
class ContactSearchResponse(JsonApiCollectionResponse[ContactResource]):
    """JSON API response for contact search operations."""

    meta: ContactSearchMeta | None = Field(default=None, description="Search metadata")


class GlobalSearchResponse(
    JsonApiCollectionResponse[ContactResource | SearchResultResource]
):
    """JSON API response for global search operations."""

    meta: GlobalSearchMeta | None = Field(default=None, description="Search metadata")


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
