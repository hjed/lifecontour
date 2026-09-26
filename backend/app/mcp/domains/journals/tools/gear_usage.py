"""MCP tools that add or remove one gear item on a journal's GEAR_USAGE entry.

``update_journal_entry`` replaces the whole ``items`` list; these change one
item and leave the others alone, so an agent adding the helmet it forgot does
not have to restate the rest of the trip's gear.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import JournalNotFoundError
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.journal_write_service import JournalWriteService
from app.mcp.domains.journals.schemas import (
    GearUsageItemMCPEntry,
    GearUsageItemsMCPResponse,
)
from app.mcp.domains.journals.tools._shared import (
    JournalToolRepositories,
    create_journal_tool_repositories,
)
from app.mcp.shared.annotations import IDEMPOTENT_WRITE
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_journal_write_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


async def _require_owned_journal(
    repos: JournalToolRepositories, journal_id: int, user_id: str
) -> None:
    """Somebody else's journal is reported as missing, never as forbidden."""
    if not await repos.journal_repo.find_by_id_for_user(journal_id, user_id):
        raise JournalNotFoundError(journal_id)


async def _gear_usage_response(
    repos: JournalToolRepositories, journal_id: int
) -> GearUsageItemsMCPResponse:
    gear_usage = await repos.gear_usage_data_repo.find_by_journal_id(journal_id)
    return GearUsageItemsMCPResponse(
        journal_id=journal_id,
        items=[
            GearUsageItemMCPEntry(
                gear_item_id=str(item.gear_item_id),
                checkout_date=item.checkout_date,
                checkin_date=item.checkin_date,
            )
            for item in (gear_usage.items if gear_usage is not None else ())
        ],
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("add_gear_usage_item", "journal")
async def add_gear_usage_item(
    journal_id: Annotated[int, Field(description="Journal the gear was used on")],
    gear_item_id: Annotated[UUID, Field(description="Gear item UUID")],
    checkout_date: Annotated[
        datetime | None,
        Field(
            description=(
                "ISO datetime the item was checked out; omit to keep the item's "
                "current one (the journal's start when it has none)"
            )
        ),
    ] = None,
    checkin_date: Annotated[
        datetime | None,
        Field(
            description=(
                "ISO datetime the item was checked back in; omit to keep the "
                "item's current one (the journal's end when it has none)"
            )
        ),
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    write_service: JournalWriteService = mcp_depends(get_journal_write_service),
) -> str:
    """Record that a gear item was used on a journal, keeping its other gear.

    Adds the item (giving the journal the GEAR_USAGE type if it has none), or,
    when the journal already lists it, sets the dates sent. Every other item is
    left as it is. To replace the whole list, send GEAR_USAGE ``items`` to
    update_journal_entry instead. Returns the journal's gear items.
    """
    user_id = str(await get_current_user_id())
    repos = create_journal_tool_repositories(db_connection)
    await _require_owned_journal(repos, journal_id, user_id)
    gear_item = await repos.gear_item_repo.find_by_id(str(gear_item_id))
    if gear_item is None or gear_item.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response(
            "Gear item", str(gear_item_id)
        )

    attrs: dict[str, Any] = {"gear_item_id": str(gear_item_id)}
    if checkout_date is not None:
        attrs["checkout_date"] = checkout_date.isoformat()
    if checkin_date is not None:
        attrs["checkin_date"] = checkin_date.isoformat()
    await write_service.set_gear_usage_item(
        journal_id,
        attrs,
        db_connection,
        changed_by="mcp",
        source=Provenance.MCP,
    )

    return MCPResponseBuilder.success_response(
        await _gear_usage_response(repos, journal_id)
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("remove_gear_usage_item", "journal")
async def remove_gear_usage_item(
    journal_id: Annotated[int, Field(description="Journal the gear was used on")],
    gear_item_id: Annotated[UUID, Field(description="Gear item UUID to remove")],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    write_service: JournalWriteService = mcp_depends(get_journal_write_service),
) -> str:
    """Remove one gear item from a journal, keeping its other gear.

    The journal keeps the GEAR_USAGE type even when this was its last item.
    Returns the journal's remaining gear items.
    """
    user_id = str(await get_current_user_id())
    repos = create_journal_tool_repositories(db_connection)
    await _require_owned_journal(repos, journal_id, user_id)

    await write_service.remove_gear_usage_item(
        journal_id,
        gear_item_id,
        db_connection,
        changed_by="mcp",
        source=Provenance.MCP,
    )

    return MCPResponseBuilder.success_response(
        await _gear_usage_response(repos, journal_id)
    )


def register_gear_usage_tools(mcp: FastMCP[None]) -> None:
    """Register the gear usage item MCP tools with the FastMCP server."""
    mcp.add_tool(add_gear_usage_item)
    mcp.add_tool(remove_gear_usage_item)
