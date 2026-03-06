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
from app.api.journals.schemas import (
    CalendarCreateRequest,
    CalendarListResponse,
    CalendarResponse,
    CalendarUpdateRequest,
)
from app.core.journal.adapters.sql.calendar_repository import CalendarRepository
from app.core.journal.models.calendar import Calendar
from app.infrastructure.auth.models import SessionUser

# Default color for calendars (blue)
DEFAULT_CALENDAR_COLOR = "#3B82F6"

router = APIRouter(prefix="/calendars")


@router.get("")
@inject
async def list_calendars(
    request: Request,
    calendar_repo: FromDishka[CalendarRepository],
    user: FromDishka[SessionUser],  # Require authentication
) -> CalendarListResponse:
    """
    List all calendars for the authenticated user.

    Returns all calendars owned by the user, ordered by name.
    """
    from app.api.common.schemas import JsonApiLinks
    from app.api.journals.schemas import CalendarAttributes, CalendarResource

    base_url = get_request_base_url(request)

    # Get all calendars for the user
    calendars = await calendar_repo.get_all(user.id)

    # Convert to resources
    calendar_resources = []
    for calendar in calendars:
        calendar_attributes = CalendarAttributes(
            name=calendar.name,
            description=calendar.description,
            color=calendar.color,
            is_synced_to_google=calendar.is_synced_to_google,
            google_calendar_id=calendar.google_calendar_id,
        )

        calendar_resource = CalendarResource(
            id=str(calendar.id),
            attributes=calendar_attributes,
            links=JsonApiLinks(self=f"{base_url}/api/calendars/{calendar.id}"),
        )
        calendar_resources.append(calendar_resource)

    return CalendarListResponse(
        data=calendar_resources,
        links=JsonApiLinks(self=f"{base_url}/api/calendars"),
    )


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


@router.put("/{calendar_id}", status_code=status.HTTP_200_OK)
@inject
async def update_calendar(
    calendar_id: str,
    request: Request,
    calendar_request: CalendarUpdateRequest,
    calendar_repo: FromDishka[CalendarRepository],
    user: FromDishka[SessionUser],  # Require authentication
) -> CalendarResponse:
    """
    Update an existing calendar.
    """
    from uuid import UUID

    from fastapi import HTTPException

    from app.api.common.schemas import JsonApiLinks
    from app.api.journals.schemas import CalendarAttributes, CalendarResource

    base_url = get_request_base_url(request)

    try:
        calendar_uuid = UUID(calendar_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid calendar ID format",
        ) from e

    # Validate that path ID matches body ID if body ID is provided
    if calendar_request.data.id and calendar_request.data.id != calendar_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Path ID does not match body ID",
        )

    # Get the calendar to verify ownership
    calendar = await calendar_repo.find_by_id(calendar_uuid)
    if not calendar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar not found",
        )

    # Verify the calendar belongs to the user
    if calendar.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to modify this calendar",
        )

    # Update attributes
    attrs = calendar_request.data.attributes
    fields_set: set[str] = getattr(attrs, "model_fields_set", set())

    if "name" in fields_set:
        calendar.name = attrs.name  # type: ignore[assignment]
    if "description" in fields_set:
        calendar.description = attrs.description
    if "color" in fields_set:
        calendar.color = attrs.color  # type: ignore[assignment]
    if "is_synced_to_google" in fields_set:
        calendar.is_synced_to_google = attrs.is_synced_to_google  # type: ignore[assignment]
    if "google_calendar_id" in fields_set:
        calendar.google_calendar_id = attrs.google_calendar_id

    # Re-trigger domain validation
    from app.core.journal.models.exceptions import CalendarValidationError

    try:
        calendar.__post_init__()
    except CalendarValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    # Save changes
    updated_calendar = await calendar_repo.save(calendar)

    # Convert to resource
    calendar_attributes = CalendarAttributes(
        name=updated_calendar.name,
        description=updated_calendar.description,
        color=updated_calendar.color,
        is_synced_to_google=updated_calendar.is_synced_to_google,
        google_calendar_id=updated_calendar.google_calendar_id,
    )

    calendar_resource = CalendarResource(
        id=str(updated_calendar.id),
        attributes=calendar_attributes,
        links=JsonApiLinks(self=f"{base_url}/api/calendars/{updated_calendar.id}"),
    )

    return CalendarResponse(data=calendar_resource)


@router.delete("/{calendar_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_calendar(
    calendar_id: str,
    calendar_repo: FromDishka[CalendarRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a calendar.

    This is a minimal implementation to support E2E testing cleanup.
    Full calendar CRUD operations are planned for Iteration 7.

    Args:
        calendar_id: UUID of the calendar to delete
        calendar_repo: Calendar repository
        connection: Database connection (to check if calendar is in use)
        user: Authenticated user

    Returns:
        None (204 No Content)

    Raises:
        400: Invalid calendar ID format
        403: User doesn't own the calendar
        404: Calendar not found
        409: Calendar is in use by one or more journals
    """
    from uuid import UUID

    from fastapi import HTTPException
    from sqlalchemy import text

    # Convert string ID to UUID
    try:
        calendar_uuid = UUID(calendar_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid calendar ID format",
        ) from e

    # Get the calendar to verify ownership
    calendar = await calendar_repo.find_by_id(calendar_uuid)
    if not calendar:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar not found",
        )

    # Verify the calendar belongs to the user
    if calendar.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to delete this calendar",
        )

    # Check if calendar is in use by any journals
    # This prevents accidental deletion of calendars that are actively being used
    check_query = text(
        """
        SELECT COUNT(*) as count
        FROM journal_calendar_info
        WHERE calendar_id = :calendar_id
        """
    )
    result = await connection.execute(check_query, {"calendar_id": calendar_uuid})
    row = result.fetchone()
    usage_count: int = row[0] if row else 0

    if usage_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete calendar '{calendar.name}' because it is used by {usage_count} journal(s). "
            "Remove the calendar from all journals before deleting it.",
        )

    # Delete the calendar
    await calendar_repo.delete(calendar_uuid)

    return None
