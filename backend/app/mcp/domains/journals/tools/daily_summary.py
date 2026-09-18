"""MCP tool returning the AI-generated summary of a day."""

import json
from datetime import date

from fastmcp import FastMCP
from fastmcp.tools import tool
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.daily_summary_service import DailySummaryService
from app.mcp.domains.journals.schemas import (
    DailySummaryMCPResponse,
)
from app.mcp.shared.annotations import (
    READ_ONLY_EXTERNAL,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_daily_summary_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data


# Read-only to the caller, though it may generate and persist. Asking for a
# summary reads a summary; the caching write behind it is not part of the
# world an agent calling this tool reasons about.
@tool(annotations=READ_ONLY_EXTERNAL)
@mcp_unified_error_handler("get_daily_summary", "journal")
async def get_daily_summary(
    summary_date: str,
    daily_summary_service: DailySummaryService = mcp_depends(get_daily_summary_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """Get the AI-generated daily summary for a specific date.

    Today (in the user's configured timezone) is always eligible for a summary,
    however few journals it has, and today's summary is regenerated on read if
    it was not generated today in that timezone, so it always reflects today.
    Any other date needs at least two journals and otherwise comes back with
    status "disabled"; its summary is served from cache however old it is.

    Today's summary is also grounded in the day's agenda — its event journals
    with their times, locations and participants — while any other day's
    describes only that day's journals.

    Args:
        summary_date: The date to get the summary for (YYYY-MM-DD format)
    """
    try:
        parsed_date = date.fromisoformat(summary_date)
    except ValueError as e:
        raise ValueError(
            f"Invalid date format. Expected YYYY-MM-DD, got {summary_date}"
        ) from e

    user_id = await get_current_user_id()

    # get_or_generate is @transactional: it commits any summary it persists
    # before the response is returned (issue #945). Pass the request connection
    # and let the service own the commit boundary — this tool opens no
    # transaction itself (the required pattern; see AGENTS.md "Transactions").
    result = await daily_summary_service.get_or_generate(
        user_id, parsed_date, db_connection
    )

    if result is None:
        return json.dumps({"data": None})

    response = DailySummaryMCPResponse(
        summary_date=parsed_date.isoformat(),
        summary_text=result.get_display_text(),
        journal_count=result.journal_count,
        event_count=result.event_count,
        contact_count=result.contact_count,
        mood_average=result.mood_average,
        status=str(result.status.value)
        if hasattr(result.status, "value")
        else str(result.status),
        summary=f"Daily summary for {parsed_date.isoformat()}: {result.status}. {result.journal_count} journals, {result.event_count} events.",
    )

    return MCPResponseBuilder.success_response(response)


def register_daily_summary_tools(mcp: FastMCP[None]) -> None:
    """Register the daily summary MCP tools with the FastMCP server."""
    mcp.add_tool(get_daily_summary)
