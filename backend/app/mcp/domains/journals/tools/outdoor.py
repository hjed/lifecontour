"""MCP tools for the outdoor logbook: incomplete activities and the dashboard."""

from typing import Annotated

from core_shared.models.history import Provenance
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)
from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)
from app.core.journal.services.outdoor_dashboard_service import (
    OutdoorDashboardService,
)
from app.mcp.domains.journals.schemas import (
    CheckedOutGearMCPEntry,
    EventDateRangeSchema,
    IncompleteOutdoorActivitiesMCPResponse,
    IncompleteOutdoorActivityMCPEntry,
    OutdoorActivityDismissalMCPResponse,
    OutdoorDashboardMCPResponse,
    TemplateDoneMCPEntry,
    UpcomingOutdoorActivityMCPEntry,
    build_dashboard_summary,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
)
from app.mcp.shared.annotations import (
    IDEMPOTENT_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_incomplete_outdoor_activity_service,
    get_outdoor_activity_dismissal_service,
    get_outdoor_dashboard_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_incomplete_outdoor_activities", "journal")
async def list_incomplete_outdoor_activities(
    include_dismissed: Annotated[
        bool,
        Field(
            description=(
                "Also return dismissed journals, flagged dismissed=true "
                "(default false: dismissed journals are excluded)"
            ),
        ),
    ] = False,
    user_id: str = mcp_depends(get_current_user_id),
    incomplete_service: IncompleteOutdoorActivityService = mcp_depends(
        get_incomplete_outdoor_activity_service
    ),
) -> str:
    """
    List the user's incomplete outdoor activity journals with their reasons.

    Each entry names the rule(s) it matches: ``no_attributes`` (a subtype's own
    type-specific fields are all empty), ``missing_template`` (an
    abseiling-derived activity with no template reference), and
    ``no_participants`` (a non-bushwalking outdoor activity with no PARTICIPANT
    contacts). Only activities that have already started are listed — a journal
    beginning after the end of today (in the user's timezone) is a plan, not a
    gap. Dismissed journals are excluded unless ``include_dismissed`` is
    set (they then carry ``dismissed=true``, so they can be un-dismissed);
    entries are newest first.
    """
    entries = await incomplete_service.list_incomplete(
        user_id, include_dismissed=include_dismissed
    )

    activities = [
        IncompleteOutdoorActivityMCPEntry(
            journal_id=entry.journal_id,
            title=entry.title,
            event_date_range=EventDateRangeSchema(
                start=entry.event_date_range.start,
                end=entry.event_date_range.end,
            ),
            subtypes=[subtype.value for subtype in entry.subtypes],
            reasons=[reason.value for reason in entry.reasons],
            dismissed=entry.dismissed,
        )
        for entry in entries
    ]

    return MCPResponseBuilder.success_response(
        IncompleteOutdoorActivitiesMCPResponse(
            total_count=len(activities),
            activities=activities,
            summary=(
                f"Found {len(activities)} incomplete outdoor activit"
                f"{'y' if len(activities) == 1 else 'ies'}."
            ),
        )
    )


async def _journal_owned_by_user(
    db_connection: AsyncConnection, user_id: str, journal_id: int
) -> bool:
    """Whether the journal exists and belongs to the user."""
    repos = create_journal_tool_repositories(db_connection)
    journal = await repos.journal_repo.find_by_id(journal_id)
    return journal is not None and journal.user_id == user_id


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("dismiss_incomplete_outdoor_activity", "journal")
async def dismiss_incomplete_outdoor_activity(
    journal_id: Annotated[int, Field(description="Journal id to dismiss")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    dismissal_service: OutdoorActivityDismissalService = mcp_depends(
        get_outdoor_activity_dismissal_service
    ),
) -> str:
    """
    Dismiss a journal from the incomplete outdoor activities review.

    A dismissed journal no longer appears in the incomplete review regardless
    of matched rules. Idempotent: re-dismissing refreshes the recorded
    provenance. Reversible via ``undismiss_incomplete_outdoor_activity``.
    """
    if not await _journal_owned_by_user(db_connection, user_id, journal_id):
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    dismissal = await dismissal_service.dismiss(
        journal_id, user_id, Provenance.MCP, db_connection
    )

    return MCPResponseBuilder.success_response(
        OutdoorActivityDismissalMCPResponse(
            journal_id=journal_id,
            dismissed=True,
            provenance=dismissal.provenance.value,
            summary=f"Dismissed journal {journal_id} from the incomplete review.",
        )
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("undismiss_incomplete_outdoor_activity", "journal")
async def undismiss_incomplete_outdoor_activity(
    journal_id: Annotated[int, Field(description="Journal id to un-dismiss")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    dismissal_service: OutdoorActivityDismissalService = mcp_depends(
        get_outdoor_activity_dismissal_service
    ),
) -> str:
    """
    Un-dismiss a journal, restoring it to the incomplete review when flagged.

    Idempotent: un-dismissing a journal that was never dismissed succeeds with
    ``was_dismissed`` false.
    """
    if not await _journal_owned_by_user(db_connection, user_id, journal_id):
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    was_dismissed = await dismissal_service.undismiss(
        journal_id, user_id, db_connection
    )

    return MCPResponseBuilder.success_response(
        OutdoorActivityDismissalMCPResponse(
            journal_id=journal_id,
            dismissed=False,
            was_dismissed=was_dismissed,
            summary=(
                f"Un-dismissed journal {journal_id}."
                if was_dismissed
                else f"Journal {journal_id} was not dismissed; nothing to undo."
            ),
        )
    )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_outdoor_dashboard", "journal")
async def get_outdoor_dashboard(
    user_id: str = mcp_depends(get_current_user_id),
    dashboard_service: OutdoorDashboardService = mcp_depends(
        get_outdoor_dashboard_service
    ),
) -> str:
    """
    The outdoor logbook dashboard: all four widget sections in one call.

    A read-only projection over the user's outdoor activity journals
    (general fitness journals such as plain jogging are excluded):

    - ``upcoming_activities`` — outdoor activities and OUTDOOR_PLANNING
      events overlapping the next 30 days, soonest first, capped at 10.
    - ``checked_out_gear`` — gear whose resolved checkout window contains
      now and that Snipe-IT hasn't recorded as returned, longest out first.
    - ``activity_totals_last_30_days`` / ``activity_totals_last_365_days``
      — outdoor activity counts by journal type over rolling windows, plus
      ``total_activities_last_30_days`` / ``total_activities_last_365_days``
      counting *distinct journals*. A journal recording two independent
      subtypes lands in two type buckets, so the totals are not the sums of
      the mappings.
    - ``templates_done`` — the unique templates referenced by the user's
      abseiling activities, grouped by template type, each with how many
      activities reference it (all-time), plus
      ``templates_done_last_30_days`` counting the distinct templates done
      recently.

    Windows are anchored on "today" in the user's configured timezone
    server-side, so the tool takes no arguments.
    """
    upcoming = await dashboard_service.list_upcoming_activities(user_id)
    totals = await dashboard_service.activity_totals(user_id)
    checked_out = await dashboard_service.list_checked_out_gear(user_id)
    templates_done = await dashboard_service.templates_done(user_id)

    upcoming_entries = [
        UpcomingOutdoorActivityMCPEntry(
            journal_id=entry.journal_id,
            title=entry.title,
            event_date_range=EventDateRangeSchema(
                start=entry.event_date_range.start,
                end=entry.event_date_range.end,
            ),
            subtypes=[subtype.value for subtype in entry.subtypes],
            is_planning=entry.is_planning,
        )
        for entry in upcoming
    ]
    gear_entries = [
        CheckedOutGearMCPEntry(
            gear_item_id=item.gear_item_id,
            name=item.name,
            checked_out_since=item.checked_out_since,
            journal_id=item.journal_id,
        )
        for item in checked_out
    ]
    template_entries = {
        template_type: [
            TemplateDoneMCPEntry(
                template_id=template.template_id,
                name=template.name,
                done_count=template.done_count,
            )
            for template in templates
        ]
        for template_type, templates in templates_done.by_type.items()
    }

    return MCPResponseBuilder.success_response(
        OutdoorDashboardMCPResponse(
            upcoming_activities=upcoming_entries,
            checked_out_gear=gear_entries,
            activity_totals_last_30_days=totals.last_30_days,
            activity_totals_last_365_days=totals.last_365_days,
            total_activities_last_30_days=totals.total_last_30_days,
            total_activities_last_365_days=totals.total_last_365_days,
            templates_done=template_entries,
            templates_done_last_30_days=templates_done.recent_unique_count,
            summary=build_dashboard_summary(
                upcoming_activities=upcoming_entries,
                checked_out_gear=gear_entries,
                total_last_30_days=totals.total_last_30_days,
                templates_done=template_entries,
                templates_done_last_30_days=templates_done.recent_unique_count,
            ),
        )
    )


def register_outdoor_tools(mcp: FastMCP[None]) -> None:
    """Register the outdoor MCP tools with the FastMCP server."""
    mcp.add_tool(list_incomplete_outdoor_activities)
    mcp.add_tool(dismiss_incomplete_outdoor_activity)
    mcp.add_tool(undismiss_incomplete_outdoor_activity)
    mcp.add_tool(get_outdoor_dashboard)
