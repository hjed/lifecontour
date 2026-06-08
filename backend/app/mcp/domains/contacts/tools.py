"""
Contact domain MCP tools.

Provides AI access to contact management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

from typing import Annotated

import structlog
from core_shared.models.contacts.entities import (
    Contact,
    ContactMethod,
    ContactNote,
    ContactRelationship,
    ImportantDate,
    MethodType,
    RelationshipType,
    Tag,
)
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import Provenance, TagName
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
)
from app.core.contacts.models.repositories import TagRepository
from app.core.contacts.services import (
    ContactRelationshipService,
    ContactService,
    TagService,
)
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.contacts.schemas import (
    AddContactRelationshipRequest,
    ContactActionResponse,
    ContactCreateRequest,
    ContactListResponse,
    ContactRelationshipListResponse,
    ContactSearchResponse,
    ContactUpdateRequest,
    UpdateContactRelationshipRequest,
)
from app.mcp.shared.converters import (
    ContactConverter,
    ContactRelationshipConverter,
    SearchResponseConverter,
    SearchResultProcessor,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_contact_relationship_service,
    get_contact_service,
    get_current_user_id,
    get_immich_token_service,
    get_search_service,
    get_tag_repository,
    get_tag_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

logger = structlog.get_logger()

# Configuration constants
DEFAULT_HISTORY_LIMIT = 10


class TagInfo(BaseModel):
    """Information about a tag."""

    id: str
    name: str
    parent_id: int | None = None
    usage_count: int
    description: str


class TagListResponse(BaseModel):
    """Response for list_tags MCP tool."""

    tags: list[TagInfo]
    total_count: int
    summary: str
    suggestions: list[str]


def _convert_field_value(field_name: str, field_value: str) -> str | bool:
    """
    Convert field value to appropriate type based on field name.

    Args:
        field_name: Name of the field being updated
        field_value: String value to convert

    Returns:
        Converted value with appropriate type

    Raises:
        ContactValidationError: If the value cannot be converted to the expected type
    """
    # Boolean fields
    boolean_fields = {"is_favourite", "is_primary"}
    if field_name in boolean_fields:
        if field_value.lower() in ("true", "1", "yes"):
            return True
        elif field_value.lower() in ("false", "0", "no"):
            return False
        else:
            raise ContactValidationError(
                field_name,
                f"Field '{field_name}' expects a boolean value (true/false), got '{field_value}'",
            )

    # String fields - return as-is
    return field_value


def register_contact_tools(mcp: FastMCP[None]) -> None:
    """
    Register contact-related MCP tools with the FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools with
    """

    @mcp.tool
    @mcp_unified_error_handler("get_contact", "contact")
    async def get_contact(
        contact_id: Annotated[
            int, Field(description="The unique identifier of the contact")
        ],
        include_history: Annotated[
            bool,
            Field(
                default=False,
                description="Optional: Include field change history for the contact",
            ),
        ] = False,
        contact_service: ContactService = mcp_depends(get_contact_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Get contact details by ID for AI analysis.

        Retrieves comprehensive contact information including name, contact methods,
        tags, and a contextual summary. The response is formatted for AI consumption
        to help with relationship management and decision making.

        Optionally includes field change history to help AI understand how the contact
        information has evolved over time.

        Args:
            contact_id: The unique identifier of the contact
            include_history: Optional flag to include field change history

        Returns:
            JSON string containing AI-friendly contact information including:
            - Basic contact details (name, email, phone)
            - Associated tags for categorization
            - Contextual summary for AI understanding
            - Optional field change history if requested

        Raises:
            ContactNotFoundError: If the contact with the given ID does not exist
        """
        # Fetch contact data (contact_service is automatically injected)
        contact = await contact_service.get_contact_by_id(contact_id)

        if contact is None:
            raise ContactNotFoundError(contact_id)

        # Fetch external references for contact
        from app.core.integrations.external_link_helpers import (
            build_contact_external_links,
        )
        from app.mcp.domains.journals.schemas import ExternalLinkSchema

        external_references = (
            await contact_service.contact_repo.get_external_references(contact_id)
        )

        # Resolve the user's Immich server URL (no API-key decryption) so Immich
        # person references can be rendered as clickable links.
        user_id = await get_current_user_id()
        immich_token_service = await get_immich_token_service()
        immich_server_url = await immich_token_service.get_server_url(user_id)

        link_infos = build_contact_external_links(
            external_references=external_references,
            immich_server_url=immich_server_url,
        )
        external_links = [
            ExternalLinkSchema(
                source=link.source,
                url=link.url,
                external_id=link.external_id,
            )
            for link in link_infos
        ]

        # Convert to AI-friendly response using converter
        response = ContactConverter.to_contact_response(
            contact, external_links=external_links
        )

        # Add history context if requested
        if include_history:
            history = await contact_service.get_contact_history(
                contact_id, limit=DEFAULT_HISTORY_LIMIT
            )
            history_summary = (
                f"Recent changes: {len(history)} field updates recorded"
                if history
                else "No recent changes"
            )
            response.summary = f"{response.summary}\n\n{history_summary}"

        return MCPResponseBuilder.success_response(response)

    @mcp.tool
    @mcp_unified_error_handler("search_contacts", "search")
    async def search_contacts(
        query: Annotated[str, Field(description="Search query for contacts")],
        limit: Annotated[
            int, Field(description="Maximum number of results", ge=1, le=50)
        ] = 20,
        tags: Annotated[list[str] | None, Field(description="Filter by tags")] = None,
        search_service: SearchService = mcp_depends(get_search_service),
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
    async def create_contact(
        request: ContactCreateRequest,
        contact_service: ContactService = mcp_depends(get_contact_service),
        tag_repo: TagRepository = mcp_depends(get_tag_repository),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Create a new contact for AI-managed relationship building.

        Creates a new contact with validation and returns AI-friendly confirmation.
        Supports adding contact methods, tags, and initial notes.

        Returns:
            JSON string containing AI-friendly contact creation confirmation including:
            - Created contact details with assigned ID
            - Validation results and any warnings
            - Contextual summary for AI understanding
        """
        logger.info("MCP: Creating contact", request=request.model_dump())

        # Create contact entity with methods and notes
        contact = Contact(
            first_name=request.first_name,
            last_name=request.last_name,
            middle_name=request.middle_name,
            nick_name=request.nick_name,
            company=request.company,
            job_title=request.job_title,
            methods=[],
            addresses=[],
            notes=[],
            tags=[],
            important_dates=[],
        )

        # Add contact methods if provided
        if request.email:
            email_method = ContactMethod(
                method_type=MethodType.EMAIL,
                value=request.email,
                contact_id=0,  # Will be set when contact is saved
                is_primary=True,
            )
            assert contact.methods is not None
            contact.methods.append(email_method)

        if request.phone:
            phone_method = ContactMethod(
                method_type=MethodType.PHONE,
                value=request.phone,
                contact_id=0,  # Will be set when contact is saved
                is_primary=True,
            )
            assert contact.methods is not None
            contact.methods.append(phone_method)

        # Add initial note if provided
        if request.notes:
            note = ContactNote(
                content=request.notes,
                contact_id=0,  # Will be set when contact is saved
            )
            assert contact.notes is not None
            contact.notes.append(note)

        # Handle important dates if provided
        if request.important_dates:
            for date_data in request.important_dates:
                date_type_val = ImportantDateType(date_data.date_type)
                if date_type_val == ImportantDateType.CUSTOM:
                    raise ContactValidationError(
                        field="important_dates",
                        message="Custom important date types are not currently supported via MCP. "
                        "Please use a built-in date_type.",
                    )
                important_date = ImportantDate(
                    contact_id=0,
                    date_type=date_type_val,
                    precision=DatePrecision(date_data.precision),
                    year=date_data.year,
                    month=date_data.month,
                    day=date_data.day,
                    custom_date_type_id=None,  # Not supported directly via basic MCP structure easily without a lookup
                    custom_date_type_name=date_data.custom_type_name,
                )
                assert contact.important_dates is not None
                contact.important_dates.append(important_date)

        # Handle tags if provided - find or create tags by name
        if request.tags:
            for tag_name in request.tags:
                # Try to find existing tag by name
                existing_tag = await tag_repo.find_by_name(tag_name)

                if existing_tag:
                    # Use existing tag (add_tag handles dedup and limit)
                    contact.add_tag(existing_tag)
                else:
                    # Create new tag
                    new_tag = Tag(name=TagName(tag_name))
                    saved_tag = await tag_repo.save(new_tag)
                    contact.add_tag(saved_tag)

        # Create the contact with all methods, notes, and tags in a single transaction
        final_contact = await contact_service.create_contact(
            contact, connection, changed_by="mcp", source=Provenance.MCP
        )

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
    async def update_contact(
        request: ContactUpdateRequest,
        field_name: Annotated[
            str | None,
            Field(
                default=None,
                description="Optional: For field-level updates, specify the field name (first_name, last_name, middle_name, nick_name, is_favourite, or method/address/note field paths)",
            ),
        ] = None,
        field_value: Annotated[
            str | None,
            Field(
                default=None,
                description="Optional: For field-level updates, specify the new field value",
            ),
        ] = None,
        contact_service: ContactService = mcp_depends(get_contact_service),
        tag_repo: TagRepository = mcp_depends(get_tag_repository),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Update an existing contact for AI-managed relationship maintenance.

        Supports two update modes:
        1. Full contact update: Provide request object with multiple fields
        2. Field-level update: Provide field_name and field_value for single field updates

        Updates an existing contact with validation and returns AI-friendly confirmation.
        Supports updating contact methods, tags, and adding notes. Uses replacement
        strategy for methods/addresses/notes - all existing ones are replaced with
        the provided ones.



        Returns:
            JSON string containing AI-friendly contact update confirmation including:
            - Updated contact details with changes highlighted
            - Validation results and any warnings
            - Contextual summary for AI understanding
        """
        logger.info("MCP: Updating contact", request=request.model_dump())

        # Get existing contact
        existing_contact = await contact_service.get_contact_by_id(request.contact_id)
        if not existing_contact:
            raise ContactNotFoundError(request.contact_id)

        # Validate field-level update parameters
        if (field_name is None) != (field_value is None):
            # One is provided but not the other - this is an error
            raise ContactValidationError(
                "field_update",
                "Both field_name and field_value must be provided together for field-level updates",
            )

        # Handle field-level update if field_name and field_value are provided
        if field_name is not None and field_value is not None:
            logger.info(
                "MCP: Performing field-level update",
                contact_id=request.contact_id,
                field_name=field_name,
            )
            # Convert field_value to appropriate type based on field_name
            converted_value = _convert_field_value(field_name, field_value)
            await contact_service.update_contact_field(
                request.contact_id,
                field_name,
                converted_value,
                connection,
                changed_by="mcp",
                source=Provenance.MCP,
            )
            # Fetch updated contact for response
            final_contact = await contact_service.get_contact_by_id(request.contact_id)
            if not final_contact:
                raise ContactNotFoundError(request.contact_id)
        else:
            # Handle full contact update
            # Create updated contact entity with only changed fields
            updated_contact = Contact(
                id=request.contact_id,
                first_name=request.first_name or existing_contact.first_name,
                last_name=request.last_name or existing_contact.last_name,
                middle_name=request.middle_name or existing_contact.middle_name,
                nick_name=request.nick_name or existing_contact.nick_name,
                company=request.company
                if request.company is not None
                else existing_contact.company,
                job_title=request.job_title
                if request.job_title is not None
                else existing_contact.job_title,
                methods=None,
                addresses=None,
                notes=None,
                tags=None,
                important_dates=None,
            )

            # Add contact methods if provided (replacement strategy)
            if request.email:
                if updated_contact.methods is None:
                    updated_contact.methods = []
                email_method = ContactMethod(
                    method_type=MethodType.EMAIL,
                    value=request.email,
                    contact_id=request.contact_id,
                    is_primary=True,
                )
                updated_contact.methods.append(email_method)

            if request.phone:
                if updated_contact.methods is None:
                    updated_contact.methods = []
                phone_method = ContactMethod(
                    method_type=MethodType.PHONE,
                    value=request.phone,
                    contact_id=request.contact_id,
                    is_primary=True,
                )
                updated_contact.methods.append(phone_method)

            # Add additional note if provided
            if request.notes:
                if updated_contact.notes is None:
                    updated_contact.notes = []
                note = ContactNote(
                    content=request.notes,
                    contact_id=request.contact_id,
                )
                updated_contact.notes.append(note)

            # Handle important dates if provided (replacement strategy)
            if request.important_dates is not None:
                if updated_contact.important_dates is None:
                    updated_contact.important_dates = []
                for date_data in request.important_dates:
                    date_type_val = ImportantDateType(date_data.date_type)
                    if date_type_val == ImportantDateType.CUSTOM:
                        raise ContactValidationError(
                            field="important_dates",
                            message="Custom important date types are not currently supported via MCP. "
                            "Please use a built-in date_type.",
                        )
                    important_date = ImportantDate(
                        contact_id=request.contact_id,
                        date_type=date_type_val,
                        precision=DatePrecision(date_data.precision),
                        year=date_data.year,
                        month=date_data.month,
                        day=date_data.day,
                        custom_date_type_id=None,
                        custom_date_type_name=date_data.custom_type_name,
                    )
                    updated_contact.important_dates.append(important_date)

            # Handle tags if provided - find or create tags by name (replacement strategy)
            if request.tags is not None:
                if updated_contact.tags is None:
                    updated_contact.tags = []
                for tag_name in request.tags:
                    # Try to find existing tag by name
                    existing_tag = await tag_repo.find_by_name(tag_name)

                    if existing_tag:
                        # Use existing tag (add_tag handles dedup and limit)
                        updated_contact.add_tag(existing_tag)
                    else:
                        # Create new tag
                        new_tag = Tag(name=TagName(tag_name))
                        saved_tag = await tag_repo.save(new_tag)
                        updated_contact.add_tag(saved_tag)

            # Update the contact with all methods, notes, and tags in a single transaction
            final_contact = await contact_service.update_contact(
                updated_contact, connection, changed_by="mcp", source=Provenance.MCP
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
    async def list_contacts(
        page: Annotated[int, Field(description="Page number", ge=1)] = 1,
        limit: Annotated[int, Field(description="Contacts per page", ge=1, le=50)] = 20,
        contact_service: ContactService = mcp_depends(get_contact_service),
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
    async def global_search(
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
        search_service: SearchService = mcp_depends(get_search_service),
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
    async def toggle_contact_favourite(
        contact_id: Annotated[
            int, Field(description="ID of the contact to toggle favourite status")
        ],
        contact_service: ContactService = mcp_depends(get_contact_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
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
    @mcp_unified_error_handler("get_contact_relationships", "relationship")
    async def get_contact_relationships(
        contact_id: Annotated[
            int, Field(description="ID of the contact to list relationships for")
        ],
        relationship_service: ContactRelationshipService = mcp_depends(
            get_contact_relationship_service
        ),
    ) -> str:
        """
        List all relationships for a specific contact.

        Returns a list of all relationships associated with the contact, appropriately mapping the relationship type to match the perspective of the contact being checked.

        Args:
            contact_id: The ID of the contact to get relationships for

        Returns:
            JSON string containing the contact's relationships
        """
        logger.info("MCP: Getting contact relationships", contact_id=contact_id)

        try:
            relationships = await relationship_service.get_relationships_for_contact(
                contact_id
            )

            # Resolve the names of the "other" contact
            resolved_relationships = (
                await relationship_service.resolve_relationship_contact_names(
                    relationships, contact_id
                )
            )

            relationship_schemas = []
            for rel in resolved_relationships:
                relationship_schemas.append(
                    ContactRelationshipConverter.to_relationship_response(
                        rel, contact_id
                    )
                )

            response_data = ContactRelationshipListResponse(
                relationships=relationship_schemas,
                total_count=len(relationship_schemas),
                summary=f"Found {len(relationship_schemas)} relationships for this contact.",
            )

            logger.info(
                "MCP: Contact relationships retrieved successfully",
                contact_id=contact_id,
                count=len(relationship_schemas),
            )
            return MCPResponseBuilder.success_response(response_data)

        except ContactNotFoundError:
            raise
        except Exception as e:
            logger.error(
                "MCP: Failed to get contact relationships",
                error=str(e),
                contact_id=contact_id,
            )
            raise

    @mcp.tool
    @mcp_unified_error_handler("add_contact_relationship", "relationship")
    async def add_contact_relationship(
        request: AddContactRelationshipRequest,
        relationship_service: ContactRelationshipService = mcp_depends(
            get_contact_relationship_service
        ),
    ) -> str:
        """
        Add a new relationship between two contacts.

        Creates an association between two contacts.

        Args:
            request: Contact relationship creation details

        Returns:
            JSON string containing the newly created relationship
        """
        logger.info(
            "MCP: Adding contact relationship",
            contact_id=request.contact_id,
            target_contact_id=request.target_contact_id,
        )

        try:
            relationship_type = RelationshipType(request.relationship_type.lower())

            from typing import cast

            created_relationship = cast(
                ContactRelationship,
                await relationship_service.create_relationship(
                    from_contact_id=request.contact_id,
                    to_contact_id=request.target_contact_id,
                    relationship_type=relationship_type,
                ),
            )

            # Resolve names
            [
                resolved_rel
            ] = await relationship_service.resolve_relationship_contact_names(
                [created_relationship], request.contact_id
            )

            schema = ContactRelationshipConverter.to_relationship_response(
                resolved_rel, request.contact_id
            )

            logger.info(
                "MCP: Contact relationship added successfully",
                relationship_id=created_relationship.id,
            )
            return MCPResponseBuilder.success_response(schema)

        except Exception as e:
            logger.error(
                "MCP: Failed to add contact relationship",
                error=str(e),
                contact_id=request.contact_id,
            )
            raise

    @mcp.tool
    @mcp_unified_error_handler("update_contact_relationship", "relationship")
    async def update_contact_relationship(
        request: UpdateContactRelationshipRequest,
        relationship_service: ContactRelationshipService = mcp_depends(
            get_contact_relationship_service
        ),
    ) -> str:
        """
        Update an existing contact relationship.

        Changes the relationship type of an existing association. Resolves the correct relationship perspective automatically.

        Args:
            request: Contact relationship update details

        Returns:
            JSON string containing the updated relationship
        """
        logger.info(
            "MCP: Updating contact relationship",
            relationship_id=request.relationship_id,
        )

        try:
            rel_type = RelationshipType(request.relationship_type.lower())

            # Fetch the existing relationship to determine direction
            existing_relationship = await relationship_service.get_relationship_by_id(
                request.relationship_id
            )
            if not existing_relationship:
                raise ContactValidationError(
                    "relationship",
                    f"Relationship with ID {request.relationship_id} not found",
                )

            # Check that the request.contact_id is a participant in the relationship
            if (
                existing_relationship.from_contact_id != request.contact_id
                and existing_relationship.to_contact_id != request.contact_id
            ):
                raise ContactValidationError(
                    "relationship", "Relationship does not belong to the active contact"
                )

            # If we are updating from the perspective of the 'to_contact' (target),
            # the requested type is from target -> source, so we invert it for canonical storage (source -> target)
            if existing_relationship.to_contact_id == request.contact_id:
                rel_type = rel_type.get_inverse_type()

            updated_relationship = await relationship_service.update_relationship(
                relationship_id=request.relationship_id,
                relationship_type=rel_type,
            )

            [
                resolved_rel
            ] = await relationship_service.resolve_relationship_contact_names(
                [updated_relationship], request.contact_id
            )

            schema = ContactRelationshipConverter.to_relationship_response(
                resolved_rel, request.contact_id
            )

            logger.info(
                "MCP: Contact relationship updated successfully",
                relationship_id=updated_relationship.id,
            )
            return MCPResponseBuilder.success_response(schema)

        except Exception as e:
            logger.error(
                "MCP: Failed to update contact relationship",
                error=str(e),
                relationship_id=request.relationship_id,
            )
            raise

    @mcp.tool
    @mcp_unified_error_handler("remove_contact_relationship", "relationship")
    async def remove_contact_relationship(
        contact_id: Annotated[int, Field(description="ID of the current contact")],
        relationship_id: Annotated[
            int, Field(description="ID of the relationship to remove")
        ],
        relationship_service: ContactRelationshipService = mcp_depends(
            get_contact_relationship_service
        ),
    ) -> str:
        """
        Remove a relationship between two contacts.

        Deletes the specified relationship.

        Args:
            contact_id: The ID of the contact
            relationship_id: The ID of the relationship to remove

        Returns:
            Success message matching MCP conventions
        """
        logger.info(
            "MCP: Removing contact relationship", relationship_id=relationship_id
        )

        try:
            existing_relationship = await relationship_service.get_relationship_by_id(
                relationship_id
            )
            if not existing_relationship:
                raise ContactValidationError(
                    "relationship", f"Relationship with ID {relationship_id} not found"
                )

            # Verify it belongs to the contact
            if (
                existing_relationship.from_contact_id != contact_id
                and existing_relationship.to_contact_id != contact_id
            ):
                raise ContactValidationError(
                    "relationship", "Relationship does not belong to the active contact"
                )

            await relationship_service.delete_relationship(relationship_id)

            logger.info(
                "MCP: Contact relationship removed successfully",
                relationship_id=relationship_id,
            )

            response = ContactActionResponse(
                status="success",
                message=f"Relationship {relationship_id} successfully removed",
            )
            return MCPResponseBuilder.success_response(response)

        except Exception as e:
            logger.error(
                "MCP: Failed to remove contact relationship",
                error=str(e),
                relationship_id=relationship_id,
            )
            raise

    @mcp.tool
    @mcp_unified_error_handler("list_tags", "tag")
    async def list_tags(
        limit: Annotated[
            int, Field(description="Maximum number of tags to return", ge=1, le=100)
        ] = 50,
        tag_repo: TagRepository = mcp_depends(get_tag_repository),
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
            all_tags = await tag_repo.get_all()
            # Apply limit manually since repository doesn't support it
            tags = all_tags[:limit] if limit < len(all_tags) else all_tags

            # Convert tags to AI-friendly format
            tag_data = []
            for tag in tags:
                tag_info = TagInfo(
                    id=str(tag.id) if tag.id else "unknown",
                    name=tag.name.value,
                    parent_id=tag.parent_id,
                    usage_count=0,  # TODO: Add usage count when available
                    description=f"Tag for categorizing contacts as '{tag.name.value}'",
                )
                tag_data.append(tag_info)

            # Build AI-friendly response
            response_data = TagListResponse(
                tags=tag_data,
                total_count=len(tag_data),
                summary=f"Found {len(tag_data)} available tags for contact categorization. "
                f"Tags help organize contacts by relationship type, importance, or context.",
                suggestions=[
                    "Use tags to categorize contacts by relationship (friend, work, family)",
                    "Create tags for contact importance (vip, important, regular)",
                    "Add context-specific tags (client, vendor, colleague, neighbor)",
                    "Consider activity-based tags (active, inactive, prospect)",
                ],
            )

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

    @mcp.tool
    @mcp_unified_error_handler("merge_tags", "tag")
    async def merge_tags(
        source_id: Annotated[
            int, Field(description="ID of the source tag to merge and delete")
        ],
        target_id: Annotated[
            int, Field(description="ID of the target tag to merge into")
        ],
        tag_service: TagService = mcp_depends(get_tag_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Merge a source tag into a target tag.

        This will reassign all contacts associated with the source tag to the target tag,
        re-parent any child tags to the target tag, and then permanently delete the source tag.

        Args:
            source_id: The ID of the tag to merge and delete
            target_id: The ID of the tag to merge into

        Returns:
            Success message matching MCP conventions
        """
        logger.info("MCP: Merging tags", source_id=source_id, target_id=target_id)

        try:
            await tag_service.merge_tags(
                source_id=source_id, target_id=target_id, transaction=connection
            )

            response = ContactActionResponse(
                status="success",
                message=f"Tag {source_id} successfully merged into tag {target_id}",
            )
            return MCPResponseBuilder.success_response(response)

        except Exception as e:
            logger.error(
                "MCP: Failed to merge tags",
                error=str(e),
                source_id=source_id,
                target_id=target_id,
            )
            raise
