"""
Journal API controllers.

Handles journal-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

from datetime import UTC, datetime
from typing import Any

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, status
from meilisearch.errors import MeilisearchError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import (
    JsonApiLinks,
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
    JournalAttributes,
    JournalContactAddRequest,
    JournalCreateRequest,
    JournalListResponse,
    JournalResource,
    JournalResponse,
    JournalTagAddRequest,
    JournalTagCreateRequest,
    JournalTagListResponse,
    JournalTagResource,
    JournalTagResponse,
    JournalTypeAddRequest,
    JournalTypeDataUpdateRequest,
    JournalUpdateRequest,
)
from app.core.journal.models.entities import Journal
from app.core.journal.models.exceptions import (
    JournalNotFoundError,
    JournalValidationError,
)
from app.core.journal.models.journal_contact_relationship import (
    JournalContactRelationship,
)
from app.core.journal.models.journal_relationship_types import (
    JournalContactRelationshipType,
)
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
from app.core.search.exceptions import SearchServiceUnavailableError
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.search.search_service import SearchService

logger = structlog.get_logger()

# Constants for error messages
JOURNAL_NOT_FOUND_ERROR = "Journal not found"
INVALID_UUID_FORMAT_MSG = "Invalid UUID format"
JOURNAL_ID_NOT_SET_MSG = "Journal ID should be set after creation"

router = APIRouter(
    prefix="/journals",
    tags=["journals"],
)


def _parse_journal_type(type_str: str) -> JournalType:
    """
    Convert a type string to JournalType enum.

    Handles both enum value (lowercase like "mood_rating") and
    enum name (uppercase like "MOOD_RATING").

    Args:
        type_str: The type string to convert

    Returns:
        The corresponding JournalType enum value

    Raises:
        ValueError: If the type string is invalid
        KeyError: If the type string doesn't match any enum
    """
    try:
        # First try as enum value (lowercase like "mood_rating")
        return JournalType(type_str)
    except ValueError:
        # Fall back to enum name (uppercase like "MOOD_RATING")
        return JournalType[type_str.upper()]


async def _create_type_specific_data(
    journal_type: "JournalType",
    journal_id: int,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
) -> None:
    """
    Create type-specific data row with default values for the given journal type.

    Args:
        journal_type: The type of journal
        journal_id: The ID of the journal
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
    """
    from app.core.journal.models.journal_types import JournalType

    if journal_type == JournalType.MOOD_RATING:
        from app.core.journal.models.mood_data import MoodData

        mood_data = MoodData(journal_id=journal_id)
        await mood_data_repo.save(mood_data)
    elif journal_type == JournalType.PLAN:
        from app.core.journal.models.plan_data import PlanData

        plan_data = PlanData(journal_id=journal_id)
        await plan_data_repo.save(plan_data)
    elif journal_type == JournalType.TRAVEL:
        from app.core.journal.models.travel_data import TravelData

        travel_data = TravelData(journal_id=journal_id)
        await travel_data_repo.save(travel_data)
    # EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
    # These will be created when the user updates the type data


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
    Fetch all enrichment data for a journal.

    Retrieves types, type_data, contacts, tags, and calendar information.

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


@router.get("/tags")
@inject
async def list_journal_tags(
    request: Request,
    tag_repo: FromDishka[JournalTagRepository],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalTagListResponse:
    """
    List all available journal tags.

    Returns a list of all journal tags that can be used to categorize journals.
    """
    base_url = get_request_base_url(request)

    # Get all tags from repository
    all_tags = await tag_repo.get_all()

    # Convert to resources
    tag_resources = [
        JournalTagResource(
            type="journal-tags",
            id=str(tag.id) if tag.id else "",
            attributes={
                "name": tag.name,
                "color": tag.color,
                "parent_id": str(tag.parent_id) if tag.parent_id else None,
            },
            links=JsonApiLinks(
                self=f"{base_url}/api/journals/tags/{tag.id}",
            )
            if tag.id
            else None,
        )
        for tag in all_tags
    ]

    return JournalTagListResponse(data=tag_resources)


@router.post("/tags", status_code=status.HTTP_201_CREATED)
@inject
async def create_journal_tag(
    request: Request,
    tag_request: JournalTagCreateRequest,
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalTagResponse:
    """
    Create a new journal tag.

    Creates a new journal tag with the provided data and returns the created resource.
    """
    from uuid import UUID

    from sqlalchemy.exc import IntegrityError

    from app.core.journal.models.journal_tag import JournalTag

    base_url = get_request_base_url(request)

    # Parse parent_id if provided
    parent_id = None
    if tag_request.data.attributes.parent_id:
        try:
            parent_id = UUID(tag_request.data.attributes.parent_id)
        except ValueError as e:
            raise JournalValidationError("parent_id", INVALID_UUID_FORMAT_MSG) from e

    # Create tag entity
    tag = JournalTag(
        name=tag_request.data.attributes.name,
        color=tag_request.data.attributes.color,
        parent_id=parent_id,
    )

    # Save tag
    try:
        created_tag = await tag_repo.save(tag)
    except IntegrityError as e:
        # Check if it's a duplicate name error
        if "uq_journal_tags_name" in str(e) or "duplicate key" in str(e).lower():
            raise JournalValidationError(
                "name",
                f"A journal tag with the name '{tag.name}' already exists. Tag names must be unique.",
            ) from e
        # Re-raise other integrity errors
        raise

    # Convert to resource
    tag_resource = JournalTagResource(
        type="journal-tags",
        id=str(created_tag.id) if created_tag.id else "",
        attributes={
            "name": created_tag.name,
            "color": created_tag.color,
            "parent_id": str(created_tag.parent_id) if created_tag.parent_id else None,
        },
        links=JsonApiLinks(
            self=f"{base_url}/api/journals/tags/{created_tag.id}",
        )
        if created_tag.id
        else None,
    )

    return JournalTagResponse(data=tag_resource)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_journal_tag(
    tag_id: str,
    tag_repo: FromDishka[JournalTagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a journal tag.

    This is a minimal implementation to support E2E testing cleanup.

    IMPORTANT SECURITY NOTES:
    - Journal tags are global (not user-scoped) - any authenticated user can delete any tag
    - This endpoint checks if the tag is in use and returns 409 Conflict if it is
    - In production, this endpoint should be restricted to admin users only
    - Future improvement: Add role-based access control (admin-only deletion)

    Args:
        tag_id: UUID of the tag to delete
        tag_repo: Tag repository
        connection: Database connection (to check if tag is in use)
        user: Authenticated user

    Returns:
        None (204 No Content)

    Raises:
        400: Invalid tag ID format
        404: Tag not found
        409: Tag is in use by one or more journals
    """
    from uuid import UUID

    from fastapi import HTTPException
    from sqlalchemy import text

    # Convert string ID to UUID
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tag ID format",
        ) from e

    # Get the tag to verify it exists
    tag = await tag_repo.find_by_id(tag_uuid)
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tag not found",
        )

    # Check if tag is in use by any journals
    # This prevents accidental deletion of tags that are actively being used
    check_query = text(
        """
        SELECT COUNT(*) as count
        FROM journal_tag_assignments
        WHERE tag_id = :tag_id
        """
    )
    result = await connection.execute(check_query, {"tag_id": tag_uuid})
    row = result.fetchone()
    usage_count: int = row[0] if row else 0

    if usage_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete tag '{tag.name}' because it is assigned to {usage_count} journal(s). "
            "Remove the tag from all journals before deleting it.",
        )

    # Delete the tag
    await tag_repo.delete(tag_uuid)

    return None


