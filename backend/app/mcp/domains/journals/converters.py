"""
Journal domain MCP conversion utilities.

Provides utilities for converting journal domain entities to AI-friendly MCP response formats,
reducing duplication and ensuring consistent response structures.
"""

from datetime import datetime
from typing import Any

from core_shared.models.journals import Calendar, Journal

from app.core.journal.models.journal_tag import JournalTag
from app.mcp.domains.journals.schemas import (
    CalendarSchema,
    ContactRelationshipSchema,
    EventDateRangeSchema,
    JournalChildSummary,
    JournalResponse,
    JournalSearchResult,
)


class JournalConverter:
    """Converter for journal entities to AI-friendly MCP formats."""

    @staticmethod
    def to_response(
        journal: Journal,
        types: list[str],
        type_data: dict[str, dict[str, Any]],
        contacts: list[tuple[int, str, str]],  # (id, name, relationship_type)
        tags: list[JournalTag],
        calendar: Calendar | None = None,
        parent: Journal | None = None,
        children: list[Journal] | None = None,
        additional_context: str = "",
    ) -> JournalResponse:
        """
        Convert a Journal entity to an AI-friendly JournalResponse.

        Args:
            journal: The journal entity
            types: List of journal type names
            type_data: Type-specific data organized by type
            contacts: List of contact tuples (id, name, relationship_type)
            tags: List of JournalTag entities
            calendar: Calendar entity (if EVENT type)
            parent: Parent journal entity (if child)
            children: List of child journal entities (if parent)
            additional_context: Additional context to include in summary

        Returns:
            JournalResponse optimized for AI consumption
        """
        # Build contact relationships
        contact_relationships = [
            ContactRelationshipSchema(
                id=contact_id, name=name, relationship_type=rel_type
            )
            for contact_id, name, rel_type in contacts
        ]

        # Build tag names
        tag_names = [tag.name for tag in tags]

        # Build calendar schema
        calendar_schema = None
        if calendar:
            calendar_schema = CalendarSchema(
                id=str(calendar.id), name=calendar.name, color=calendar.color
            )

        # Build parent summary
        parent_summary = None
        if parent:
            parent_summary = JournalChildSummary(
                id=parent.id or 0,
                title=parent.title,
                summary=f"Parent journal: {parent.title}",
            )

        # Build children summaries
        children_summaries = []
        if children:
            for child in children:
                children_summaries.append(
                    JournalChildSummary(
                        id=child.id or 0,
                        title=child.title,
                        summary=f"Child journal: {child.title}",
                    )
                )

        # Build AI-friendly summary
        summary = JournalConverter._build_journal_summary(
            title=journal.title,
            types=types,
            tags=tag_names,
            contacts=contact_relationships,
            calendar=calendar_schema,
            parent=parent_summary,
            children_count=len(children_summaries),
            additional_context=additional_context,
        )

        return JournalResponse(
            id=journal.id or 0,
            title=journal.title,
            content=journal.content,
            summary=summary,
            event_date_range=EventDateRangeSchema(
                start=journal.event_date_range.start, end=journal.event_date_range.end
            ),
            types=types,
            type_data=type_data,
            contacts=contact_relationships,
            tags=tag_names,
            calendar=calendar_schema,
            parent=parent_summary,
            children=children_summaries,
            created_at=journal.created_at or journal.event_date_range.start,
            updated_at=journal.updated_at or journal.event_date_range.start,
        )

    @staticmethod
    def _build_journal_summary(
        title: str,
        types: list[str],
        tags: list[str],
        contacts: list[ContactRelationshipSchema],
        calendar: CalendarSchema | None,
        parent: JournalChildSummary | None,
        children_count: int,
        additional_context: str = "",
    ) -> str:
        """Build an AI-friendly summary of the journal."""
        summary_parts = [f"Journal: {title}"]

        if types:
            types_str = ", ".join(types)
            summary_parts.append(f"Types: {types_str}")

        if tags:
            tags_str = ", ".join(tags)
            summary_parts.append(f"Tags: {tags_str}")

        if contacts:
            contact_summary = f"{len(contacts)} contact(s)"
            summary_parts.append(contact_summary)

        if calendar:
            summary_parts.append(f"Calendar: {calendar.name}")

        if parent:
            summary_parts.append(f"Child of: {parent.title}")

        if children_count > 0:
            summary_parts.append(f"{children_count} child journal(s)")

        if additional_context:
            summary_parts.append(additional_context)

        return ". ".join(summary_parts) + "."

    @staticmethod
    def to_search_result(
        search_hit: dict[str, Any], additional_context: str = ""
    ) -> JournalSearchResult:
        """
        Convert a search hit to an AI-friendly JournalSearchResult.

        Args:
            search_hit: Search result from MeiliSearch
            additional_context: Additional context to include in summary

        Returns:
            JournalSearchResult optimized for AI consumption
        """
        # Extract search hit information
        journal_id = search_hit.get("id", 0)
        title = search_hit.get("title", "")
        content = search_hit.get("content", "")
        content_excerpt = content[:200] + "..." if len(content) > 200 else content

        # Extract date range
        start = search_hit.get("event_date_range_start")
        end = search_hit.get("event_date_range_end")

        # Ensure start and end are datetime objects
        if not isinstance(start, datetime):
            start = datetime.fromisoformat(str(start)) if start else datetime.now()
        if not isinstance(end, datetime):
            end = datetime.fromisoformat(str(end)) if end else datetime.now()

        # Extract types and tags
        types = search_hit.get("types", [])
        tags = search_hit.get("tag_names", [])

        # Extract highlighting
        highlighted = search_hit.get("_formatted", {})

        # Build AI-friendly summary with search context
        summary_parts = [f"Journal: {title}"]
        if types:
            summary_parts.append(f"Types: {', '.join(types)}")
        if tags:
            summary_parts.append(f"Tags: {', '.join(tags)}")
        if additional_context:
            summary_parts.append(additional_context)

        summary = ". ".join(summary_parts) + "."

        return JournalSearchResult(
            id=journal_id,
            title=title,
            content_excerpt=content_excerpt,
            event_date_range=EventDateRangeSchema(start=start, end=end),
            types=types,
            tags=tags,
            highlighted=highlighted,
            summary=summary,
        )
