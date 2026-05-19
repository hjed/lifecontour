"""
Journal domain MCP conversion utilities.

Provides utilities for converting journal domain entities to AI-friendly MCP response formats,
reducing duplication and ensuring consistent response structures.
"""

from datetime import UTC, datetime
from typing import Any

from core_shared.models.journals import Calendar, GearItem, Journal
from core_shared.models.journals.activity_template import ActivityTemplate

from app.core.integrations.external_link_helpers import ExternalLinkInfo
from app.core.journal.models.journal_tag import JournalTag
from app.mcp.domains.journals.schemas import (
    ActivityTemplateListMCPResponse,
    ActivityTemplateMCPResponse,
    CalendarSchema,
    ContactRelationshipSchema,
    ContactRelationshipSummary,
    EventDateRangeSchema,
    ExternalLinkSchema,
    GearItemListMCPResponse,
    GearItemMCPResponse,
    JournalChildSummary,
    JournalResponse,
    JournalSearchResult,
    TemplatePitchMCPSchema,
)


class JournalConverter:
    """Converter for journal entities to AI-friendly MCP formats."""

    @staticmethod
    def to_response(
        journal: Journal,
        types: list[str],
        type_data: dict[str, dict[str, Any]],
        contacts: list[ContactRelationshipSummary],
        tags: list[JournalTag],
        calendar: Calendar | None = None,
        parent: Journal | None = None,
        children: list[Journal] | None = None,
        additional_context: str = "",
        external_links: list[ExternalLinkInfo] | None = None,
    ) -> JournalResponse:
        """
        Convert a Journal entity to an AI-friendly JournalResponse.

        Args:
            journal: The journal entity
            types: List of journal type names
            type_data: Type-specific data organized by type
            contacts: List of ContactRelationshipSummary objects
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
                id=contact.id,
                name=contact.name,
                relationship_type=contact.relationship_type,
                status=contact.status,
                role=contact.role,
            )
            for contact in contacts
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

        # Build external link schemas
        external_link_schemas = [
            ExternalLinkSchema(
                source=link.source,
                url=link.url,
                external_id=link.external_id,
            )
            for link in (external_links or [])
        ]

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
            external_links=external_link_schemas,
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
            start = (
                datetime.fromisoformat(str(start)) if start else datetime.now(tz=UTC)
            )
        if not isinstance(end, datetime):
            end = datetime.fromisoformat(str(end)) if end else datetime.now(tz=UTC)

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


class ActivityTemplateMCPConverter:
    """Converter for activity template entities to AI-friendly MCP formats."""

    @staticmethod
    def to_mcp_response(template: ActivityTemplate) -> ActivityTemplateMCPResponse:
        """Convert a template entity to an MCP response."""
        pitches = []
        if template.pitches:
            for p in template.pitches:
                pitches.append(
                    TemplatePitchMCPSchema(
                        pitch_number=p.pitch_number,
                        height=p.height or 0,
                        anchor_location=p.anchor_location,
                        anchor_type=p.anchor_type,
                        did_rescue=p.did_rescue or False,
                        did_setup=p.did_setup or False,
                    )
                )

        # Build AI-friendly summary
        summary = f"Template: {template.name} ({template.template_type})"
        if template.region:
            summary += f" in {template.region}"
        if template.pitches:
            summary += f" with {len(template.pitches)} pitches"

        return ActivityTemplateMCPResponse(
            id=str(template.id),
            name=template.name,
            template_type=template.template_type,
            region=template.region,
            description=template.description,
            french_grade=template.french_grade,
            canyon_type=template.canyon_type,
            water_gauge_name=template.water_gauge_name,
            is_vertical=template.is_vertical,
            is_horizontal=template.is_horizontal,
            climbing_type=template.climbing_type,
            grade=template.grade,
            length=template.length,
            pitches=pitches,
            summary=summary,
        )

    @staticmethod
    def to_mcp_list_response(
        templates: list[ActivityTemplate],
    ) -> ActivityTemplateListMCPResponse:
        """Convert a list of templates to an MCP list response."""
        mcp_templates = [
            ActivityTemplateMCPConverter.to_mcp_response(t) for t in templates
        ]

        summary = f"Found {len(templates)} templates."

        return ActivityTemplateListMCPResponse(
            templates=mcp_templates,
            summary=summary,
        )


class GearItemMCPConverter:
    """Converter for gear item entities to AI-friendly MCP formats."""

    @staticmethod
    def to_mcp_response(
        gear_item: GearItem,
    ) -> GearItemMCPResponse:
        """Convert a gear item entity to an MCP response."""
        summary = f"Gear: {gear_item.name}"
        if gear_item.manufacturer:
            summary += f" by {gear_item.manufacturer}"
        if gear_item.model:
            summary += f" ({gear_item.model})"

        return GearItemMCPResponse(
            id=str(gear_item.id),
            name=gear_item.name,
            model=gear_item.model,
            serial_number=gear_item.serial_number,
            purchase_date=(
                gear_item.purchase_date.isoformat() if gear_item.purchase_date else None
            ),
            manufacturer=gear_item.manufacturer,
            summary=summary,
        )

    @staticmethod
    def to_mcp_list_response(
        gear_items: list[GearItem],
    ) -> GearItemListMCPResponse:
        """Convert a list of gear items to an MCP list response."""
        mcp_items = [GearItemMCPConverter.to_mcp_response(item) for item in gear_items]

        summary = f"Found {len(gear_items)} gear items."

        return GearItemListMCPResponse(
            gear_items=mcp_items,
            summary=summary,
        )
