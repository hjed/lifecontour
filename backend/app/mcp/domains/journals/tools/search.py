"""MCP tools for finding journals: filtered full-text search and date windows.

The search itself belongs to ``JournalSearchService``; these tools parse the
arguments, report an unreachable search backend, and explain empty results.
"""

import dataclasses
from datetime import date
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.tools import tool
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.integrations.link_sources import (
    resolve_journal_source,
)
from app.core.journal.services.journal_search_service import (
    SEARCH_SUGGESTIONS,
    SEARCH_UNAVAILABLE_HINT,
    WINDOW_SUGGESTIONS,
    JournalSearchFilters,
    JournalSearchHit,
    JournalSearchService,
    explain_empty_result,
)
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.search.exceptions import SearchServiceUnavailableError
from app.mcp.domains.journals.schemas import (
    EventDateRangeSchema,
    JournalDateWindowResponse,
    JournalSearchResponse,
    JournalSearchResult,
    SearchDiagnostics,
)
from app.mcp.domains.journals.tools._shared import (
    JournalToolRepositories,
    build_search_results,
    create_journal_tool_repositories,
    fetch_types_for_journal,
    journal_to_search_result,
    parse_optional_datetime_filter,
    parse_type_filters,
)
from app.mcp.shared.annotations import (
    READ_ONLY,
)
from app.mcp.shared.decorators import mcp_unified_error_handler
from app.mcp.shared.dependencies import (
    get_async_connection,
    get_current_user_id,
    get_journal_search_service,
    get_journal_tag_service,
    mcp_depends,
)
from app.mcp.shared.response_builders import MCPResponseBuilder


def _parse_integration_source_filter(value: str | None) -> str | None:
    """Normalise an integration source filter (None passes through)."""
    return None if value is None else resolve_journal_source(value)


def _search_hit_to_result(hit: JournalSearchHit) -> JournalSearchResult:
    """Render a search hit as the MCP search result schema."""
    return JournalSearchResult(
        id=hit.id,
        title=hit.title,
        content_excerpt=hit.content_excerpt,
        event_date_range=EventDateRangeSchema(start=hit.start, end=hit.end),
        types=hit.types,
        tags=[],
        highlighted=hit.highlighted,
        summary=f"Journal: {hit.title}",
    )


