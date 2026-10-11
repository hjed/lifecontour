"""MCP tools linking journals to contacts."""

from typing import Annotated

from core_shared.models.journals import (
    JournalContactRelationship,
    JournalContactRelationshipType,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.services.journal_contact_service import JournalContactService
from app.mcp.domains.journals.schemas import (
    JournalSearchResponse,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
    journal_to_search_result,
)
from app.mcp.shared.annotations import (
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_journal_contact_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_contact_journals", "journal")
async def get_contact_journals(
    contact_id: Annotated[
        int, Field(description="The unique identifier of the contact")
    ],
    limit: Annotated[
        int,
        Field(
            default=20,
            description="Maximum number of results to return (default: 20)",
        ),
    ] = 20,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get journals associated with a contact.

    Retrieves journals that have relationships with the specified contact.
    Returns AI-friendly summaries.

    Args:
        contact_id: The unique identifier of the contact
        limit: Maximum number of results to return

    Returns:
        JSON string containing AI-friendly journal summaries

    Raises:
        ContactNotFoundError: If the contact with the given ID does not exist
    """
    # Create repositories
    contact_rel_repo = SqlJournalContactRelationshipRepository(db_connection)
    journal_repo = SqlJournalRepository(db_connection)

    # Get relationships
    relationships = await contact_rel_repo.get_by_contact(contact_id)

    # Get journals
    journals = []
    for rel in relationships[:limit]:
        journal = await journal_repo.find_by_id(rel.journal_id)
        if journal:
            journals.append(journal)

    # Convert to search results
    results = [journal_to_search_result(journal) for journal in journals]

    response = JournalSearchResponse(
        results=results,
        query=None,
        total_hits=len(results),
        processing_time_ms=0,
        summary=f"Found {len(results)} journal(s) for contact {contact_id}",
    )

    return MCPResponseBuilder.success_response(response)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("link_journal_to_contact", "journal")
async def link_journal_to_contact(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal")
    ],
    contact_id: Annotated[
        int, Field(description="The unique identifier of the contact")
    ],
    relationship_type: Annotated[
        str,
        Field(description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"),
    ],
    status: Annotated[
        str | None,
        Field(
            description="Attendee status: ATTENDING, ATTENDED, MAYBE, NO_REPLY, DECLINED"
        ),
    ] = None,
    role: Annotated[
        str | None,
        Field(description="Event role: ORGANISER, FACILITATOR_HELPER"),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    journal_contact_service: JournalContactService = mcp_depends(
        get_journal_contact_service
    ),
) -> str:
    """
    Link a journal to a contact with a specific relationship type.

    Creates a relationship between a journal and a contact.
    Returns confirmation response.

    Args:
        journal_id: The unique identifier of the journal
        contact_id: The unique identifier of the contact
        relationship_type: Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)

    Returns:
        JSON string containing relationship creation confirmation

    Raises:
        ValueError: If relationship is invalid, or if journal or contact do not exist.
    """
    # Validate relationship type
    try:
        relationship_enum = JournalContactRelationshipType[relationship_type.upper()]
    except KeyError as e:
        raise ValueError(f"Invalid relationship_type: {relationship_type}") from e

    # Parse status and role if present
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole

    status_enum, role_enum = None, None
    if status is not None:
        try:
            status_enum = AttendeeStatus[status.upper()]
        except KeyError as e:
            raise ValueError(f"Invalid status: {status}") from e

    if role is not None:
        try:
            role_enum = ContactEventRole[role.upper()]
        except KeyError as e:
            raise ValueError(f"Invalid role: {role}") from e

    # Create repositories
    repos = create_journal_tool_repositories(db_connection)

    # The journal is read owner-scoped: linking writes to it, so somebody else's
    # must be as unreachable here as it is through the read tools (#1267). The
    # contact is the service's to check, against the same owner: another user's
    # contact answers not-found exactly as a missing one does.
    user_id = await get_current_user_id()
    journal = await repos.journal_repo.find_by_id_for_user(journal_id, str(user_id))
    if not journal:
        raise ValueError(f"Could not find journal with ID {journal_id}")

    rel = JournalContactRelationship(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=relationship_enum,
        status=status_enum,
        role=role_enum,
    )

    import sqlalchemy.exc

    try:
        await journal_contact_service.add_contact_to_journal(
            rel, user_id=str(user_id), transaction=db_connection
        )
    except sqlalchemy.exc.IntegrityError as e:
        raise ValueError("Relationship already exists") from e

    class LinkResponse(BaseModel):
        journal_id: int
        contact_id: int
        relationship_type: str
        status: str | None
        role: str | None
        linked: bool
        summary: str

    response = LinkResponse(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=relationship_enum.value,
        status=status_enum.value if status_enum is not None else None,
        role=role_enum.value if role_enum is not None else None,
        linked=True,
        summary=f"Successfully linked journal {journal_id} to contact {contact_id} as {relationship_enum.value}",
    )

    return MCPResponseBuilder.success_response(response)


def register_journal_contact_tools(mcp: FastMCP[None]) -> None:
    """Register the contacts MCP tools with the FastMCP server."""
    mcp.add_tool(get_contact_journals)
    mcp.add_tool(link_journal_to_contact)
