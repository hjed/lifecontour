"""Full-text journal search for AI clients, on top of the MeiliSearch
``SearchService`` the REST API uses (word matching, typo tolerance, relevance).

A backend failure is raised as :class:`SearchServiceUnavailableError` so the
caller can report it loudly rather than as an empty result, and
:func:`explain_empty_result` says what an empty result means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any

from meilisearch.errors import MeilisearchError

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.search.exceptions import SearchServiceUnavailableError
from app.infrastructure.search.search_service import SearchService

if TYPE_CHECKING:
    from core_shared.models.journals import Journal

    from app.core.journal.models.repositories import JournalRepository

SEARCH_UNAVAILABLE_HINT = (
    "The search backend (MeiliSearch) could not be reached, so this is NOT an "
    "empty result. Retry shortly, or use browse_journals_by_date_window / "
    "search_activities, which are database-backed."
)


@dataclass(frozen=True)
class JournalSearchHit:
    """One journal matched by a full-text search."""

    id: int
    title: str
    content_excerpt: str
    start: datetime
    end: datetime
    types: list[str]
    highlighted: dict[str, str]


def hit_from_document(hit: dict[str, Any]) -> JournalSearchHit:
    """Build a :class:`JournalSearchHit` from a MeiliSearch document hit."""
    start = hit.get("event_date_range_start")
    end = hit.get("event_date_range_end")
    now = datetime.now(UTC)
    content = hit.get("content") or ""
    formatted = hit.get("_formatted") or {}
    highlighted = {
        key: value
        for key in ("title", "content", "location")
        if isinstance(value := formatted.get(key), str) and "<mark>" in value
    }
    return JournalSearchHit(
        id=int(hit["id"]),
        title=hit.get("title") or "",
        content_excerpt=content[:200] + "..." if len(content) > 200 else content,
        start=datetime.fromisoformat(start) if start else now,
        end=datetime.fromisoformat(end) if end else now,
        types=[str(t).lower() for t in hit.get("types", [])],
        highlighted=highlighted,
    )


def search_journals_text(
    search_service: SearchService,
    *,
    query: str,
    user_id: str,
    limit: int,
    offset: int = 0,
    type_filters: list[str] | None = None,
    journal_ids: set[int] | None = None,
) -> tuple[list[JournalSearchHit], int, int]:
    """Run a journal full-text search through MeiliSearch (REST parity).

    Returns ``(results, total_hits, processing_time_ms)``. A MeiliSearch
    failure is raised as :class:`SearchServiceUnavailableError` so the caller
    reports it loudly rather than as an empty result.
    """
    if journal_ids is not None and not journal_ids:
        # Nothing to intersect with; an empty `id IN []` is a Meili error.
        return [], 0, 0
    filters: dict[str, Any] = {"user_id": user_id}
    if type_filters:
        filters["types"] = [t.upper() for t in type_filters]
    if journal_ids is not None:
        filters["id"] = sorted(journal_ids)
    try:
        raw = search_service.search_journals(
            query=query, filters=filters, limit=limit, offset=offset
        )
    except MeilisearchError as exc:
        raise SearchServiceUnavailableError("MeiliSearch", str(exc)) from exc
    results = [hit_from_document(hit) for hit in raw.get("hits", [])]
    return (
        results,
        int(raw.get("estimated_total_hits", len(results))),
        int(raw.get("processing_time_ms", 0)),
    )


@dataclass(frozen=True)
class EmptyResultDiagnostics:
    """Why a search came back empty (see the MCP ``diagnostics`` block)."""

    search_backend: str
    filters: dict[str, Any]
    journals_for_user_total: int
    journals_linked_to_source: int | None
    suggestions: list[str]


async def explain_empty_result(
    journal_repo: SqlJournalRepository,
    user_id: str,
    *,
    search_backend: str,
    filters: dict[str, Any],
    source_filter: str | None = None,
    journals_linked_to_source: int | None = None,
    suggestions: list[str],
) -> EmptyResultDiagnostics:
    """Explain an empty result so the agent can tell absence from a bad query."""
    total = await journal_repo.count_all(user_id=user_id)
    if source_filter is not None and journals_linked_to_source is None:
        journals_linked_to_source = len(
            await journal_repo.find_ids_by_integration_source(user_id, source_filter)
        )
    return EmptyResultDiagnostics(
        search_backend=search_backend,
        filters={k: v for k, v in filters.items() if v not in (None, "", [])},
        journals_for_user_total=total,
        journals_linked_to_source=journals_linked_to_source,
        suggestions=suggestions,
    )


SEARCH_SUGGESTIONS = [
    "Try fewer or different words — every word must match somewhere in the "
    "title, content or location (typos are tolerated).",
    "If you know roughly when it happened, use browse_journals_by_date_window.",
    "For activities, search_activities filters by activity type and date.",
    "Drop the types / integration_source filter to see whether it excluded "
    "the journal.",
]

WINDOW_SUGGESTIONS = [
    "Widen the window (days_back / days_forward) or move anchor_date.",
    "Dates are matched on the journal's event date range, in UTC.",
    "Use search_journals for a text search without a date restriction.",
]


def compute_date_window(
    anchor: date, days_back: int, days_forward: int
) -> tuple[date, date]:
    """Compute a date window around an anchor date.

    Args:
        anchor: The centre date for the window.
        days_back: How many days before the anchor to include.
        days_forward: How many days after the anchor to include.

    Returns:
        Tuple of (window_start, window_end) as date objects.
    """
    return (
        anchor - timedelta(days=days_back),
        anchor + timedelta(days=days_forward),
    )


@dataclass(frozen=True)
class DateWindowOutcome:
    """A page of the journals in a date window.

    ``searched`` says which read produced the page: a full-text search
    (``hits``) or a database listing (``journals``); the other list is empty.
    ``start_iso`` is the window's first day; ``total_count`` counts every match,
    not just this page.
    """

    window_start: date
    window_end: date
    start_iso: str
    total_count: int
    searched: bool
    journals: list[Journal]
    hits: list[JournalSearchHit]


class JournalSearchService:
    """Finds a user's journals by date window, filters and full text."""

    def __init__(
        self, journal_repo: JournalRepository, search_service: SearchService
    ) -> None:
        self.journal_repo = journal_repo
        self.search_service = search_service

    async def browse_window(
        self,
        user_id: str,
        *,
        anchor: date,
        days_back: int,
        days_forward: int,
        type_filters: list[str],
        search: str | None,
        limit: int,
        offset: int,
    ) -> DateWindowOutcome:
        """The journals whose event range overlaps the window around ``anchor``.

        One type filter is applied by the database; several are applied only
        to a text search. A non-blank ``search`` runs through MeiliSearch
        restricted to the window's journals.

        Raises:
            SearchServiceUnavailableError: If the text search cannot reach
                MeiliSearch.
        """
        window_start, window_end = compute_date_window(anchor, days_back, days_forward)

        start_iso = window_start.isoformat()
        # Use end-of-day for window_end so journals occurring later on that
        # day are included (the repo compares event_date_range_start <= end_date,
        # and date.isoformat() alone yields midnight which would exclude them).
        end_iso = datetime.combine(window_end, time(23, 59, 59), tzinfo=UTC).isoformat()

        journal_type = type_filters[0] if len(type_filters) == 1 else None

        total_count = await self.journal_repo.count_all(
            user_id=user_id,
            journal_type=journal_type,
            start_date=start_iso,
            end_date=end_iso,
        )

        if search and search.strip():
            # Text search inside the window goes through MeiliSearch (word
            # matching and typo tolerance, as in the web UI) restricted to the
            # window's journal ids, rather than a literal substring match.
            in_window = await self.journal_repo.get_all(
                user_id=user_id,
                limit=max(total_count, 1),
                offset=0,
                journal_type=journal_type,
                start_date=start_iso,
                end_date=end_iso,
            )
            window_ids = {j.id for j in in_window if j.id is not None}
            matched, _total, _ms = search_journals_text(
                self.search_service,
                query=search.strip(),
                user_id=user_id,
                limit=max(len(window_ids), 1),
                type_filters=type_filters,
                journal_ids=window_ids,
            )
            return DateWindowOutcome(
                window_start=window_start,
                window_end=window_end,
                start_iso=start_iso,
                total_count=len(matched),
                searched=True,
                journals=[],
                hits=matched[offset : offset + limit],
            )

        journals = await self.journal_repo.get_all(
            user_id=user_id,
            limit=limit,
            offset=offset,
            journal_type=journal_type,
            start_date=start_iso,
            end_date=end_iso,
        )
        return DateWindowOutcome(
            window_start=window_start,
            window_end=window_end,
            start_iso=start_iso,
            total_count=total_count,
            searched=False,
            journals=journals,
            hits=[],
        )
