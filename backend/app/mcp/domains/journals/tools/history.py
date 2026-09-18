"""MCP tool returning a journal's field-level change history."""

from datetime import datetime
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.history.adapters.sql.field_history_repository import (
    SqlFieldHistoryRepository,
)
from app.core.history.models import FieldHistoryEntry
from app.core.history.services.journal_history_service import JournalHistoryService
from app.mcp.domains.journals.schemas import (
    JournalHistoryEntry,
    JournalHistoryResponse,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
)
from app.mcp.shared.annotations import (
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


def _journal_history_entry_to_schema(
    entry: FieldHistoryEntry,
) -> JournalHistoryEntry:
    """Map a domain ``FieldHistoryEntry`` to the MCP schema.

    Mirrors the REST ``HistoryConverter`` value coercion (Provenance enum →
    string, ISO string → datetime) so the MCP tool returns exactly the same
    field-level detail and provenance the UI shows.
    """
    created_at: datetime | None = None
    if entry.created_at:
        if isinstance(entry.created_at, str):
            try:
                created_at = datetime.fromisoformat(entry.created_at)
            except ValueError:
                created_at = None
        else:
            created_at = entry.created_at

    source = entry.source.value if hasattr(entry.source, "value") else str(entry.source)

    return JournalHistoryEntry(
        entity_type=entry.entity_type,
        entity_id=entry.entity_id,
        field_name=entry.field_name,
        old_value=entry.old_value,
        new_value=entry.new_value,
        changed_by=entry.changed_by,
        source=source,
        created_at=created_at,
    )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_journal_history", "journal")
async def get_journal_history(
    journal_id: Annotated[
        int, Field(description="The unique identifier of the journal")
    ],
    page: Annotated[int, Field(description="Page number (1-based)", ge=1)] = 1,
    limit: Annotated[int, Field(description="Entries per page", ge=1, le=100)] = 20,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Return a journal's field-level change history with provenance.

    Provides AI-agent parity with the REST ``GET /api/journals/{id}/history``
    endpoint: paginated, most-recent-first entries covering the journal's own
    fields plus its type-specific data, routes, and gear, each tagged with its
    origin (UI, MCP, an external sync, etc.). History is produced asynchronously
    by the projection consumer, so a just-made change may take a moment to
    appear.
    """
    user_id = await get_current_user_id()
    repos = create_journal_tool_repositories(db_connection)

    # Scope to the authenticated user: a journal owned by someone else is
    # reported as not-found so history cannot leak across users (mirrors
    # get_route_history and the REST endpoint).
    journal = await repos.journal_repo.find_by_id(journal_id)
    if journal is None or journal.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    history_service = JournalHistoryService(SqlFieldHistoryRepository(db_connection))

    offset = (page - 1) * limit
    history_entries = await history_service.get_journal_history(
        journal_id=journal_id,
        limit=limit,
        offset=offset,
    )
    total_count = await history_service.get_journal_history_count(
        journal_id=journal_id,
    )

    entries = [_journal_history_entry_to_schema(entry) for entry in history_entries]

    response = JournalHistoryResponse(
        journal_id=journal_id,
        total_count=total_count,
        page=page,
        limit=limit,
        entries=entries,
        summary=(
            f"Journal {journal_id} has {total_count} recorded change(s); "
            f"showing {len(entries)} on page {page}."
        ),
    )
    return MCPResponseBuilder.success_response(response)


def register_journal_history_tools(mcp: FastMCP[None]) -> None:
    """Register the history MCP tools with the FastMCP server."""
    mcp.add_tool(get_journal_history)
