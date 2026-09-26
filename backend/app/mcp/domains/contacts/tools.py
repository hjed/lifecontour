"""
Contact domain MCP tools.

Provides AI access to contact management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
"""

from typing import Annotated, Any

import structlog
from core_shared.models.contacts.entities import (
    Contact,
    ContactMethod,
    ContactNote,
    ContactRelationship,
    ImportantDate,
    MethodType,
    RelationshipType,
)
from core_shared.models.contacts.exceptions import ContactValidationError
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from core_shared.models.contacts.value_objects import Provenance
from core_shared.models.date_window import (
    DEFAULT_UPCOMING_DAYS_AHEAD,
    MAX_UPCOMING_DAYS_AHEAD,
)
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
)
from app.core.contacts.models.repositories import TagRepository
from app.core.contacts.models.upcoming_dates import (
    UpcomingContactDate,
    UpcomingContactDates,
)
from app.core.contacts.services import (
    ContactRelationshipService,
    ContactService,
    TagService,
)
from app.core.contacts.services.contact_merge_service import ContactMergeService
from app.core.contacts.services.contact_subentity_sync import SubResourceMerge
from app.core.contacts.services.upcoming_important_dates_service import (
    UpcomingImportantDatesService,
)
from app.core.integrations.link_sources import (
    contact_source_names,
    resolve_contact_source,
)
from app.infrastructure.search.search_service import SearchService
from app.mcp.domains.contacts.schemas import (
    AddContactRelationshipRequest,
    ContactActionResponse,
    ContactCreateRequest,
    ContactFieldKind,
    ContactListResponse,
    ContactRelationshipListResponse,
    ContactSearchResponse,
    ContactUpdateRequest,
    UpcomingImportantDateResponse,
    UpcomingImportantDatesResponse,
    UpcomingImportantDatesWindow,
    UpdateContactRelationshipRequest,
)
from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.arguments import JsonBool
from app.mcp.shared.converters import (
    ContactConverter,
    ContactRelationshipConverter,
    SearchResponseConverter,
    SearchResultProcessor,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_contact_merge_service,
    get_contact_relationship_service,
    get_contact_service,
    get_current_user_id,
    get_immich_token_service,
    get_search_service,
    get_tag_repository,
    get_tag_service,
    get_upcoming_important_dates_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

logger = structlog.get_logger()

# Configuration constants
DEFAULT_HISTORY_LIMIT = 10


def _parse_contact_tag_id(field_name: str, raw_id: str) -> int:
    """Parse a contact tag ID from its MCP-boundary string form into an int.

    Contact tag IDs cross the MCP boundary as strings so they round-trip cleanly
    from read tools (``list_contact_tags``) into write tools, and match the
    stringified journal tag tools. The database and service layer key contact
    tags by int, so the tools convert here at the edge.

    Raises:
        ContactValidationError: if ``raw_id`` is not a valid integer id.
    """
    try:
        return int(raw_id)
    except TypeError, ValueError:
        raise ContactValidationError(
            field_name, f"must be a numeric tag ID, got {raw_id!r}"
        ) from None


class TagInfo(BaseModel):
    """Information about a tag."""

    id: str
    name: str
    parent_id: str | None = None
    usage_count: int
    description: str


class UpdatedTagInfo(BaseModel):
    """A contact tag as returned by update_contact_tag."""

    id: str
    name: str
    color: str | None = None
    description: str | None = None
    parent_id: str | None = None


class TagListResponse(BaseModel):
    """Response for list_contact_tags MCP tool."""

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


async def _build_contact_response(
    contact_id: int,
    contact: Contact,
    contact_service: ContactService,
    *,
    include_history: bool,
    include_archived: bool = False,
) -> str:
    """Full contact payload (links, summary, optional history) for get_contact*."""
    from app.core.integrations.external_link_helpers import (
        build_contact_external_links,
    )
    from app.mcp.domains.journals.schemas import ExternalLinkSchema

    external_references = await contact_service.get_external_references(contact_id)

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
        contact, external_links=external_links, include_archived=include_archived
    )

    # Add history context if requested
    if include_history:
        # ``user_id`` is resolved above for the Immich link; it is passed here
        # because this feed carries a linked task's rows and a task is owned
        # while a contact is not.
        history = await contact_service.get_contact_history(
            contact_id, limit=DEFAULT_HISTORY_LIMIT, reader_user_id=user_id
        )
        history_summary = (
            f"Recent changes: {len(history)} field updates recorded"
            if history
            else "No recent changes"
        )
        response.summary = f"{response.summary}\n\n{history_summary}"

    return MCPResponseBuilder.success_response(response)


