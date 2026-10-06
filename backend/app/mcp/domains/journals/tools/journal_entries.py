"""MCP tools for creating and updating journal entries.

Inputs are validated here, before anything is written; the composite write
itself — journal, types, type data, relationships and tags — belongs to
``JournalWriteService``, which owns the unit of work.
"""

from typing import Annotated, Any
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    ActivityTemplate,
    EventDateRange,
    Journal,
    JournalContactRelationshipType,
    JournalNotFoundError,
    JournalType,
    JournalValidationError,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.external_link_helpers import (
    ExternalLinkInfo,
)
from app.core.journal.adapters.sql.activity_template_repository import (
    SqlActivityTemplateRepository,
)
from app.core.journal.services.journal_enrichment_service import (
    JournalEnrichmentService,
)
from app.core.journal.services.journal_external_link_service import (
    JournalExternalLinkService,
)
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.template_application import (
    apply_template_to_type_data,
)
from app.mcp.domains.journals.converters import (
    JournalConverter,
)
from app.mcp.domains.journals.schemas import (
    JournalCreateRequest,
    JournalUpdateRequest,
    validate_type_data,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
    fetch_parent_journal,
)
from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    IDEMPOTENT_WRITE,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_journal_enrichment_service,
    get_journal_external_link_service,
    get_journal_write_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


def _external_links_preserved(
    before: list[ExternalLinkInfo], after: list[ExternalLinkInfo]
) -> bool | None:
    """Whether every pre-update link survived; None when there were none."""
    if not before:
        return None
    before_keys = {(link.source, link.external_id) for link in before}
    after_keys = {(link.source, link.external_id) for link in after}
    return before_keys <= after_keys


_NOTE_IMPLIED_CONTEXT = (
    "NOTE was requested alongside other types; NOTE is implicit (a journal with "
    "no typed data) so it is not stored separately and will not appear in types."
)


def _note_implied_context(requested_types: list[str] | None) -> str:
    """Explain why NOTE is absent when it was requested with other types."""
    if not requested_types:
        return ""
    names = {t.upper() for t in requested_types}
    if JournalType.NOTE.name in names and len(names) > 1:
        return _NOTE_IMPLIED_CONTEXT
    return ""


def _validate_contact_relationships(
    contact_relationships: list[dict[str, Any]],
) -> None:
    """
    Validate contact relationship inputs without any DB operations.

    Call this BEFORE any DB writes to ensure all inputs are valid.
    Raises ValueError with a clear message if any relationship has invalid
    or missing required fields, wrong types, or unrecognised enum values.
    """
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole

    valid_relationship_types = {t.name for t in JournalContactRelationshipType}

    for i, rel in enumerate(contact_relationships):
        if not isinstance(rel, dict):
            raise ValueError(
                f"contact_relationships[{i}]: expected a dict, got {type(rel).__name__}"
            )

        contact_id = rel.get("contact_id")
        relationship_type_str = rel.get("relationship_type")

        if not contact_id:
            raise ValueError(
                f"contact_relationships[{i}]: missing required field 'contact_id'"
            )
        if not isinstance(contact_id, int):
            raise ValueError(
                f"contact_relationships[{i}]: 'contact_id' must be an int, "
                f"got {type(contact_id).__name__}"
            )
        if not relationship_type_str:
            raise ValueError(
                f"contact_relationships[{i}]: missing required field 'relationship_type'"
            )
        if not isinstance(relationship_type_str, str):
            raise ValueError(
                f"contact_relationships[{i}]: 'relationship_type' must be a string, "
                f"got {type(relationship_type_str).__name__}"
            )
        if relationship_type_str.upper() not in valid_relationship_types:
            raise ValueError(
                f"contact_relationships[{i}]: invalid relationship_type "
                f"'{relationship_type_str}'. "
                f"Valid types are: {', '.join(sorted(valid_relationship_types))}"
            )

        status_raw = rel.get("status")
        if isinstance(status_raw, str):
            try:
                AttendeeStatus[status_raw.upper()]
            except KeyError:
                valid_statuses = {s.name for s in AttendeeStatus}
                raise ValueError(
                    f"contact_relationships[{i}]: invalid status '{status_raw}'. "
                    f"Valid statuses are: {', '.join(sorted(valid_statuses))}"
                ) from None

        role_raw = rel.get("role")
        if isinstance(role_raw, str):
            try:
                ContactEventRole[role_raw.upper()]
            except KeyError:
                valid_roles = {r.name for r in ContactEventRole}
                raise ValueError(
                    f"contact_relationships[{i}]: invalid role '{role_raw}'. "
                    f"Valid roles are: {', '.join(sorted(valid_roles))}"
                ) from None


