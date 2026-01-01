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


class SearchService:
    """Service for search operations using MeiliSearch."""

    def __init__(self) -> None:
        """Initialize the search service."""
        self.client = get_meilisearch_client()

    def search_contacts(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
        sort: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Search contacts using MeiliSearch.

        Args:
            query: Search query string
            filters: Optional filters to apply
            limit: Maximum number of results
            offset: Offset for pagination
            sort: Optional sort criteria

        Returns:
            Search results with metadata
        """
        try:
            index_name = get_index_name("contacts")
            index = self.client.index(index_name)

            # Build search parameters
            search_params = {
                "limit": limit,
                "offset": offset,
                "attributesToHighlight": [
                    "first_name",
                    "last_name",
                    "email",
                    "notes_content",
                ],
                "highlightPreTag": "<mark>",
                "highlightPostTag": "</mark>",
                "attributesToRetrieve": [
                    "id",
                    "first_name",
                    "last_name",
                    "full_name",
                    "email",
                    "phone",
                    "tags",
                    "created_at",
                    "updated_at",
                ],
            }

            # Add filters if provided
            if filters:
                filter_expressions = []
                for key, value in filters.items():
                    if isinstance(value, list):
                        # Handle array filters (e.g., tags)
                        filter_expressions.append(f"{key} IN {value}")
                    elif isinstance(value, bool):
                        # Handle boolean filters (e.g., is_favourite)
                        filter_expressions.append(f"{key} = {str(value).lower()}")
                    else:
                        filter_expressions.append(f"{key} = '{value}'")

                if filter_expressions:
                    search_params["filter"] = " AND ".join(filter_expressions)

            # Add sort if provided
            if sort:
                search_params["sort"] = sort

            # Perform the search
            results = index.search(query, search_params)

            # Format the response
            response = {
                "hits": results["hits"],
                "query": query,
                "processing_time_ms": results["processingTimeMs"],
                "limit": limit,
                "offset": offset,
                "estimated_total_hits": results.get("estimatedTotalHits", 0),
                "facet_distribution": results.get("facetDistribution", {}),
                "facet_stats": results.get("facetStats", {}),
            }

            logger.debug(
                "Contact search completed",
                query=query,
                hits_count=len(results["hits"]),
                processing_time_ms=results["processingTimeMs"],
            )

            return response

        except MeilisearchError as e:
            logger.error(
                "MeiliSearch error during contact search", query=query, error=str(e)
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error during contact search", query=query, error=str(e)
            )
            raise

    def search_journals(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 20,
        offset: int = 0,
        sort: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Search journals using MeiliSearch.

        Args:
            query: Search query string
            filters: Optional filters to apply
            limit: Maximum number of results
            offset: Offset for pagination
            sort: Optional sort criteria

        Returns:
            Search results with metadata
        """
        try:
            index_name = get_index_name("journals")
            index = self.client.index(index_name)

            # Build search parameters
            search_params = {
                "limit": limit,
                "offset": offset,
                "attributesToHighlight": [
                    "title",
                    "content",
                    "location",
                ],
                "highlightPreTag": "<mark>",
                "highlightPostTag": "</mark>",
                "attributesToRetrieve": [
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
                    "created_at",
                    "updated_at",
                ],
            }

            # Add filters if provided
            if filters:
                filter_expressions = []
                for key, value in filters.items():
                    if isinstance(value, list):
                        # Handle array filters (e.g., types, contact_ids)
                        filter_expressions.append(f"{key} IN {value}")
                    else:
                        filter_expressions.append(f"{key} = '{value}'")

                if filter_expressions:
                    search_params["filter"] = " AND ".join(filter_expressions)

            # Add sort if provided
            if sort:
                search_params["sort"] = sort

            # Perform the search
            results = index.search(query, search_params)

            # Format the response
            response = {
                "hits": results["hits"],
                "query": query,
                "processing_time_ms": results["processingTimeMs"],
                "limit": limit,
                "offset": offset,
                "estimated_total_hits": results.get("estimatedTotalHits", 0),
                "facet_distribution": results.get("facetDistribution", {}),
                "facet_stats": results.get("facetStats", {}),
            }

            logger.debug(
                "Journal search completed",
                query=query,
                hits_count=len(results["hits"]),
                processing_time_ms=results["processingTimeMs"],
            )

            return response

        except MeilisearchError as e:
            logger.error(
                "MeiliSearch error during journal search", query=query, error=str(e)
            )
            raise
        except Exception as e:
            logger.error(
                "Unexpected error during journal search", query=query, error=str(e)
            )
            raise

    def global_search(
        self,
        query: str,
        entity_types: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Perform global search across all entity types.

        Args:
            query: Search query string
            entity_types: Optional list of entity types to search
            limit: Maximum number of results
            offset: Offset for pagination

        Returns:
            Global search results with metadata
        """
        try:
            # Determine which entity types to search
            available_types = ["contact", "journal"]
            search_types = entity_types if entity_types else available_types

            # Collect results from all entity types
            all_hits = []
            total_processing_time = 0

            # Search contacts if requested
            if "contact" in search_types:
                try:
                    contact_results = self.search_contacts(
                        query=query, limit=limit, offset=offset
                    )
                    all_hits.extend(contact_results["hits"])
                    total_processing_time += contact_results.get(
                        "processing_time_ms", 0
                    )
                except Exception as e:
                    logger.warning(
                        "Error searching contacts in global search",
                        query=query,
                        error=str(e),
                    )

            # Search journals if requested
            if "journal" in search_types:
                try:
                    journal_results = self.search_journals(
                        query=query, limit=limit, offset=offset
                    )
                    all_hits.extend(journal_results["hits"])
                    total_processing_time += journal_results.get(
                        "processing_time_ms", 0
                    )
                except Exception as e:
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
        self, query: str, entity_type: str = "contacts", limit: int = 5
    ) -> list[str]:
        """
        Get search suggestions for autocomplete.

        Args:
            query: Partial query string
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

        except Exception as e:
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
            except Exception as e:
                logger.warning("Could not get index information", error=str(e))

            return {
                "status": health.get("status", "unknown"),
                "meilisearch_health": health,
                "indices": indices_info,
            }

        except Exception as e:
            logger.error("Error getting search health", error=str(e))
            return {"status": "error", "error": str(e), "indices": []}