@router.get("")
@inject
async def list_journals(
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
    page: int = Query(default=1, description="Page number", ge=1),
    limit: int = Query(default=20, description="Items per page", ge=1, le=100),
    journal_type: str | None = Query(
        default=None, description="Filter by journal type", alias="type"
    ),
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

    # Get all journals for the user
    journals = await journal_service.get_journals_paginated(
        user_id=user.id,
        offset=pagination.offset,
        limit=pagination.limit,
        journal_type=journal_type,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        contact_id=str(contact_id) if contact_id else None,
        tag_id=tag_id,
        calendar_id=calendar_id,
        parent_id=parent_id,
        search=search,
    )

    total_count = await journal_service.get_journals_count(
        user_id=user.id,
        journal_type=journal_type,
        start_date=start_date.isoformat() if start_date else None,
        end_date=end_date.isoformat() if end_date else None,
        contact_id=str(contact_id) if contact_id else None,
        tag_id=tag_id,
        calendar_id=calendar_id,
        parent_id=parent_id,
        search=search,
    )

    # Convert to resources with enriched data
    journal_resources = []
    for journal in journals:
        # Enrich journal with types, contacts, tags, etc.
        types, type_data, _, _, _ = await _enrich_journal_data(
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

        resource = JournalConverter.to_resource(
            journal, base_url, types=types, type_data=type_data
        )
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


# Search endpoint - MUST be before /{journal_id} to avoid route conflicts
@router.get("/search")
@inject
async def search_journals(
    request: Request,
    search_service: FromDishka[SearchService],
    user: FromDishka[SessionUser],  # Require authentication
    q: str = Query(..., description="Search query", min_length=1, max_length=500),
    page: int = Query(default=1, description="Page number", ge=1),
    limit: int = Query(default=20, description="Results per page", ge=1, le=100),
    types: list[str] | None = Query(
        default=None, description="Filter by journal types"
    ),
    sort: list[str] | None = Query(default=None, description="Sort criteria"),
) -> JournalListResponse:
    """
    Search journals using MeiliSearch.

    Supports full-text search across title and content with filtering and pagination.
    """
    # Calculate offset from page
    offset = (page - 1) * limit

    # Build filters - always filter by user_id for security
    filters: dict[str, Any] = {"user_id": user.id}
    if types:
        filters["types"] = types

    try:
        results = search_service.search_journals(
            query=q,
            filters=filters,
            limit=limit,
            offset=offset,
            sort=sort,
        )
    except MeilisearchError as e:
        logger.error("MeiliSearch error during journal search", error=str(e), query=q)
        raise SearchServiceUnavailableError("MeiliSearch", str(e)) from e

    # Convert search results to journal resources
    from app.api.journals.schemas import EventDateRangeSchema

    base_url = get_request_base_url(request)
    journal_resources: list[JournalResource] = []

    for hit in results["hits"]:
        # Create a minimal journal resource from search hit
        # Note: This is a simplified resource from search results
        # For full details, clients should fetch the complete journal via
        # GET /journals/{id}

        # Parse event date range from search results
        start_date = hit.get("event_date_range_start")
        end_date = hit.get("event_date_range_end")

        # Use current time as fallback if dates are missing (should not happen in normal operation)
        # This is a defensive measure for data integrity issues
        if not start_date or not end_date:
            logger.warning(
                "Missing event_date_range in search results, using fallback",
                journal_id=hit.get("id"),
            )
            start_date = datetime.now(UTC)
            end_date = datetime.now(UTC)

        event_date_range = EventDateRangeSchema(
            start=start_date,
            end=end_date,
        )

        # Normalize types from MeiliSearch (uppercase) to API format (lowercase)
        types_from_search = hit.get("types", [])
        normalized_types = [t.lower() for t in types_from_search]

        attributes = JournalAttributes(
            title=hit.get("title", ""),
            content=hit.get("content", ""),
            event_date_range=event_date_range,
            types=normalized_types,
            created_at=hit.get("created_at"),
            updated_at=hit.get("updated_at"),
        )

        # Only include relevant search metadata fields to avoid exposing internal details
        search_metadata = {
            key: hit[key]
            for key in ("_rankingScore", "_rankingScoreDetails")
            if key in hit
        }

        resource = JournalResource(
            id=str(hit["id"]),
            attributes=attributes,
            links=JsonApiLinks(self=f"{base_url}/api/journals/{hit['id']}"),
            meta={
                "highlighted": hit.get("_formatted", {}),
                "search_metadata": search_metadata,
            },
        )
        journal_resources.append(resource)

    # Build pagination metadata
    total_count = results.get("estimated_total_hits", 0)
    pagination_meta = create_pagination_meta(total_count, page, limit)

    # Build pagination links with query parameters
    base_url_without_query = str(request.url).split("?")[0]
    additional_params: dict[str, str | list[str]] = {"q": q}
    if types:
        additional_params["types"] = types
    if sort:
        additional_params["sort"] = sort

    links = create_pagination_links(
        base_url_without_query, page, limit, total_count, additional_params
    )

    return JournalListResponse(
        data=journal_resources,
        meta=pagination_meta,
        links=links,
    )


@router.get("/{journal_id}")
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


async def _process_journal_types(
    journal_id: int,
    types: list[str],
    journal_service: JournalService,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    connection: AsyncConnection,
) -> None:
    """
    Process and add types to a journal.

    Args:
        journal_id: The ID of the journal
        types: List of type strings to add
        journal_service: Service for journal operations
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
        connection: Database connection
    """
    for type_str in types:
        try:
            # Convert type string to enum
            journal_type = _parse_journal_type(type_str)

            await journal_service.add_type_to_journal(
                journal_id, journal_type, connection
            )

            # Create type-specific data row with default values
            await _create_type_specific_data(
                journal_type,
                journal_id,
                mood_data_repo,
                plan_data_repo,
                travel_data_repo,
            )
        except (ValueError, KeyError):
            # Invalid type, skip
            pass


async def _process_journal_type_data(
    journal_id: int,
    type_data: dict[str, Any],
    calendar_info_repo: CalendarInfoRepository,
    photo_album_data_repo: PhotoAlbumDataRepository,
) -> None:
    """
    Process and save type-specific data for a journal.

    Args:
        journal_id: The ID of the journal
        type_data: Dictionary of type-specific data (keys are case-insensitive)
        calendar_info_repo: Repository for calendar info
        photo_album_data_repo: Repository for photo album data
    """
    # Normalize type_data keys to lowercase for case-insensitive matching
    normalized_type_data = {k.lower(): v for k, v in type_data.items()}

    # Process EVENT type data
    if "event" in normalized_type_data:
        from datetime import time as dt_time
        from uuid import UUID

        from app.core.journal.models.calendar_info import CalendarInfo

        event_data = normalized_type_data["event"]

        # Convert string times to time objects if provided
        start_time = None
        if event_data.get("start_time"):
            start_time_str = event_data["start_time"]
            # Parse HH:MM:SS format
            hours, minutes, seconds = map(int, start_time_str.split(":"))
            start_time = dt_time(hours, minutes, seconds)

        end_time = None
        if event_data.get("end_time"):
            end_time_str = event_data["end_time"]
            # Parse HH:MM:SS format
            hours, minutes, seconds = map(int, end_time_str.split(":"))
            end_time = dt_time(hours, minutes, seconds)

        calendar_info = CalendarInfo(
            journal_id=journal_id,
            calendar_id=UUID(event_data["calendar_id"]),
            start_time=start_time,
            end_time=end_time,
            is_all_day=event_data.get("is_all_day", False),
            location=event_data.get("location"),
            sync_invitees=event_data.get("sync_invitees", False),
        )
        await calendar_info_repo.save(calendar_info)

    # Process PHOTO_ALBUM type data
    if "photo_album" in normalized_type_data:
        from app.core.journal.models.photo_album_data import PhotoAlbumData

        photo_data = normalized_type_data["photo_album"]
        photo_album_data = PhotoAlbumData(
            journal_id=journal_id,
            immich_album_id=photo_data["immich_album_id"],
        )
        await photo_album_data_repo.save(photo_album_data)


async def _process_journal_contact_relationships(
    journal_id: int,
    contacts_data: list[dict[str, Any]],
    contact_relationship_repo: JournalContactRelationshipRepository,
) -> None:
    """
    Process and create contact relationships for a journal.

    Args:
        journal_id: The ID of the journal
        contacts_data: List of contact relationship data
        contact_relationship_repo: Repository for contact relationships
    """
    for contact_data in contacts_data:
        try:
            # Extract contact_id and relationship_type from attributes
            # contact_data is a dict from JSON, not a Pydantic model
            if "attributes" in contact_data:
                attrs = contact_data["attributes"]
                contact_id = int(attrs["contact_id"])
                relationship_type = JournalContactRelationshipType[
                    attrs["relationship_type"]
                ]

                # Create the relationship
                relationship = JournalContactRelationship(
                    journal_id=journal_id,
                    contact_id=contact_id,
                    relationship_type=relationship_type,
                )
                await contact_relationship_repo.create(relationship)
        except (ValueError, KeyError, AttributeError, IntegrityError):
            # Invalid contact relationship, skip
            pass


@router.post("", status_code=status.HTTP_201_CREATED)
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

    # Ensure journal_id is not None (it should always be set after creation)
    if created_journal.id is None:
        raise ValueError(JOURNAL_ID_NOT_SET_MSG)
    journal_id = created_journal.id

    # Add types if provided in the request
    if journal_request.data.attributes.types:
        await _process_journal_types(
            journal_id,
            journal_request.data.attributes.types,
            journal_service,
            mood_data_repo,
            plan_data_repo,
            travel_data_repo,
            connection,
        )

    # Process type_data if provided in the request
    if journal_request.data.attributes.type_data:
        await _process_journal_type_data(
            journal_id,
            journal_request.data.attributes.type_data,
            calendar_info_repo,
            photo_album_data_repo,
        )

    # Add contact relationships if provided in the request (via relationships field)
    if (
        hasattr(journal_request.data, "relationships")
        and journal_request.data.relationships
    ):
        relationships = journal_request.data.relationships
        if relationships.contacts:
            contacts_data = relationships.contacts.get("data", [])
            await _process_journal_contact_relationships(
                journal_id,
                contacts_data,
                contact_relationship_repo,
            )

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


@router.put("/{journal_id}")
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
        # Convert EventDateRange to JSON-serializable dict
        changed_fields["event_date_range"] = {
            "start": updated_journal.event_date_range.start.isoformat(),
            "end": updated_journal.event_date_range.end.isoformat(),
        }
    if journal_request.data.attributes.parent_id is not None:
        changed_fields["parent_id"] = updated_journal.parent_id
    if journal_request.data.attributes.order is not None:
        changed_fields["order"] = updated_journal.order

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


@router.patch("/{journal_id}")
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

    # Use existing values if not provided (use is not None to allow empty strings)
    title = (
        journal_request.data.attributes.title
        if journal_request.data.attributes.title is not None
        else existing_journal.title
    )
    content = (
        journal_request.data.attributes.content
        if journal_request.data.attributes.content is not None
        else existing_journal.content
    )

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

    # Track only changed fields for partial update (use is not None to allow empty
    # strings)
    changed_fields: dict[str, Any] = {}
    if journal_request.data.attributes.title is not None:
        changed_fields["title"] = title
    if journal_request.data.attributes.content is not None:
        changed_fields["content"] = content
    if journal_request.data.attributes.event_date_range is not None:
        # Convert EventDateRange to JSON-serializable dict
        changed_fields["event_date_range"] = {
            "start": event_date_range.start.isoformat(),
            "end": event_date_range.end.isoformat(),
        }
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
@router.post("/{journal_id}/types")
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
    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse journal type
    try:
        journal_type = _parse_journal_type(type_request.data.attributes.journal_type)
    except (ValueError, KeyError) as e:
        from app.core.journal.models.exceptions import JournalValidationError

        raise JournalValidationError(
            "journal_type",
            f"Invalid journal type: {type_request.data.attributes.journal_type}",
        ) from e

    # Add type with automatic dependency resolution
    await journal_service.add_type_to_journal(journal_id, journal_type, connection)

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


@router.delete("/{journal_id}/types/{journal_type}")
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
    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse journal type
    try:
        jtype = _parse_journal_type(journal_type)
    except (ValueError, KeyError) as e:
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


async def _update_event_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    calendar_info_repo: CalendarInfoRepository,
) -> None:
    """Update EVENT type-specific data."""
    from uuid import UUID

    calendar_info = await calendar_info_repo.find_by_journal_id(journal_id)
    if not calendar_info:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Update fields from request
    if "calendar_id" in attrs:
        calendar_info.calendar_id = UUID(attrs["calendar_id"])
    if "start_time" in attrs:
        calendar_info.start_time = attrs["start_time"]
    if "end_time" in attrs:
        calendar_info.end_time = attrs["end_time"]
    if "is_all_day" in attrs:
        calendar_info.is_all_day = attrs["is_all_day"]
    if "location" in attrs:
        calendar_info.location = attrs["location"]
    if "sync_invitees" in attrs:
        calendar_info.sync_invitees = attrs["sync_invitees"]

    await calendar_info_repo.save(calendar_info)


async def _update_mood_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    mood_data_repo: MoodDataRepository,
) -> None:
    """Update MOOD_RATING type-specific data."""
    mood_data = await mood_data_repo.find_by_journal_id(journal_id)
    if not mood_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Update fields from request
    if "mood_value" in attrs:
        mood_data.mood_value = attrs["mood_value"]
    if "mood_label" in attrs:
        mood_data.mood_label = attrs["mood_label"]
    if "energy_level" in attrs:
        mood_data.energy_level = attrs["energy_level"]

    await mood_data_repo.save(mood_data)


