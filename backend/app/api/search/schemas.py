"""
Search API schemas for request and response models.

Defines Pydantic models for search-related API endpoints.
"""

from typing import Any

from pydantic import BaseModel, Field


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


class SearchHit(BaseModel):
    """Individual search result hit."""

    id: int = Field(..., description="Entity ID")
    entity_type: str = Field(..., description="Type of entity")
    title: str | None = Field(default=None, description="Display title")
    content: str | None = Field(default=None, description="Content snippet")
    highlighted: dict[str, Any] | None = Field(
        default=None, description="Highlighted fields"
    )
    metadata: dict[str, Any] | None = Field(
        default=None, description="Additional metadata"
    )


class SearchResponse(BaseModel):
    """Response model for search operations."""

    hits: list[SearchHit] = Field(..., description="Search results")
    query: str = Field(..., description="Original search query")
    total_hits: int = Field(..., description="Total number of matching results")
    processing_time_ms: int = Field(
        ..., description="Search processing time in milliseconds"
    )
    limit: int = Field(..., description="Results limit used")
    offset: int = Field(..., description="Results offset used")
    facets: dict[str, Any] | None = Field(default=None, description="Facet information")


class ContactSearchResponse(SearchResponse):
    """Response model for contact search operations."""

    available_tags: list[str] | None = Field(
        default=None, description="Available tags for filtering"
    )


class GlobalSearchResponse(SearchResponse):
    """Response model for global search operations."""

    searched_entity_types: list[str] = Field(
        ..., description="Entity types that were searched"
    )
    available_entity_types: list[str] = Field(
        ..., description="All available entity types"
    )
    results_by_type: dict[str, int] | None = Field(
        default=None, description="Number of results by entity type"
    )


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
