"""
Journal API controllers.

Handles journal-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

from datetime import datetime
from typing import Any

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import (
    PaginationParams,
    create_pagination_links,
    create_pagination_meta,
    get_request_base_url,
)
from app.api.journals.converters import (
    JournalConverter,
    JournalRequestConverter,
    TypeDataConverter,
)
from app.api.journals.schemas import (
    JournalContactAddRequest,
    JournalCreateRequest,
    JournalListResponse,
    JournalResponse,
    JournalTagAddRequest,
    JournalTypeAddRequest,
    JournalTypeDataUpdateRequest,
    JournalUpdateRequest,
)
from app.core.journal.models.entities import Journal
from app.core.journal.models.exceptions import JournalNotFoundError
from app.core.journal.models.journal_types import JournalType
from app.core.journal.models.repositories import (
    CalendarInfoRepository,
    CalendarRepository,
    JournalContactRelationshipRepository,
    JournalTagRepository,
    MoodDataRepository,
    PhotoAlbumDataRepository,
    PlanDataRepository,
    TravelDataRepository,
)
from app.core.journal.services.journal_service import JournalService
from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()

# Constants for error messages
JOURNAL_NOT_FOUND_ERROR = "Journal not found"

router = APIRouter(
    prefix="/journals",
    tags=["journals"],
)


async def _enrich_journal_data(
    journal: Journal,
    calendar_info_repo: CalendarInfoRepository,
    calendar_repo: CalendarRepository,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    photo_album_data_repo: PhotoAlbumDataRepository,
    contact_relationship_repo: JournalContactRelationshipRepository,
    tag_repo: JournalTagRepository,
) -> tuple[
    list[str],
    dict[str, Any],
    list[Any],
    list[Any],
    Any,
]:
    """
    Fetch all enrichment data for a journal (types, type_data, contacts, tags, calendar).

    Returns:
        Tuple of (types, type_data, contacts, tags, calendar)
    """
    types = []
    type_data = {}

    # Fetch type-specific data
    calendar_info = await calendar_info_repo.find_by_journal_id(journal.id)  # type: ignore
    if calendar_info:
        types.append(JournalType.EVENT.value)
        calendar = await calendar_repo.find_by_id(calendar_info.calendar_id)
        type_data[JournalType.EVENT.value] = TypeDataConverter.calendar_info_to_schema(
            calendar_info
        )
    else:
        calendar = None

    mood_data = await mood_data_repo.find_by_journal_id(journal.id)  # type: ignore
    if mood_data:
        types.append(JournalType.MOOD_RATING.value)
        type_data[JournalType.MOOD_RATING.value] = (
            TypeDataConverter.mood_data_to_schema(mood_data)
        )

    plan_data = await plan_data_repo.find_by_journal_id(journal.id)  # type: ignore
    if plan_data:
        types.append(JournalType.PLAN.value)
        type_data[JournalType.PLAN.value] = TypeDataConverter.plan_data_to_schema(
            plan_data
        )

    travel_data = await travel_data_repo.find_by_journal_id(journal.id)  # type: ignore
    if travel_data:
        types.append(JournalType.TRAVEL.value)
        type_data[JournalType.TRAVEL.value] = TypeDataConverter.travel_data_to_schema(
            travel_data
        )

    photo_album_data = await photo_album_data_repo.find_by_journal_id(journal.id)  # type: ignore
    if photo_album_data:
        types.append(JournalType.PHOTO_ALBUM.value)
        type_data[JournalType.PHOTO_ALBUM.value] = (
            TypeDataConverter.photo_album_data_to_schema(photo_album_data)
        )

    # If no types found, it's a NOTE
    if not types:
        types.append(JournalType.NOTE.value)

    # Fetch contacts
    contacts = await contact_relationship_repo.get_by_journal(journal.id)  # type: ignore

    # Fetch tags
    tags = await tag_repo.get_tags_for_journal(journal.id)  # type: ignore

    return types, type_data, contacts, tags, calendar


@router.get("", response_model=JournalListResponse)
@inject
async def list_journals(
    request: Request,
    journal_service: FromDishka[JournalService],
    user: FromDishka[SessionUser],  # Require authentication
    page: int = Query(default=1, description="Page number", ge=1),
    limit: int = Query(default=20, description="Items per page", ge=1, le=100),
    type: str | None = Query(default=None, description="Filter by journal type"),
    start_date: datetime | None = Query(
        default=None, description="Filter by start date (inclusive)"
    ),
    end_date: datetime | None = Query(
        default=None, description="Filter by end date (inclusive)"
    ),
    contact_id: int | None = Query(default=None, description="Filter by contact ID"),
    tag_id: str | None = Query(default=None, description="Filter by tag ID"),
    calendar_id: str | None = Query(default=None, description="Filter by calendar ID"),
    parent_id: int | None = Query(default=None, description="Filter by parent ID"),
    search: str | None = Query(default=None, description="Search query"),
) -> JournalListResponse:
    """
    List journals with pagination and filtering.

    Returns a paginated list of journals following JSON API specification.
    """
    pagination = PaginationParams(page=page, limit=limit)
    base_url = get_request_base_url(request)

    # TODO: Implement filtering in journal service
    # For now, just get all journals for the user
    journals = await journal_service.get_journals_paginated(
        user_id=user.id,
        offset=pagination.offset,
        limit=pagination.limit,
    )

    total_count = await journal_service.get_journals_count(user_id=user.id)

    # Convert to resources
    journal_resources = []
    for journal in journals:
        # TODO: Fetch type data, contacts, tags, calendar for each journal
        resource = JournalConverter.to_resource(journal, base_url)
        journal_resources.append(resource)

    meta = create_pagination_meta(total_count, page, limit)
    links = create_pagination_links(
        f"{base_url}/api/journals", page, limit, total_count
    )

    return JournalListResponse(
        data=journal_resources,
        meta=meta,
        links=links,
    )


@router.get("/{journal_id}", response_model=JournalResponse)
@inject
async def get_journal(
    journal_id: int,
    request: Request,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Get a single journal by ID.

    Returns a single journal resource following JSON API specification.
    """
    base_url = get_request_base_url(request)

    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.post("", response_model=JournalResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_journal(
    request: Request,
    journal_request: JournalCreateRequest,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Create a new journal.

    Creates a new journal with the provided data and returns the created resource.
    """
    base_url = get_request_base_url(request)

    journal = JournalRequestConverter.from_create_request(journal_request.data, user.id)

    created_journal = await journal_service.create_journal(journal, connection)

    # TODO: Handle types and type_data from request
    # TODO: Handle contacts and tags from request

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        created_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        created_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.put("/{journal_id}", response_model=JournalResponse)
@inject
async def update_journal(
    journal_id: int,
    request: Request,
    journal_request: JournalUpdateRequest,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Update an existing journal (full replacement).

    Updates the journal with the provided data and returns the updated resource.
    """
    base_url = get_request_base_url(request)

    existing_journal = await journal_service.get_journal(journal_id)
    if not existing_journal:
        raise JournalNotFoundError(journal_id)

    updated_journal = JournalRequestConverter.from_update_request(
        journal_request.data, existing_journal
    )

    # Track only the fields that were provided in the request (partial update support)
    changed_fields: dict[str, Any] = {}
    if journal_request.data.attributes.title is not None:
        changed_fields["title"] = updated_journal.title
    if journal_request.data.attributes.content is not None:
        changed_fields["content"] = updated_journal.content
    if journal_request.data.attributes.event_date_range is not None:
        changed_fields["event_date_range"] = updated_journal.event_date_range
    if journal_request.data.attributes.parent_id is not None:
        changed_fields["parent_id"] = updated_journal.parent_id
    if journal_request.data.attributes.order is not None:
        changed_fields["order"] = updated_journal.order

    saved_journal = await journal_service.update_journal(
        updated_journal, changed_fields, connection
    )

    # TODO: Handle types and type_data updates
    # TODO: Handle contacts and tags updates

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        saved_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        saved_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.patch("/{journal_id}", response_model=JournalResponse)
@inject
async def partial_update_journal(
    journal_id: int,
    request: Request,
    journal_request: JournalUpdateRequest,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Partially update an existing journal.

    Updates only the provided fields and returns the updated resource.
    """
    base_url = get_request_base_url(request)

    existing_journal = await journal_service.get_journal(journal_id)
    if not existing_journal:
        raise JournalNotFoundError(journal_id)

    # For partial update, merge with existing values
    # Only update fields that are provided in the request
    from app.core.journal.models.value_objects import EventDateRange

    # Use existing values if not provided
    title = journal_request.data.attributes.title or existing_journal.title
    content = journal_request.data.attributes.content or existing_journal.content

    event_date_range = EventDateRange(
        start=(
            journal_request.data.attributes.event_date_range.start
            if journal_request.data.attributes.event_date_range
            else existing_journal.event_date_range.start
        ),
        end=(
            journal_request.data.attributes.event_date_range.end
            if journal_request.data.attributes.event_date_range
            else existing_journal.event_date_range.end
        ),
    )

    updated_journal = Journal(
        id=existing_journal.id,
        user_id=existing_journal.user_id,
        title=title,
        content=content,
        event_date_range=event_date_range,
        parent_id=(
            journal_request.data.attributes.parent_id
            if journal_request.data.attributes.parent_id is not None
            else existing_journal.parent_id
        ),
        order=(
            journal_request.data.attributes.order
            if journal_request.data.attributes.order is not None
            else existing_journal.order
        ),
        created_at=existing_journal.created_at,
        updated_at=existing_journal.updated_at,
    )

    # Track only changed fields for partial update
    changed_fields: dict[str, Any] = {}
    if journal_request.data.attributes.title:
        changed_fields["title"] = title
    if journal_request.data.attributes.content:
        changed_fields["content"] = content
    if journal_request.data.attributes.event_date_range:
        changed_fields["event_date_range"] = event_date_range
    if journal_request.data.attributes.parent_id is not None:
        changed_fields["parent_id"] = journal_request.data.attributes.parent_id
    if journal_request.data.attributes.order is not None:
        changed_fields["order"] = journal_request.data.attributes.order

    saved_journal = await journal_service.update_journal(
        updated_journal, changed_fields, connection
    )

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        saved_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        saved_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.delete("/{journal_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_journal(
    journal_id: int,
    journal_service: FromDishka[JournalService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a journal.

    Deletes the journal and all its associated data.
    """
    existing_journal = await journal_service.get_journal(journal_id)
    if not existing_journal:
        raise JournalNotFoundError(journal_id)

    await journal_service.delete_journal(journal_id, connection)


# Type Management Endpoints
@router.post("/{journal_id}/types", response_model=JournalResponse)
@inject
async def add_type_to_journal(
    journal_id: int,
    request: Request,
    type_request: JournalTypeAddRequest,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Add a type to a journal with automatic dependency resolution.

    When a type is added, all its dependent types are automatically added as well.
    """
    from app.core.journal.models.journal_types import JournalType

    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse journal type
    try:
        journal_type = JournalType[type_request.data.attributes.journal_type]
    except KeyError as e:
        from app.core.journal.models.exceptions import JournalValidationError

        raise JournalValidationError(
            "journal_type",
            f"Invalid journal type: {type_request.data.attributes.journal_type}",
        ) from e

    # Add type with automatic dependency resolution
    await journal_service.add_type_to_journal(journal_id, journal_type, connection)

    # TODO: Save type-specific data from type_request.data.attributes.type_data

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.delete("/{journal_id}/types/{journal_type}", response_model=JournalResponse)
@inject
async def remove_type_from_journal(
    journal_id: int,
    journal_type: str,
    request: Request,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Remove a type from a journal.

    Validates that removing the type won't break dependencies.
    """
    from app.core.journal.models.journal_types import JournalType

    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse journal type
    try:
        jtype = JournalType[journal_type]
    except KeyError as e:
        from app.core.journal.models.exceptions import JournalValidationError

        raise JournalValidationError(
            "journal_type", f"Invalid journal type: {journal_type}"
        ) from e

    # Remove type
    await journal_service.remove_type_from_journal(journal_id, jtype, connection)

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.put("/{journal_id}/types/{journal_type}/data", response_model=JournalResponse)
@inject
async def update_type_data(
    journal_id: int,
    journal_type: str,
    request: Request,
    type_data_request: JournalTypeDataUpdateRequest,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Update type-specific data for a journal.

    The journal must already have the specified type.
    """
    from app.core.journal.models.journal_types import JournalType

    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse journal type
    try:
        _ = JournalType[journal_type]
    except KeyError as e:
        from app.core.journal.models.exceptions import JournalValidationError

        raise JournalValidationError(
            "journal_type", f"Invalid journal type: {journal_type}"
        ) from e

    # TODO: Update type-specific data based on journal type
    # This will require accessing the appropriate repository for each type
    # For now, just return the journal
    _ = type_data_request  # Suppress unused variable warning

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


# Relationship Management Endpoints
@router.post("/{journal_id}/relationships/contacts", response_model=JournalResponse)
@inject
async def add_contact_to_journal(
    journal_id: int,
    request: Request,
    contact_request: JournalContactAddRequest,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Add a contact relationship to a journal.
    """
    from app.core.journal.models.journal_relationship_types import (
        JournalContactRelationshipType,
    )

    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse relationship type
    try:
        _ = JournalContactRelationshipType[
            contact_request.data.attributes.relationship_type
        ]
    except KeyError as e:
        from app.core.journal.models.exceptions import JournalValidationError

        raise JournalValidationError(
            "relationship_type",
            f"Invalid relationship type: {contact_request.data.attributes.relationship_type}",
        ) from e

    # TODO: Get JournalContactService from DI
    # For now, this is a placeholder
    # contact_service = ...
    # relationship = JournalContactRelationship(
    #     journal_id=journal_id,
    #     contact_id=contact_request.data.attributes.contact_id,
    #     relationship_type=relationship_type,
    # )
    # await contact_service.add_contact_to_journal(relationship, connection)
    _ = connection  # Suppress unused variable warning

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.delete(
    "/{journal_id}/relationships/contacts/{contact_id}/{relationship_type}",
    response_model=JournalResponse,
)
@inject
async def remove_contact_from_journal(
    journal_id: int,
    contact_id: int,
    relationship_type: str,
    request: Request,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Remove a contact relationship from a journal.
    """
    from app.core.journal.models.journal_relationship_types import (
        JournalContactRelationshipType,
    )

    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse relationship type
    try:
        _ = JournalContactRelationshipType[relationship_type]
    except KeyError as e:
        from app.core.journal.models.exceptions import JournalValidationError

        raise JournalValidationError(
            "relationship_type", f"Invalid relationship type: {relationship_type}"
        ) from e

    # TODO: Get JournalContactService from DI and remove relationship
    # await contact_service.remove_contact_from_journal(journal_id, contact_id, rel_type, connection)
    _ = (connection, contact_id)  # Suppress unused variable warnings

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.post("/{journal_id}/relationships/tags", response_model=JournalResponse)
@inject
async def add_tag_to_journal(
    journal_id: int,
    request: Request,
    tag_request: JournalTagAddRequest,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Add a tag to a journal.
    """
    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # TODO: Get JournalTagService from DI and add tag
    # await tag_service.add_tag_to_journal(journal_id, tag_request.data.attributes.tag_id, connection)
    _ = (connection, tag_request)  # Suppress unused variable warnings

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)


@router.delete(
    "/{journal_id}/relationships/tags/{tag_id}", response_model=JournalResponse
)
@inject
async def remove_tag_from_journal(
    journal_id: int,
    tag_id: str,
    request: Request,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Remove a tag from a journal.
    """
    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # TODO: Get JournalTagService from DI and remove tag
    # await tag_service.remove_tag_from_journal(journal_id, tag_id, connection)
    _ = (connection, tag_id)  # Suppress unused variable warnings

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        contact_relationship_repo,
        tag_repo,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return JournalResponse(data=journal_resource)
