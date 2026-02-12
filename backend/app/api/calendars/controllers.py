"""
Calendar API controllers.

Minimal calendar management endpoints for creating calendars.
Full calendar CRUD operations are planned for Iteration 7.
"""

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import get_request_base_url
from app.api.journals.schemas import CalendarCreateRequest, CalendarResponse
from app.core.journal.adapters.sql.calendar_repository import CalendarRepository
from app.core.journal.models.calendar import Calendar
from app.infrastructure.auth.models import SessionUser

# Default color for calendars (blue)
DEFAULT_CALENDAR_COLOR = "#3B82F6"

router = APIRouter(prefix="/calendars")


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_calendar(
    request: Request,
    calendar_request: CalendarCreateRequest,
    calendar_repo: FromDishka[CalendarRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> CalendarResponse:
    """
    Create a new calendar.

    Creates a new calendar with the provided data and returns the created resource.
    This is a minimal implementation to support E2E testing.
    Full calendar CRUD operations are planned for Iteration 7.
    """
    from app.api.common.schemas import JsonApiLinks
    from app.api.journals.schemas import CalendarResource

    base_url = get_request_base_url(request)

    # Create calendar entity
    calendar = Calendar(
        user_id=user.id,
        name=calendar_request.data.attributes.name,
        color=calendar_request.data.attributes.color or DEFAULT_CALENDAR_COLOR,
        description=calendar_request.data.attributes.description,
        is_synced_to_google=calendar_request.data.attributes.is_synced_to_google,
        google_calendar_id=calendar_request.data.attributes.google_calendar_id,
    )

    # Save calendar
    created_calendar = await calendar_repo.save(calendar)

    # Convert to resource - use created_calendar to include defaults
    from app.api.journals.schemas import CalendarAttributes

    calendar_attributes = CalendarAttributes(
        name=created_calendar.name,
        description=created_calendar.description,
        color=created_calendar.color,
        is_synced_to_google=created_calendar.is_synced_to_google,
        google_calendar_id=created_calendar.google_calendar_id,
    )

    calendar_resource = CalendarResource(
        id=str(created_calendar.id),
        attributes=calendar_attributes,
        links=JsonApiLinks(self=f"{base_url}/api/calendars/{created_calendar.id}"),
    )

    return CalendarResponse(data=calendar_resource)
