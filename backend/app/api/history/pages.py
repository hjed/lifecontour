"""The paged history answer shared by the owner-scoped history routes.

The task and task-list history endpoints take the same query parameters and
answer with the same ``HistoryListResponse``; only the resource type and the
path differ. Building that answer here keeps them identical by construction.
"""

from typing import Annotated

from fastapi import Query

from app.api.common.identifiers import INT32_MAX
from app.api.common.schemas import create_pagination_links, create_pagination_meta
from app.api.history.converters import HistoryConverter
from app.api.history.schemas import HistoryListResponse
from app.core.history.models import FieldHistoryEntry

# ``page`` reaches SQL as ``(page - 1) * limit``, bound to PostgreSQL's
# ``OFFSET`` as a bigint, so it is bounded to keep an absurd value a 400 rather
# than a database error. ``limit`` is capped so no page is a bulk export.
HistoryPageQuery = Annotated[int, Query(description="Page number", ge=1, le=INT32_MAX)]
HistoryLimitQuery = Annotated[int, Query(description="Items per page", ge=1, le=100)]


def history_offset(page: int, limit: int) -> int:
    """The repository offset for a 1-based page."""
    return (page - 1) * limit


def history_page_response(
    entries: list[FieldHistoryEntry],
    *,
    total_count: int,
    resource_type: str,
    self_url: str,
    page: int,
    limit: int,
) -> HistoryListResponse:
    """One page of history as JSON:API, with pagination meta and links."""
    return HistoryListResponse(
        data=[HistoryConverter.to_resource(entry, resource_type) for entry in entries],
        meta=create_pagination_meta(total_count, page, limit),
        links=create_pagination_links(self_url, page, limit, total_count),
    )
