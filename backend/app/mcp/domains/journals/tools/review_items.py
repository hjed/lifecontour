"""MCP tools for the journal review queue (suspected duplicates to merge)."""

import json
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.review_item_repository import SqlReviewItemRepository
from app.core.journal.services.review_item_service import ReviewItemService
from app.mcp.shared.annotations import (
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_review_item_service,
    mcp_depends,
)

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_review_items", "journal")
async def list_review_items(
    limit: Annotated[
        int,
        Field(
            default=20,
            description="Maximum number of results to return (default: 20)",
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(
            default=0,
            description="Number of results to skip (default: 0)",
        ),
    ] = 0,
    status: Annotated[
        str,
        Field(
            default="pending",
            description="Filter by items status, must be 'pending' for now",
        ),
    ] = "pending",
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List pending journal review items for the user.

    Retrieves a list of journals that might need merging, deduplication,
    or review. Used typically to show pending tasks in a queue/sidebar.

    Returns AI-friendly response containing reason, confidence score, and
    candidate journal ids for review.
    """
    user_id = await get_current_user_id()

    if status != "pending":
        return json.dumps({"error": "Only 'pending' status is currently supported"})

    review_item_repo = SqlReviewItemRepository(db_connection)

    items = await review_item_repo.find_pending_by_user(
        user_id, limit=limit, offset=offset
    )
    total_count = await review_item_repo.count_pending_by_user(user_id)

    # Batch-fetch journal summaries for context
    journal_ids = set()
    for item in items:
        journal_ids.add(item.source_journal_id)
        journal_ids.add(item.candidate_journal_id)

    journal_repo = SqlJournalRepository(db_connection)

    journals = await journal_repo.find_by_ids_for_user(user_id, list(journal_ids))
    journal_map = {j.id: j for j in journals if j.id is not None}

    # Build response payload
    results = []
    for item in items:
        source_journal = journal_map.get(item.source_journal_id)
        candidate_journal = journal_map.get(item.candidate_journal_id)

        results.append(
            {
                "id": item.id,
                "status": item.status,
                "reason": item.reason.value
                if hasattr(item.reason, "value")
                else item.reason,
                "confidence_score": item.confidence_score,
                "details": item.details,
                "source_journal": {
                    "id": item.source_journal_id,
                    "title": source_journal.title
                    if source_journal
                    else f"Journal {item.source_journal_id}",
                },
                "candidate_journal": {
                    "id": item.candidate_journal_id,
                    "title": candidate_journal.title
                    if candidate_journal
                    else f"Journal {item.candidate_journal_id}",
                },
            }
        )

    response_data = {
        "meta": {"total_count": total_count, "offset": offset, "limit": limit},
        "data": results,
        "summary": f"Found {total_count} pending review item(s).",
    }

    return json.dumps(response_data, indent=2)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("dismiss_review_item", "journal")
async def dismiss_review_item(
    item_id: int,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    review_item_service: ReviewItemService = mcp_depends(get_review_item_service),
) -> str:
    """
    Dismiss a journal review item.

    Use this tool to dismiss a pending merge candidate review item that the user
    has determined is not a match or should not be merged.
    """
    user_id = await get_current_user_id()

    item = await review_item_service.dismiss(
        item_id, user_id, transaction=db_connection
    )

    if not item:
        return json.dumps({"error": f"Review item {item_id} not found."})

    return json.dumps(
        {
            "success": True,
            "message": f"Successfully dismissed review item {item_id}.",
            "status": item.status,
        },
        indent=2,
    )


def register_review_item_tools(mcp: FastMCP[None]) -> None:
    """Register the review items MCP tools with the FastMCP server."""
    mcp.add_tool(list_review_items)
    mcp.add_tool(dismiss_review_item)
