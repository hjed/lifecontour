"""MCP tools for journal series.

A series groups related journal entries — auto-created from recurring Google
Calendar events during sync, or created manually (e.g. a series of medical
appointments). These tools let AI assistants create series, manage their
members, and inspect them.
"""

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    JournalValidationError,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.series_merge import SeriesMergePair, SeriesMergePolicies
from app.core.journal.services.journal_series_merge_service import (
    JournalSeriesMergeService,
    SeriesMergeReport,
)
from app.core.journal.services.journal_series_service import (
    JournalSeriesService,
    parse_series_id,
)
from app.mcp.domains.journals.schemas import (
    JournalSeriesDetailMCPResponse,
    JournalSeriesListMCPResponse,
    JournalSeriesMCPResponse,
    SeriesDeletedMCPResponse,
    SeriesMemberJournalMCP,
    SeriesMembershipAddedMCPResponse,
    SeriesMembershipRemovedMCPResponse,
    SeriesMergeDayMCP,
    SeriesMergeJournalMCP,
    SeriesMergeReportMCPResponse,
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


def _series_fields(series: JournalSeries) -> dict[str, object]:
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


def _series(series: JournalSeries) -> JournalSeriesMCPResponse:
    return JournalSeriesMCPResponse.model_validate(_series_fields(series))


class SeriesMergePairArgument(BaseModel):
    """A same-day pair from ``preview_series_merge`` to merge."""

    # A misspelt key would otherwise drop the pair's id and fail as "stale".
    model_config = ConfigDict(extra="forbid")

    source_journal_id: int
    destination_journal_id: int


def _merge_report(report: SeriesMergeReport) -> SeriesMergeReportMCPResponse:
    return SeriesMergeReportMCPResponse(
        source_series_id=str(report.source_series.id),
        destination_series_id=str(report.destination_series.id),
        days=[
            SeriesMergeDayMCP(
                date=day.date,
                kind=day.kind,
                source_journal_ids=list(day.source_journal_ids),
                destination_journal_ids=list(day.destination_journal_ids),
                differing_fields=list(day.differing_fields),
                skip_reason=day.skip_reason,
            )
            for day in report.days
        ],
        journals={
            str(journal_id): SeriesMergeJournalMCP(
                id=journal_id,
                title=member.journal.title,
                event_date_range_start=(
                    member.journal.event_date_range.start.isoformat()
                ),
                location=(
                    member.calendar_info.location if member.calendar_info else None
                ),
            )
            for journal_id, member in report.members.items()
        },
    )


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_series", "journal")
async def create_series(
    name: str,
    description: str | None = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> JournalSeriesMCPResponse:
    """
    Create a journal series — a named group of related journal entries.

    Use a series to link journals that belong together over time, e.g. a course
    of medical appointments or a training block. Journals synced from recurring
    calendar events are grouped into series automatically; this tool is for
    manual grouping. Add members with add_journal_to_series.
    """
    user_id = await get_current_user_id()
    try:
        series = JournalSeries(name=name, user_id=user_id, description=description)
    except ValueError as e:
        raise JournalValidationError("name", str(e)) from e

    created = await series_service.create_series(series, db_connection)
    return _series(created)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_series", "journal")
async def list_series(
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> JournalSeriesListMCPResponse:
    """
    List all journal series for the current user, ordered by name.
    """
    user_id = await get_current_user_id()
    all_series = await series_service.list_series(user_id)
    return JournalSeriesListMCPResponse(series=[_series(s) for s in all_series])


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_series", "journal")
async def get_series(
    series_id: str,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> JournalSeriesDetailMCPResponse:
    """
    Get a journal series with its member journals.
    """
    user_id = await get_current_user_id()
    parsed_id = parse_series_id(series_id)
    series = await series_service.get_series(parsed_id, user_id)

    member_ids = await series_service.get_member_journal_ids(parsed_id, user_id)
    journal_repo = SqlJournalRepository(db_connection)
    members = await journal_repo.find_by_ids_for_user(user_id, member_ids)
    members_by_id = {j.id: j for j in members if j.id is not None}

    return JournalSeriesDetailMCPResponse.model_validate(
        {
            **_series_fields(series),
            "member_journals": [
                SeriesMemberJournalMCP(
                    id=journal_id,
                    title=members_by_id[journal_id].title,
                    event_date_range_start=(
                        members_by_id[journal_id].event_date_range.start.isoformat()
                        if members_by_id[journal_id].event_date_range
                        else None
                    ),
                )
                for journal_id in member_ids
                if journal_id in members_by_id
            ],
        }
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_series", "journal")
async def update_series(
    series_id: str,
    name: str,
    description: str | None = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> JournalSeriesMCPResponse:
    """
    Rename or re-describe a journal series.
    """
    user_id = await get_current_user_id()
    updated = await series_service.update_series(
        series_id=parse_series_id(series_id),
        user_id=user_id,
        name=name,
        description=description,
        transaction=db_connection,
    )
    return _series(updated)


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("delete_series", "journal")
async def delete_series(
    series_id: str,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> SeriesDeletedMCPResponse:
    """
    Delete a journal series. Member journals are NOT deleted — only the
    grouping is removed.
    """
    user_id = await get_current_user_id()
    await series_service.delete_series(
        parse_series_id(series_id), user_id, db_connection
    )
    return SeriesDeletedMCPResponse(deleted=True, series_id=series_id)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("add_journal_to_series", "journal")
async def add_journal_to_series(
    series_id: str,
    journal_id: int,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> SeriesMembershipAddedMCPResponse:
    """
    Add a journal entry to a series (idempotent — re-adding is a no-op).

    A journal may belong to multiple series (e.g. an auto-created calendar
    series plus a manual grouping).
    """
    user_id = await get_current_user_id()
    await series_service.add_journal_to_series(
        series_id=parse_series_id(series_id),
        journal_id=journal_id,
        user_id=user_id,
        transaction=db_connection,
    )
    return SeriesMembershipAddedMCPResponse(
        added=True, series_id=series_id, journal_id=journal_id
    )


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("remove_journal_from_series", "journal")
async def remove_journal_from_series(
    series_id: str,
    journal_id: int,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    series_service: JournalSeriesService = mcp_depends(get_journal_series_service),
) -> SeriesMembershipRemovedMCPResponse:
    """
    Remove a journal entry from a series (idempotent). The journal itself is
    not deleted.
    """
    user_id = await get_current_user_id()
    await series_service.remove_journal_from_series(
        series_id=parse_series_id(series_id),
        journal_id=journal_id,
        user_id=user_id,
        transaction=db_connection,
    )
    return SeriesMembershipRemovedMCPResponse(
        removed=True, series_id=series_id, journal_id=journal_id
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
) -> SeriesMergeReportMCPResponse:
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
    "combine" (content only — its default — concatenating both). When only one
    journal of a pair is an event, its timing is kept whole whatever the timing
    policy: the other has no clock times to contribute.
    """
    user_id = await get_current_user_id()
    report = await merge_service.preview_merge(
        destination_series_id=parse_series_id(destination_series_id),
        source_series_id=parse_series_id(source_series_id),
        user_id=user_id,
        policies=SeriesMergePolicies.from_mapping(policies),
    )
    return _merge_report(report)


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("merge_series", "journal")
async def merge_series(
    destination_series_id: str,
    source_series_id: str,
    pairs: list[SeriesMergePairArgument] | None = None,
    policies: dict[str, str] | None = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    merge_service: JournalSeriesMergeService = mcp_depends(
        get_journal_series_merge_service
    ),
) -> SeriesMergeReportMCPResponse:
    """
    Merge the source series into the destination series, deleting the source.

    Call preview_series_merge first. Every source member joins the destination
    series. Each pair in ``pairs`` — "candidate" days from the preview, as
    {source_journal_id, destination_journal_id} — is merged into the
    destination journal using ``policies`` (same meaning as in the preview);
    candidates left out are not merged. If any pair is no longer a candidate
    (the data changed since the preview) nothing is written and an error is
    returned: preview again. Later calendar syncs of a recurring source series
    add their instances to the destination.
    """
    user_id = await get_current_user_id()
    report = await merge_service.merge_series(
        destination_series_id=parse_series_id(destination_series_id),
        source_series_id=parse_series_id(source_series_id),
        user_id=user_id,
        policies=SeriesMergePolicies.from_mapping(policies),
        pairs=[
            SeriesMergePair(p.source_journal_id, p.destination_journal_id)
            for p in pairs or []
        ],
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )
    return _merge_report(report)


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
    mcp.add_tool(merge_series)
