"""MCP tools for journal series.

A series groups related journal entries — auto-created from recurring Google
Calendar events during sync, or created manually (e.g. a series of medical
appointments). These tools let AI assistants create series, manage their
members, and inspect them.
"""

import json
from typing import Any

from core_shared.models.journals import (
    JournalValidationError,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.series_merge import SeriesMergePolicies
from app.core.journal.services.journal_series_merge_service import (
    JournalSeriesMergeService,
    SeriesMergeReport,
)
from app.core.journal.services.journal_series_service import (
    JournalSeriesService,
    parse_series_id,
)
from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_journal_series_merge_service,
    get_journal_series_service,
    mcp_depends,
)


def _series_to_dict(series: JournalSeries) -> dict[str, Any]:
    return {
        "id": str(series.id),
        "name": series.name,
        "description": series.description,
        "calendar_id": str(series.calendar_id) if series.calendar_id else None,
        "recurring_event_id": series.recurring_event_id,
        "auto_created": series.auto_created,
        "created_at": series.created_at.isoformat() if series.created_at else None,
        "updated_at": series.updated_at.isoformat() if series.updated_at else None,
    }


def _merge_report_to_dict(report: SeriesMergeReport) -> dict[str, Any]:
    return {
        "source_series_id": str(report.source_series.id),
        "destination_series_id": str(report.destination_series.id),
        "days": [
            {
                "date": day.date.isoformat(),
                "kind": day.kind.value,
                "source_journal_ids": list(day.source_journal_ids),
                "destination_journal_ids": list(day.destination_journal_ids),
                "differing_fields": [f.value for f in day.differing_fields],
                "skip_reason": day.skip_reason.value if day.skip_reason else None,
            }
            for day in report.days
        ],
        "journals": {
            str(journal_id): {
                "id": journal_id,
                "title": member.journal.title,
                "event_date_range_start": (
                    member.journal.event_date_range.start.isoformat()
                ),
                "location": (
                    member.calendar_info.location if member.calendar_info else None
                ),
            }
            for journal_id, member in report.members.items()
        },
    }


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_series", "journal")
async def create_series(
    name: str,
    description: str | None = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> str:
    """
    Create a journal series — a named group of related journal entries.

    Use a series to link journals that belong together over time, e.g. a course
    of medical appointments or a training block. Journals synced from recurring
    calendar events are grouped into series automatically; this tool is for
    manual grouping. Add members with add_journal_to_series.

    Returns:
        JSON string with the created series (id, name, description,
        auto_created flag).
    """
    user_id = await get_current_user_id()
    try:
        series = JournalSeries(name=name, user_id=user_id, description=description)
    except ValueError as e:
        raise JournalValidationError("name", str(e)) from e

    created = await series_service.create_series(series, db_connection)
    return json.dumps(_series_to_dict(created), indent=2)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_series", "journal")
async def list_series(
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> str:
    """
    List all journal series for the current user, ordered by name.

    Returns:
        JSON string with a "series" list; each item has id, name, description,
        and whether it was auto-created from a recurring calendar event.
    """
    user_id = await get_current_user_id()
    all_series = await series_service.list_series(user_id)
    return json.dumps({"series": [_series_to_dict(s) for s in all_series]}, indent=2)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_series", "journal")
async def get_series(
    series_id: str,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> str:
    """
    Get a journal series with its member journals.

    Returns:
        JSON string with the series fields plus "member_journals": a list of
        {id, title, event_date_range_start} ordered by event date.
    """
    user_id = await get_current_user_id()
    parsed_id = parse_series_id(series_id)
    series = await series_service.get_series(parsed_id, user_id)

    member_ids = await series_service.get_member_journal_ids(parsed_id, user_id)
    journal_repo = SqlJournalRepository(db_connection)
    members = await journal_repo.find_by_ids_for_user(user_id, member_ids)
    members_by_id = {j.id: j for j in members if j.id is not None}

    result = _series_to_dict(series)
    result["member_journals"] = [
        {
            "id": journal_id,
            "title": members_by_id[journal_id].title,
            "event_date_range_start": (
                members_by_id[journal_id].event_date_range.start.isoformat()
                if members_by_id[journal_id].event_date_range
                else None
            ),
        }
        for journal_id in member_ids
        if journal_id in members_by_id
    ]
    return json.dumps(result, indent=2)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_series", "journal")
async def update_series(
    series_id: str,
    name: str,
    description: str | None = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> str:
    """
    Rename or re-describe a journal series.

    Returns:
        JSON string with the updated series.
    """
    user_id = await get_current_user_id()
    updated = await series_service.update_series(
        series_id=parse_series_id(series_id),
        user_id=user_id,
        name=name,
        description=description,
        transaction=db_connection,
    )
    return json.dumps(_series_to_dict(updated), indent=2)


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("delete_series", "journal")
async def delete_series(
    series_id: str,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> str:
    """
    Delete a journal series. Member journals are NOT deleted — only the
    grouping is removed.

    Returns:
        JSON string confirming the deletion.
    """
    user_id = await get_current_user_id()
    await series_service.delete_series(
        parse_series_id(series_id), user_id, db_connection
    )
    return json.dumps({"deleted": True, "series_id": series_id}, indent=2)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("add_journal_to_series", "journal")
async def add_journal_to_series(
    series_id: str,
    journal_id: int,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> str:
    """
    Add a journal entry to a series (idempotent — re-adding is a no-op).

    A journal may belong to multiple series (e.g. an auto-created calendar
    series plus a manual grouping).

    Returns:
        JSON string confirming the membership.
    """
    user_id = await get_current_user_id()
    await series_service.add_journal_to_series(
        series_id=parse_series_id(series_id),
        journal_id=journal_id,
        user_id=user_id,
        transaction=db_connection,
    )
    return json.dumps(
        {"added": True, "series_id": series_id, "journal_id": journal_id}, indent=2
    )


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("remove_journal_from_series", "journal")
async def remove_journal_from_series(
    series_id: str,
    journal_id: int,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> str:
    """
    Remove a journal entry from a series (idempotent). The journal itself is
    not deleted.

    Returns:
        JSON string confirming the removal.
    """
    user_id = await get_current_user_id()
    await series_service.remove_journal_from_series(
        series_id=parse_series_id(series_id),
        journal_id=journal_id,
        user_id=user_id,
        transaction=db_connection,
    )
    return json.dumps(
        {"removed": True, "series_id": series_id, "journal_id": journal_id}, indent=2
    )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("preview_series_merge", "journal")
async def preview_series_merge(
    destination_series_id: str,
    source_series_id: str,
    policies: dict[str, str] | None = None,
    merge_service: JournalSeriesMergeService = mcp_depends(
        get_journal_series_merge_service
    ),
) -> str:
    """
    Preview merging the source series into the destination series. Writes nothing.

    A merge moves every source member into the destination and deletes the
    source series. A source and a destination journal whose events start on the
    same local day (the user's timezone) can also be merged into one journal,
    the destination's surviving.

    ``policies`` maps a field to what survives in every merged pair. Fields:
    "title", "content", "timing" (dates plus the event's clock times and zone),
    "location", "event_description". Policies: "destination" (default),
    "source", "skip_if_different" (don't merge a pair whose values differ), and
    "combine" (content only — its default — concatenating both).

    Returns:
        JSON string with "days" (date, kind, source_journal_ids,
        destination_journal_ids, differing_fields, skip_reason) and "journals"
        ({id: {title, event_date_range_start, location}}). A day's kind is
        "candidate" (will merge), "skipped" (a skip_if_different field differs),
        "ambiguous" (more than one journal on a side; not merged), "unpaired"
        or "already_shared" (the journal is in both series).
    """
    user_id = await get_current_user_id()
    report = await merge_service.preview_merge(
        destination_series_id=parse_series_id(destination_series_id),
        source_series_id=parse_series_id(source_series_id),
        user_id=user_id,
        policies=SeriesMergePolicies.from_mapping(policies),
    )
    return json.dumps(_merge_report_to_dict(report), indent=2)


def register_journal_series_tools(mcp: FastMCP[None]) -> None:
    """Register journal series MCP tools with the FastMCP server."""
    mcp.add_tool(create_series)
    mcp.add_tool(list_series)
    mcp.add_tool(get_series)
    mcp.add_tool(update_series)
    mcp.add_tool(delete_series)
    mcp.add_tool(add_journal_to_series)
    mcp.add_tool(remove_journal_from_series)
    mcp.add_tool(preview_series_merge)
