"""
MCP entity conversion utilities.

Provides utilities for converting domain entities to AI-friendly MCP response formats,
reducing duplication and ensuring consistent response structures.
"""

from typing import Any

from app.core.contacts.models.entities import Contact
from app.mcp.domains.contacts.schemas import (
    ContactResponse,
    ContactSearchResult,
    GlobalSearchResponse,
)


class ContactConverter:
    """Converter for Contact entities to MCP response formats."""

    @staticmethod
    def to_contact_response(
        contact: Contact, additional_context: str = ""
    ) -> ContactResponse:
        """
        Convert a Contact entity to an AI-friendly ContactResponse.

        Args:
            contact: Contact domain entity
            additional_context: Additional context to include in summary

        Returns:
            ContactResponse optimized for AI consumption
        """
        # Extract basic contact information
        full_name = contact.get_full_name()
        primary_email = contact.get_primary_email()
        primary_phone = contact.get_primary_phone()
        tag_names = [str(tag.name) for tag in contact.tags]

        # Build AI-friendly summary
        summary = ContactConverter._build_contact_summary(
            full_name=full_name,
            tags=tag_names,
            email=primary_email,
            phone=primary_phone,
            notes=contact.notes,
            additional_context=additional_context,
        )

        return ContactResponse(
            id=str(contact.id),
            name=full_name,
            email=primary_email,
            phone=primary_phone,
            tags=tag_names,
            is_favourite=contact.is_favourite,
            summary=summary,
        )

    @staticmethod
    def to_search_result(
        search_hit: dict[str, Any], additional_context: str = ""
    ) -> ContactSearchResult:
        """
        Convert a search hit to an AI-friendly ContactSearchResult.

        Args:
            search_hit: Search result from MeiliSearch
            additional_context: Additional context to include in summary

        Returns:
            ContactSearchResult optimized for AI consumption
        """
        # Extract search hit information
        contact_id = str(search_hit.get("id", ""))
        first_name = search_hit.get("first_name", "")
        last_name = search_hit.get("last_name", "")
        full_name = search_hit.get("full_name", f"{first_name} {last_name}".strip())
        email = search_hit.get("email")
        phone = search_hit.get("phone")
        tags = search_hit.get("tags", [])
        highlighted = search_hit.get("_formatted", {})

        # Build AI-friendly summary with search context
        summary_parts = [f"{full_name} is a contact"]
        if tags:
            tag_list = ", ".join(tags)
            summary_parts.append(f"tagged as: {tag_list}")

        if email:
            summary_parts.append(f"Email: {email}")
        if phone:
            summary_parts.append(f"Phone: {phone}")

        # Add search relevance context
        if highlighted:
            summary_parts.append("Found through search highlighting")

        if additional_context:
            summary_parts.append(additional_context)

        summary = ". ".join(summary_parts) + "."

        return ContactSearchResult(
            id=contact_id,
            name=full_name,
            email=email,
            phone=phone,
            tags=tags,
            highlighted=highlighted,
            summary=summary,
        )

    @staticmethod
    def _build_contact_summary(
        full_name: str,
        tags: list[str],
        email: str | None = None,
        phone: str | None = None,
        notes: list[Any] | None = None,
        additional_context: str = "",
    ) -> str:
        """
        Build an AI-friendly summary for a contact.

        Args:
            full_name: Contact's full name
            tags: List of tag names
            email: Primary email address
            phone: Primary phone number
            notes: List of contact notes
            additional_context: Additional context to include

        Returns:
            AI-friendly summary string
        """
        summary_parts = [f"{full_name} is a contact"]

        if tags:
            tag_list = ", ".join(tags)
            summary_parts.append(f"tagged as: {tag_list}")

        # Include notes if available
        if notes:
            # Get the most recent note
            latest_note = notes[0] if notes else None
            if latest_note and hasattr(latest_note, "content"):
                summary_parts.append(f"Notes: {latest_note.content}")

        if email:
            summary_parts.append(f"Primary email: {email}")

        if phone:
            summary_parts.append(f"Primary phone: {phone}")

        if additional_context:
            summary_parts.append(additional_context)

        return ". ".join(summary_parts) + "."


