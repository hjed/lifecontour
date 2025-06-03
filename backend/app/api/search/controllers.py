"""
Search API controllers.

Handles search-related HTTP endpoints including contact search,
global search, and search suggestions.
"""

import structlog
from fastapi import APIRouter, HTTPException, Query
from meilisearch.errors import MeilisearchError

from app.api.common.schemas import JsonApiLinks
from app.api.contacts.converters import contact_to_json_api
from app.api.dependencies import SearchServiceDep
from app.api.search.schemas import (
    ContactSearchResponse,
    GlobalSearchResponse,
    SearchHealthResponse,
    SearchMeta,
    SearchSuggestionsResponse,
)
from app.core.contacts.models.entities import Contact

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

        # Convert search results to Contact entities and then to JSON API format
        contact_data = []
        for hit in results["hits"]:
            # Create a minimal Contact entity from search hit
            contact = Contact(
                id=hit["id"],
                first_name=hit.get("first_name", ""),
                last_name=hit.get("last_name"),
                middle_name=hit.get("middle_name"),
                nick_name=hit.get("nick_name"),
                methods=[],  # Search results don't include full relationship data
                addresses=[],
                notes=[],
                tags=[],
                created_at=hit.get("created_at"),
                updated_at=hit.get("updated_at"),
            )

            # Convert to JSON API format
            json_contact = contact_to_json_api(contact, include_relationships=False)
            contact_data.append(json_contact)

        # Build pagination links
        links = JsonApiLinks(
            self=f"/api/search/contacts?q={q}&limit={limit}&offset={offset}",
            next=f"/api/search/contacts?q={q}&limit={limit}&offset={offset + limit}"
                 if len(results["hits"]) == limit else None,
            prev=f"/api/search/contacts?q={q}&limit={limit}&offset={max(0, offset - limit)}"
                 if offset > 0 else None,
        )

        # Build search metadata
        meta = SearchMeta(
            query=q,
            total_count=results.get("estimated_total_hits", 0),
            current_page=(offset // limit) + 1 if limit > 0 else 1,
            processing_time_ms=results.get("processing_time_ms", 0),
            facets=results.get("facet_distribution"),
            available_tags=None,  # Could be populated from facets
        )

        return ContactSearchResponse(
            data=contact_data,
            meta=meta,
            links=links,
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

        # Convert search results to Contact entities and then to JSON API format
        contact_data = []
        results_by_type: dict[str, int] = {}

        for hit in results["hits"]:
            entity_type = hit.get("entity_type", "unknown")

            # Count results by type
            results_by_type[entity_type] = results_by_type.get(entity_type, 0) + 1

            # For now, only handle contacts in global search
            # Other entity types will be added later
            if entity_type == "contact":
                # Create a minimal Contact entity from search hit
                contact = Contact(
                    id=hit["id"],
                    first_name=hit.get("first_name", ""),
                    last_name=hit.get("last_name"),
                    middle_name=hit.get("middle_name"),
                    nick_name=hit.get("nick_name"),
                    methods=[],  # Search results don't include full relationship data
                    addresses=[],
                    notes=[],
                    tags=[],
                    created_at=hit.get("created_at"),
                    updated_at=hit.get("updated_at"),
                )

                # Convert to JSON API format
                json_contact = contact_to_json_api(contact, include_relationships=False)
                contact_data.append(json_contact)

        # Build pagination links
        links = JsonApiLinks(
            self=f"/api/search/global?q={q}&limit={limit}&offset={offset}",
            next=f"/api/search/global?q={q}&limit={limit}&offset={offset + limit}"
                 if len(results["hits"]) == limit else None,
            prev=f"/api/search/global?q={q}&limit={limit}&offset={max(0, offset - limit)}"
                 if offset > 0 else None,
        )

        # Build search metadata
        meta = SearchMeta(
            query=q,
            total_count=results.get("estimated_total_hits", 0),
            current_page=(offset // limit) + 1 if limit > 0 else 1,
            processing_time_ms=results.get("processing_time_ms", 0),
            facets=results.get("facet_distribution"),
            searched_entity_types=results.get("searched_entity_types", []),
            available_entity_types=results.get("available_entity_types", []),
            results_by_type=results_by_type,
        )

        return GlobalSearchResponse(
            data=contact_data,
            meta=meta,
            links=links,
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