async def _zero_result_diagnostics(
    repos: JournalToolRepositories,
    user_id: str,
    *,
    search_backend: str,
    filters: dict[str, Any],
    source_filter: str | None = None,
    journals_linked_to_source: int | None = None,
    suggestions: list[str],
) -> SearchDiagnostics:
    """MCP schema for :func:`explain_empty_result`."""
    explained = await explain_empty_result(
        repos.journal_repo,
        user_id,
        search_backend=search_backend,
        filters=filters,
        source_filter=source_filter,
        journals_linked_to_source=journals_linked_to_source,
        suggestions=suggestions,
    )
    return SearchDiagnostics(**dataclasses.asdict(explained))


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("search_journals", "journal")
async def search_journals(
    query: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Search query for full-text search",
        ),
    ] = None,
    types: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Comma-separated list of journal types to filter by",
        ),
    ] = None,
    integration_source: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Filter by integration source (e.g. 'strava', "
            "'google_calendar', 'immich_album'). "
            "Returns only journals linked to the specified external system.",
        ),
    ] = None,
    start_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: ISO date or datetime lower bound. Journals "
            "whose event range overlaps the window are returned.",
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: ISO date or datetime upper bound. A bare "
            "date includes the whole day.",
        ),
    ] = None,
    tags: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional: Comma-separated journal tag names or tag ids "
            "(see list_journal_tags). A journal matching any of them — or any "
            "of their descendant tags — is returned.",
        ),
    ] = None,
    contact_id: Annotated[
        int | None,
        Field(
            default=None, description="Optional: Only journals linked to this contact"
        ),
    ] = None,
    calendar_id: Annotated[
        str | None,
        Field(default=None, description="Optional: Only journals on this calendar"),
    ] = None,
    parent_id: Annotated[
        int | None,
        Field(
            default=None,
            description="Optional: Only the direct children of this journal "
            "(e.g. the days of a trip)",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=20,
            description="Maximum number of results to return (default: 20)",
        ),
    ] = 20,
    offset: Annotated[
        int,
        Field(default=0, ge=0, description="Number of results to skip (default: 0)"),
    ] = 0,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    journal_search_service: JournalSearchService = mcp_depends(
        get_journal_search_service
    ),
    tag_service: JournalTagService = mcp_depends(get_journal_tag_service),
) -> str:
    """
    Search journals with filtering options.

    With a ``query``, the search runs through MeiliSearch exactly like the web
    UI (word matching, typo tolerance, relevance ranking) — not a literal
    substring match — so "Zion canyoning" finds a canyoning journal whose text
    mentions Zion. Without a query, journals are listed from the database
    (newest first). Every other argument is a filter, and they combine: they
    narrow the listing and the full-text query alike, so
    ``query="canyon", start_date="2025-10-01", tags="trips"`` searches the text
    of October's trip journals only.
    If MeiliSearch is unreachable the tool returns an explicit
    "Search unavailable" error, never a silent empty result.

    Args:
        query: Optional search query for full-text search
        types: Optional comma-separated list of journal types
        integration_source: Optional integration source filter (strava, google_calendar)
        start_date: Optional ISO date/datetime lower bound for the event range
        end_date: Optional ISO date/datetime upper bound for the event range
        tags: Optional comma-separated tag names or tag ids
        contact_id: Optional contact the journal must be linked to
        calendar_id: Optional calendar the journal must belong to
        parent_id: Optional parent journal whose direct children to return
        limit: Maximum number of results to return
        offset: Number of results to skip, for paging

    Returns:
        JSON string containing AI-friendly search results with:
        - List of matching journals with excerpts
        - Search metadata (total hits, processing time)
        - Contextual summary for AI understanding

    Raises:
        ValueError: If invalid filter values are provided
    """
    user_id = await get_current_user_id()
    repos = create_journal_tool_repositories(db_connection)
    type_filters = parse_type_filters(types)
    source_filter = _parse_integration_source_filter(integration_source)
    start_filter = parse_optional_datetime_filter(start_date, "start_date")
    end_filter = parse_optional_datetime_filter(end_date, "end_date", is_end=True)
    tag_filters = (
        await tag_service.resolve_filter_tag_ids(tags.split(",")) if tags else None
    )

    # The filters as the agent spelled them, for the diagnostics.
    reported_filters: dict[str, Any] = {
        "types": types,
        "integration_source": source_filter,
        "start_date": start_date,
        "end_date": end_date,
        "tags": tags,
        "contact_id": contact_id,
        "calendar_id": calendar_id,
        "parent_id": parent_id,
    }

    async def read_types(journal_id: int) -> list[str]:
        journal_types, _ = await fetch_types_for_journal(journal_id, repos)
        return journal_types

    try:
        outcome = await journal_search_service.search(
            user_id,
            query=query,
            filters=JournalSearchFilters(
                type_filters=type_filters,
                source_filter=source_filter,
                start_date=start_filter,
                end_date=end_filter,
                tag_ids=tag_filters,
                contact_id=contact_id,
                calendar_id=calendar_id,
                parent_id=parent_id,
            ),
            limit=limit,
            offset=offset,
            read_types=read_types,
        )
    except SearchServiceUnavailableError as exc:
        return MCPResponseBuilder.error_response(
            error_type="Search unavailable",
            message=exc.message,
            context={"query": query, "hint": SEARCH_UNAVAILABLE_HINT},
        )

    source_journal_ids = outcome.source_journal_ids
    if source_filter is not None and not source_journal_ids:
        # No journals match the integration source — return empty, and say
        # whether anything is linked to that source at all.
        response = JournalSearchResponse(
            results=[],
            query=query,
            total_hits=0,
            processing_time_ms=0,
            summary=f"Found 0 journal(s) linked to {source_filter}",
            diagnostics=await _zero_result_diagnostics(
                repos,
                user_id,
                search_backend="database",
                filters=reported_filters,
                journals_linked_to_source=0,
                suggestions=[
                    f"No journal is linked to {source_filter}. Check "
                    "list_integrations, or trigger_sync if the integration "
                    "is connected but has not imported yet.",
                    *SEARCH_SUGGESTIONS[:2],
                ],
            ),
        )
        return MCPResponseBuilder.success_response(response)

    summary_suffix = f" linked to {source_filter}" if source_filter else ""
    total_hits = outcome.total_hits

    if outcome.backend == "meilisearch":
        results = [_search_hit_to_result(hit) for hit in outcome.hits]
        diagnostic_filters = {"query": query, **reported_filters}
        suggestions = SEARCH_SUGGESTIONS
    else:
        journal_types = outcome.journal_types
        results = (
            await build_search_results(outcome.journals, repos)
            if journal_types is None
            else [
                journal_to_search_result(journal, types=journal_types[journal.id])
                for journal in outcome.journals
                if journal.id is not None
            ]
        )
        diagnostic_filters = reported_filters
        suggestions = SEARCH_SUGGESTIONS[1:]

    response = JournalSearchResponse(
        results=results,
        query=query,
        total_hits=total_hits,
        processing_time_ms=outcome.processing_time_ms,
        summary=f"Found {total_hits} journal(s){summary_suffix}",
        diagnostics=await _zero_result_diagnostics(
            repos,
            user_id,
            search_backend=outcome.backend,
            filters=diagnostic_filters,
            source_filter=source_filter,
            journals_linked_to_source=(
                len(source_journal_ids) if source_journal_ids else None
            ),
            suggestions=suggestions,
        )
        if total_hits == 0
        else None,
    )
    return MCPResponseBuilder.success_response(response)