def _upcoming_date_response(date: UpcomingContactDate) -> UpcomingImportantDateResponse:
    """One occurrence in the shape an agent reads.

    A transcription: the recurrence was resolved and the row was ranked before
    this is reached. The importance the row was ranked *by* is deliberately
    dropped — it is a ranking input, not something to report.
    """
    return UpcomingImportantDateResponse(
        contact_id=date.contact.id,
        contact_name=date.contact.display_name,
        date_type=date.occurrence.important_date.date_type.value,
        custom_date_type_name=date.occurrence.important_date.custom_date_type_name,
        occurs_on=date.occurrence.occurs_on,
        days_away=date.occurrence.days_away,
        years=date.occurrence.years,
        observed_for_leap_day=date.occurrence.observed_for_leap_day,
    )


def _upcoming_dates_summary(upcoming: UpcomingContactDates) -> str:
    """One line naming the window and what is in it.

    An empty window is described as the ordinary answer it is, so a model has no
    reason to read absence as a failure.
    """
    span = (
        f"{upcoming.window.first_day.isoformat()} to "
        f"{upcoming.window.last_day.isoformat()}"
    )
    if not upcoming.dates:
        return f"No important contact dates fall between {span}."

    soonest = upcoming.dates[0]
    return (
        f"{upcoming.total} important contact "
        f"{'date' if upcoming.total == 1 else 'dates'} between {span}. "
        f"Soonest: {soonest.contact.display_name} "
        f"in {soonest.occurrence.days_away} "
        f"{'day' if soonest.occurrence.days_away == 1 else 'days'}."
    )


_INCLUDE_ARCHIVED_DESC = (
    "Optional: also list archived emails, phones and addresses in "
    "contact_fields - values the person no longer uses, kept for reference"
)


def _require_contact_field(
    contact: Contact, kind: ContactFieldKind, field_id: int
) -> None:
    """Refuse an id that is not one of this contact's values of that kind."""
    if kind == "address":
        found = any(a.id == field_id for a in contact.addresses or [])
    else:
        found = any(
            m.id == field_id and m.method_type.value == kind
            for m in contact.methods or []
        )
    if not found:
        raise ContactValidationError(
            "field_id", f"No {kind} with id {field_id} found on contact {contact.id}"
        )


