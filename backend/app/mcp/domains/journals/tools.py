"""
Journal domain MCP tools.

Provides AI access to journal management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

import json
from datetime import datetime
from typing import Annotated, Any

import structlog
from dishka.integrations.starlette import FromDishka, inject
from fastmcp import FastMCP
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import Contact
from app.core.contacts.models.repositories import ContactRepository
from app.core.journal.models.calendar import Calendar
from app.core.journal.models.entities import Journal
from app.core.journal.models.exceptions import (
    JournalNotFoundError,
    JournalValidationError,
)
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_relationship_types import (
    JournalContactRelationshipType,
)
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.journal_types import JournalType
from app.core.journal.models.repositories import (
    CalendarInfoRepository,
    CalendarRepository,
    JournalContactRelationshipRepository,
    JournalRepository,
    JournalTagRepository,
    MoodDataRepository,
    PhotoAlbumDataRepository,
    PlanDataRepository,
    TravelDataRepository,
)
from app.core.journal.models.value_objects import EventDateRange
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.journals.converters import JournalConverter
from app.mcp.domains.journals.schemas import (
    JournalCreateRequest,
    JournalListResponse,
    JournalSearchResponse,
    JournalUpdateRequest,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.response_builders import MCPResponseBuilder

logger = structlog.get_logger()

# Configuration constants
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50


def _parse_iso_datetime(datetime_str: str) -> datetime:
    """
    Parse ISO 8601 datetime string, handling 'Z' suffix for UTC.

    Python's datetime.fromisoformat() doesn't accept 'Z' suffix, so we
    replace it with '+00:00' for UTC timezone.

    Args:
        datetime_str: ISO 8601 datetime string (e.g., "2024-01-15T14:00:00Z")

    Returns:
        Parsed datetime object with timezone info
    """
    # Replace 'Z' suffix with '+00:00' for UTC
    if datetime_str.endswith("Z"):
        datetime_str = datetime_str[:-1] + "+00:00"
    return datetime.fromisoformat(datetime_str)


def register_journal_tools(mcp: FastMCP[None]) -> None:
    """
    Register journal-related MCP tools with the FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools with
    """

    @mcp.tool
    @mcp_unified_error_handler("get_journal", "journal")
    @inject
    async def get_journal(
        journal_service: FromDishka[JournalService],
        journal_repo: FromDishka[JournalRepository],
        calendar_info_repo: FromDishka[CalendarInfoRepository],
        calendar_repo: FromDishka[CalendarRepository],
        mood_data_repo: FromDishka[MoodDataRepository],
        photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
        plan_data_repo: FromDishka[PlanDataRepository],
        travel_data_repo: FromDishka[TravelDataRepository],
        contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
        tag_repo: FromDishka[JournalTagRepository],
        contact_repo: FromDishka[ContactRepository],
        journal_id: Annotated[
            int, Field(description="The unique identifier of the journal")
        ],
        include_children: Annotated[
            bool,
            Field(
                default=False,
                description="Optional: Include child journals in the response",
            ),
        ] = False,
    ) -> str:
        """
        Get journal details by ID for AI analysis.

        Retrieves comprehensive journal information including title, content,
        types, type-specific data, contact relationships, tags, and calendar info.
        The response is formatted for AI consumption to help with journal management
        and decision making.

        Optionally includes child journals to help AI understand hierarchical
        journal organization.

        Args:
            journal_id: The unique identifier of the journal
            include_children: Optional flag to include child journals

        Returns:
            JSON string containing AI-friendly journal information including:
            - Basic journal details (title, content, date range)
            - Journal types and type-specific data
            - Contact relationships with relationship types
            - Tags assigned to the journal
            - Calendar information for EVENT type journals
            - Parent and child journal information
            - Contextual summary for AI understanding

        Raises:
            JournalNotFoundError: If the journal with the given ID does not exist
        """
        logger.info("MCP: Getting journal", journal_id=journal_id)

        # Fetch journal
        journal = await journal_repo.find_by_id(journal_id)
        if journal is None:
            raise JournalNotFoundError(journal_id)

        # Fetch enrichment data
        types, type_data, contacts, tags, calendar = await _enrich_journal_data(
            journal,
            calendar_info_repo,
            calendar_repo,
            mood_data_repo,
            photo_album_data_repo,
            plan_data_repo,
            travel_data_repo,
            contact_relationship_repo,
            tag_repo,
            contact_repo,
        )

        # Fetch parent if exists
        parent = None
        if journal.parent_id:
            parent = await journal_repo.find_by_id(journal.parent_id)

        # Fetch children if requested
        children = None
        if include_children:
            children = await journal_repo.get_children(journal_id)

        # Convert to AI-friendly response
        response = JournalConverter.to_journal_response(
            journal, types, type_data, contacts, tags, calendar, parent, children
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("search_journals", "search")
    @inject
    async def search_journals(
        search_service: FromDishka[SearchService],
        query: Annotated[str, Field(description="Search query for journals")],
        limit: Annotated[
            int, Field(description="Maximum number of results", ge=1, le=50)
        ] = 20,
        types: Annotated[
            list[str] | None, Field(description="Filter by journal types")
        ] = None,
    ) -> str:
        """
        Search journals using MeiliSearch for AI analysis.

        Performs full-text search across journal fields with highlighting,
        filtering, and AI-friendly result formatting.

        Args:
            query: Search query string
            limit: Maximum number of results to return (1-50)
            types: Optional list of journal types to filter by

        Returns:
            JSON string containing AI-friendly search results
        """
        logger.info("MCP: Searching journals", query=query, limit=limit, types=types)

        # Build filters
        filters = {}
        if types:
            filters["types"] = types

        # Perform search
        results = search_service.search_journals(
            query=query,
            filters=filters if filters else None,
            limit=limit,
            offset=0,
        )

        # Convert search hits to AI-friendly format
        search_results = []
        for hit in results["hits"]:
            search_result = JournalConverter.to_search_result(hit)
            search_results.append(search_result)

        # Create overall search summary
        total_hits = results.get("estimated_total_hits", 0)
        processing_time = results.get("processing_time_ms", 0)

        summary_parts = [
            f"Found {total_hits} journals matching '{query}'",
            f"Search completed in {processing_time}ms",
        ]

        if types:
            summary_parts.append(f"Filtered by types: {', '.join(types)}")

        search_summary = ". ".join(summary_parts) + "."

        # Create response
        response = JournalSearchResponse(
            results=search_results,
            query=query,
            total_hits=total_hits,
            processing_time_ms=processing_time,
            summary=search_summary,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("list_journals", "journal")
    @inject
    async def list_journals(
        journal_service: FromDishka[JournalService],
        journal_repo: FromDishka[JournalRepository],
        calendar_info_repo: FromDishka[CalendarInfoRepository],
        calendar_repo: FromDishka[CalendarRepository],
        mood_data_repo: FromDishka[MoodDataRepository],
        photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
        plan_data_repo: FromDishka[PlanDataRepository],
        travel_data_repo: FromDishka[TravelDataRepository],
        contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
        tag_repo: FromDishka[JournalTagRepository],
        contact_repo: FromDishka[ContactRepository],
        user_id: Annotated[str, Field(description="User ID to filter journals")],
        page: Annotated[int, Field(description="Page number", ge=1)] = 1,
        limit: Annotated[
            int, Field(description="Journals per page", ge=1, le=50)
        ] = DEFAULT_PAGE_SIZE,
    ) -> str:
        """
        List journals with pagination for AI analysis.

        Retrieves a paginated list of journals with AI-friendly formatting
        and contextual summaries for journal management.

        Args:
            user_id: User ID to filter journals
            page: Page number (starting from 1)
            limit: Number of journals per page (1-50)

        Returns:
            JSON string containing AI-friendly journal list
        """
        logger.info("MCP: Listing journals", user_id=user_id, page=page, limit=limit)

        # Calculate offset
        offset = (page - 1) * limit

        # Get journals with pagination
        journals = await journal_service.get_journals_paginated(
            user_id, offset=offset, limit=limit
        )
        total_count = await journal_repo.count_by_user(user_id)

        # Enrich each journal
        journal_responses = []
        for journal in journals:
            types, type_data, contacts, tags, calendar = await _enrich_journal_data(
                journal,
                calendar_info_repo,
                calendar_repo,
                mood_data_repo,
                photo_album_data_repo,
                plan_data_repo,
                travel_data_repo,
                contact_relationship_repo,
                tag_repo,
                contact_repo,
            )
            journal_response = JournalConverter.to_journal_response(
                journal, types, type_data, contacts, tags, calendar
            )
            journal_responses.append(journal_response)

        # Create overall summary
        total_pages = (total_count + limit - 1) // limit
        summary_parts = [
            f"Retrieved {len(journal_responses)} journals from page {page} of {total_pages}",
            f"Total journals in system: {total_count}",
        ]

        list_summary = ". ".join(summary_parts) + "."

        # Create response
        response = JournalListResponse(
            journals=journal_responses,
            total_count=total_count,
            page=page,
            limit=limit,
            summary=list_summary,
        )

        logger.info(
            "MCP: Journal list retrieved",
            page=page,
            limit=limit,
            journals_count=len(journal_responses),
            total_count=total_count,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("create_journal_entry", "management")
    @inject
    async def create_journal_entry(
        journal_service: FromDishka[JournalService],
        journal_repo: FromDishka[JournalRepository],
        calendar_info_repo: FromDishka[CalendarInfoRepository],
        calendar_repo: FromDishka[CalendarRepository],
        mood_data_repo: FromDishka[MoodDataRepository],
        photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
        plan_data_repo: FromDishka[PlanDataRepository],
        travel_data_repo: FromDishka[TravelDataRepository],
        contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
        tag_repo: FromDishka[JournalTagRepository],
        contact_repo: FromDishka[ContactRepository],
        connection: FromDishka[AsyncConnection],
        user_id: Annotated[str, Field(description="User ID creating the journal")],
        journal_data: Annotated[
            str, Field(description="JSON string with journal data")
        ],
    ) -> str:
        """
        Create a new journal entry for AI-managed journal keeping.

        Creates a new journal with validation and returns AI-friendly confirmation.
        Supports adding types, type-specific data, contact relationships, and tags.

        Args:
            user_id: User ID creating the journal
            journal_data: JSON string containing journal information

        Returns:
            JSON string containing AI-friendly journal creation confirmation
        """
        logger.info("MCP: Creating journal", user_id=user_id, journal_data=journal_data)

        # Parse journal data
        data = json.loads(journal_data)
        request = JournalCreateRequest(**data)

        # Parse event date range (handle 'Z' suffix for UTC)
        start_date = _parse_iso_datetime(request.event_date_range["start"])
        end_date = _parse_iso_datetime(request.event_date_range["end"])
        event_date_range = EventDateRange(start=start_date, end=end_date)

        # Create journal entity
        journal = Journal(
            user_id=user_id,
            title=request.title,
            content=request.content,
            event_date_range=event_date_range,
            parent_id=int(request.parent_id) if request.parent_id else None,
        )

        # Create the journal
        final_journal = await journal_service.create_journal(journal, connection)

        # Ensure journal was created with an ID
        if final_journal.id is None:
            raise JournalValidationError(
                "id", "Journal was not assigned an ID after creation"
            )

        # Add types if provided
        if request.types:
            for type_str in request.types:
                journal_type = JournalType(type_str.lower())
                await journal_service.add_type_to_journal(
                    final_journal.id, journal_type, connection
                )

        # Add contact relationships if provided
        if request.contact_relationships:
            for rel_data in request.contact_relationships:
                relationship = JournalContactRelationship(
                    journal_id=final_journal.id,
                    contact_id=int(rel_data["contact_id"]),
                    relationship_type=JournalContactRelationshipType(
                        rel_data["relationship_type"]
                    ),
                )
                await contact_relationship_repo.create(relationship)

        # Add tags if provided
        if request.tags:
            for tag_name in request.tags:
                # Try to find existing tag
                existing_tag = await tag_repo.find_by_name(tag_name)
                if existing_tag and existing_tag.id:
                    await tag_repo.assign_tag(final_journal.id, existing_tag.id)
                else:
                    # Create new tag
                    new_tag = JournalTag(name=tag_name)
                    saved_tag = await tag_repo.save(new_tag)
                    if saved_tag.id:
                        await tag_repo.assign_tag(final_journal.id, saved_tag.id)

        # Fetch enrichment data for response
        types, type_data, contacts, tags, calendar = await _enrich_journal_data(
            final_journal,
            calendar_info_repo,
            calendar_repo,
            mood_data_repo,
            photo_album_data_repo,
            plan_data_repo,
            travel_data_repo,
            contact_relationship_repo,
            tag_repo,
            contact_repo,
        )

        # Create AI-friendly response
        response = JournalConverter.to_journal_response(
            final_journal,
            types,
            type_data,
            contacts,
            tags,
            calendar,
            additional_context="Successfully created journal",
        )

        logger.info(
            "MCP: Journal created successfully",
            journal_id=final_journal.id,
            journal_title=final_journal.title,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("update_journal_entry", "management")
    @inject
    async def update_journal_entry(
        journal_service: FromDishka[JournalService],
        journal_repo: FromDishka[JournalRepository],
        calendar_info_repo: FromDishka[CalendarInfoRepository],
        calendar_repo: FromDishka[CalendarRepository],
        mood_data_repo: FromDishka[MoodDataRepository],
        photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
        plan_data_repo: FromDishka[PlanDataRepository],
        travel_data_repo: FromDishka[TravelDataRepository],
        contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
        tag_repo: FromDishka[JournalTagRepository],
        contact_repo: FromDishka[ContactRepository],
        connection: FromDishka[AsyncConnection],
        journal_data: Annotated[
            str, Field(description="JSON string with journal update data")
        ],
    ) -> str:
        """
        Update an existing journal entry for AI-managed journal maintenance.

        Updates an existing journal with validation and returns AI-friendly confirmation.
        Supports partial updates - only provided fields are updated.

        Args:
            journal_data: JSON string containing journal update information

        Returns:
            JSON string containing AI-friendly journal update confirmation
        """
        logger.info("MCP: Updating journal", journal_data=journal_data)

        # Parse journal data
        data = json.loads(journal_data)
        request = JournalUpdateRequest(**data)

        # Get existing journal
        existing_journal = await journal_repo.find_by_id(request.journal_id)
        if not existing_journal:
            raise JournalNotFoundError(request.journal_id)

        # Track changed fields
        changed_fields: dict[str, Any] = {}

        # Update fields if provided
        if request.title is not None:
            existing_journal.title = request.title
            changed_fields["title"] = request.title

        if request.content is not None:
            existing_journal.content = request.content
            changed_fields["content"] = request.content

        if request.event_date_range is not None:
            # Parse dates (handle 'Z' suffix for UTC)
            start_date = _parse_iso_datetime(request.event_date_range["start"])
            end_date = _parse_iso_datetime(request.event_date_range["end"])
            existing_journal.event_date_range = EventDateRange(
                start=start_date, end=end_date
            )
            changed_fields["event_date_range"] = {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
            }

        # Update the journal
        final_journal = await journal_service.update_journal(
            existing_journal, changed_fields, connection
        )

        # Fetch enrichment data for response
        types, type_data, contacts, tags, calendar = await _enrich_journal_data(
            final_journal,
            calendar_info_repo,
            calendar_repo,
            mood_data_repo,
            photo_album_data_repo,
            plan_data_repo,
            travel_data_repo,
            contact_relationship_repo,
            tag_repo,
            contact_repo,
        )

        # Create AI-friendly response
        response = JournalConverter.to_journal_response(
            final_journal,
            types,
            type_data,
            contacts,
            tags,
            calendar,
            additional_context="Successfully updated journal",
        )

        logger.info(
            "MCP: Journal updated successfully",
            journal_id=final_journal.id,
            journal_title=final_journal.title,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("delete_journal", "management")
    @inject
    async def delete_journal(
        journal_service: FromDishka[JournalService],
        journal_repo: FromDishka[JournalRepository],
        connection: FromDishka[AsyncConnection],
        journal_id: Annotated[
            int, Field(description="The unique identifier of the journal to delete")
        ],
        delete_children: Annotated[
            bool,
            Field(
                default=False,
                description="Whether to delete child journals (default: False, children become orphans)",
            ),
        ] = False,
    ) -> str:
        """
        Delete a journal entry for AI-managed journal cleanup.

        Deletes a journal with optional cascade deletion of children.
        By default, child journals become orphans (parent_id set to NULL).

        Args:
            journal_id: The unique identifier of the journal to delete
            delete_children: Whether to delete child journals (default: False)

        Returns:
            JSON string containing AI-friendly deletion confirmation
        """
        logger.info(
            "MCP: Deleting journal",
            journal_id=journal_id,
            delete_children=delete_children,
        )

        # Validate journal exists
        journal = await journal_repo.find_by_id(journal_id)
        if journal is None:
            raise JournalNotFoundError(journal_id)

        # Get children count for response
        children = await journal_repo.get_children(journal_id)
        children_count = len(children)

        # Handle children based on delete_children flag
        if delete_children and children_count > 0:
            # Delete all children first
            for child in children:
                if child.id:
                    await journal_service.delete_journal(child.id, connection)

        # Delete the journal
        await journal_service.delete_journal(journal_id, connection)

        # Build response message
        if delete_children and children_count > 0:
            message = f"Successfully deleted journal '{journal.title}' and {children_count} child journals"
        elif children_count > 0:
            message = f"Successfully deleted journal '{journal.title}'. {children_count} child journals are now orphans"
        else:
            message = f"Successfully deleted journal '{journal.title}'"

        from pydantic import BaseModel

        class DeleteResponse(BaseModel):
            success: bool
            message: str
            journal_id: str

        response = DeleteResponse(
            success=True, message=message, journal_id=str(journal_id)
        )

        logger.info(
            "MCP: Journal deleted successfully",
            journal_id=journal_id,
            children_count=children_count,
            delete_children=delete_children,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("get_contact_journals", "journal")
    @inject
    async def get_contact_journals(
        journal_repo: FromDishka[JournalRepository],
        calendar_info_repo: FromDishka[CalendarInfoRepository],
        calendar_repo: FromDishka[CalendarRepository],
        mood_data_repo: FromDishka[MoodDataRepository],
        photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
        plan_data_repo: FromDishka[PlanDataRepository],
        travel_data_repo: FromDishka[TravelDataRepository],
        contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
        tag_repo: FromDishka[JournalTagRepository],
        contact_repo: FromDishka[ContactRepository],
        contact_id: Annotated[
            int, Field(description="The unique identifier of the contact")
        ],
        relationship_type: Annotated[
            str | None,
            Field(
                default=None,
                description="Optional: Filter by relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)",
            ),
        ] = None,
        limit: Annotated[
            int, Field(description="Maximum number of journals", ge=1, le=50)
        ] = DEFAULT_PAGE_SIZE,
    ) -> str:
        """
        Get journals for a contact with optional relationship filtering.

        Retrieves all journals where the contact appears, optionally filtered
        by relationship type. Useful for understanding a contact's involvement
        in various journal entries.

        Args:
            contact_id: The unique identifier of the contact
            relationship_type: Optional relationship type filter
            limit: Maximum number of journals to return

        Returns:
            JSON string containing AI-friendly journal list for the contact
        """
        logger.info(
            "MCP: Getting journals for contact",
            contact_id=contact_id,
            relationship_type=relationship_type,
            limit=limit,
        )

        # Get relationships for contact
        all_relationships = await contact_relationship_repo.get_by_contact(contact_id)

        # Filter by relationship type if provided
        if relationship_type:
            rel_type = JournalContactRelationshipType(relationship_type)
            relationships = [
                rel for rel in all_relationships if rel.relationship_type == rel_type
            ]
        else:
            relationships = all_relationships

        # Get journals from relationships (limit to specified count)
        journal_responses = []
        for relationship in relationships[:limit]:
            journal = await journal_repo.find_by_id(relationship.journal_id)
            if journal:
                types, type_data, contacts, tags, calendar = await _enrich_journal_data(
                    journal,
                    calendar_info_repo,
                    calendar_repo,
                    mood_data_repo,
                    photo_album_data_repo,
                    plan_data_repo,
                    travel_data_repo,
                    contact_relationship_repo,
                    tag_repo,
                    contact_repo,
                )
                journal_response = JournalConverter.to_journal_response(
                    journal, types, type_data, contacts, tags, calendar
                )
                journal_responses.append(journal_response)

        # Get contact name for summary
        contact = await contact_repo.find_by_id(contact_id)
        contact_name = contact.get_full_name() if contact else f"Contact {contact_id}"

        # Create summary
        summary_parts = [f"Found {len(journal_responses)} journals for {contact_name}"]
        if relationship_type:
            summary_parts.append(f"with relationship type {relationship_type}")
        summary = ". ".join(summary_parts) + "."

        # Create response
        response = JournalListResponse(
            journals=journal_responses,
            total_count=len(relationships),
            page=1,
            limit=limit,
            summary=summary,
        )

        logger.info(
            "MCP: Contact journals retrieved",
            contact_id=contact_id,
            journals_count=len(journal_responses),
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("link_journal_to_contact", "management")
    @inject
    async def link_journal_to_contact(
        journal_repo: FromDishka[JournalRepository],
        contact_repo: FromDishka[ContactRepository],
        contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
        calendar_info_repo: FromDishka[CalendarInfoRepository],
        calendar_repo: FromDishka[CalendarRepository],
        mood_data_repo: FromDishka[MoodDataRepository],
        photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
        plan_data_repo: FromDishka[PlanDataRepository],
        travel_data_repo: FromDishka[TravelDataRepository],
        tag_repo: FromDishka[JournalTagRepository],
        journal_id: Annotated[
            int, Field(description="The unique identifier of the journal")
        ],
        contact_id: Annotated[
            int, Field(description="The unique identifier of the contact")
        ],
        relationship_type: Annotated[
            str,
            Field(
                description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"
            ),
        ],
    ) -> str:
        """
        Link a journal to a contact with a specific relationship type.

        Creates a relationship between a journal and a contact, specifying
        how the contact is related to the journal entry.

        Args:
            journal_id: The unique identifier of the journal
            contact_id: The unique identifier of the contact
            relationship_type: Type of relationship

        Returns:
            JSON string containing AI-friendly confirmation
        """
        logger.info(
            "MCP: Linking journal to contact",
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=relationship_type,
        )

        # Validate journal exists
        journal = await journal_repo.find_by_id(journal_id)
        if journal is None:
            raise JournalNotFoundError(journal_id)

        # Validate contact exists
        contact = await contact_repo.find_by_id(contact_id)
        if contact is None:
            raise JournalValidationError(
                "contact_id", f"Contact with ID {contact_id} not found"
            )

        # Create relationship
        rel_type = JournalContactRelationshipType(relationship_type)
        relationship = JournalContactRelationship(
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=rel_type,
        )
        await contact_relationship_repo.create(relationship)

        # Fetch enrichment data for response
        types, type_data, contacts, tags, calendar = await _enrich_journal_data(
            journal,
            calendar_info_repo,
            calendar_repo,
            mood_data_repo,
            photo_album_data_repo,
            plan_data_repo,
            travel_data_repo,
            contact_relationship_repo,
            tag_repo,
            contact_repo,
        )

        # Create AI-friendly response
        response = JournalConverter.to_journal_response(
            journal,
            types,
            type_data,
            contacts,
            tags,
            calendar,
            additional_context=f"Successfully linked to {contact.get_full_name()} as {relationship_type}",
        )

        logger.info(
            "MCP: Journal linked to contact successfully",
            journal_id=journal_id,
            contact_id=contact_id,
            relationship_type=relationship_type,
        )

        return MCPResponseBuilder.success_response(response)


async def _enrich_journal_data(
    journal: Journal,
    calendar_info_repo: CalendarInfoRepository,
    calendar_repo: CalendarRepository,
    mood_data_repo: MoodDataRepository,
    photo_album_data_repo: PhotoAlbumDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    contact_relationship_repo: JournalContactRelationshipRepository,
    tag_repo: JournalTagRepository,
    contact_repo: ContactRepository,
) -> tuple[
    list[str],
    dict[str, Any],
    list[tuple[JournalContactRelationship, Contact]],
    list[JournalTag],
    Calendar | None,
]:
    """
    Enrich journal with type data, contacts, tags, and calendar info.

    Args:
        journal: The journal to enrich
        calendar_info_repo: Calendar info repository
        calendar_repo: Calendar repository
        mood_data_repo: Mood data repository
        photo_album_data_repo: Photo album data repository
        plan_data_repo: Plan data repository
        travel_data_repo: Travel data repository
        contact_relationship_repo: Contact relationship repository
        tag_repo: Tag repository
        contact_repo: Contact repository

    Returns:
        Tuple of (types, type_data, contacts, tags, calendar)
    """
    types: list[str] = []
    type_data: dict[str, Any] = {}
    calendar = None

    # Ensure journal has an ID
    if journal.id is None:
        return types, type_data, [], [], calendar

    # Check for EVENT type
    calendar_info = await calendar_info_repo.find_by_journal_id(journal.id)
    if calendar_info:
        types.append("EVENT")
        calendar = await calendar_repo.find_by_id(calendar_info.calendar_id)
        type_data["EVENT"] = {
            "calendar_id": str(calendar_info.calendar_id),
            "start_time": (
                calendar_info.start_time.isoformat()
                if calendar_info.start_time
                else None
            ),
            "end_time": (
                calendar_info.end_time.isoformat() if calendar_info.end_time else None
            ),
            "is_all_day": calendar_info.is_all_day,
            "location": calendar_info.location,
            "sync_invitees": calendar_info.sync_invitees,
        }

    # Check for MOOD_RATING type
    mood_data = await mood_data_repo.find_by_journal_id(journal.id)
    if mood_data:
        types.append("MOOD_RATING")
        type_data["MOOD_RATING"] = {
            "mood_value": mood_data.mood_value,
            "mood_label": mood_data.mood_label,
            "energy_level": mood_data.energy_level,
        }

    # Check for PHOTO_ALBUM type
    photo_album_data = await photo_album_data_repo.find_by_journal_id(journal.id)
    if photo_album_data:
        types.append("PHOTO_ALBUM")
        type_data["PHOTO_ALBUM"] = {
            "immich_album_id": photo_album_data.immich_album_id,
        }

    # Check for PLAN type
    plan_data = await plan_data_repo.find_by_journal_id(journal.id)
    if plan_data:
        types.append("PLAN")
        documents = await plan_data_repo.get_documents(journal.id)
        type_data["PLAN"] = {
            "documents": [
                {
                    "id": str(doc.id),
                    "url": doc.url,
                    "title": doc.title,
                    "description": doc.description,
                    "order": doc.order,
                }
                for doc in documents
            ]
        }

    # Check for TRAVEL type
    travel_data = await travel_data_repo.find_by_journal_id(journal.id)
    if travel_data:
        types.append("TRAVEL")
        type_data["TRAVEL"] = {
            "flights": [
                {
                    "id": str(flight.id),
                    "flight_number": flight.flight_number,
                    "airline": flight.airline,
                    "departure_airport": flight.departure_airport,
                    "arrival_airport": flight.arrival_airport,
                }
                for flight in travel_data.flights
            ],
            "accommodations": [
                {
                    "id": str(acc.id),
                    "name": acc.name,
                    "address": acc.address,
                }
                for acc in travel_data.accommodations
            ],
            "transportation": [
                {
                    "id": str(trans.id),
                    "type": trans.type,
                    "details": trans.details,
                }
                for trans in travel_data.transportation
            ],
        }

    # If no types found, it's a NOTE
    if not types:
        types.append("NOTE")

    # Fetch contact relationships
    relationships = await contact_relationship_repo.get_by_journal(journal.id)
    contacts = []
    for relationship in relationships:
        contact = await contact_repo.find_by_id(relationship.contact_id)
        if contact:
            contacts.append((relationship, contact))

    # Fetch tags
    tags = await tag_repo.get_tags_for_journal(journal.id)

    return types, type_data, contacts, tags, calendar
