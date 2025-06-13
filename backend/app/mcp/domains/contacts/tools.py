"""
Contact domain MCP tools.

Provides AI access to contact management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

import json
from typing import Annotated

import structlog
from dishka.integrations.starlette import FromDishka, inject
from fastmcp import FastMCP
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.entities import (
    Contact,
    ContactMethod,
    ContactNote,
    MethodType,
)
from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
)
from app.core.contacts.services import ContactService
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.contacts.schemas import (
    ContactCreateRequest,
    ContactListResponse,
    ContactSearchResponse,
)
from app.mcp.shared.converters import (
    ContactConverter,
    SearchResponseConverter,
    SearchResultProcessor,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.response_builders import MCPResponseBuilder

logger = structlog.get_logger()


def register_contact_tools(mcp: FastMCP[None]) -> None:
    """
    Register contact-related MCP tools with the FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools with
    """

    @mcp.tool
    @mcp_unified_error_handler("get_contact", "contact")
    @inject
    async def get_contact(
        contact_service: FromDishka[ContactService],
        contact_id: Annotated[
            int, Field(description="The unique identifier of the contact")
        ],
    ) -> str:
        """
        Get contact details by ID for AI analysis.

        Retrieves comprehensive contact information including name, contact methods,
        tags, and a contextual summary. The response is formatted for AI consumption
        to help with relationship management and decision making.

        Args:
            contact_id: The unique identifier of the contact

        Returns:
            JSON string containing AI-friendly contact information including:
            - Basic contact details (name, email, phone)
            - Associated tags for categorization
            - Contextual summary for AI understanding

        Raises:
            ContactNotFoundError: If the contact with the given ID does not exist
        """
        # Fetch contact data (contact_service is automatically injected)
        contact = await contact_service.get_contact_by_id(contact_id)

        if contact is None:
            raise ContactNotFoundError(contact_id)

        # Convert to AI-friendly response using converter
        response = ContactConverter.to_contact_response(contact)

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("search_contacts", "search")
    @inject
    async def search_contacts(
        search_service: FromDishka[SearchService],
        query: Annotated[str, Field(description="Search query for contacts")],
        limit: Annotated[
            int, Field(description="Maximum number of results", ge=1, le=50)
        ] = 20,
        tags: Annotated[list[str] | None, Field(description="Filter by tags")] = None,
    ) -> str:
        """
        Search contacts using MeiliSearch for AI analysis.

        Performs full-text search across contact fields with highlighting,
        filtering, and AI-friendly result formatting. Supports typo tolerance
        and faceted search for better AI understanding.

        Args:
            query: Search query string
            limit: Maximum number of results to return (1-50)
            tags: Optional list of tags to filter by

        Returns:
            JSON string containing AI-friendly search results including:
            - Matching contacts with highlighting
            - Search metadata and processing time
            - Available tags for further filtering
            - Contextual summary for AI understanding
        """
        # Build filters
        filters = {}
        if tags:
            filters["tags"] = tags

        # Perform search
        results = search_service.search_contacts(
            query=query,
            filters=filters if filters else None,
            limit=limit,
            offset=0,
        )

        # Convert search hits to AI-friendly format using shared processor
        search_results = SearchResultProcessor.process_contact_search_hits(
            results["hits"]
        )

        # Get available tags from facets
        available_tags = []
        facet_distribution = results.get("facet_distribution", {})
        if "tags" in facet_distribution:
            available_tags = list(facet_distribution["tags"].keys())

        # Create overall search summary using converter
        total_hits = results.get("estimated_total_hits", 0)
        processing_time = results.get("processing_time_ms", 0)

        search_summary = SearchResponseConverter.build_search_summary(
            query=query,
            total_hits=total_hits,
            processing_time_ms=processing_time,
            available_tags=available_tags,
            filters={"tags": tags} if tags else None,
        )

        # Create response
        response = ContactSearchResponse(
            results=search_results,
            query=query,
            total_hits=total_hits,
            processing_time_ms=processing_time,
            available_tags=available_tags,
            summary=search_summary,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("create_contact", "management")
    @inject
    async def create_contact(
        contact_service: FromDishka[ContactService],
        connection: FromDishka[AsyncConnection],
        contact_data: Annotated[
            str, Field(description="JSON string with contact data")
        ],
    ) -> str:
        """
        Create a new contact for AI-managed relationship building.

        Creates a new contact with validation and returns AI-friendly confirmation.
        Supports adding contact methods, tags, and initial notes.

        Args:
            contact_data: JSON string containing contact information with fields:
                - first_name (required): Contact's first name
                - last_name (optional): Contact's last name
                - middle_name (optional): Contact's middle name
                - nick_name (optional): Contact's nickname
                - email (optional): Primary email address
                - phone (optional): Primary phone number
                - tags (optional): List of tags to assign
                - notes (optional): Initial notes about the contact

        Returns:
            JSON string containing AI-friendly contact creation confirmation including:
            - Created contact details with assigned ID
            - Validation results and any warnings
            - Contextual summary for AI understanding
        """
        logger.info("MCP: Creating contact", contact_data=contact_data)

        # Parse contact data
        data = json.loads(contact_data)
        request = ContactCreateRequest(**data)

        # Create contact entity
        contact = Contact(
            first_name=request.first_name,
            last_name=request.last_name,
            middle_name=request.middle_name,
            nick_name=request.nick_name,
        )

        # Create the contact first
        saved_contact = await contact_service.create_contact(contact, connection)

        # Ensure contact was created with an ID
        if saved_contact.id is None:
            raise ContactValidationError(
                "id", "Contact was not assigned an ID after creation"
            )

        contact_id = saved_contact.id

        # Add contact methods if provided
        if request.email:
            email_method = ContactMethod(
                method_type=MethodType.EMAIL,
                value=request.email,
                contact_id=contact_id,
                is_primary=True,
            )
            await contact_service.add_contact_method(
                contact_id, email_method, connection
            )

        if request.phone:
            phone_method = ContactMethod(
                method_type=MethodType.PHONE,
                value=request.phone,
                contact_id=contact_id,
                is_primary=True,
            )
            await contact_service.add_contact_method(
                contact_id, phone_method, connection
            )

        # Add initial note if provided
        if request.notes:
            note = ContactNote(
                content=request.notes,
                contact_id=contact_id,
            )
            await contact_service.add_contact_note(contact_id, note, connection)

        # Reload contact to get all methods and relationships
        final_contact = await contact_service.get_contact_by_id(contact_id)
        if not final_contact:
            raise ContactValidationError("id", "Failed to reload created contact")

        # Create AI-friendly response using shared converter
        response = ContactConverter.to_contact_response(
            final_contact, additional_context="Successfully created contact"
        )

        logger.info(
            "MCP: Contact created successfully",
            contact_id=final_contact.id,
            contact_name=final_contact.get_full_name(),
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("list_contacts", "contact")
    @inject
    async def list_contacts(
        contact_service: FromDishka[ContactService],
        page: Annotated[int, Field(description="Page number", ge=1)] = 1,
        limit: Annotated[int, Field(description="Contacts per page", ge=1, le=50)] = 20,
    ) -> str:
        """
        List contacts with pagination for AI analysis.

        Retrieves a paginated list of contacts with AI-friendly formatting
        and contextual summaries for relationship management.

        Args:
            page: Page number (starting from 1)
            limit: Number of contacts per page (1-50)

        Returns:
            JSON string containing AI-friendly contact list including:
            - Paginated contact list with summaries
            - Pagination metadata
            - Overall context and insights
        """
        logger.info("MCP: Listing contacts", page=page, limit=limit)

        # Calculate offset
        offset = (page - 1) * limit

        # Get contacts with pagination
        contacts = await contact_service.get_contacts_paginated(limit, offset)
        total_count = await contact_service.get_contacts_count()

        # Convert to AI-friendly format using shared converter
        contact_responses = []
        for contact in contacts:
            contact_response = ContactConverter.to_contact_response(contact)
            contact_responses.append(contact_response)

        # Create overall summary
        total_pages = (total_count + limit - 1) // limit
        summary_parts = [
            f"Retrieved {len(contact_responses)} contacts from page {page} of {total_pages}",
            f"Total contacts in system: {total_count}",
        ]

        if contact_responses:
            # Add insights about the contacts
            all_tags: set[str] = set()
            for contact_response in contact_responses:
                all_tags.update(contact_response.tags)

            if all_tags:
                summary_parts.append(f"Tags represented: {', '.join(sorted(all_tags))}")

        list_summary = ". ".join(summary_parts) + "."

        # Create response
        response = ContactListResponse(
            contacts=contact_responses,
            total_count=total_count,
            page=page,
            limit=limit,
            summary=list_summary,
        )

        logger.info(
            "MCP: Contact list retrieved",
            page=page,
            limit=limit,
            contacts_count=len(contact_responses),
            total_count=total_count,
        )

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("global_search", "search")
    @inject
    async def global_search(
        search_service: FromDishka[SearchService],
        query: Annotated[
            str, Field(description="Global search query across all entities")
        ],
        limit: Annotated[
            int, Field(description="Maximum number of results", ge=1, le=50)
        ] = 20,
        entity_types: Annotated[
            list[str] | None,
            Field(description="Entity types to search (e.g., 'contact')"),
        ] = None,
    ) -> str:
        """
        Perform global search across all entity types for AI analysis.

        Searches across all available entity types (contacts, and future entities like
        journal entries, calendar events) with unified results and AI-friendly formatting.

        Args:
            query: Global search query string
            limit: Maximum number of results to return (1-50)
            entity_types: Optional list of entity types to search

        Returns:
            JSON string containing AI-friendly global search results including:
            - Unified search results across entity types
            - Search metadata and processing time
            - Available entity types for context
            - Contextual summary for AI understanding
        """
        logger.info(
            "MCP: Performing global search",
            query=query,
            limit=limit,
            entity_types=entity_types,
        )

        # Perform global search
        results = search_service.global_search(
            query=query,
            entity_types=entity_types,
            limit=limit,
            offset=0,
        )

        # Convert search results to AI-friendly format using shared converter
        response = SearchResponseConverter.to_global_search_response(
            results, additional_context="Global search completed successfully"
        )

        logger.info(
            "MCP: Global search completed",
            query=query,
            total_hits=results.get("estimated_total_hits", 0),
            processing_time_ms=results.get("processing_time_ms", 0),
        )

        return MCPResponseBuilder.success_response(response)
