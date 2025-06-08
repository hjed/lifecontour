"""
Search API controllers.

Handles search-related HTTP endpoints including contact search,
global search, and search suggestions following JSON API specification.
"""

import structlog
from fastapi import APIRouter, Depends, Query, Request
from meilisearch.errors import MeilisearchError

from app.api.auth.dependencies import require_authentication
from app.api.common.schemas import (
    create_pagination_links,
    create_pagination_meta,
    get_request_base_url,
)
from app.api.contacts.schemas import ContactResource
from app.api.dependencies import SearchServiceDep
from app.api.search.schemas import (
    ContactSearchMeta,
    ContactSearchResponse,
    GlobalSearchMeta,
    GlobalSearchResponse,
    SearchHealthResponse,
    SearchResultAttributes,
    SearchResultMeta,
    SearchResultResource,
    SearchSuggestionsResponse,
)
from app.api.search.utils import (
    calculate_pagination_offset,
    create_contact_resource_from_search_hit,
)
from app.core.search.exceptions import SearchServiceUnavailableError

logger = structlog.get_logger()

# Router for authenticated search endpoints
authenticated_router = APIRouter(
    prefix="/search", tags=["search"], dependencies=[Depends(require_authentication)]
)

# Router for public search endpoints (like health)
public_router = APIRouter(prefix="/search", tags=["search"])

# Combined router for export
router = APIRouter()


@authenticated_router.get("/contacts", response_model=ContactSearchResponse)
def search_contacts(
    request: Request,
    search_service: SearchServiceDep,
    q: str = Query(..., description="Search query", min_length=1, max_length=500),
    page: int = Query(default=1, description="Page number", ge=1),
    limit: int = Query(default=20, description="Results per page", ge=1, le=100),
    tags: list[str] | None = Query(default=None, description="Filter by tags"),
    sort: list[str] | None = Query(default=None, description="Sort criteria"),
) -> ContactSearchResponse:
    """
    Search contacts using MeiliSearch.

    Supports full-text search across fields with highlighting, facets, and pagination.
    Supports filtering by tags and custom sorting.
    """
    # Calculate offset from page
    offset = calculate_pagination_offset(page, limit)

    # Build filters
    filters = {}
    if tags:
        filters["tags"] = tags

    try:
        results = search_service.search_contacts(
            query=q,
            filters=filters if filters else None,
            limit=limit,
            offset=offset,
            sort=sort,
        )
    except MeilisearchError as e:
        logger.error("MeiliSearch error during contact search", error=str(e), query=q)
        raise SearchServiceUnavailableError("MeiliSearch", str(e)) from e

    # Convert to contact resources (same format as contact API)
    base_url = get_request_base_url(request)
    contact_resources = [
        create_contact_resource_from_search_hit(hit, base_url)
        for hit in results["hits"]
    ]

    # Build pagination metadata
    total_count = results.get("estimated_total_hits", 0)
    pagination_meta = create_pagination_meta(total_count, page, limit)

    # Build search-specific metadata
    search_meta = ContactSearchMeta(
        query=q,
        processing_time_ms=results.get("processing_time_ms", 0),
        facets=results.get("facet_distribution"),
        available_tags=list(
            results.get("facet_distribution", {}).get("tags", {}).keys()
        ),
        total_count=pagination_meta.total_count,
        page_count=pagination_meta.page_count,
        current_page=pagination_meta.current_page,
        per_page=pagination_meta.per_page,
    )

    # Build pagination links with query parameters
    base_url = str(request.url).split("?")[0]
    additional_params: dict[str, str | list[str]] = {"q": q}
    if tags:
        additional_params["tags"] = tags
    if sort:
        additional_params["sort"] = sort

    links = create_pagination_links(
        base_url, page, limit, total_count, additional_params
    )

    return ContactSearchResponse(
        data=contact_resources,
        meta=search_meta,
        links=links,
    )


