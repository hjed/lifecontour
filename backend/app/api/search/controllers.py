"""
Search API controllers.

Handles search-related HTTP endpoints including contact search,
global search, and search suggestions.
"""

import structlog
from fastapi import APIRouter, HTTPException, Query
from meilisearch.errors import MeilisearchError

from app.api.dependencies import SearchServiceDep
from app.api.search.schemas import (
    ContactSearchResponse,
    GlobalSearchResponse,
    SearchHealthResponse,
    SearchHit,
    SearchSuggestionsResponse,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/contacts", response_model=ContactSearchResponse)
def search_contacts(
    search_service: SearchServiceDep,
    q: str = Query(..., description="Search query", min_length=1, max_length=500),
    limit: int = Query(default=20, description="Maximum results", ge=1, le=100),
    offset: int = Query(default=0, description="Results offset", ge=0),
    tags: list[str] | None = Query(default=None, description="Filter by tags"),
    sort: list[str] | None = Query(default=None, description="Sort criteria"),
) -> ContactSearchResponse:
    """
    Search contacts using MeiliSearch.

    Supports full-text search across contact fields with optional filtering
    by tags and custom sorting.
    """
    try:
        # Build filters
        filters = {}
        if tags:
            filters["tags"] = tags

        # Perform search
        results = search_service.search_contacts(
            query=q,
            filters=filters if filters else None,
            limit=limit,
            offset=offset,
            sort=sort,
        )

        # Convert to API response format
        hits = []
        for hit in results["hits"]:
            search_hit = SearchHit(
                id=hit["id"],
                entity_type="contact",
                title=hit.get(
                    "full_name",
                    f"{hit.get('first_name', '')} {hit.get('last_name', '')}",
                ).strip(),
                content=f"Email: {hit.get('email', 'N/A')}, Phone: {hit.get('phone', 'N/A')}",
                highlighted=hit.get("_formatted"),
                metadata={
                    "first_name": hit.get("first_name"),
                    "last_name": hit.get("last_name"),
                    "email": hit.get("email"),
                    "phone": hit.get("phone"),
                    "tags": hit.get("tags", []),
                    "created_at": hit.get("created_at"),
                    "updated_at": hit.get("updated_at"),
                },
            )
            hits.append(search_hit)

        return ContactSearchResponse(
            hits=hits,
            query=q,
            total_hits=results.get("estimated_total_hits", 0),
            processing_time_ms=results.get("processing_time_ms", 0),
            limit=limit,
            offset=offset,
            facets=results.get("facet_distribution"),
            available_tags=None,  # Could be populated from facets
        )

    except MeilisearchError as e:
        logger.error("MeiliSearch error during contact search", error=str(e), query=q)
        raise HTTPException(
            status_code=503, detail="Search service temporarily unavailable"
        ) from e
    except Exception as e:
        logger.error("Unexpected error during contact search", error=str(e), query=q)
        raise HTTPException(
            status_code=500, detail="Internal server error during search"
        ) from e


@router.get("/global", response_model=GlobalSearchResponse)
def global_search(
    search_service: SearchServiceDep,
    q: str = Query(..., description="Search query", min_length=1, max_length=500),
    limit: int = Query(default=20, description="Maximum results", ge=1, le=100),
    offset: int = Query(default=0, description="Results offset", ge=0),
    entity_types: list[str] | None = Query(
        default=None, description="Entity types to search"
    ),
) -> GlobalSearchResponse:
    """
    Perform global search across all entity types.

    Searches across contacts and other entities (when implemented)
    with unified results.
    """
    try:
        # Perform global search
        results = search_service.global_search(
            query=q, entity_types=entity_types, limit=limit, offset=offset
        )

        # Convert to API response format
        hits = []
        results_by_type: dict[str, int] = {}

        for hit in results["hits"]:
            entity_type = hit.get("entity_type", "unknown")

            # Count results by type
            results_by_type[entity_type] = results_by_type.get(entity_type, 0) + 1

            # Create search hit based on entity type
            if entity_type == "contact":
                title = hit.get(
                    "full_name",
                    f"{hit.get('first_name', '')} {hit.get('last_name', '')}",
                ).strip()
                content = f"Contact: {hit.get('email', 'N/A')}"
            else:
                title = hit.get("title", hit.get("name", "Unknown"))
                content = hit.get("content", hit.get("description", ""))

            search_hit = SearchHit(
                id=hit["id"],
                entity_type=entity_type,
                title=title,
                content=content,
                highlighted=hit.get("_formatted"),
                metadata=hit,
            )
            hits.append(search_hit)

        return GlobalSearchResponse(
            hits=hits,
            query=q,
            total_hits=results.get("estimated_total_hits", 0),
            processing_time_ms=results.get("processing_time_ms", 0),
            limit=limit,
            offset=offset,
            facets=results.get("facet_distribution"),
            searched_entity_types=results.get("searched_entity_types", []),
            available_entity_types=results.get("available_entity_types", []),
            results_by_type=results_by_type,
        )

    except MeilisearchError as e:
        logger.error("MeiliSearch error during global search", error=str(e), query=q)
        raise HTTPException(
            status_code=503, detail="Search service temporarily unavailable"
        ) from e
    except Exception as e:
        logger.error("Unexpected error during global search", error=str(e), query=q)
        raise HTTPException(
            status_code=500, detail="Internal server error during search"
        ) from e


@router.get("/suggestions", response_model=SearchSuggestionsResponse)
def get_search_suggestions(
    search_service: SearchServiceDep,
    q: str = Query(..., description="Partial query", min_length=1, max_length=100),
    entity_type: str = Query(default="contacts", description="Entity type"),
    limit: int = Query(default=5, description="Max suggestions", ge=1, le=20),
) -> SearchSuggestionsResponse:
    """
    Get search suggestions for autocomplete.

    Returns suggested search terms based on the partial query.
    """
    try:
        suggestions = search_service.get_search_suggestions(
            query=q, entity_type=entity_type, limit=limit
        )

        return SearchSuggestionsResponse(suggestions=suggestions, query=q)

    except Exception as e:
        logger.error("Error getting search suggestions", error=str(e), query=q)
        # For suggestions, we can gracefully degrade
        return SearchSuggestionsResponse(suggestions=[], query=q)


@router.get("/health", response_model=SearchHealthResponse)
def get_search_health(search_service: SearchServiceDep) -> SearchHealthResponse:
    """
    Get search system health status.

    Returns information about MeiliSearch connectivity and index status.
    """
    try:
        health = search_service.get_search_health()

        return SearchHealthResponse(
            status=health.get("status", "unknown"),
            meilisearch_status=health.get("meilisearch_health", {}).get("status"),
            indices=health.get("indices", []),
            error=health.get("error"),
        )

    except Exception as e:
        logger.error("Error checking search health", error=str(e))
        return SearchHealthResponse(
            status="error", meilisearch_status="unknown", indices=[], error=str(e)
        )
