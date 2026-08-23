"""Full-text journal search for AI clients, on top of the MeiliSearch
``SearchService`` the REST API uses (word matching, typo tolerance, relevance).

A backend failure is raised as :class:`SearchServiceUnavailableError` so the
caller can report it loudly rather than as an empty result, and
:func:`explain_empty_result` says what an empty result means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from meilisearch.errors import MeilisearchError

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.search.exceptions import SearchServiceUnavailableError
from app.infrastructure.search.search_service import SearchService

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
            query=query, filters=filters, limit=limit, offset=0
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