@authenticated_router.get("/global", response_model=GlobalSearchResponse)
def global_search(
    request: Request,
    search_service: SearchServiceDep,
    q: str = Query(..., description="Search query", min_length=1, max_length=500),
    page: int = Query(default=1, description="Page number", ge=1),
    limit: int = Query(default=20, description="Results per page", ge=1, le=100),
    entity_types: list[str] | None = Query(
        default=None, description="Entity types to search"
    ),
) -> GlobalSearchResponse:
    """
    Perform global search across all entity types.

    Returns JSON API compliant search results across contacts and other entities
    (when implemented) with unified results.
    """
    # Calculate offset from page
    offset = calculate_pagination_offset(page, limit)

    # Perform global search
    try:
        results = search_service.global_search(
            query=q, entity_types=entity_types, limit=limit, offset=offset
        )
    except MeilisearchError as e:
        logger.error("MeiliSearch error during global search", error=str(e), query=q)
        raise SearchServiceUnavailableError("MeiliSearch", str(e)) from e

    logger.debug(
        "Global search request",
        query=q,
        page=page,
        limit=limit,
        entity_types=entity_types,
    )

    # Convert to JSON API resource format
    search_resources: list[ContactResource | SearchResultResource] = []
    results_by_type: dict[str, int] = {}
    base_url = get_request_base_url(request)

    for hit in results["hits"]:
        entity_type = hit.get("entity_type", "unknown")

        # Count results by type
        results_by_type[entity_type] = results_by_type.get(entity_type, 0) + 1

        # Create composite ID
        resource_id = f"{entity_type}-{hit['id']}"

        # Create resource based on entity type
        resource: ContactResource | SearchResultResource
        if entity_type == "contact":
            resource = create_contact_resource_from_search_hit(hit, base_url)
        else:
            # For other entity types, use SearchResultResource
            title = hit.get("title", hit.get("name", "Unknown"))
            content = hit.get("content", hit.get("description", ""))

            resource = SearchResultResource(
                id=resource_id,
                attributes=SearchResultAttributes(
                    entity_type=entity_type,
                    title=title,
                    content=content,
                    highlighted=hit.get("_formatted"),
                ),
                meta=SearchResultMeta(
                    original_id=hit["id"],
                    search_metadata=hit,
                ),
            )
        search_resources.append(resource)

    # Build pagination metadata
    total_count = results.get("estimated_total_hits", 0)
    pagination_meta = create_pagination_meta(total_count, page, limit)

    # Build search-specific metadata
    search_meta = GlobalSearchMeta(
        query=q,
        processing_time_ms=results.get("processing_time_ms", 0),
        facets=results.get("facet_distribution"),
        searched_entity_types=results.get("searched_entity_types", []),
        available_entity_types=results.get("available_entity_types", []),
        results_by_type=results_by_type,
        total_count=pagination_meta.total_count,
        page_count=pagination_meta.page_count,
        current_page=pagination_meta.current_page,
        per_page=pagination_meta.per_page,
    )

    # Build pagination links with query parameters
    base_url = str(request.url).split("?")[0]
    additional_params: dict[str, str | list[str]] = {"q": q}
    if entity_types:
        additional_params["entity_types"] = entity_types

    links = create_pagination_links(
        base_url, page, limit, total_count, additional_params
    )

    return GlobalSearchResponse(
        data=search_resources,
        meta=search_meta,
        links=links,
    )


@authenticated_router.get("/suggestions", response_model=SearchSuggestionsResponse)
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
    except MeilisearchError as e:
        logger.error(
            "MeiliSearch error getting search suggestions", error=str(e), query=q
        )
        # For suggestions, we gracefully degrade instead of raising exceptions
        return SearchSuggestionsResponse(suggestions=[], query=q)
    except Exception as e:
        logger.error(
            "Unexpected error getting search suggestions", error=str(e), query=q
        )
        # For suggestions, we gracefully degrade instead of raising exceptions
        return SearchSuggestionsResponse(suggestions=[], query=q)


@public_router.get("/health", response_model=SearchHealthResponse)
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
    except MeilisearchError as e:
        logger.error("MeiliSearch error checking search health", error=str(e))
        # For health checks, we return error status instead of raising exceptions
        return SearchHealthResponse(
            status="error",
            meilisearch_status="unavailable",
            indices=[],
            error=f"MeiliSearch connection failed: {str(e)}",
        )
    except Exception as e:
        logger.error("Unexpected error checking search health", error=str(e))
        # For health checks, we return error status instead of raising exceptions
        return SearchHealthResponse(
            status="error", meilisearch_status="unknown", indices=[], error=str(e)
        )


# Include sub-routers in the main router
router.include_router(authenticated_router)
router.include_router(public_router)