@tool(annotations=READ_ONLY)
@mcp_unified_error_handler("browse_journals_by_date_window", "journal")
async def browse_journals_by_date_window(
    anchor_date: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional ISO date to anchor the window on (defaults to today "
                "in the user's configured timezone). Example: '2026-04-02'"
            ),
        ),
    ] = None,
    days_back: Annotated[
        int,
        Field(
            default=2,
            ge=0,
            description="Number of days before the anchor date to include (default: 2)",
        ),
    ] = 2,
    days_forward: Annotated[
        int,
        Field(
            default=4,
            ge=0,
            description="Number of days after the anchor date to include (default: 4)",
        ),
    ] = 4,
    types: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional comma-separated journal types to filter by",
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional text search query within the window",
        ),
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=50,
            ge=1,
            description="Maximum results to return per page (default: 50)",
        ),
    ] = 50,
    offset: Annotated[
        int,
        Field(
            default=0,
            ge=0,
            description="Number of results to skip for pagination (default: 0)",
        ),
    ] = 0,
    db_connection: AsyncConnection = mcp_depends(get_async_connection),
    journal_search_service: JournalSearchService = mcp_depends(
        get_journal_search_service
    ),
) -> str:
    """
    Browse journals within a date window anchored on a given date.

    Returns journals falling within [anchor - days_back, anchor + days_forward].
    Defaults to a 7-day window (2 days back, 4 days forward from today).
    Days are the user's local days: "today" and each day's midnight are taken in
    the user's configured timezone (UTC when none is set), which the response
    reports as ``timezone``.
    Supports pagination via offset/limit and optional type/search filters.

    Use this tool for time-oriented journal browsing, such as seeing
    what happened recently or what is coming up.

    Args:
        anchor_date: ISO date string to centre the window on (defaults to today
            in the user's timezone)
        days_back: Days before the anchor to include
        days_forward: Days after the anchor to include
        types: Comma-separated journal types to filter by
        search: Text search query
        limit: Page size
        offset: Pagination offset

    Returns:
        JSON with journals in the window, window boundaries, and pagination info
    """
    user_id = await get_current_user_id()
    repos = create_journal_tool_repositories(db_connection)

    # Parsed here, but left unresolved: the service defaults it to today in the
    # user's timezone, which is also the zone its day boundaries are drawn in.
    requested_anchor: date | None = None
    if anchor_date is not None:
        try:
            requested_anchor = date.fromisoformat(anchor_date.strip())
        except ValueError as exc:
            raise ValueError(
                f"Invalid anchor_date '{anchor_date}'. Must be ISO format (YYYY-MM-DD)."
            ) from exc

    type_filters = parse_type_filters(types)

    try:
        window = await journal_search_service.browse_window(
            user_id,
            anchor=requested_anchor,
            days_back=days_back,
            days_forward=days_forward,
            type_filters=type_filters,
            search=search,
            limit=limit,
            offset=offset,
        )
    except SearchServiceUnavailableError as exc:
        return MCPResponseBuilder.error_response(
            error_type="Search unavailable",
            message=exc.message,
            context={"search": search, "hint": SEARCH_UNAVAILABLE_HINT},
        )

    results = (
        [_search_hit_to_result(hit) for hit in window.hits]
        if window.searched
        else await build_search_results(window.journals, repos)
    )
    total_count = window.total_count
    start_iso = window.start_iso
    end_iso = window.window_end.isoformat()
    anchor_iso = window.anchor.isoformat()

    has_more = (offset + limit) < total_count

    response = JournalDateWindowResponse(
        results=results,
        window_start=start_iso,
        window_end=end_iso,
        anchor_date=anchor_iso,
        timezone=window.timezone,
        total_count=total_count,
        has_more=has_more,
        summary=(
            f"Found {total_count} journal(s) between "
            f"{start_iso} and {end_iso} "
            f"(anchored on {anchor_iso}, {window.timezone})"
        ),
        diagnostics=await _zero_result_diagnostics(
            repos,
            user_id,
            search_backend="meilisearch" if search and search.strip() else "database",
            filters={
                "window_start": start_iso,
                "window_end": end_iso,
                "timezone": window.timezone,
                "types": types,
                "search": search,
            },
            suggestions=(
                [*WINDOW_SUGGESTIONS, SEARCH_SUGGESTIONS[0]]
                if search
                else WINDOW_SUGGESTIONS
            ),
        )
        if total_count == 0
        else None,
    )

    return MCPResponseBuilder.success_response(response)


def register_journal_search_tools(mcp: FastMCP[None]) -> None:
    """Register the search MCP tools with the FastMCP server."""
    mcp.add_tool(search_journals)
    mcp.add_tool(browse_journals_by_date_window)
