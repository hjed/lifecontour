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
    Tag,
)
from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
)
from app.core.contacts.models.repositories import TagRepository
from app.core.contacts.models.value_objects import TagName
from app.core.contacts.services import ContactService
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.contacts.schemas import (
    ContactCreateRequest,
    ContactListResponse,
    ContactSearchResponse,
    ContactUpdateRequest,
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
        tag_repo: FromDishka[TagRepository],
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

        # Create contact entity with methods and notes
        contact = Contact(
            first_name=request.first_name,
            last_name=request.last_name,
            middle_name=request.middle_name,
            nick_name=request.nick_name,
        )

        # Add contact methods if provided
        if request.email:
            email_method = ContactMethod(
                method_type=MethodType.EMAIL,
                value=request.email,
                contact_id=0,  # Will be set when contact is saved
                is_primary=True,
            )
            contact.methods.append(email_method)

        if request.phone:
            phone_method = ContactMethod(
                method_type=MethodType.PHONE,
                value=request.phone,
                contact_id=0,  # Will be set when contact is saved
                is_primary=True,
            )
            contact.methods.append(phone_method)

        # Add initial note if provided
        if request.notes:
            note = ContactNote(
                content=request.notes,
                contact_id=0,  # Will be set when contact is saved
            )
            contact.notes.append(note)

        # Handle tags if provided - find or create tags by name
        if request.tags:
            for tag_name in request.tags:
                # Try to find existing tag by name
                existing_tag = await tag_repo.find_by_name(tag_name)

                if existing_tag:
                    # Use existing tag
                    contact.tags.append(existing_tag)
                else:
                    # Create new tag
                    new_tag = Tag(name=TagName(tag_name))
                    saved_tag = await tag_repo.save(new_tag)
                    contact.tags.append(saved_tag)

        # Create the contact with all methods, notes, and tags in a single transaction
        final_contact = await contact_service.create_contact(contact, connection)

        # Ensure contact was created with an ID
        if final_contact.id is None:
            raise ContactValidationError(
                "id", "Contact was not assigned an ID after creation"
            )

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
    @mcp_unified_error_handler("update_contact", "management")
    @inject
    async def update_contact(
        contact_service: FromDishka[ContactService],
        tag_repo: FromDishka[TagRepository],
        connection: FromDishka[AsyncConnection],
        contact_data: Annotated[
            str, Field(description="JSON string with contact update data")
        ],
    ) -> str:
        """
        Update an existing contact for AI-managed relationship maintenance.

        Updates an existing contact with validation and returns AI-friendly confirmation.
        Supports updating contact methods, tags, and adding notes. Uses replacement
        strategy for methods/addresses/notes - all existing ones are replaced with
        the provided ones.

        Args:
            contact_data: JSON string containing contact update information with fields:
                - contact_id (required): ID of the contact to update
                - first_name (optional): Updated first name
                - last_name (optional): Updated last name
                - middle_name (optional): Updated middle name
                - nick_name (optional): Updated nickname
                - email (optional): Updated primary email address
                - phone (optional): Updated primary phone number
                - tags (optional): Updated tags (replaces existing tags)
                - notes (optional): Additional notes to add

        Returns:
            JSON string containing AI-friendly contact update confirmation including:
            - Updated contact details with changes highlighted
            - Validation results and any warnings
            - Contextual summary for AI understanding
        """
        logger.info("MCP: Updating contact", contact_data=contact_data)

        # Parse contact data
        data = json.loads(contact_data)
        request = ContactUpdateRequest(**data)

        # Get existing contact
        existing_contact = await contact_service.get_contact_by_id(request.contact_id)
        if not existing_contact:
            raise ContactNotFoundError(request.contact_id)

        # Create updated contact entity with only changed fields
        updated_contact = Contact(
            id=request.contact_id,
            first_name=request.first_name or existing_contact.first_name,
            last_name=request.last_name or existing_contact.last_name,
            middle_name=request.middle_name or existing_contact.middle_name,
            nick_name=request.nick_name or existing_contact.nick_name,
        )

        # Add contact methods if provided (replacement strategy)
        if request.email:
            email_method = ContactMethod(
                method_type=MethodType.EMAIL,
                value=request.email,
                contact_id=request.contact_id,
                is_primary=True,
            )
            updated_contact.methods.append(email_method)

        if request.phone:
            phone_method = ContactMethod(
                method_type=MethodType.PHONE,
                value=request.phone,
                contact_id=request.contact_id,
                is_primary=True,
            )
            updated_contact.methods.append(phone_method)

        # Add additional note if provided
        if request.notes:
            note = ContactNote(
                content=request.notes,
                contact_id=request.contact_id,
            )
            updated_contact.notes.append(note)

        # Handle tags if provided - find or create tags by name (replacement strategy)
        if request.tags is not None:
            for tag_name in request.tags:
                # Try to find existing tag by name
                existing_tag = await tag_repo.find_by_name(tag_name)

                if existing_tag:
                    # Use existing tag
                    updated_contact.tags.append(existing_tag)
                else:
                    # Create new tag
                    new_tag = Tag(name=TagName(tag_name))
                    saved_tag = await tag_repo.save(new_tag)
                    updated_contact.tags.append(saved_tag)

        # Update the contact with all methods, notes, and tags in a single transaction
        final_contact = await contact_service.update_contact(
            updated_contact, connection
        )

        # Create AI-friendly response using shared converter
        response = ContactConverter.to_contact_response(
            final_contact, additional_context="Successfully updated contact"
        )

        logger.info(
            "MCP: Contact updated successfully",
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

    @mcp.tool
    @mcp_unified_error_handler("toggle_contact_favourite", "management")
    @inject
    async def toggle_contact_favourite(
        contact_service: FromDishka[ContactService],
        connection: FromDishka[AsyncConnection],
        contact_id: Annotated[
            int, Field(description="ID of the contact to toggle favourite status")
        ],
    ) -> str:
        """
        Toggle the favourite status of a contact for AI-managed relationship prioritization.

        Toggles whether a contact is marked as a favourite, which helps prioritize
        important contacts for quick access and AI analysis. Returns the updated
        contact information with the new favourite status.

        Args:
            contact_id: The ID of the contact to toggle favourite status

        Returns:
            JSON string containing AI-friendly contact information with updated favourite status including:
            - Updated contact details with new favourite status
            - Confirmation of the favourite status change
            - Contextual summary for AI understanding
        """
        logger.info("MCP: Toggling contact favourite status", contact_id=contact_id)

        try:
            # Toggle the favourite status
            updated_contact = await contact_service.toggle_contact_favourite(
                contact_id, connection
            )

            # Create AI-friendly response using shared converter
            favourite_status = (
                "favourite" if updated_contact.is_favourite else "not favourite"
            )
            response = ContactConverter.to_contact_response(
                updated_contact,
                additional_context=f"Contact favourite status updated - now marked as {favourite_status}",
            )

            logger.info(
                "MCP: Contact favourite status toggled successfully",
                contact_id=updated_contact.id,
                contact_name=updated_contact.get_full_name(),
                is_favourite=updated_contact.is_favourite,
            )

            return MCPResponseBuilder.success_response(response)

        except ContactNotFoundError as e:
            logger.warning(
                "MCP: Contact not found for favourite toggle",
                contact_id=contact_id,
                error=str(e),
            )
            raise ContactValidationError(
                "contact_id", f"Contact with ID {contact_id} not found"
            ) from e

    @mcp.tool
    @mcp_unified_error_handler("list_tags", "tag")
    @inject
    async def list_tags(
        tag_repo: FromDishka[TagRepository],
        limit: Annotated[
            int, Field(description="Maximum number of tags to return", ge=1, le=100)
        ] = 50,
    ) -> str:
        """
        List all available tags for AI-managed contact categorization.

        Retrieves all tags that can be used to categorize contacts, providing
        AI with a comprehensive view of available contact categories and
        organizational structures.

        Args:
            limit: Maximum number of tags to return (1-100, default: 50)

        Returns:
            JSON string containing AI-friendly tag information including:
            - List of all available tags with names and usage counts
            - Tag categorization suggestions for AI understanding
            - Contextual summary of the tag system
        """
        logger.info("MCP: Listing tags", limit=limit)

        try:
            # Get all tags from repository
            tags = await tag_repo.get_all(limit=limit)

            # Convert tags to AI-friendly format
            tag_data = []
            for tag in tags:
                tag_info = {
                    "id": str(tag.id) if tag.id else "unknown",
                    "name": tag.name.value,
                    "usage_count": 0,  # TODO: Add usage count when available
                    "description": f"Tag for categorizing contacts as '{tag.name.value}'",
                }
                tag_data.append(tag_info)

            # Build AI-friendly response
            response_data = {
                "tags": tag_data,
                "total_count": len(tag_data),
                "summary": f"Found {len(tag_data)} available tags for contact categorization. "
                f"Tags help organize contacts by relationship type, importance, or context.",
                "suggestions": [
                    "Use tags to categorize contacts by relationship (friend, work, family)",
                    "Create tags for contact importance (vip, important, regular)",
                    "Add context-specific tags (client, vendor, colleague, neighbor)",
                    "Consider activity-based tags (active, inactive, prospect)",
                ],
            }

            logger.info(
                "MCP: Tags listed successfully",
                tag_count=len(tag_data),
                limit=limit,
            )

            return MCPResponseBuilder.success_response(response_data)

        except Exception as e:
            logger.error(
                "MCP: Failed to list tags",
                error=str(e),
                limit=limit,
            )
            raise
