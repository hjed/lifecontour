"""
Journal domain MCP tools.

Provides AI access to journal management functionality through MCP tools.
Each tool is designed to return AI-friendly, contextual information.
Tools are moving into one module per area; ``register_journal_tools``
registers every one of them.
"""

import json
from datetime import date
from typing import Annotated, Any
from uuid import UUID

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    ActivityTemplate,
    Calendar,
    CanyonType,
    ClimbingType,
    GearItem,
    JournalNotFoundError,
    JournalValidationError,
    TemplatePitch,
    TemplateType,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.calendar_repository import SqlCalendarRepository
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.review_item_repository import SqlReviewItemRepository
from app.core.journal.services.activity_template_service import (
    ActivityTemplateService,
)
from app.core.journal.services.calendar_service import (
    CalendarInUseError,
    CalendarService,
)
from app.core.journal.services.daily_summary_service import DailySummaryService
from app.core.journal.services.gear_item_service import GearItemService
from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_type_data_reader import (
    read_journal_types_and_data,
)
from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)
from app.core.journal.services.outdoor_dashboard_service import (
    OutdoorDashboardService,
)
from app.core.journal.services.review_item_service import ReviewItemService
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.mcp.domains.journals.converters import (
    ActivityTemplateMCPConverter,
    GearItemMCPConverter,
    JournalConverter,
)
from app.mcp.domains.journals.schemas import (
    CheckedOutGearMCPEntry,
    DailySummaryMCPResponse,
    EventDateRangeSchema,
    IncompleteOutdoorActivitiesMCPResponse,
    IncompleteOutdoorActivityMCPEntry,
    JournalTagInfo,
    JournalTagListMCPResponse,
    JournalTemplateMCPResponse,
    MergeCandidateResult,
    MergeCandidatesResponse,
    MergeJournalMCPRequest,
    OutdoorActivityDismissalMCPResponse,
    OutdoorDashboardMCPResponse,
    TemplateDoneMCPEntry,
    TemplatePitchInput,
    UpcomingOutdoorActivityMCPEntry,
    build_dashboard_summary,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
    fetch_contact_relationships_with_names,
    fetch_parent_journal,
)
from app.mcp.domains.journals.tools.activities import register_activity_tools
from app.mcp.domains.journals.tools.contacts import register_journal_contact_tools
from app.mcp.domains.journals.tools.hierarchy import register_journal_hierarchy_tools
from app.mcp.domains.journals.tools.history import register_journal_history_tools
from app.mcp.domains.journals.tools.journal_entries import register_journal_entry_tools
from app.mcp.domains.journals.tools.journals import register_journal_read_tools
from app.mcp.domains.journals.tools.routes import register_journal_route_tools
from app.mcp.domains.journals.tools.search import register_journal_search_tools
from app.mcp.domains.journals.tools.series import register_journal_series_tools
from app.mcp.shared.annotations import (
    ADDITIVE_WRITE,
    DESTRUCTIVE_WRITE,
    IDEMPOTENT_WRITE,
    READ_ONLY,
    READ_ONLY_EXTERNAL,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_activity_template_service,
    get_async_connection,
    get_calendar_service,
    get_current_user_id,
    get_daily_summary_service,
    get_gear_item_service,
    get_incomplete_outdoor_activity_service,
    get_journal_tag_service,
    get_outbox_event_publisher,
    get_outdoor_activity_dismissal_service,
    get_outdoor_dashboard_service,
    get_review_item_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data


def _parse_calendar_id(calendar_id: Any) -> UUID | None:
    if calendar_id is None:
        return None

    if isinstance(calendar_id, UUID):
        return calendar_id

    if isinstance(calendar_id, str):
        try:
            return UUID(calendar_id)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID."
            ) from exc

    raise ValueError(f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID.")


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_calendars", "journal")
async def list_calendars(
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List all calendars available for EVENT journals.
    """
    user_id = await get_current_user_id()
    calendar_repo = SqlCalendarRepository(db_connection)

    calendars = await calendar_repo.get_all(user_id=user_id)

    class CalendarListItem(BaseModel):
        id: str
        name: str
        description: str | None = None
        color: str | None = None

    class CalendarListResponse(BaseModel):
        calendars: list[CalendarListItem]

    response = CalendarListResponse(
        calendars=[
            CalendarListItem(
                id=str(c.id),
                name=c.name,
                description=c.description,
                color=c.color,
            )
            for c in calendars
        ]
    )

    return MCPResponseBuilder.success_response(response)


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_calendar", "journal")
async def create_calendar(
    name: Annotated[str, Field(description="Calendar name")],
    description: Annotated[
        str | None, Field(description="Calendar description", default=None)
    ] = None,
    color: Annotated[
        str | None, Field(description="Calendar color hex code", default=None)
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    calendar_service: CalendarService = mcp_depends(get_calendar_service),
) -> str:
    """
    Create a new calendar to be used with EVENT journals.
    """
    user_id = await get_current_user_id()

    new_calendar = Calendar(
        user_id=user_id,
        name=name,
        description=description,
        color=color or "#3B82F6",
        is_synced_to_google=False,
        google_calendar_id=None,
    )

    saved_calendar = await calendar_service.create_calendar(
        new_calendar, transaction=db_connection
    )

    class CalendarResponse(BaseModel):
        id: str
        name: str
        summary: str

    return MCPResponseBuilder.success_response(
        CalendarResponse(
            id=str(saved_calendar.id),
            name=saved_calendar.name,
            summary=f"Created calendar '{saved_calendar.name}'",
        )
    )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_calendar", "journal")
async def update_calendar(
    calendar_id: Annotated[str, Field(description="Calendar UUID")],
    name: Annotated[
        str | None, Field(description="Calendar name", default=None)
    ] = None,
    description: Annotated[
        str | None, Field(description="Calendar description", default=None)
    ] = None,
    color: Annotated[
        str | None, Field(description="Calendar color hex code", default=None)
    ] = None,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    calendar_service: CalendarService = mcp_depends(get_calendar_service),
) -> str:
    """
    Update an existing calendar.
    """
    user_id = await get_current_user_id()
    calendar_repo = SqlCalendarRepository(db_connection)

    calendar_uuid = _parse_calendar_id(calendar_id)
    if calendar_uuid is None:
        raise ValueError(f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID.")

    calendar = await calendar_repo.find_by_id(calendar_uuid)
    if not calendar or calendar.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Calendar", calendar_id)

    if name is not None:
        calendar.name = name
    if description is not None:
        calendar.description = description
    if color is not None:
        calendar.color = color

    saved_calendar = await calendar_service.update_calendar(
        calendar, transaction=db_connection
    )

    class CalendarResponse(BaseModel):
        id: str
        name: str
        summary: str

    return MCPResponseBuilder.success_response(
        CalendarResponse(
            id=str(saved_calendar.id),
            name=saved_calendar.name,
            summary=f"Updated calendar '{saved_calendar.name}'",
        )
    )


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("delete_calendar", "journal")
async def delete_calendar(
    calendar_id: Annotated[str, Field(description="Calendar UUID")],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    calendar_service: CalendarService = mcp_depends(get_calendar_service),
) -> str:
    """
    Delete a calendar. Will fail if the calendar is in use.
    """
    user_id = await get_current_user_id()
    calendar_repo = SqlCalendarRepository(db_connection)

    calendar_uuid = _parse_calendar_id(calendar_id)
    if calendar_uuid is None:
        raise ValueError(f"Invalid calendar_id '{calendar_id}'. Must be a valid UUID.")

    calendar = await calendar_repo.find_by_id(calendar_uuid)
    if not calendar or calendar.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Calendar", calendar_id)

    if calendar.id is not None:
        try:
            await calendar_service.delete_calendar(
                calendar, user_id, transaction=db_connection
            )
        except CalendarInUseError as exc:
            return MCPResponseBuilder.error_response(
                "CONFLICT",
                f"Calendar is in use by {exc.usage_count} journal(s)",
            )

    class DeleteCalendarResponse(BaseModel):
        summary: str

    return MCPResponseBuilder.success_response(
        DeleteCalendarResponse(summary=f"Deleted calendar '{calendar.name}'")
    )


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("merge_journals", "journal")
async def merge_journals(
    target_journal_id: Annotated[
        int,
        Field(description="The ID of the journal to keep (the merge target)"),
    ],
    merge_data: Annotated[
        str,
        Field(
            description=(
                "JSON string with merge parameters. Required key: "
                '"source_journal_id" (int) — the journal to absorb and delete. '
                'Optional keys: "overrides" (object) — explicit conflict resolution '
                'with keys: "title" (str), "content" (str), '
                '"event_date_range" ({start, end}), '
                '"type_data" ({TYPE: {field: value}}); '
                '"fitness_merge_mode" ("replace" | "additive") — how to combine '
                'fitness data, defaulting to "replace"'
            )
        ),
    ],
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    event_publisher: OutboxEventPublisher = mcp_depends(get_outbox_event_publisher),
) -> str:
    """
    Merge a source journal into a target journal.

    The source journal's content, tags, contacts, type data, routes,
    and child journals are absorbed into the target. The source is then
    deleted. Use 'overrides' to resolve conflicts explicitly (title,
    content, date range, or type-specific data).

    When both journals hold fitness data, 'fitness_merge_mode' decides how to
    reconcile it. The default 'replace' keeps the target's metrics and drops
    the source's integration links — the right choice for a duplicate or a
    re-import. Pass 'additive' when the two journals are two parts of one
    outing (a ride split by a stopped recording, an activity logged on two
    devices): distance, duration, elevation and calories sum, heart rates
    combine, and both journals' Strava activities stay linked to the survivor.

    Call get_merge_candidates first to find suitable merge targets.

    Args:
        target_journal_id: ID of the journal to keep
        merge_data: JSON string containing source_journal_id, optional overrides
            and optional fitness_merge_mode

    Returns:
        JSON string containing the merged target journal with all combined data
    """
    merge_request = MergeJournalMCPRequest.model_validate_json(merge_data)

    repos = create_journal_tool_repositories(db_connection)

    # Verify ownership — both journals must belong to the current user
    user_id = await get_current_user_id()
    target = await repos.journal_repo.find_by_id(target_journal_id)
    if not target or target.user_id != user_id:
        raise JournalNotFoundError(target_journal_id)
    source = await repos.journal_repo.find_by_id(merge_request.source_journal_id)
    if not source or source.user_id != user_id:
        raise JournalNotFoundError(merge_request.source_journal_id)

    # The tasks domain's merge service is built here rather than added to the
    # shared journal tool repositories: merge is the only journal tool that
    # touches task links. It owns the anchor repository and publishes an event
    # per task the merge moves, so the journal domain never constructs one.
    merge_service = JournalMergeService(
        repos.journal_repo,
        event_publisher,
        TaskJournalMergeService(
            task_anchor_repo=SqlTaskAnchorRepository(db_connection),
            event_publisher=event_publisher,
        ),
    )

    merged_journal = await merge_service.merge_journals(
        target_id=target_journal_id,
        source_id=merge_request.source_journal_id,
        transaction=db_connection,
        overrides=merge_request.overrides,
        fitness_merge_mode=merge_request.fitness_merge_mode,
        # An assistant merged these journals, so the tasks it moved say so.
        source=Provenance.MCP,
        changed_by="mcp",
    )

    # Fetch enriched target
    types, type_data = await read_journal_types_and_data(target_journal_id, repos)

    contacts = await fetch_contact_relationships_with_names(
        target_journal_id,
        repos.contact_relationship_repo,
        repos.contact_repo,
    )

    journal_tags = await repos.tag_repo.get_tags_for_journal(target_journal_id)

    # The merge leaves the survivor's parent_id alone, so the response has to
    # report it — otherwise the target reads back as orphaned.
    parent = await fetch_parent_journal(merged_journal, repos.journal_repo, user_id)

    response = JournalConverter.to_response(
        journal=merged_journal,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=journal_tags,
        parent=parent,
    )

    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_merge_candidates", "journal")
async def get_merge_candidates(
    journal_id: Annotated[
        int,
        Field(description="The ID of the journal to find merge candidates for"),
    ],
    limit: Annotated[
        int,
        Field(
            default=10,
            description="Maximum number of candidates to return (default: 10)",
        ),
    ] = 10,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Find journals that could be merged with a given journal.

    Returns journals with overlapping date ranges belonging to the same
    user, ordered by start date. Use this before merge_journals
    to identify suitable merge targets.

    Args:
        journal_id: The journal to find candidates for
        limit: Maximum number of candidates to return

    Returns:
        JSON string with merge candidate summaries and AI recommendations
    """
    repos = create_journal_tool_repositories(db_connection)

    # Owner-scoped, and it matters more here than anywhere else: the candidate
    # query below used to scope itself to ``target.user_id`` — the *owner's* id,
    # not the caller's — so one foreign journal id returned a list of that
    # user's overlapping journals, titles and content included (#1267).
    user_id = str(await get_current_user_id())
    target = await repos.journal_repo.find_by_id_for_user(journal_id, user_id)
    if not target:
        raise JournalNotFoundError(journal_id)

    # Find journals with overlapping date ranges for the same user. The caller's
    # id, not the target's: they are the same id now that the read above is
    # owner-scoped, and saying so keeps them the same if that guard is ever moved.
    overlapping = await repos.journal_repo.find_overlapping_for_user(
        user_id,
        exclude_journal_id=journal_id,
        date_range=target.event_date_range,
        limit=max(1, min(limit, 50)),
    )

    candidates: list[MergeCandidateResult] = []
    for candidate in overlapping:
        assert candidate.id is not None, "A stored journal has an id"
        candidate_id = candidate.id
        candidate_title = candidate.title
        candidate_content = candidate.content or ""
        candidate_start = candidate.event_date_range.start
        candidate_end = candidate.event_date_range.end

        # Fetch types and tags for each candidate
        c_types, _ = await read_journal_types_and_data(candidate_id, repos)
        c_tags = await repos.tag_repo.get_tags_for_journal(candidate_id)
        tag_names = [t.name for t in c_tags]

        content_excerpt = candidate_content[:200]
        candidates.append(
            MergeCandidateResult(
                id=candidate_id,
                title=candidate_title,
                content_excerpt=content_excerpt,
                event_date_range=EventDateRangeSchema(
                    start=candidate_start,
                    end=candidate_end,
                ),
                types=c_types,
                tags=tag_names,
                summary=(
                    f"'{candidate_title}' ({', '.join(c_types)}) "
                    f"overlaps with target date range"
                ),
            )
        )

    summary_text = (
        f"Found {len(candidates)} merge candidate(s) for "
        f"'{target.title}' (ID: {journal_id})"
    )
    if candidates:
        summary_text += ". Review each candidate and use merge_journals to combine."
    else:
        summary_text += ". No journals with overlapping date ranges found."

    response = MergeCandidatesResponse(
        target_journal_id=journal_id,
        target_title=target.title,
        candidates=candidates,
        summary=summary_text,
    )

    return MCPResponseBuilder.success_response(response)


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


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_template", "journal")
async def create_template(
    name: Annotated[str, Field(description="Template name")],
    template_type: Annotated[TemplateType, Field(description="Type of template")],
    region: Annotated[str | None, Field(default=None, description="Region")] = None,
    description: Annotated[
        str | None, Field(default=None, description="Description")
    ] = None,
    french_grade: Annotated[
        str | None, Field(default=None, description="French grade")
    ] = None,
    canyon_type: Annotated[
        CanyonType | None, Field(default=None, description="Canyon type")
    ] = None,
    water_gauge_name: Annotated[
        str | None, Field(default=None, description="Water gauge name")
    ] = None,
    is_vertical: Annotated[
        bool | None, Field(default=None, description="Is vertical")
    ] = None,
    is_horizontal: Annotated[
        bool | None, Field(default=None, description="Is horizontal")
    ] = None,
    climbing_type: Annotated[
        ClimbingType | None, Field(default=None, description="Climbing type")
    ] = None,
    grade: Annotated[int | None, Field(default=None, description="Grade")] = None,
    length: Annotated[
        int | None, Field(default=None, description="Length in metres")
    ] = None,
    pitches: Annotated[
        list[TemplatePitchInput] | None,
        Field(default=None, description="Pitches in order; pitch_number is required"),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    activity_template_service: ActivityTemplateService = mcp_depends(
        get_activity_template_service
    ),
) -> str:
    """
    Create a new activity template.
    """
    import uuid

    template_id = str(uuid.uuid4())
    pitch_entities: list[TemplatePitch] = []
    if pitches:
        pitch_entities.extend(
            TemplatePitch(template_id=template_id, **p.model_dump(mode="json"))
            for p in pitches
        )

    template = ActivityTemplate(
        id=template_id,
        user_id=user_id,
        name=name,
        template_type=template_type,
        region=region,
        description=description,
        french_grade=french_grade,
        canyon_type=canyon_type,
        water_gauge_name=water_gauge_name,
        is_vertical=is_vertical,
        is_horizontal=is_horizontal,
        climbing_type=climbing_type,
        grade=grade,
        length=length,
        pitches=pitch_entities,
    )

    saved_template = await activity_template_service.create(
        template, transaction=db_connection
    )

    response = ActivityTemplateMCPConverter.to_mcp_response(saved_template)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_template", "journal")
async def get_template(
    template_id: Annotated[str, Field(description="Template UUID")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get a specific activity template by ID.
    """
    repos = create_journal_tool_repositories(db_connection)

    try:
        import uuid

        uuid.UUID(template_id)
        template = await repos.activity_template_repo.find_by_id(template_id)
        if not template or template.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Template", template_id)

        response = ActivityTemplateMCPConverter.to_mcp_response(template)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "template_id", "Invalid UUID"
        )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_journal_template", "journal")
async def get_journal_template(
    journal_id: Annotated[int, Field(description="Journal id")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Retrieve the activity template an abseiling-derived journal was created from.

    Returns the referenced template (including its own standard pitches) for any
    abseiling-derived journal (ABSEILING_TRIP / CANYONING / CLIMBING / CAVING),
    reading the consolidated ``abseiling_data.template_id``. The template's
    standard pitches are returned even when the journal's own pitches have been
    edited. ``has_template`` is false when the journal has no template reference
    (or is not abseiling-derived).
    """
    repos = create_journal_tool_repositories(db_connection)

    journal = await repos.journal_repo.find_by_id(journal_id)
    if not journal or journal.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Journal", journal_id)

    abseiling_data = await repos.abseiling_data_repo.find_by_journal_id(journal_id)
    template = None
    if abseiling_data is not None and abseiling_data.template_id is not None:
        candidate = await repos.activity_template_repo.find_by_id(
            str(abseiling_data.template_id)
        )
        if candidate is not None and candidate.user_id == user_id:
            template = candidate

    if template is None:
        return MCPResponseBuilder.success_response(
            JournalTemplateMCPResponse(
                journal_id=journal_id,
                has_template=False,
                template=None,
                summary=f"Journal {journal_id} has no template reference.",
            )
        )

    return MCPResponseBuilder.success_response(
        JournalTemplateMCPResponse(
            journal_id=journal_id,
            has_template=True,
            template=ActivityTemplateMCPConverter.to_mcp_response(template),
            summary=f"Journal {journal_id} based on template: {template.name}.",
        )
    )


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("search_templates", "journal")
async def search_templates(
    template_type: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional type of template (e.g. canyoning, climbing) to filter by",
        ),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Search activity templates for the user.
    """
    repos = create_journal_tool_repositories(db_connection)

    templates = await repos.activity_template_repo.find_by_user(user_id)

    if template_type:
        templates = [t for t in templates if t.template_type == template_type]

    response = ActivityTemplateMCPConverter.to_mcp_list_response(templates)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_template", "journal")
async def update_template(
    template_id: Annotated[str, Field(description="Template UUID")],
    name: Annotated[
        str | None, Field(default=None, description="Template name")
    ] = None,
    region: Annotated[str | None, Field(default=None, description="Region")] = None,
    description: Annotated[
        str | None, Field(default=None, description="Description")
    ] = None,
    french_grade: Annotated[
        str | None, Field(default=None, description="French grade")
    ] = None,
    canyon_type: Annotated[
        CanyonType | None, Field(default=None, description="Canyon type")
    ] = None,
    water_gauge_name: Annotated[
        str | None, Field(default=None, description="Water gauge name")
    ] = None,
    is_vertical: Annotated[
        bool | None, Field(default=None, description="Is vertical")
    ] = None,
    is_horizontal: Annotated[
        bool | None, Field(default=None, description="Is horizontal")
    ] = None,
    climbing_type: Annotated[
        ClimbingType | None, Field(default=None, description="Climbing type")
    ] = None,
    grade: Annotated[int | None, Field(default=None, description="Grade")] = None,
    length: Annotated[
        int | None, Field(default=None, description="Length in metres")
    ] = None,
    pitches: Annotated[
        list[TemplatePitchInput] | None,
        Field(default=None, description="Pitches in order; pitch_number is required"),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    activity_template_service: ActivityTemplateService = mcp_depends(
        get_activity_template_service
    ),
) -> str:
    """
    Update an existing activity template.
    """
    repos = create_journal_tool_repositories(db_connection)

    try:
        import uuid

        uuid.UUID(template_id)
        template = await repos.activity_template_repo.find_by_id(template_id)
        if not template or template.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response("Template", template_id)

        if name is not None:
            template.name = name
        if region is not None:
            template.region = region
        if description is not None:
            template.description = description
        if french_grade is not None:
            template.french_grade = french_grade
        if canyon_type is not None:
            template.canyon_type = canyon_type
        if water_gauge_name is not None:
            template.water_gauge_name = water_gauge_name
        if is_vertical is not None:
            template.is_vertical = is_vertical
        if is_horizontal is not None:
            template.is_horizontal = is_horizontal
        if climbing_type is not None:
            template.climbing_type = climbing_type
        if grade is not None:
            template.grade = grade
        if length is not None:
            template.length = length

        if pitches is not None:
            pitch_entities: list[TemplatePitch] = []
            pitch_entities.extend(
                TemplatePitch(template_id=str(template.id), **p.model_dump(mode="json"))
                for p in pitches
            )
            template.pitches = pitch_entities

        try:
            template.__post_init__()
        except Exception as e:  # noqa: BLE001
            return MCPResponseBuilder.validation_error_response("template", str(e))

        saved_template = await activity_template_service.update(
            template, transaction=db_connection
        )

        response = ActivityTemplateMCPConverter.to_mcp_response(saved_template)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "template_id", "Invalid UUID"
        )


@tool(annotations=ADDITIVE_WRITE)
@mcp_unified_error_handler("create_gear_item", "journal")
async def create_gear_item(
    name: Annotated[str, Field(description="Gear item name")],
    model: Annotated[
        str | None, Field(default=None, description="Model name/number")
    ] = None,
    serial_number: Annotated[
        str | None, Field(default=None, description="Serial number")
    ] = None,
    purchase_date: Annotated[
        str | None, Field(default=None, description="Purchase date (YYYY-MM-DD)")
    ] = None,
    manufacturer: Annotated[
        str | None, Field(default=None, description="Manufacturer name")
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    gear_item_service: GearItemService = mcp_depends(get_gear_item_service),
) -> str:
    """
    Create a new gear item for tracking equipment (ropes, harnesses, helmets, etc.).
    """
    parsed_purchase_date = None
    if purchase_date:
        try:
            parsed_purchase_date = date.fromisoformat(purchase_date)
        except ValueError:
            return MCPResponseBuilder.validation_error_response(
                "purchase_date", "Invalid date format, use YYYY-MM-DD"
            )

    item = GearItem(
        user_id=user_id,
        name=name,
        model=model,
        serial_number=serial_number,
        purchase_date=parsed_purchase_date,
        manufacturer=manufacturer,
    )

    saved_item = await gear_item_service.create(item, transaction=db_connection)

    response = GearItemMCPConverter.to_mcp_response(saved_item)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_gear_items", "journal")
async def list_gear_items(
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List all gear items for the current user.
    """
    repos = create_journal_tool_repositories(db_connection)

    items = await repos.gear_item_repo.find_by_user(user_id)

    response = GearItemMCPConverter.to_mcp_list_response(items)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("get_gear_item", "journal")
async def get_gear_item(
    gear_item_id: Annotated[str, Field(description="Gear item UUID")],
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Get a specific gear item by ID.
    """
    repos = create_journal_tool_repositories(db_connection)

    try:
        import uuid as uuid_mod

        uuid_mod.UUID(gear_item_id)
        item = await repos.gear_item_repo.find_by_id(gear_item_id)
        if not item or item.user_id != user_id:
            return MCPResponseBuilder.not_found_error_response(
                "Gear item", gear_item_id
            )

        response = GearItemMCPConverter.to_mcp_response(item)
        return MCPResponseBuilder.success_response(response)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "gear_item_id", "Invalid UUID"
        )


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_gear_item", "journal")
async def update_gear_item(
    gear_item_id: Annotated[str, Field(description="Gear item UUID")],
    name: Annotated[str | None, Field(default=None, description="Updated name")] = None,
    model: Annotated[
        str | None,
        Field(default=None, description="Updated model (pass empty string to clear)"),
    ] = None,
    serial_number: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated serial number (pass empty string to clear)",
        ),
    ] = None,
    purchase_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated purchase date YYYY-MM-DD (pass empty string to clear)",
        ),
    ] = None,
    manufacturer: Annotated[
        str | None,
        Field(
            default=None,
            description="Updated manufacturer (pass empty string to clear)",
        ),
    ] = None,
    user_id: str = mcp_depends(get_current_user_id),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    gear_item_service: GearItemService = mcp_depends(get_gear_item_service),
) -> str:
    """
    Update an existing gear item.
    """
    repos = create_journal_tool_repositories(db_connection)

    try:
        import uuid as uuid_mod

        uuid_mod.UUID(gear_item_id)
    except ValueError:
        return MCPResponseBuilder.validation_error_response(
            "gear_item_id", "Invalid UUID"
        )

    item = await repos.gear_item_repo.find_by_id(gear_item_id)
    if not item or item.user_id != user_id:
        return MCPResponseBuilder.not_found_error_response("Gear item", gear_item_id)

    if name is not None:
        item.name = name
    if model is not None:
        item.model = None if model == "" else model
    if serial_number is not None:
        item.serial_number = None if serial_number == "" else serial_number
    if purchase_date is not None:
        if purchase_date == "":
            item.purchase_date = None
        else:
            try:
                item.purchase_date = date.fromisoformat(purchase_date)
            except ValueError:
                return MCPResponseBuilder.validation_error_response(
                    "purchase_date", "Invalid date format, use YYYY-MM-DD"
                )
    if manufacturer is not None:
        item.manufacturer = None if manufacturer == "" else manufacturer

    try:
        item.__post_init__()
    except Exception as e:  # noqa: BLE001
        return MCPResponseBuilder.validation_error_response("gear_item", str(e))

    # The service computes the changed-fields diff against the persisted state
    # and publishes GearItemUpdated with MCP provenance.
    saved_item = await gear_item_service.update(
        item,
        transaction=db_connection,
        changed_by="mcp",
        source=Provenance.MCP,
    )

    response = GearItemMCPConverter.to_mcp_response(saved_item)
    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("list_journal_tags", "tag")
async def list_journal_tags(
    limit: Annotated[
        int, Field(description="Maximum number of tags to return", ge=1, le=100)
    ] = 50,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    List all available journal tags for organising journal entries.

    Journal tags are a separate namespace from contact tags — use
    list_contact_tags for those. Tags are hierarchical: a tag with a
    parent_id is a child of that tag, and a null parent_id marks a root tag.

    Args:
        limit: Maximum number of tags to return (1-100, default: 50)

    Returns:
        JSON string containing journal tags ordered by name, each with its
        colour, description, and parent_id for reconstructing the hierarchy.
    """
    repos = create_journal_tool_repositories(db_connection)

    all_tags = await repos.tag_repo.get_all()
    tags = all_tags[:limit]

    tag_data = [
        JournalTagInfo(
            id=str(tag.id),
            name=tag.name,
            color=tag.color,
            description=tag.description,
            parent_id=str(tag.parent_id) if tag.parent_id else None,
            created_at=tag.created_at.isoformat() if tag.created_at else None,
        )
        for tag in tags
    ]

    response_data = JournalTagListMCPResponse(
        tags=tag_data,
        total_count=len(tag_data),
        summary=f"Found {len(tag_data)} journal tag(s). "
        "Journal tags categorise journal entries by theme, project, or activity.",
        suggestions=[
            "Use tags to group journals by theme (training, travel, reflection)",
            "Nest tags under a parent to build a hierarchy (activities/climbing)",
            "Assign tags when creating or updating a journal entry",
        ],
    )

    return MCPResponseBuilder.success_response(response_data)


@tool(annotations=IDEMPOTENT_WRITE)
@mcp_unified_error_handler("update_journal_tag", "tag")
async def update_journal_tag(
    tag_id: Annotated[str, Field(description="UUID of the journal tag to update")],
    name: Annotated[
        str | None, Field(description="New tag name (must be unique)")
    ] = None,
    color: Annotated[
        str | None, Field(description="New hex colour code, e.g. #FF0000")
    ] = None,
    description: Annotated[
        str | None, Field(description="New description of what the tag is for")
    ] = None,
    parent_id: Annotated[
        str | None, Field(description="UUID of the new parent tag")
    ] = None,
    move_to_root: Annotated[
        bool,
        Field(description="Clear the tag's parent, making it a root tag"),
    ] = False,
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Update an existing journal tag's name, colour, description, or parent.

    Journal tags are a separate namespace from contact tags — use
    update_contact_tag for those, and list_journal_tags to find tag UUIDs.

    Only the arguments you supply are changed; omitted arguments are left as
    they are. To move a tag to the root of the hierarchy, pass
    move_to_root=true rather than a null parent_id, since an omitted parent_id
    means "leave the parent alone".

    Args:
        tag_id: UUID of the tag to update
        name: New name; must not collide with another tag (case-insensitive)
        color: New hex colour code (7 characters, e.g. #FF0000)
        description: New description of what the tag is for
        parent_id: UUID of the new parent tag
        move_to_root: Clear the parent instead of setting one

    Returns:
        JSON string containing the updated tag.
    """
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", f"Invalid tag UUID: {tag_id}") from e

    parent_uuid = None
    if parent_id is not None:
        try:
            parent_uuid = UUID(parent_id)
        except ValueError as e:
            raise JournalValidationError(
                "parent_id", f"Invalid parent tag UUID: {parent_id}"
            ) from e

    # The service owns the unit of work; MCP tools never open transactions.
    updated = await tag_service.update_tag(
        tag_id=tag_uuid,
        transaction=db_connection,
        name=name,
        color=color,
        description=description,
        parent_id=parent_uuid,
        set_parent_null=move_to_root,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    response_data = JournalTagInfo(
        id=str(updated.id),
        name=updated.name,
        color=updated.color,
        description=updated.description,
        parent_id=str(updated.parent_id) if updated.parent_id else None,
        created_at=updated.created_at.isoformat() if updated.created_at else None,
    )

    return MCPResponseBuilder.success_response(response_data)


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("delete_journal_tag", "tag")
async def delete_journal_tag(
    tag_id: Annotated[str, Field(description="UUID of the journal tag to delete")],
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Delete a journal tag, removing it from every journal it is assigned to.

    Journal tags are a separate namespace from contact tags — use
    delete_contact_tag for those, and list_journal_tags to find tag UUIDs.

    This is not blocked when the tag is in use: journals keep their content and
    simply lose this tag. Any child tags of the deleted tag are re-parented to
    the root of the hierarchy rather than being deleted.

    Args:
        tag_id: UUID of the tag to delete

    Returns:
        JSON string confirming the deletion.
    """
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", f"Invalid tag UUID: {tag_id}") from e

    # The service owns the unit of work; MCP tools never open transactions.
    await tag_service.delete_tag(
        tag_id=tag_uuid,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    class DeleteJournalTagResponse(BaseModel):
        status: str
        summary: str

    return MCPResponseBuilder.success_response(
        DeleteJournalTagResponse(
            status="success",
            summary=f"Deleted journal tag {tag_id} and removed it from all journals",
        )
    )


@tool(annotations=DESTRUCTIVE_WRITE)
@mcp_unified_error_handler("merge_journal_tag", "tag")
async def merge_journal_tag(
    source_tag_id: Annotated[
        str, Field(description="UUID of the journal tag to merge away and delete")
    ],
    target_tag_id: Annotated[
        str, Field(description="UUID of the journal tag to merge into (the survivor)")
    ],
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
) -> str:
    """
    Merge one journal tag into another, consolidating duplicates.

    Journal tags are a separate namespace from contact tags — use
    merge_contact_tags for those, and list_journal_tags to find tag UUIDs.

    Every journal tagged with the source tag ends up tagged with the target
    instead; a journal already carrying both keeps a single tag. Child tags of
    the source are adopted by the target rather than moved to the root. The
    source tag is then deleted.

    A tag cannot be merged into itself, nor into one of its own descendants —
    the surviving hierarchy would run through a tag that no longer exists.

    Args:
        source_tag_id: UUID of the tag to merge away and delete
        target_tag_id: UUID of the tag that survives the merge

    Returns:
        JSON string confirming the merge.
    """
    try:
        source_uuid = UUID(source_tag_id)
    except ValueError as e:
        raise JournalValidationError(
            "source_tag_id", f"Invalid tag UUID: {source_tag_id}"
        ) from e

    try:
        target_uuid = UUID(target_tag_id)
    except ValueError as e:
        raise JournalValidationError(
            "target_tag_id", f"Invalid tag UUID: {target_tag_id}"
        ) from e

    # The service owns the unit of work; MCP tools never open transactions.
    await tag_service.merge_tag(
        source_id=source_uuid,
        target_id=target_uuid,
        transaction=db_connection,
        source=Provenance.MCP,
        changed_by="mcp",
    )

    class MergeJournalTagResponse(BaseModel):
        status: str
        summary: str

    return MCPResponseBuilder.success_response(
        MergeJournalTagResponse(
            status="success",
            summary=(
                f"Merged journal tag {source_tag_id} into {target_tag_id}; "
                "the source tag was deleted"
            ),
        )
    )


def register_journal_tools(mcp: FastMCP[None]) -> None:
    """Register every journal-domain MCP tool with the FastMCP server."""
    register_journal_read_tools(mcp)
    register_journal_entry_tools(mcp)
    register_journal_search_tools(mcp)
    register_journal_hierarchy_tools(mcp)
    register_activity_tools(mcp)
    register_journal_history_tools(mcp)
    register_journal_contact_tools(mcp)
    mcp.add_tool(list_calendars)
    mcp.add_tool(create_calendar)
    mcp.add_tool(update_calendar)
    mcp.add_tool(delete_calendar)
    mcp.add_tool(merge_journals)
    mcp.add_tool(get_merge_candidates)
    mcp.add_tool(list_review_items)
    mcp.add_tool(dismiss_review_item)
    mcp.add_tool(list_incomplete_outdoor_activities)
    mcp.add_tool(dismiss_incomplete_outdoor_activity)
    mcp.add_tool(undismiss_incomplete_outdoor_activity)
    mcp.add_tool(get_outdoor_dashboard)
    mcp.add_tool(get_daily_summary)
    mcp.add_tool(create_template)
    mcp.add_tool(get_template)
    mcp.add_tool(get_journal_template)
    mcp.add_tool(search_templates)
    mcp.add_tool(update_template)
    mcp.add_tool(create_gear_item)
    mcp.add_tool(list_gear_items)
    mcp.add_tool(get_gear_item)
    mcp.add_tool(update_gear_item)
    mcp.add_tool(list_journal_tags)
    mcp.add_tool(update_journal_tag)
    mcp.add_tool(delete_journal_tag)
    mcp.add_tool(merge_journal_tag)
    register_journal_series_tools(mcp)
    register_journal_route_tools(mcp)