def register_contact_tools(mcp: FastMCP[None]) -> None:
    """
    Register contact-related MCP tools with the FastMCP server.

    Args:
        mcp: The FastMCP server instance to register tools with
    """

    @mcp.tool(annotations=READ_ONLY)
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
        include_archived: Annotated[
            JsonBool, Field(description=_INCLUDE_ARCHIVED_DESC)
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

        return await _build_contact_response(
            contact_id,
            contact,
            contact_service,
            include_history=include_history,
            include_archived=include_archived,
        )

    @mcp.tool(annotations=READ_ONLY)
    @mcp_unified_error_handler("get_contact_by_external_id", "contact")
    async def get_contact_by_external_id(
        source: Annotated[
            str,
            Field(
                description="Integration source the id belongs to. One of: "
                + ", ".join(contact_source_names())
                + ". Any other value is rejected."
            ),
        ],
        external_id: Annotated[
            str,
            Field(
                description="The external system's identifier exactly as a contact's "
                "external_links report it: a Google People resource name "
                "('people/c123') or an Immich person UUID."
            ),
        ],
        include_history: Annotated[
            bool,
            Field(default=False, description="Optional: Include field history"),
        ] = False,
        include_archived: Annotated[
            JsonBool, Field(description=_INCLUDE_ARCHIVED_DESC)
        ] = False,
        contact_service: ContactService = mcp_depends(get_contact_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Find the contact linked to an external system's record.

        Resolves ``(source, external_id)`` — e.g. ('google', 'people/c123') —
        to a contact and returns the same payload as get_contact.

        Raises:
            ValueError: If ``source`` is not a recognised contact integration

        Returns a "Not found" error payload when no contact is linked to that id.
        """
        normalized_source = resolve_contact_source(source)
        normalized_id = external_id.strip()
        if not normalized_id:
            raise ValueError("external_id must not be empty")

        contact = await contact_service.find_contact_by_external_reference(
            normalized_source, normalized_id, connection
        )
        if contact is None or contact.id is None:
            return MCPResponseBuilder.error_response(
                error_type="Not found",
                message=(
                    f"No contact is linked to {normalized_source} id '{normalized_id}'"
                ),
                context={"source": normalized_source, "external_id": normalized_id},
            )
        return await _build_contact_response(
            contact.id,
            contact,
            contact_service,
            include_history=include_history,
            include_archived=include_archived,
        )

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @mcp_unified_error_handler("merge_contacts", "contact")
    async def merge_contacts(
        survivor_contact_id: Annotated[
            int,
            Field(description="The ID of the contact to keep (the surviving contact)"),
        ],
        source_contact_id: Annotated[
            int,
            Field(description="The ID of the contact to absorb and delete"),
        ],
        overrides: Annotated[
            dict[str, Any] | None,
            Field(
                default=None,
                description=(
                    "Optional explicit per-field conflict resolution. Each key is "
                    "the concrete value to apply to the survivor (resolve the "
                    "survivor / source / custom choice before calling). Supported "
                    "keys: 'first_name', 'last_name', 'middle_name', 'nick_name', "
                    "'company', 'job_title', 'photo_url' (str), 'is_favourite' "
                    "(bool). Omitted fields default to survivor-wins / prefer "
                    "non-empty."
                ),
            ),
        ] = None,
        merge_service: ContactMergeService = mcp_depends(get_contact_merge_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Merge a source contact into a surviving contact.

        The survivor keeps its identity and gains the source's deduplicated
        aggregate: relationships, journal links, contact methods, addresses,
        notes, important dates, and tags. Scalar identity fields resolve
        survivor-wins / prefer-non-empty by default; pass ``overrides`` to keep
        the survivor value, take the source value, or supply a custom value per
        field. The source contact is deleted once the merge completes, and the
        survivor's AI summary is queued for regeneration.

        Args:
            survivor_contact_id: ID of the contact to keep
            source_contact_id: ID of the contact to absorb (deleted on success)
            overrides: Optional per-field conflict resolution overrides

        Returns:
            JSON string containing the unified surviving contact
        """
        merged = await merge_service.merge_contacts(
            survivor_contact_id,
            source_contact_id,
            transaction=connection,
            changed_by="mcp",
            source=Provenance.MCP,
            overrides=overrides,
        )

        response = ContactConverter.to_contact_response(merged)
        return MCPResponseBuilder.success_response(response)

    @mcp.tool(annotations=READ_ONLY)
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
            filters=filters or None,
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

    @mcp.tool(annotations=ADDITIVE_WRITE)
    @mcp_unified_error_handler("create_contact", "management")
    async def create_contact(
        request: ContactCreateRequest,
        contact_service: ContactService = mcp_depends(get_contact_service),
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

        # Create the contact, resolving any tag names (find-or-create) and writing
        # methods/notes/tags as one committed unit of work in the service layer
        # (issue #945). This tool opens no transaction itself — the
        # @transactional service owns the commit (see AGENTS.md "Transactions").
        final_contact = await contact_service.create_contact(
            contact,
            connection,
            changed_by="mcp",
            source=Provenance.MCP,
            tag_names=request.tags,
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

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
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
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Update an existing contact for AI-managed relationship maintenance.

        Supports two update modes:
        1. Full contact update: Provide request object with multiple fields
        2. Field-level update: Provide field_name and field_value for single field updates

        Updates an existing contact with validation and returns AI-friendly confirmation.
        Only what is supplied changes: ``email`` and ``phone`` edit the
        contact's primary method of that type and leave its other methods
        alone, ``notes`` adds a note beside the existing ones, ``tags``
        replaces the tag set, and ``important_dates`` is the contact's whole
        date list - a date of the same type as a stored one edits it in place,
        so its history shows what changed, and a stored date left out of the
        list is removed. Omit a field to leave it untouched.

        To edit safely, pass the ``version`` from get_contact as
        ``expected_version``: the update is then refused, with nothing written,
        if the contact changed in between. The refusal carries
        ``current_version`` to retry with after re-reading. This guards both
        update modes.



        Returns:
            JSON string containing AI-friendly contact update confirmation including:
            - Updated contact details with changes highlighted
            - Validation results and any warnings
            - Contextual summary for AI understanding
        """
        logger.info("MCP: Updating contact", request=request.model_dump())

        # Checked inside the service's unit of work, under the row lock, so a
        # stale version refuses before anything is written. Applies to both
        # update modes below.
        expected_etags = (
            [request.expected_version] if request.expected_version is not None else None
        )

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
                expected_etags=expected_etags,
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

            # The service treats a sub-resource list as the whole desired state,
            # so the email, phone and note are named as changes instead, and
            # the service applies them to the contact as it reads it under the
            # row lock. A list holding just the new email would delete the
            # phone beside it (#1524); one built from existing_contact would
            # delete anything added since that read.
            primary_methods: dict[MethodType, str] = {}
            if request.email:
                primary_methods[MethodType.EMAIL] = request.email
            if request.phone:
                primary_methods[MethodType.PHONE] = request.phone
            subresource_merge = SubResourceMerge(
                primary_methods=primary_methods,
                new_notes=[request.notes] if request.notes else [],
            )

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

            # Update the contact, resolving any tag names (replacement strategy:
            # request.tags replaces all existing tags; None leaves them untouched)
            # and writing everything as one committed unit of work in the service
            # layer (issue #945). This tool opens no transaction itself — the
            # @transactional service owns the commit (see AGENTS.md "Transactions").
            final_contact = await contact_service.update_contact(
                updated_contact,
                connection,
                changed_by="mcp",
                source=Provenance.MCP,
                tag_names=request.tags,
                expected_etags=expected_etags,
                subresource_merge=subresource_merge,
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

    @mcp.tool(annotations=READ_ONLY)
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

    @mcp.tool(annotations=READ_ONLY)
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

    @mcp.tool(annotations=ADDITIVE_WRITE)
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

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @mcp_unified_error_handler("set_contact_field_archived", "management")
    async def set_contact_field_archived(
        contact_id: Annotated[int, Field(description="ID of the contact")],
        kind: Annotated[
            ContactFieldKind,
            Field(description="Which kind of value field_id names"),
        ],
        field_id: Annotated[
            int,
            Field(
                description="The value's id, as get_contact's contact_fields lists it"
            ),
        ],
        archived: Annotated[
            JsonBool,
            Field(description="true to archive the value, false to restore it"),
        ],
        contact_service: ContactService = mcp_depends(get_contact_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Archive or restore one of a contact's emails, phones or addresses.

        Archive a value the person no longer uses - an old number, a childhood
        home - rather than deleting it: it is kept for reference and still
        matches the contact (e.g. calendar attendees, search), but it is removed
        from synced providers such as Google Contacts. Archiving the primary
        value also makes it no longer primary; restoring does not make it
        primary again. The change is recorded in the contact's history.

        Returns the contact as get_contact does with include_archived.
        """
        contact = await contact_service.get_contact_by_id(contact_id)
        if contact is None:
            raise ContactNotFoundError(contact_id)
        _require_contact_field(contact, kind, field_id)

        update_field = (
            contact_service.update_contact_address_field
            if kind == "address"
            else contact_service.update_contact_method_field
        )
        await update_field(
            contact_id,
            field_id,
            "is_archived",
            archived,
            connection,
            changed_by="mcp",
            source=Provenance.MCP,
        )

        updated = await contact_service.get_contact_by_id(contact_id)
        if updated is None:
            raise ContactNotFoundError(contact_id)
        return await _build_contact_response(
            contact_id,
            updated,
            contact_service,
            include_history=False,
            include_archived=True,
        )

    @mcp.tool(annotations=READ_ONLY)
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

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @mcp_unified_error_handler("add_contact_relationship", "relationship")
    async def add_contact_relationship(
        request: AddContactRelationshipRequest,
        relationship_service: ContactRelationshipService = mcp_depends(
            get_contact_relationship_service
        ),
        connection: AsyncConnection = mcp_depends(get_async_connection),
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
                    transaction=connection,
                    changed_by="mcp",
                    source=Provenance.MCP,
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

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @mcp_unified_error_handler("update_contact_relationship", "relationship")
    async def update_contact_relationship(
        request: UpdateContactRelationshipRequest,
        relationship_service: ContactRelationshipService = mcp_depends(
            get_contact_relationship_service
        ),
        connection: AsyncConnection = mcp_depends(get_async_connection),
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
                transaction=connection,
                changed_by="mcp",
                source=Provenance.MCP,
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

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @mcp_unified_error_handler("remove_contact_relationship", "relationship")
    async def remove_contact_relationship(
        contact_id: Annotated[int, Field(description="ID of the current contact")],
        relationship_id: Annotated[
            int, Field(description="ID of the relationship to remove")
        ],
        relationship_service: ContactRelationshipService = mcp_depends(
            get_contact_relationship_service
        ),
        connection: AsyncConnection = mcp_depends(get_async_connection),
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

            await relationship_service.delete_relationship(
                relationship_id,
                transaction=connection,
                changed_by="mcp",
                source=Provenance.MCP,
            )

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

    @mcp.tool(annotations=READ_ONLY)
    @mcp_unified_error_handler("list_contact_tags", "tag")
    async def list_contact_tags(
        limit: Annotated[
            int, Field(description="Maximum number of tags to return", ge=1, le=100)
        ] = 50,
        tag_repo: TagRepository = mcp_depends(get_tag_repository),
    ) -> str:
        """
        List all available tags for AI-managed contact categorization.

        Retrieves all tags that can be used to categorize contacts, providing
        AI with a comprehensive view of available contact categories and
        organizational structures. Contact tags are a separate namespace from
        journal tags — use list_journal_tags for those.

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
                    parent_id=(
                        str(tag.parent_id) if tag.parent_id is not None else None
                    ),
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

    @mcp.tool(annotations=IDEMPOTENT_WRITE)
    @mcp_unified_error_handler("update_contact_tag", "tag")
    async def update_contact_tag(
        tag_id: Annotated[str, Field(description="ID of the contact tag to update")],
        name: Annotated[
            str | None, Field(description="New tag name (must be unique)")
        ] = None,
        color: Annotated[
            str | None, Field(description="New hex colour code, e.g. #FF0000")
        ] = None,
        description: Annotated[
            str | None, Field(description="New description of what the tag is for")
        ] = None,
        parent_id: Annotated[
            str | None, Field(description="ID of the new parent tag")
        ] = None,
        move_to_root: Annotated[
            bool,
            Field(description="Clear the tag's parent, making it a root tag"),
        ] = False,
        tag_service: TagService = mcp_depends(get_tag_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Update an existing contact tag's name, colour, description, or parent.

        Contact tags are a separate namespace from journal tags — use
        update_journal_tag for those, and list_contact_tags to find tag IDs.

        Only the arguments you supply are changed; omitted arguments are left
        as they are. To move a tag to the root of the hierarchy, pass
        move_to_root=true rather than a null parent_id, since an omitted
        parent_id means "leave the parent alone".

        Args:
            tag_id: The ID of the tag to update
            name: New name; must not collide with another tag
            color: New hex colour code (7 characters, e.g. #FF0000)
            description: New description of what the tag is for
            parent_id: ID of the new parent tag
            move_to_root: Clear the parent instead of setting one

        Returns:
            JSON string containing the updated tag
        """
        logger.info("MCP: Updating contact tag", tag_id=tag_id)

        try:
            parsed_tag_id = _parse_contact_tag_id("tag_id", tag_id)
            parsed_parent_id = (
                _parse_contact_tag_id("parent_id", parent_id)
                if parent_id is not None
                else None
            )
            # The service owns the unit of work; MCP tools never open transactions.
            updated = await tag_service.update_tag(
                tag_id=parsed_tag_id,
                transaction=connection,
                name=name,
                color=color,
                description=description,
                parent_id=parsed_parent_id,
                set_parent_null=move_to_root,
            )

            response = UpdatedTagInfo(
                id=str(updated.id),
                name=updated.name.value,
                color=updated.color,
                description=updated.description,
                parent_id=(
                    str(updated.parent_id) if updated.parent_id is not None else None
                ),
            )
            return MCPResponseBuilder.success_response(response)

        except Exception as e:
            logger.error(
                "MCP: Failed to update contact tag", error=str(e), tag_id=tag_id
            )
            raise

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @mcp_unified_error_handler("delete_contact_tag", "tag")
    async def delete_contact_tag(
        tag_id: Annotated[str, Field(description="ID of the contact tag to delete")],
        tag_service: TagService = mcp_depends(get_tag_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Delete a contact tag, removing it from every contact it is assigned to.

        Contact tags are a separate namespace from journal tags — use
        delete_journal_tag for those, and list_contact_tags to find tag IDs.

        This is not blocked when the tag is in use: contacts are kept and simply
        lose this tag. Any child tags of the deleted tag are re-parented to the
        root of the hierarchy rather than being deleted.

        Args:
            tag_id: The ID of the tag to delete

        Returns:
            JSON string confirming the deletion
        """
        logger.info("MCP: Deleting contact tag", tag_id=tag_id)

        try:
            parsed_tag_id = _parse_contact_tag_id("tag_id", tag_id)
            # The service owns the unit of work; MCP tools never open transactions.
            await tag_service.delete_tag(tag_id=parsed_tag_id, transaction=connection)

            response = ContactActionResponse(
                status="success",
                message=(f"Tag {parsed_tag_id} deleted and removed from all contacts"),
            )
            return MCPResponseBuilder.success_response(response)

        except Exception as e:
            logger.error(
                "MCP: Failed to delete contact tag", error=str(e), tag_id=tag_id
            )
            raise

    @mcp.tool(annotations=DESTRUCTIVE_WRITE)
    @mcp_unified_error_handler("merge_contact_tags", "tag")
    async def merge_contact_tags(
        source_id: Annotated[
            str, Field(description="ID of the source tag to merge and delete")
        ],
        target_id: Annotated[
            str, Field(description="ID of the target tag to merge into")
        ],
        tag_service: TagService = mcp_depends(get_tag_service),
        connection: AsyncConnection = mcp_depends(get_async_connection),
    ) -> str:
        """
        Merge a source contact tag into a target contact tag.

        Contact tags are a separate namespace from journal tags — use
        merge_journal_tag for those, and list_contact_tags to find tag IDs.

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
            parsed_source_id = _parse_contact_tag_id("source_id", source_id)
            parsed_target_id = _parse_contact_tag_id("target_id", target_id)
            await tag_service.merge_tags(
                source_id=parsed_source_id,
                target_id=parsed_target_id,
                transaction=connection,
            )

            response = ContactActionResponse(
                status="success",
                message=(
                    f"Tag {parsed_source_id} successfully merged "
                    f"into tag {parsed_target_id}"
                ),
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

    @mcp.tool(annotations=READ_ONLY)
    @mcp_unified_error_handler("list_upcoming_important_dates", "contact")
    async def list_upcoming_important_dates(
        days_ahead: Annotated[
            int,
            Field(
                ge=0,
                le=MAX_UPCOMING_DAYS_AHEAD,
                description=(
                    "How many days beyond today to include. Zero is today "
                    "alone. Leave it out for the usual week."
                ),
            ),
        ] = DEFAULT_UPCOMING_DAYS_AHEAD,
        upcoming_dates_service: UpcomingImportantDatesService = mcp_depends(
            get_upcoming_important_dates_service
        ),
    ) -> str:
        """
        List the important contact dates coming up: birthdays and anniversaries.

        The window runs from **today** to ``days_ahead`` days ahead, **inclusive
        at both ends**, and defaults to **seven** days — the same window the
        user's own home dashboard shows, so your answer and their screen agree.
        It is anchored on today in **their timezone**, and every date comes back
        already resolved into that window: do not compute the window, the day
        boundaries or "how many days away" from a timestamp yourself.

        **A recurring date is resolved, not reported as stored.** ``occurs_on``
        is the day it falls on *this* time round, so a birthday recorded in 1991
        comes back on this year's day. ``years`` is what that makes — an age for
        a birthday, a count for an anniversary — and is **null** when there is
        no answer, because the date was recorded without a year or with one
        after the occurrence. Say the bare type in that case rather than working
        a number out from anything else.

        **29 February is observed on the 28th** in a year that has no 29th. When
        that happens ``observed_for_leap_day`` is true and ``occurs_on`` is a
        stand-in rather than the day the user wrote down, which is worth saying
        out loud rather than reporting a date they will not recognise.

        Every kind of date participates, including ones the user named
        themselves — for those, ``custom_date_type_name`` is what to call it. A
        date recorded as a year alone has no day to place and so is never here.

        The order is soonest first and, within a day, the contact who matters
        most to the user first. That ranking is inferred from their own
        behaviour; there is no importance setting behind it and nothing to
        report about it.

        The whole window comes back in one answer and is **not paginated**:
        there is no second page to ask for, and an **empty** list is an ordinary
        answer — a quiet week — rather than a failure or a reason to retry.

        Args:
            days_ahead: How far ahead to look, 0 to 90, defaulting to 7.

        Returns:
            JSON string with a window object naming start_date, end_date and
            days_ahead; a total_count; and dates, each with the contact's id and
            name, the date type, occurs_on, days_away, years and
            observed_for_leap_day.
        """
        user_id = await get_current_user_id()

        logger.info(
            "MCP: Listing upcoming important dates",
            user_id=user_id,
            days_ahead=days_ahead,
        )

        upcoming = await upcoming_dates_service.upcoming_dates(
            user_id, days_ahead=days_ahead
        )

        return MCPResponseBuilder.success_response(
            UpcomingImportantDatesResponse(
                window=UpcomingImportantDatesWindow(
                    start_date=upcoming.window.first_day,
                    end_date=upcoming.window.last_day,
                    days_ahead=upcoming.window.days_ahead,
                ),
                total_count=upcoming.total,
                dates=[_upcoming_date_response(date) for date in upcoming.dates],
                summary=_upcoming_dates_summary(upcoming),
            )
        )