async def _update_photo_album_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    photo_album_data_repo: PhotoAlbumDataRepository,
) -> None:
    """Update PHOTO_ALBUM type-specific data."""
    photo_album_data = await photo_album_data_repo.find_by_journal_id(journal_id)
    if not photo_album_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Update fields from request
    if "immich_album_id" in attrs:
        photo_album_data.immich_album_id = attrs["immich_album_id"]

    await photo_album_data_repo.save(photo_album_data)


@router.put("/{journal_id}/types/{journal_type}/data")
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
    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse journal type
    try:
        jtype = _parse_journal_type(journal_type)
    except (ValueError, KeyError) as e:
        raise JournalValidationError(
            "journal_type", f"Invalid journal type: {journal_type}"
        ) from e

    # Get the attributes from the request
    attrs = type_data_request.data.attributes

    # Update type-specific data based on the type
    if jtype == JournalType.EVENT:
        await _update_event_type_data(
            journal_id, journal_type, attrs, calendar_info_repo
        )
    elif jtype == JournalType.MOOD_RATING:
        await _update_mood_type_data(journal_id, journal_type, attrs, mood_data_repo)
    elif jtype == JournalType.PHOTO_ALBUM:
        await _update_photo_album_type_data(
            journal_id, journal_type, attrs, photo_album_data_repo
        )
    elif jtype in (JournalType.PLAN, JournalType.TRAVEL):
        # PLAN and TRAVEL types have complex nested data structures
        # For now, return an error indicating this is not yet supported
        raise JournalValidationError(
            "journal_type",
            f"Updating {journal_type} type data is not yet supported. "
            "Please use the full journal update endpoint instead.",
        )
    else:
        # NOTE type has no type-specific data
        raise JournalValidationError(
            "journal_type", f"Type {journal_type} has no type-specific data to update"
        )

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
@router.post("/{journal_id}/relationships/contacts")
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
    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse contact_id and relationship type
    try:
        contact_id = int(contact_request.data.attributes.contact_id)
    except ValueError as e:
        raise JournalValidationError("contact_id", "Invalid contact ID format") from e

    try:
        relationship_type = JournalContactRelationshipType[
            contact_request.data.attributes.relationship_type
        ]
    except KeyError as e:
        rel_type = contact_request.data.attributes.relationship_type
        raise JournalValidationError(
            "relationship_type",
            f"Invalid relationship type: {rel_type}",
        ) from e

    # Create the relationship
    relationship = JournalContactRelationship(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=relationship_type,
    )
    try:
        await contact_relationship_repo.create(relationship)
    except IntegrityError as e:
        raise JournalValidationError(
            "contact_id",
            f"Contact not found or relationship already exists: {contact_id}",
        ) from e

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


