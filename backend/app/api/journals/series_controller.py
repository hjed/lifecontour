"""Journal series API endpoints.

A series groups related journal entries — auto-created from recurring Google
Calendar events during sync, or created manually (e.g. a series of medical
appointments). Registered before the main journals router so the literal
``/journals/series`` paths win over ``/journals/{journal_id}``.
"""

from core_shared.models.journals import (
    JournalValidationError,
)
from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import JsonApiLinks, get_request_base_url
from app.api.journals.schemas import (
    JournalSeriesCreateRequest,
    JournalSeriesListResponse,
    JournalSeriesRelationshipRequest,
    JournalSeriesResource,
    JournalSeriesResponse,
    JournalSeriesUpdateRequest,
)
from app.core.journal.models.journal_series import JournalSeries
from app.core.journal.models.repositories import JournalRepository
from app.core.journal.services.journal_series_service import (
    JournalSeriesService,
    parse_series_id,
)
from app.infrastructure.auth.models import SessionUser

series_router = APIRouter(tags=["journals"])


def _to_resource(
    series: JournalSeries,
    base_url: str,
    member_journals: list[dict[str, object]] | None = None,
) -> JournalSeriesResource:
    attributes: dict[str, object] = {
        "name": series.name,
        "description": series.description,
        "calendar_id": str(series.calendar_id) if series.calendar_id else None,
        "recurring_event_id": series.recurring_event_id,
        "auto_created": series.auto_created,
    }
    if member_journals is not None:
        attributes["member_journals"] = member_journals
    return JournalSeriesResource(
        type="journal-series",
        id=str(series.id) if series.id else "",
        attributes=attributes,
        links=JsonApiLinks(self=f"{base_url}/api/journals/series/{series.id}")
        if series.id
        else None,
    )


@series_router.get("/journals/series")
@inject
async def list_journal_series(
    request: Request,
    series_service: FromDishka[JournalSeriesService],
    user: FromDishka[SessionUser],
) -> JournalSeriesListResponse:
    """List all journal series for the current user, ordered by name."""
    base_url = get_request_base_url(request)
    all_series = await series_service.list_series(user.id)
    return JournalSeriesListResponse(
        data=[_to_resource(series, base_url) for series in all_series]
    )


@series_router.post("/journals/series", status_code=status.HTTP_201_CREATED)
@inject
async def create_journal_series(
    request: Request,
    series_request: JournalSeriesCreateRequest,
    series_service: FromDishka[JournalSeriesService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> JournalSeriesResponse:
    """Create a manual journal series."""
    base_url = get_request_base_url(request)
    attributes = series_request.data.attributes
    try:
        series = JournalSeries(
            name=attributes.name,
            user_id=user.id,
            description=attributes.description,
        )
    except ValueError as e:
        raise JournalValidationError("name", str(e)) from e

    created = await series_service.create_series(series, connection)
    return JournalSeriesResponse(data=_to_resource(created, base_url))


@series_router.get("/journals/series/{series_id}")
@inject
async def get_journal_series(
    series_id: str,
    request: Request,
    series_service: FromDishka[JournalSeriesService],
    journal_repo: FromDishka[JournalRepository],
    user: FromDishka[SessionUser],
) -> JournalSeriesResponse:
    """Get a series with its member journal summaries."""
    base_url = get_request_base_url(request)
    parsed_id = parse_series_id(series_id)
    series = await series_service.get_series(parsed_id, user.id)

    member_ids = await series_service.get_member_journal_ids(parsed_id, user.id)
    members = await journal_repo.find_by_ids_for_user(user.id, member_ids)
    members_by_id = {j.id: j for j in members if j.id is not None}
    member_journals: list[dict[str, object]] = [
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

    return JournalSeriesResponse(
        data=_to_resource(series, base_url, member_journals=member_journals)
    )


@series_router.patch("/journals/series/{series_id}")
@inject
async def update_journal_series(
    series_id: str,
    request: Request,
    series_request: JournalSeriesUpdateRequest,
    series_service: FromDishka[JournalSeriesService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> JournalSeriesResponse:
    """Rename or re-describe a series."""
    base_url = get_request_base_url(request)
    attributes = series_request.data.attributes
    updated = await series_service.update_series(
        series_id=parse_series_id(series_id),
        user_id=user.id,
        name=attributes.name,
        description=attributes.description,
        transaction=connection,
    )
    return JournalSeriesResponse(data=_to_resource(updated, base_url))


@series_router.delete(
    "/journals/series/{series_id}", status_code=status.HTTP_204_NO_CONTENT
)
@inject
async def delete_journal_series(
    series_id: str,
    series_service: FromDishka[JournalSeriesService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> None:
    """Delete a series. Member journals are untouched."""
    await series_service.delete_series(parse_series_id(series_id), user.id, connection)


@series_router.post(
    "/journals/{journal_id}/relationships/series",
    status_code=status.HTTP_204_NO_CONTENT,
)
@inject
async def add_journal_to_series(
    journal_id: int,
    relationship_request: JournalSeriesRelationshipRequest,
    series_service: FromDishka[JournalSeriesService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> None:
    """Add a journal to a series (idempotent)."""
    await series_service.add_journal_to_series(
        series_id=parse_series_id(relationship_request.data.id),
        journal_id=journal_id,
        user_id=user.id,
        transaction=connection,
    )


@series_router.delete(
    "/journals/{journal_id}/relationships/series/{series_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
@inject
async def remove_journal_from_series(
    journal_id: int,
    series_id: str,
    series_service: FromDishka[JournalSeriesService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> None:
    """Remove a journal from a series (idempotent)."""
    await series_service.remove_journal_from_series(
        series_id=parse_series_id(series_id),
        journal_id=journal_id,
        user_id=user.id,
        transaction=connection,
    )
