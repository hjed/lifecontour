"""
Search service for MeiliSearch operations.

Provides high-level search functionality for contacts and global search
with proper error handling and response formatting.
"""

from typing import Any

import structlog
from meilisearch.errors import MeilisearchError

from app.infrastructure.search.meilisearch_client import (
    get_index_name,
    get_meilisearch_client,
)

logger = structlog.get_logger()

OWNER_ATTRIBUTE = "user_id"


def owner_filter(user_id: str) -> str:
    """The filter expression that restricts a search to one owner's documents.

    The value is double-quoted with backslashes and double quotes escaped,
    which is how MeiliSearch reads a literal inside a filter expression.
    """
    escaped = user_id.replace("\\", "\\\\").replace('"', '\\"')
    return f'{OWNER_ATTRIBUTE} = "{escaped}"'


class SearchService:
    """Service for search operations using MeiliSearch."""

    def __init__(self) -> None:
        """Initialize the search service."""
        self.client = get_meilisearch_client()

    def _build_search_params(
        self,
        *,
        owner_id: str,
        limit: int,
        offset: int,
        attributes_to_highlight: list[str],
        attributes_to_retrieve: list[str],
        filters: dict[str, Any] | None = None,
        sort: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Build search parameters for MeiliSearch.

        The filter is an array, whose top-level elements MeiliSearch ANDs. The
        owner's expression is the first element and each client filter is an
        element of its own, so no client filter can widen the search beyond the
        owner's documents.

        Args:
            owner_id: The user whose documents the search is restricted to
            limit: Maximum number of results
            offset: Offset for pagination
            attributes_to_highlight: Fields to highlight in results
            attributes_to_retrieve: Fields to include in results
            filters: Optional filters to apply
            sort: Optional sort criteria

        Returns:
            Dictionary of search parameters

        Raises:
            ValueError: If ``filters`` names the owner attribute; the owner is
                only ever given through ``owner_id``.
        """
        if filters and OWNER_ATTRIBUTE in filters:
            raise ValueError(
                f"Pass the owner as owner_id, not as a '{OWNER_ATTRIBUTE}' filter"
            )

        search_params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "attributesToHighlight": attributes_to_highlight,
            "highlightPreTag": "<mark>",
            "highlightPostTag": "</mark>",
            "attributesToRetrieve": attributes_to_retrieve,
            "showRankingScore": True,
        }

        filter_expressions = [owner_filter(owner_id)]
        if filters:
            for key, value in filters.items():
                if isinstance(value, list):
                    # Handle array filters (e.g., tags, types)
                    filter_expressions.append(f"{key} IN {value}")
                elif isinstance(value, bool):
                    # Handle boolean filters (e.g., is_favourite)
                    filter_expressions.append(f"{key} = {str(value).lower()}")
                else:
                    filter_expressions.append(f"{key} = '{value}'")
        search_params["filter"] = filter_expressions

        # Add sort if provided
        if sort:
            search_params["sort"] = sort

        return search_params

    def _perform_search(
        self,
        index_name: str,
        query: str,
        search_params: dict[str, Any],
        entity_type: str,
    ) -> dict[str, Any]:
        """
        Perform a search on a specific index.

        Args:
            index_name: Name of the index to search
            query: Search query string
            search_params: Search parameters
            entity_type: Type of entity being searched (for logging)

        Returns:
            Formatted search results

        Raises:
            MeilisearchError: If MeiliSearch operation fails
            Exception: For unexpected errors
        """
        try:
            index = self.client.index(index_name)
            results = index.search(query, search_params)

            # Format the response
            response = {
                "hits": results["hits"],
                "query": query,
                "processing_time_ms": results["processingTimeMs"],
                "limit": search_params["limit"],
                "offset": search_params["offset"],
                "estimated_total_hits": results.get("estimatedTotalHits", 0),
                "facet_distribution": results.get("facetDistribution", {}),
                "facet_stats": results.get("facetStats", {}),
            }

            logger.debug(
                "Search completed",
                entity_type=entity_type,
                query=query,
                hits_count=len(results["hits"]),
                processing_time_ms=results["processingTimeMs"],
            )

            return response

        except MeilisearchError as e:
            logger.error(
                "MeiliSearch error during search",
                entity_type=entity_type,
                query=query,
                error=str(e),
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error during search",
                entity_type=entity_type,
                query=query,
                error=str(e),
            )
            raise

    def search_contacts(
        self,
        query: str,
        *,
        user_id: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
        sort: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Search contacts using MeiliSearch.

        Args:
            query: Search query string
            user_id: The acting user; only their documents are searched
            filters: Optional filters to apply
            limit: Maximum number of results
            offset: Offset for pagination
            sort: Optional sort criteria

        Returns:
            Search results with metadata
        """
        index_name = get_index_name("contacts")

        search_params = self._build_search_params(
            owner_id=user_id,
            limit=limit,
            offset=offset,
            attributes_to_highlight=[
                "first_name",
                "last_name",
                "company",
                "job_title",
                "email",
                "notes_content",
            ],
            attributes_to_retrieve=[
                "id",
                "first_name",
                "last_name",
                "middle_name",
                "nick_name",
                "full_name",
                "company",
                "job_title",
                "email",
                "phone",
                "tags",
                "entity_type",
                "created_at",
                "updated_at",
                "is_favourite",
                "has_summary",
                "relationships",
                "last_activity_date",
                "journal_count_30d",
                "activity_count_30d",
            ],
            filters=filters,
            sort=sort,
        )

        return self._perform_search(
            index_name=index_name,
            query=query,
            search_params=search_params,
            entity_type="Contact",
        )

    def search_journals(
        self,
        query: str,
        *,
        user_id: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
        sort: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Search journals using MeiliSearch.

        Args:
            query: Search query string
            user_id: The acting user; only their documents are searched
            filters: Optional filters to apply
            limit: Maximum number of results
            offset: Offset for pagination
            sort: Optional sort criteria

        Returns:
            Search results with metadata
        """
        index_name = get_index_name("journals")

        search_params = self._build_search_params(
            owner_id=user_id,
            limit=limit,
            offset=offset,
            attributes_to_highlight=[
                "title",
                "content",
                "location",
            ],
            attributes_to_retrieve=[
                "id",
                "user_id",
                "title",
                "content",
                "event_date_range_start",
                "event_date_range_end",
                "types",
                "contact_ids",
                "tag_ids",
                "calendar_id",
                "parent_id",
                "location",
                "entity_type",
                "created_at",
                "updated_at",
            ],
            filters=filters,
            sort=sort,
        )

        return self._perform_search(
            index_name=index_name,
            query=query,
            search_params=search_params,
            entity_type="Journal",
        )

    def global_search(
        self,
        query: str,
        *,
        user_id: str,
        entity_types: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Perform global search across all entity types.

        Args:
            query: Search query string
            user_id: The acting user; only their documents are searched
            entity_types: Optional list of entity types to search
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            Global search results with metadata
        """
        try:
            # Determine which entity types to search
            available_types = ["contact", "journal"]
            search_types = entity_types or available_types

            # Collect results from all entity types
            all_hits = []
            total_processing_time = 0

            # Search contacts if requested
            if "contact" in search_types:
                try:
                    contact_results = self.search_contacts(
                        query=query, user_id=user_id, limit=limit, offset=offset
                    )
                    all_hits.extend(contact_results["hits"])
                    total_processing_time += contact_results.get(
                        "processing_time_ms", 0
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "Error searching contacts in global search",
                        query=query,
                        error=str(e),
                    )

            # Search journals if requested
            if "journal" in search_types:
                try:
                    journal_results = self.search_journals(
                        query=query, user_id=user_id, limit=limit, offset=offset
                    )
                    all_hits.extend(journal_results["hits"])
                    total_processing_time += journal_results.get(
                        "processing_time_ms", 0
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "Error searching journals in global search",
                        query=query,
                        error=str(e),
                    )

            # Sort by relevance (MeiliSearch score) if available
            all_hits.sort(key=lambda x: x.get("_rankingScore", 0), reverse=True)

            # Apply limit to combined results
            all_hits = all_hits[:limit]

            # Build response
            results = {
                "hits": all_hits,
                "query": query,
                "processing_time_ms": total_processing_time,
                "limit": limit,
                "offset": offset,
                "estimated_total_hits": len(all_hits),
                "searched_entity_types": search_types,
                "available_entity_types": available_types,
            }

            logger.debug(
                "Global search completed",
                query=query,
                entity_types=search_types,
                hits_count=len(all_hits),
            )

            return results

        except Exception as e:
            logger.error(
                "Error during global search",
                query=query,
                entity_types=entity_types,
                error=str(e),
            )
            raise

    def get_search_suggestions(
        self,
        query: str,
        *,
        user_id: str,
        entity_type: str = "contacts",
        limit: int = 5,
    ) -> list[str]:
        """
        Get search suggestions for autocomplete.

        Args:
            query: Partial query string
            user_id: The acting user; once suggestions are implemented they
                may only come from this user's documents
            entity_type: Type of entity to get suggestions for
            limit: Maximum number of suggestions

        Returns:
            List of search suggestions
        """
        try:
            # For now, return empty suggestions
            # This would be implemented with MeiliSearch's autocomplete features
            # or by analyzing common search terms

            logger.debug(
                "Search suggestions requested", query=query, entity_type=entity_type
            )

            return []

        except Exception as e:  # noqa: BLE001
            logger.error(
                "Error getting search suggestions",
                query=query,
                entity_type=entity_type,
                error=str(e),
            )
            return []

    def get_search_health(self) -> dict[str, Any]:
        """
        Get search system health information.

        Returns:
            Health information for the search system
        """
        try:
            # Check MeiliSearch health
            health = self.client.health()

            # Get index information
            indices_info: list[dict[str, Any]] = []
            try:
                indices = self.client.get_indexes()
                results = (
                    indices.get("results", []) if isinstance(indices, dict) else []
                )
                for index_info in results:
                    if not isinstance(index_info, dict):
                        continue

                    index_uid = index_info.get("uid")
                    if not index_uid:
                        continue

                    index = self.client.index(index_uid)
                    stats = index.get_stats()

                    if isinstance(stats, dict):
                        indices_info.append(
                            {
                                "name": index_uid,
                                "primary_key": index_info.get("primaryKey"),
                                "documents_count": stats.get("numberOfDocuments", 0),
                                "is_indexing": stats.get("isIndexing", False),
                            }
                        )
            except Exception as e:  # noqa: BLE001
                logger.warning("Could not get index information", error=str(e))

            return {
                "status": health.get("status", "unknown"),
                "meilisearch_health": health,
                "indices": indices_info,
            }

        except Exception as e:  # noqa: BLE001
            logger.error("Error getting search health", error=str(e))
            return {"status": "error", "error": str(e), "indices": []}
