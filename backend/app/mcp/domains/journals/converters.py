"""
MCP journal entity conversion utilities.

Provides utilities for converting journal domain entities to AI-friendly MCP response formats,
ensuring consistent response structures optimized for AI consumption.
"""

from typing import Any

from app.core.contacts.models.entities import Contact
from app.core.journal.models.calendar import Calendar
from app.core.journal.models.entities import Journal
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_tag import JournalTag

from .schemas import (
    CalendarInfo as CalendarInfoSchema,
)
from .schemas import (
    ContactRelationshipInfo,
    JournalChildSummary,
    JournalResponse,
    JournalSearchResult,
    TagInfo,
    TypeDataResponse,
)


class JournalConverter:
    """Converter for Journal entities to MCP response formats."""

    @staticmethod
    def to_journal_response(
        journal: Journal,
        types: list[str],
        type_data: dict[str, Any],
        contacts: list[tuple[JournalContactRelationship, Contact]],
        tags: list[JournalTag],
        calendar: Calendar | None,
        parent: Journal | None = None,
        children: list[Journal] | None = None,
        additional_context: str = "",
    ) -> JournalResponse:
        """
        Convert a Journal entity to an AI-friendly JournalResponse.

        Args:
            journal: Journal domain entity
            types: List of journal type strings
            type_data: Type-specific data organized by type
            contacts: List of (relationship, contact) tuples
            tags: List of JournalTag entities
            calendar: Calendar entity for EVENT type journals
            parent: Parent journal entity (optional)
            children: List of child journal entities (optional)
            additional_context: Additional context to include in summary

        Returns:
            JournalResponse optimized for AI consumption
        """
        # Build contact relationship info
        contact_infos = [
            ContactRelationshipInfo(
                contact_id=str(contact.id),
                contact_name=contact.get_full_name(),
                relationship_type=relationship.relationship_type.value.upper(),
            )
            for relationship, contact in contacts
            if contact.id is not None
        ]

        # Build tag info
        tag_infos = [
            TagInfo(
                tag_id=str(tag.id),
                tag_name=tag.name,
                tag_color=tag.color,
            )
            for tag in tags
            if tag.id is not None
        ]

        # Build calendar info for EVENT type
        calendar_info = None
        if calendar and "EVENT" in types and type_data.get("EVENT"):
            event_data = type_data["EVENT"]
            calendar_info = CalendarInfoSchema(
                calendar_id=str(calendar.id),
                calendar_name=calendar.name,
                start_time=event_data.get("start_time"),
                end_time=event_data.get("end_time"),
                is_all_day=event_data.get("is_all_day", False),
                location=event_data.get("location"),
            )

        # Build parent info
        parent_info = None
        if parent:
            parent_info = {"id": str(parent.id), "title": parent.title}

        # Build children summaries
        child_summaries = []
        if children:
            for child in children:
                child_summary = JournalConverter._build_journal_summary(
                    child.title,
                    child.content,
                    types=[],  # Don't include types in child summaries
                    tags=[],
                    contacts=[],
                )
                child_summaries.append(
                    JournalChildSummary(
                        id=str(child.id),
                        title=child.title,
                        summary=child_summary,
                    )
                )

        # Build type data response
        type_data_response = None
        if type_data:
            type_data_response = TypeDataResponse(
                EVENT=type_data.get("EVENT"),
                MOOD_RATING=type_data.get("MOOD_RATING"),
                PHOTO_ALBUM=type_data.get("PHOTO_ALBUM"),
                PLAN=type_data.get("PLAN"),
                TRAVEL=type_data.get("TRAVEL"),
            )

        # Build AI-friendly summary
        summary = JournalConverter._build_journal_summary(
            title=journal.title,
            content=journal.content,
            types=types,
            tags=[tag.name for tag in tags],
            contacts=[contact.get_full_name() for _, contact in contacts],
            additional_context=additional_context,
        )

        return JournalResponse(
            id=str(journal.id),
            title=journal.title,
            content=journal.content,
            event_date_range={
                "start": journal.event_date_range.start.isoformat(),
                "end": journal.event_date_range.end.isoformat(),
            },
            types=types,
            type_data=type_data_response,
            contacts=contact_infos,
            tags=tag_infos,
            calendar=calendar_info,
            parent=parent_info,
            children=child_summaries,
            summary=summary,
        )

    @staticmethod
    def _build_journal_summary(
        title: str,
        content: str,
        types: list[str],
        tags: list[str],
        contacts: list[str],
        additional_context: str = "",
    ) -> str:
        """
        Build an AI-friendly summary for a journal.

        Args:
            title: Journal title
            content: Journal content (markdown)
            types: List of journal types
            tags: List of tag names
            contacts: List of contact names
            additional_context: Additional context to include

        Returns:
            AI-friendly summary string
        """
        summary_parts = [f"Journal entry titled '{title}'"]

        # Add content preview (first 100 characters)
        if content:
            content_preview = content[:100].replace("\n", " ").strip()
            if len(content) > 100:
                content_preview += "..."
            summary_parts.append(f"Content: {content_preview}")

        # Add types
        if types:
            type_list = ", ".join(types)
            summary_parts.append(f"Types: {type_list}")

        # Add contacts
        if contacts:
            contact_list = ", ".join(contacts[:3])  # Limit to first 3
            if len(contacts) > 3:
                contact_list += f" (and {len(contacts) - 3} more)"
            summary_parts.append(f"Related contacts: {contact_list}")

        # Add tags
        if tags:
            tag_list = ", ".join(tags[:5])  # Limit to first 5
            if len(tags) > 5:
                tag_list += f" (and {len(tags) - 5} more)"
            summary_parts.append(f"Tags: {tag_list}")

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
        journal_id = str(search_hit.get("id", ""))
        title = search_hit.get("title", "")
        content = search_hit.get("content", "")
        event_date_range_start = search_hit.get("event_date_range_start", "")
        event_date_range_end = search_hit.get("event_date_range_end", "")
        types = search_hit.get("types", [])
        tags = search_hit.get("tag_ids", [])
        highlighted = search_hit.get("_formatted", {})

        # Build AI-friendly summary with search context
        summary_parts = [f"Journal entry '{title}'"]

        if types:
            type_list = ", ".join(types)
            summary_parts.append(f"Types: {type_list}")

        if tags:
            tag_list = ", ".join(tags[:5])
            if len(tags) > 5:
                tag_list += f" (and {len(tags) - 5} more)"
            summary_parts.append(f"Tags: {tag_list}")

        # Add search relevance context
        if highlighted:
            summary_parts.append("Found through search highlighting")

        if additional_context:
            summary_parts.append(additional_context)

        summary = ". ".join(summary_parts) + "."

        return JournalSearchResult(
            id=journal_id,
            title=title,
            content=content[:200] + "..." if len(content) > 200 else content,
            event_date_range={
                "start": event_date_range_start,
                "end": event_date_range_end,
            },
            types=types,
            tags=tags,
            highlighted=highlighted,
            summary=summary,
        )
