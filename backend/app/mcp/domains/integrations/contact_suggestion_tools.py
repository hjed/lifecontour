"""MCP tools for contact suggestions.

Participant emails that integrations (such as Google Calendar) reported on at
least five of the user's journals, but that match no contact, are suggested as
contacts. These tools list them, accept one -- as a new contact or into an
existing one -- and manage the ignore list. The ``@transactional`` service
owns every commit; no tool opens a transaction.
"""

from datetime import datetime
from typing import Annotated

from core_shared.models.history import Provenance
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.services.contact_suggestion_service import (
    AcceptTarget,
    ContactSuggestionService,
    ExistingContactTarget,
    NewContactTarget,
    normalise_email,
)
from app.mcp.shared.annotations import ADDITIVE_WRITE, IDEMPOTENT_WRITE, READ_ONLY
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_contact_suggestion_service,
    get_current_user_id,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


class ContactSuggestionMCPEntry(BaseModel):
    email: str
    display_name: str | None
    event_count: int
    last_seen_at: datetime


class ContactSuggestionsMCPResponse(BaseModel):
    suggestions: list[ContactSuggestionMCPEntry]
    ignored_emails: list[str]
    total_count: int
    summary: str


class AcceptedContactSuggestionMCPResponse(BaseModel):
    email: str
    contact_id: int
    linked_journal_count: int
    summary: str


class IgnoredContactSuggestionMCPResponse(BaseModel):
    email: str
    ignored: bool
    was_ignored: bool | None = None
    summary: str


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_contact_suggestions", "contact")
async def list_contact_suggestions(
    user_id: str = mcp_depends(get_current_user_id),
    service: ContactSuggestionService = mcp_depends(get_contact_suggestion_service),
) -> str:
    """
    List people who keep appearing on the user's events but are not contacts.

    Each suggestion is a participant email seen on at least five of the user's
    journals (e.g. Google Calendar invites) that matches no contact, most-seen
    first, with the name integrations reported for it. Also returns the emails
    the user has ignored. Act on a suggestion with ``accept_contact_suggestion``
    or ``ignore_contact_suggestion``.
    """
    suggestions = await service.list_suggestions(user_id)
    ignored = await service.list_ignored(user_id)
    return MCPResponseBuilder.success_response(
        ContactSuggestionsMCPResponse(
            suggestions=[
                ContactSuggestionMCPEntry(
                    email=s.email,
                    display_name=s.display_name,
                    event_count=s.event_count,
                    last_seen_at=s.last_seen_at,
                )
                for s in suggestions
            ],
            ignored_emails=[i.email for i in ignored],
            total_count=len(suggestions),
            summary=(
                f"{len(suggestions)} contact suggestion(s); "
                f"{len(ignored)} email(s) ignored."
            ),
        )
    )


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("accept_contact_suggestion", "contact")
async def accept_contact_suggestion(
    email: Annotated[str, Field(description="The suggested email address")],
    contact_id: Annotated[
        int | None,
        Field(description="Add the email to this existing contact"),
    ] = None,
    first_name: Annotated[
        str | None,
        Field(description="Create a new contact with this first name"),
    ] = None,
    last_name: Annotated[
        str | None,
        Field(description="Last name for the new contact"),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    service: ContactSuggestionService = mcp_depends(get_contact_suggestion_service),
) -> str:
    """
    Make a suggested email a contact's and link it to past events.

    Pass exactly one of ``contact_id`` (add the email to that existing contact)
    or ``first_name`` (create a new contact, optionally with ``last_name``).
    The contact is then linked to every journal the email was seen on, with the
    attendance the integration reported, and the suggestion disappears.
    """
    if (contact_id is None) == (first_name is None or not first_name.strip()):
        return MCPResponseBuilder.validation_error_response(
            "contact_id",
            "Pass exactly one of contact_id (existing contact) or first_name "
            "(new contact).",
        )
    target: AcceptTarget = (
        ExistingContactTarget(contact_id=contact_id)
        if contact_id is not None
        else NewContactTarget(
            first_name=(first_name or "").strip(),
            last_name=(last_name or "").strip() or None,
        )
    )

    accepted = await service.accept(
        user_id,
        email,
        target,
        transaction=db_connection,
        provenance=Provenance.MCP,
    )
    saved_id = accepted.contact.id
    assert saved_id is not None  # a saved contact always has one
    normalised = normalise_email(email)
    return MCPResponseBuilder.success_response(
        AcceptedContactSuggestionMCPResponse(
            email=normalised,
            contact_id=saved_id,
            linked_journal_count=accepted.linked_journal_count,
            summary=(
                f"{normalised} now belongs to contact {saved_id}, linked to "
                f"{accepted.linked_journal_count} journal(s)."
            ),
        )
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("ignore_contact_suggestion", "contact")
async def ignore_contact_suggestion(
    email: Annotated[str, Field(description="The email never to suggest again")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    service: ContactSuggestionService = mcp_depends(get_contact_suggestion_service),
) -> str:
    """
    Stop suggesting an email as a contact. Idempotent and persistent;
    reversible with ``unignore_contact_suggestion``.
    """
    await service.ignore(
        user_id, email, transaction=db_connection, provenance=Provenance.MCP
    )
    normalised = normalise_email(email)
    return MCPResponseBuilder.success_response(
        IgnoredContactSuggestionMCPResponse(
            email=normalised,
            ignored=True,
            summary=f"{normalised} will no longer be suggested as a contact.",
        )
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("unignore_contact_suggestion", "contact")
async def unignore_contact_suggestion(
    email: Annotated[str, Field(description="The ignored email to restore")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    service: ContactSuggestionService = mcp_depends(get_contact_suggestion_service),
) -> str:
    """
    Let an ignored email be suggested as a contact again. Idempotent:
    restoring an email that was not ignored succeeds with ``was_ignored`` false.
    """
    was_ignored = await service.unignore(user_id, email, transaction=db_connection)
    normalised = normalise_email(email)
    return MCPResponseBuilder.success_response(
        IgnoredContactSuggestionMCPResponse(
            email=normalised,
            ignored=False,
            was_ignored=was_ignored,
            summary=(
                f"{normalised} can be suggested again."
                if was_ignored
                else f"{normalised} was not ignored; nothing to undo."
            ),
        )
    )


def register_contact_suggestion_tools(mcp: FastMCP[None]) -> None:
    """Register the contact-suggestion MCP tools with the FastMCP server."""
    mcp.add_tool(list_contact_suggestions)
    mcp.add_tool(accept_contact_suggestion)
    mcp.add_tool(ignore_contact_suggestion)
    mcp.add_tool(unignore_contact_suggestion)