@router.delete("/{journal_id}/relationships/contacts/{contact_id}/{relationship_type}")
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

    # Parse contact_id and relationship type
    try:
        contact_id_int = int(contact_id)
    except ValueError as e:
        from app.core.journal.models.exceptions import JournalValidationError

        raise JournalValidationError("contact_id", "Invalid contact ID format") from e

    try:
        relationship_type_enum = JournalContactRelationshipType[relationship_type]
    except KeyError as e:
        from app.core.journal.models.exceptions import JournalValidationError

        raise JournalValidationError(
            "relationship_type", f"Invalid relationship type: {relationship_type}"
        ) from e

    # Delete the relationship
    await contact_relationship_repo.delete(
        journal_id, contact_id_int, relationship_type_enum
    )

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


@router.post("/{journal_id}/relationships/tags")
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
    from uuid import UUID

    from app.core.journal.models.exceptions import JournalValidationError

    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse tag_id
    try:
        tag_uuid = UUID(tag_request.data.attributes.tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", INVALID_UUID_FORMAT_MSG) from e

    # Verify tag exists
    tag = await tag_repo.find_by_id(tag_uuid)
    if not tag:
        raise JournalValidationError("tag_id", f"Tag not found: {tag_uuid}")

    # Assign tag to journal
    await tag_repo.assign_tag(journal_id, tag_uuid)

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


@router.delete("/{journal_id}/relationships/tags/{tag_id}")
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
    from uuid import UUID

    from app.core.journal.models.exceptions import JournalValidationError

    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse tag_id
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", INVALID_UUID_FORMAT_MSG) from e

    # Remove tag from journal
    await tag_repo.remove_tag(journal_id, tag_uuid)

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