class SearchResponseConverter:
    """Converter for search responses to AI-friendly formats."""

    @staticmethod
    def build_search_summary(
        query: str,
        total_hits: int,
        processing_time_ms: int,
        available_tags: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        additional_context: str = "",
    ) -> str:
        """
        Build an AI-friendly search summary.

        Args:
            query: Original search query
            total_hits: Total number of matching results
            processing_time_ms: Search processing time
            available_tags: Available tags for filtering
            filters: Applied filters
            additional_context: Additional context

        Returns:
            AI-friendly search summary
        """
        summary_parts = [
            f"Found {total_hits} contacts matching '{query}'",
            f"Search completed in {processing_time_ms}ms",
        ]

        if filters and "tags" in filters:
            filter_tags = filters["tags"]
            summary_parts.append(f"Filtered by tags: {', '.join(filter_tags)}")

        if available_tags:
            # Show first 10 tags to avoid overwhelming the summary
            tag_preview = ", ".join(available_tags[:10])
            if len(available_tags) > 10:
                tag_preview += f" (and {len(available_tags) - 10} more)"
            summary_parts.append(f"Available tags for filtering: {tag_preview}")

        if additional_context:
            summary_parts.append(additional_context)

        return ". ".join(summary_parts) + "."

    @staticmethod
    def build_global_search_summary(
        query: str,
        total_hits: int,
        processing_time_ms: int,
        searched_entity_types: list[str],
        available_entity_types: list[str],
        additional_context: str = "",
    ) -> str:
        """
        Build an AI-friendly global search summary.

        Args:
            query: Original search query
            total_hits: Total number of matching results
            processing_time_ms: Search processing time
            searched_entity_types: Entity types that were searched
            available_entity_types: All available entity types
            additional_context: Additional context

        Returns:
            AI-friendly global search summary
        """
        summary_parts = [
            f"Found {total_hits} results matching '{query}' across {len(searched_entity_types)} entity types",
            f"Search completed in {processing_time_ms}ms",
        ]

        if searched_entity_types:
            summary_parts.append(
                f"Searched entity types: {', '.join(searched_entity_types)}"
            )

        summary_parts.append(
            f"Available entity types: {', '.join(available_entity_types)}"
        )

        if additional_context:
            summary_parts.append(additional_context)

        return ". ".join(summary_parts) + "."

    @staticmethod
    def to_global_search_response(
        search_results: dict[str, Any], additional_context: str = ""
    ) -> "GlobalSearchResponse":
        """
        Convert global search results to AI-friendly GlobalSearchResponse.

        Args:
            search_results: Global search results from SearchService
            additional_context: Additional context to include in summary

        Returns:
            GlobalSearchResponse optimized for AI consumption
        """
        # Extract search metadata
        query = search_results.get("query", "")
        total_hits = search_results.get("estimated_total_hits", 0)
        processing_time_ms = search_results.get("processing_time_ms", 0)
        searched_entity_types = search_results.get("searched_entity_types", ["contact"])
        available_entity_types = search_results.get(
            "available_entity_types", ["contact"]
        )

        # Process search hits using shared processor
        hits = search_results.get("hits", [])
        search_result_objects = SearchResultProcessor.process_global_search_hits(
            hits, additional_context
        )

        # Build AI-friendly summary
        summary = SearchResponseConverter.build_global_search_summary(
            query=query,
            total_hits=total_hits,
            processing_time_ms=processing_time_ms,
            searched_entity_types=searched_entity_types,
            available_entity_types=available_entity_types,
            additional_context=additional_context,
        )

        return GlobalSearchResponse(
            results=search_result_objects,
            query=query,
            total_hits=total_hits,
            processing_time_ms=processing_time_ms,
            searched_entity_types=searched_entity_types,
            available_entity_types=available_entity_types,
            summary=summary,
        )


class SearchResultProcessor:
    """Processor for search results to reduce duplication across search tools."""

    @staticmethod
    def process_contact_search_hits(
        hits: list[dict[str, Any]], additional_context: str = ""
    ) -> list[ContactSearchResult]:
        """
        Process search hits into ContactSearchResult objects.

        Args:
            hits: List of search hits from MeiliSearch
            additional_context: Additional context to include in summaries

        Returns:
            List of ContactSearchResult objects optimized for AI consumption
        """
        search_results = []
        for hit in hits:
            search_result = ContactConverter.to_search_result(hit, additional_context)
            search_results.append(search_result)
        return search_results

    @staticmethod
    def process_global_search_hits(
        hits: list[dict[str, Any]], additional_context: str = ""
    ) -> list[ContactSearchResult]:
        """
        Process global search hits into ContactSearchResult objects.

        Args:
            hits: List of search hits from global search
            additional_context: Additional context to include in summaries

        Returns:
            List of ContactSearchResult objects with entity type context
        """
        search_results = []
        for hit in hits:
            # Add entity type context for global search
            entity_context = "Found in contact database"
            if additional_context:
                entity_context = f"{additional_context}. {entity_context}"
            else:
                entity_context = f"{entity_context}"

            search_result = ContactConverter.to_search_result(hit, entity_context)
            search_results.append(search_result)
        return search_results
