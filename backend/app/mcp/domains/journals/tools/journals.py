"""MCP tools for reading, looking up and deleting journal entries.

``list_journal_types`` describes the types a journal can carry; the
``get_journal*`` tools return the full owner-scoped journal payload.
"""

import json
from typing import Annotated

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    JournalNotFoundError,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.link_sources import (
    journal_source_names,
    resolve_journal_source,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_enrichment_service import (
    JournalEnrichmentService,
)
from app.core.journal.services.journal_external_link_service import (
    JournalExternalLinkService,
)
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_type_metadata import describe_journal_types
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.mcp.domains.journals.converters import (
    JournalConverter,
)
from app.mcp.domains.journals.tools._shared import (
    fetch_parent_journal,
)
from app.mcp.shared.annotations import (
    DESTRUCTIVE_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_journal_enrichment_service,
    get_journal_external_link_service,
    get_outbox_event_publisher,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_journal_types", "journal")
async def list_journal_types() -> str:
    """
    List all valid journal types, their descriptions, dependencies, and type_data fields.

    Call this BEFORE create_journal_entry or update_journal_entry to discover
    valid type names, what type_data fields each type accepts, the unit each
    numeric field is stored in, and the allowed values of closed vocabularies
    (anchor types, canyon types, climbing types, pitch types, grades).

    Returns:
        JSON with all available journal types and their schemas
    """
    return json.dumps(describe_journal_types(), indent=2)


async def _build_journal_response(
    journal_id: int,
    user_id: str,
    db_connection: AsyncConnection,
    link_service: JournalExternalLinkService,
    enrichment_service: JournalEnrichmentService,
    *,
    include_children: bool = False,
) -> str:
    """Full owner-scoped journal payload shared by the get_journal* tools."""
    journal_repo = SqlJournalRepository(db_connection)

    journal = await journal_repo.find_by_id(journal_id)
    if not journal or str(journal.user_id) != str(user_id):
        raise JournalNotFoundError(journal_id)

    # Resolve the parent this journal hangs off, so a child created with a
    # parent_id reads back as one.
    parent = await fetch_parent_journal(journal, journal_repo, user_id)
    children = await journal_repo.get_children(journal_id) if include_children else None

    response = JournalConverter.to_enriched_response(
        journal,
        await enrichment_service.enrich(journal_id, user_id),
        parent=parent,
        children=children,
        external_links=await link_service.links_for_journal(journal_id, user_id),
    )

    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_journal", "journal")
async def get_journal(
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
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    link_service: JournalExternalLinkService = mcp_depends(
        get_journal_external_link_service
    ),
    enrichment_service: JournalEnrichmentService = mcp_depends(
        get_journal_enrichment_service
    ),
) -> str:
    """
    Get journal details by ID for AI analysis.

    Retrieves comprehensive journal information including title, content, types,
    type-specific data, contact relationships, tags, and a contextual summary.
    Optionally includes child journals.

    Args:
        journal_id: The unique identifier of the journal
        include_children: Optional flag to include child journals

    Returns:
        JSON string containing AI-friendly journal information including:
        - Journal details (title, content, date range)
        - Types and type-specific data
        - Contact relationships
        - Tags
        - Optional child journals
        - Contextual summary for AI understanding

    Raises:
        JournalNotFoundError: If the journal with the given ID does not exist
    """
    user_id = await get_current_user_id()
    return await _build_journal_response(
        journal_id,
        user_id,
        db_connection,
        link_service,
        enrichment_service,
        include_children=include_children,
    )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_journal_by_external_id", "journal")
async def get_journal_by_external_id(
    source: Annotated[
        str,
        Field(
            description="Integration source the id belongs to. One of: "
            + ", ".join(journal_source_names())
            + ". Any other value is rejected."
        ),
    ],
    external_id: Annotated[
        str,
        Field(
            description="The external system's identifier exactly as a journal's "
            "external_links report it: a Strava activity id ('16152597201'), a "
            "Google Calendar event id, an Immich album UUID, a Snipe-IT "
            "maintenance id, or (source 'snipeit') the Snipe-IT asset id of the "
            "gear checked out on the journal."
        ),
    ],
    include_children: Annotated[
        bool,
        Field(default=False, description="Optional: Include child journals"),
    ] = False,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    link_service: JournalExternalLinkService = mcp_depends(
        get_journal_external_link_service
    ),
    enrichment_service: JournalEnrichmentService = mcp_depends(
        get_journal_enrichment_service
    ),
) -> str:
    """
    Find the journal linked to an external system's record.

    Resolves ``(source, external_id)`` — e.g. ('strava', '16152597201') — to
    the user's journal and returns the same payload as get_journal. Use this
    instead of searching by title when you already hold an integration id.

    Raises:
        ValueError: If ``source`` is not a recognised integration source

    Returns a "Not found" error payload when no journal is linked to that id.
    """
    source_filter = resolve_journal_source(source)
    normalized_id = external_id.strip()
    if not normalized_id:
        raise ValueError("external_id must not be empty")

    user_id = await get_current_user_id()
    journal_id = await SqlJournalRepository(db_connection).find_id_by_external_id(
        user_id, source_filter, normalized_id
    )
    if journal_id is None:
        return MCPResponseBuilder.error_response(
            error_type="Not found",
            message=f"No journal is linked to {source_filter} id '{normalized_id}'",
            context={"source": source_filter, "external_id": normalized_id},
        )
    return await _build_journal_response(
        journal_id,
        user_id,
        db_connection,
        link_service,
        enrichment_service,
        include_children=include_children,
    )


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("delete_journal", "journal")
async def delete_journal(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal to delete")
    ],
    delete_children: Annotated[
        bool,
        Field(
            default=False,
            description="Optional: Delete child journals as well",
        ),
    ] = False,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    event_publisher: OutboxEventPublisher = mcp_depends(get_outbox_event_publisher),
) -> str:
    """
    Delete a journal entry.

    Deletes a journal entry and optionally its children.
    Returns confirmation response.

    Deletion is refused while any task is anchored to this journal as its
    creating or due journal — whatever that task's status, since a done task's
    link to the journal it was created in is part of the record. Cancel,
    complete or retarget those tasks first, or cancel the journal instead of
    deleting it. A journal a task merely mentions can be deleted; the mention
    goes with it and the task is unaffected.

    The refusal is resolvable without a UI: it comes back with
    ``code: "JOURNAL_HAS_ANCHORED_TASKS"``, an explanatory ``message``, the
    ``journal_id`` that could not be deleted, and a ``blocking_tasks`` list.
    Each entry gives the task's ``task_id``, ``text``, ``status`` and
    ``blocking_roles`` (``creating`` and/or ``due``) plus the
    ``action_journal_id`` and ``action_journal_title`` of the journal that
    surfaces it — normally the task's due journal, or its creating journal when
    the due journal is the one being deleted. Read that journal, deal with the
    task there, and retry.

    Args:
        journal_id: The unique identifier of the journal to delete
        delete_children: Optional flag to delete child journals

    Returns:
        JSON string containing deletion confirmation

    Raises:
        JournalNotFoundError: If the journal with the given ID does not exist
        JournalHasAnchoredTasksError: If a task is anchored to the journal
    """
    # Explicitly reject unsupported delete_children behavior to avoid silent misuse
    if delete_children:
        raise NotImplementedError(
            "The 'delete_children' flag is not yet supported. "
            "Child journals are not deleted automatically."
        )

    # Create repositories
    journal_repo = SqlJournalRepository(db_connection)
    contact_relationship_repo = SqlJournalContactRelationshipRepository(db_connection)

    # Somebody else's journal is reported as missing rather than refused, so
    # neither the deletion nor the explanation it can now return says anything
    # about a journal that is not yours. Same check as the read tool above.
    user_id = await get_current_user_id()
    journal = await journal_repo.find_by_id(journal_id)
    if not journal or str(journal.user_id) != str(user_id):
        raise JournalNotFoundError(journal_id)

    journal_service = JournalService(
        journal_repo,
        event_publisher,
        contact_relationship_repo,
        task_anchor_repo=SqlTaskAnchorRepository(db_connection),
    )

    # Delete journal
    await journal_service.delete_journal(
        journal_id, db_connection, changed_by="mcp", source=Provenance.MCP
    )

    class DeleteResponse(BaseModel):
        journal_id: int
        deleted: bool
        summary: str

    response = DeleteResponse(
        journal_id=journal_id,
        deleted=True,
        summary=f"Successfully deleted journal {journal_id}",
    )

    return MCPResponseBuilder.success_response(response)


def register_journal_read_tools(mcp: FastMCP[None]) -> None:
    """Register the journals MCP tools with the FastMCP server."""
    mcp.add_tool(list_journal_types)
    mcp.add_tool(get_journal)
    mcp.add_tool(get_journal_by_external_id)
    mcp.add_tool(delete_journal)
