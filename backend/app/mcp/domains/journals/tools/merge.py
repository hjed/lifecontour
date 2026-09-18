"""MCP tools for merging duplicate journals."""

from typing import Annotated

from core_shared.models.history import Provenance
from core_shared.models.journals import (
    JournalNotFoundError,
)
from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_type_data_reader import (
    read_journal_types_and_data,
)
from app.core.tasks.adapters.sql.task_anchor_repository import SqlTaskAnchorRepository
from app.core.tasks.services.task_journal_merge_service import (
    TaskJournalMergeService,
)
from app.infrastructure.events.outbox_event_publisher import OutboxEventPublisher
from app.mcp.domains.journals.converters import (
    JournalConverter,
)
from app.mcp.domains.journals.schemas import (
    EventDateRangeSchema,
    MergeCandidateResult,
    MergeCandidatesResponse,
    MergeJournalMCPRequest,
)
from app.mcp.domains.journals.tools._shared import (
    create_journal_tool_repositories,
    fetch_contact_relationships_with_names,
    fetch_parent_journal,
)
from app.mcp.shared.annotations import (
    DESTRUCTIVE_WRITE,
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_outbox_event_publisher,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder

# EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
# These will be created when the user provides type_data


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


def register_journal_merge_tools(mcp: FastMCP[None]) -> None:
    """Register the merge MCP tools with the FastMCP server."""
    mcp.add_tool(merge_journals)
    mcp.add_tool(get_merge_candidates)