def _to_service_relationships(
    contact_relationships: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalise the MCP flat relationship dicts to the JSON:API-nested shape.

    ``JournalWriteService._process_journal_contact_relationships`` (shared with
    the REST controllers) expects ``{"attributes": {...}}`` items with a string
    ``contact_id`` and an upper-cased ``relationship_type`` enum name. The MCP
    request uses flat ``{contact_id: int, relationship_type: str, ...}`` items,
    so we adapt them here at the call boundary rather than changing the shared
    helper's contract. Inputs are assumed already validated by
    :func:`_validate_contact_relationships`.
    """
    nested: list[dict[str, Any]] = []
    for rel in contact_relationships:
        attributes: dict[str, Any] = {
            "contact_id": str(rel["contact_id"]),
            "relationship_type": rel["relationship_type"].upper(),
        }
        if rel.get("status") is not None:
            attributes["status"] = rel["status"]
        if rel.get("role") is not None:
            attributes["role"] = rel["role"]
        nested.append({"attributes": attributes})
    return nested


async def _load_own_template(
    template_id: str,
    user_id: str,
    activity_template_repo: SqlActivityTemplateRepository,
) -> ActivityTemplate:
    """Load a template the caller owns, refusing anything they cannot use.

    Another user's template is reported as missing rather than forbidden: the
    caller has no way to tell it exists, and no way to act on the difference.
    """
    try:
        UUID(template_id)
    except ValueError as e:
        raise JournalValidationError(
            "template_id", f"Template ID {template_id!r} must be a valid UUID"
        ) from e

    template = await activity_template_repo.find_by_id(template_id)
    if template is None or template.user_id != user_id:
        raise JournalValidationError(
            "template_id",
            f"Template {template_id} not found. Call search_templates to list "
            "your templates.",
        )
    return template


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_journal_entry", "journal")
async def create_journal_entry(
    request: JournalCreateRequest,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    write_service: JournalWriteService = mcp_depends(get_journal_write_service),
    link_service: JournalExternalLinkService = mcp_depends(
        get_journal_external_link_service
    ),
    enrichment_service: JournalEnrichmentService = mcp_depends(
        get_journal_enrichment_service
    ),
) -> str:
    """
    Create a new journal entry with types, type-specific data, relationships, and tags.

    IMPORTANT: Call list_journal_types first if you are unsure which type names
    or type_data fields are valid. Invalid type names will be rejected.

    Creates a journal entry with support for multiple types, type-specific data
    (e.g. calendar_id for EVENT), contact relationships, and tags.
    Type dependencies are added automatically (e.g. BUSHWALKING adds
    OUTDOOR_ACTIVITY and FITNESS).

    For a trip down a known canyon, cave or climb, pass that activity template's
    id as ``template_id`` (find one with search_templates) instead of copying its
    pitches yourself: the journal records the template reference and is filled in
    with the template's standard pitches, the abseil counts derived from them,
    and the template's own type fields. Anything you also pass in ``type_data``
    wins over the template — your own ``pitches`` replace the template's, and the
    abseil counts are derived from whichever pitches are stored unless you set
    the counts yourself.

    Returns:
        JSON string containing AI-friendly journal information including:
        - Journal details (title, content, date range)
        - Types and type-specific data
        - Contact relationships
        - Tags
        - Contextual summary for AI understanding

    Raises:
        JournalValidationError: If validation fails
        ValueError: If invalid type/relationship_type/status/role values are provided
    """
    # No JSON parsing needed, FastMCP handles request model conversion directly

    # Get current user ID from auth context
    user_id = await get_current_user_id()

    # --- Validate ALL inputs upfront BEFORE any DB writes ---
    # This ensures ValueError is raised before the journal INSERT,
    # preventing partial data commits when the error handler catches it.
    valid_type_names = {t.name for t in JournalType}

    if request.types:
        invalid_types = [t for t in request.types if t.upper() not in valid_type_names]
        if invalid_types:
            raise ValueError(
                f"Invalid journal type(s): {', '.join(invalid_types)}. "
                f"Valid types are: {', '.join(sorted(valid_type_names))}"
            )

        # Enforce type_data requirements for GEAR_MAINTENANCE and GEAR_USAGE
        req_types_upper = {t.upper() for t in request.types}

        def has_non_empty_type_data(target_type: str) -> bool:
            if not request.type_data:
                return False
            for k, v in request.type_data.items():
                if k.upper() == target_type:
                    return bool(v)
            return False

        if "GEAR_MAINTENANCE" in req_types_upper and not has_non_empty_type_data(
            "GEAR_MAINTENANCE"
        ):
            raise ValueError(
                "Type GEAR_MAINTENANCE requires corresponding non-empty type_data to be provided"
            )
        if "GEAR_USAGE" in req_types_upper and not has_non_empty_type_data(
            "GEAR_USAGE"
        ):
            raise ValueError(
                "Type GEAR_USAGE requires corresponding non-empty type_data to be provided"
            )

    if request.type_data:
        invalid_type_data_keys = [
            k for k in request.type_data if k.upper() not in valid_type_names
        ]
        if invalid_type_data_keys:
            raise ValueError(
                f"Invalid type_data key(s): {', '.join(invalid_type_data_keys)}. "
                f"Valid types are: {', '.join(sorted(valid_type_names))}"
            )

    # Check every value against its type's write model before anything is
    # written, so a bad one is refused with the field named rather than
    # reaching the column (see validate_type_data).
    validated_type_data = validate_type_data(request.type_data)

    if request.contact_relationships:
        _validate_contact_relationships(request.contact_relationships)

    # Repositories are needed to resolve the template below, and to read back
    # enrichment data for the response.
    repos = create_journal_tool_repositories(db_connection)

    # A template contributes its standard pitches and its own type fields — the
    # same thing selecting one in the UI does (the abseil counts then follow from
    # the pitches, in AbseilingService). Resolved here, before any write, so an
    # unusable template_id creates no journal.
    type_data = validated_type_data
    # ``is not None`` rather than truthiness: an explicit empty string is a
    # malformed id, and must be refused rather than quietly creating an
    # untemplated journal.
    if request.template_id is not None:
        template = await _load_own_template(
            request.template_id, user_id, repos.activity_template_repo
        )
        type_data = apply_template_to_type_data(template, request.types, type_data)

    # --- All inputs validated, proceed with DB writes ---

    # Create journal entity
    journal = Journal(
        user_id=user_id,
        title=request.title,
        content=request.content,
        event_date_range=EventDateRange(
            start=request.event_date_range.start,
            end=request.event_date_range.end,
        ),
        parent_id=request.parent_id,
    )

    # Delegate the whole composite write (journal + types + type-data +
    # relationships + tags) to the @transactional service, which owns the commit
    # before the response is returned (issue #945/#967). This tool opens no
    # transaction itself.
    relationships = (
        _to_service_relationships(request.contact_relationships)
        if request.contact_relationships
        else None
    )
    created_journal = await write_service.create_journal(
        journal,
        request.types,
        type_data,
        relationships,
        db_connection,
        tags=request.tags,
        changed_by="mcp",
        source=Provenance.MCP,
    )

    # Ensure journal_id is not None (it should always be set after creation)
    if created_journal.id is None:
        msg = "Journal ID should be set after creation"
        raise ValueError(msg)
    journal_id = created_journal.id

    parent = await fetch_parent_journal(created_journal, repos.journal_repo, user_id)
    external_links = await link_service.links_for_journal(journal_id, user_id)

    # Convert to AI-friendly response
    response = JournalConverter.to_enriched_response(
        created_journal,
        await enrichment_service.enrich(journal_id, user_id),
        parent=parent,
        additional_context=_note_implied_context(request.types),
        external_links=external_links,
    )

    return MCPResponseBuilder.success_response(response)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_journal_entry", "journal")
async def update_journal_entry(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal to update")
    ],
    request: JournalUpdateRequest,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    write_service: JournalWriteService = mcp_depends(get_journal_write_service),
    link_service: JournalExternalLinkService = mcp_depends(
        get_journal_external_link_service
    ),
    enrichment_service: JournalEnrichmentService = mcp_depends(
        get_journal_enrichment_service
    ),
) -> str:
    """
    Update an existing journal entry with partial data.

    IMPORTANT: Call list_journal_types first if you are unsure which type names
    or type_data fields are valid. Invalid values will be rejected.

    Only provided fields are updated; omitted fields remain unchanged.
    When types, tags, or contact_relationships are provided they REPLACE all
    existing values (not merge). Types are expanded through their dependencies
    first, so re-typing (e.g. BUSHWALKING -> CANYONING) keeps the type_data of
    every type that remains, including shared dependencies such as FITNESS and
    its Strava link. Only genuinely dropped types lose data; the response lists
    them in ``types_removed`` and the populated fields lost in
    ``type_data_discarded``.

    To edit safely, pass the ``version`` from get_journal as
    ``expected_version``: the update is then refused, with nothing written, if
    the journal changed in between. The refusal carries ``current_version`` to
    retry with after re-reading.

    Returns:
        JSON string containing AI-friendly updated journal information

    Raises:
        JournalNotFoundError: If the journal with the given ID does not exist
        JournalValidationError: If validation fails
        PreconditionFailedError: If expected_version names a superseded version
        ValueError: If invalid type/relationship values provided
    """
    # No JSON parsing needed, FastMCP handles request model conversion directly

    # --- Validate ALL inputs upfront BEFORE any DB writes ---
    valid_type_names = {t.name for t in JournalType}

    if request.types is not None:
        invalid_types = [t for t in request.types if t.upper() not in valid_type_names]
        if invalid_types:
            raise ValueError(
                f"Invalid journal type(s): {', '.join(invalid_types)}. "
                f"Valid types are: {', '.join(sorted(valid_type_names))}"
            )

    if request.type_data is not None:
        invalid_type_data_keys = [
            k for k in request.type_data if k.upper() not in valid_type_names
        ]
        if invalid_type_data_keys:
            raise ValueError(
                f"Invalid type_data key(s): {', '.join(invalid_type_data_keys)}. "
                f"Valid types are: {', '.join(sorted(valid_type_names))}"
            )

    if request.contact_relationships is not None:
        _validate_contact_relationships(request.contact_relationships)

    # Check every value against its type's write model before anything is
    # written. The composite update reaches the type-data write down two
    # different branches and only one of them ran the domain's checks, so an
    # over-long value came back as a bare "Internal error" when ``types`` was
    # sent alongside it (see validate_type_data).
    validated_type_data = validate_type_data(request.type_data, partial=True)

    # --- All inputs validated, proceed with DB writes ---

    # Repositories are still needed to load the journal and read back enrichment
    # data for the response.
    repos = create_journal_tool_repositories(db_connection)

    # Get the existing journal, owner-scoped. Somebody else's is reported as
    # missing, exactly as the read and delete tools report it (#1267) — without
    # this the tool rewrote another user's journal and read it back in its own
    # success response.
    user_id = await get_current_user_id()
    existing_journal = await repos.journal_repo.find_by_id_for_user(
        journal_id, str(user_id)
    )
    if not existing_journal:
        raise JournalNotFoundError(journal_id)

    # Snapshot integration links so the response can state whether the update
    # preserved them (an agent cannot otherwise tell an omitted field from a
    # destroyed link).
    links_before = await link_service.links_for_journal(journal_id, user_id)

    # Apply the requested core-field changes to the loaded journal.
    if request.title is not None:
        existing_journal.title = request.title
    if request.content is not None:
        existing_journal.content = request.content
    if request.event_date_range is not None:
        existing_journal.event_date_range = EventDateRange(
            start=request.event_date_range.start,
            end=request.event_date_range.end,
        )

    if "parent_id" in request.model_fields_set:
        existing_journal.parent_id = request.parent_id

    # Delegate the whole composite update (core fields + replace-all types /
    # type-data / relationships / tags) to the @transactional service, which
    # owns the commit before the response (issue #945/#967). Tri-state: a field
    # left as None on the request is not touched; a provided list replaces all.
    relationships = (
        _to_service_relationships(request.contact_relationships)
        if request.contact_relationships is not None
        else None
    )
    update_result = await write_service.update_journal_composite(
        existing_journal,
        db_connection,
        types=request.types,
        type_data=validated_type_data,
        relationships=relationships,
        tags=request.tags,
        changed_by="mcp",
        source=Provenance.MCP,
        # Checked inside the service's unit of work, under the row lock, so a
        # stale version refuses before any part of the composite is written.
        expected_etags=(
            [request.expected_version] if request.expected_version is not None else None
        ),
    )
    updated_journal = update_result.journal

    parent = await fetch_parent_journal(updated_journal, repos.journal_repo, user_id)
    links_after = await link_service.links_for_journal(journal_id, user_id)
    links_preserved = _external_links_preserved(links_before, links_after)

    # Convert to AI-friendly response
    response = JournalConverter.to_enriched_response(
        updated_journal,
        await enrichment_service.enrich(journal_id, user_id),
        parent=parent,
        additional_context=_note_implied_context(request.types),
        external_links=links_after,
        external_links_preserved=links_preserved,
        types_removed=update_result.types_removed,
        type_data_discarded=update_result.type_data_discarded,
    )

    return MCPResponseBuilder.success_response(response)


def register_journal_entry_tools(mcp: FastMCP[None]) -> None:
    """Register the journal entries MCP tools with the FastMCP server."""
    mcp.add_tool(create_journal_entry)
    mcp.add_tool(update_journal_entry)
