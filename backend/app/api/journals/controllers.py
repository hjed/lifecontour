"""
Journal API controllers.

Handles journal-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

import dataclasses
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import structlog
from core_shared.models.journals import (
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalNotFoundError,
    JournalType,
    JournalValidationError,
)
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, status
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
    MergeJournalRequest,
)
from app.core.contacts.models.repositories import ContactRepository
from app.core.journal.models.repositories import (
    AbseilingDataRepository,
    BushwalkingDataRepository,
    CalendarInfoRepository,
    CalendarRepository,
    CanyoningDataRepository,
    ClimbingDataRepository,
    CrossCountrySkiingDataRepository,
    FitnessDataRepository,
    JoggingDataRepository,
    JournalContactRelationshipRepository,
    JournalTagRepository,
    KayakingDataRepository,
    MoodDataRepository,
    OutdoorActivityDataRepository,
    PhotoAlbumDataRepository,
    PlanDataRepository,
    RouteRepository,
    TravelDataRepository,
)
from app.core.journal.services.journal_merge_service import JournalMergeService
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


async def _populate_contact_names(
    resource: JournalResource,
    contact_repo: ContactRepository,
    contact_cache: dict[int, str],
) -> None:
    """Populate the names of contacts in a JournalResource."""
    if not resource.attributes.contacts:
        return

    # Gather IDs that need fetching
    contact_ids_to_fetch = [
        int(cs.id)
        for cs in resource.attributes.contacts
        if int(cs.id) not in contact_cache and not cs.name
    ]

    # Bulk fetch names in a single query
    if contact_ids_to_fetch:
        name_rows = await contact_repo.find_names_by_ids(contact_ids_to_fetch)
        for cid, (first_name, last_name) in name_rows.items():
            # Null-safe formatter: filter out None or empty name parts
            name_parts = [part for part in (first_name, last_name) if part]
            name = " ".join(name_parts)
            contact_cache[cid] = name if name else f"Contact {cid}"

        # Mark any IDs not found in the database
        for cid in contact_ids_to_fetch:
            if cid not in contact_cache:
                contact_cache[cid] = f"Unknown Contact {cid}"

    # Set names from cache
    for contact_schema in resource.attributes.contacts:
        contact_id = int(contact_schema.id)
        if contact_id in contact_cache:
            contact_schema.name = contact_cache[contact_id]


async def _build_journal_response(
    journal_resource: JournalResource,
    contact_repo: ContactRepository,
) -> JournalResponse:
    """Build a JournalResponse with populated contact names.

    Shared helper used by all endpoints returning a single JournalResponse
    to ensure consistent contact name population.
    """
    await _populate_contact_names(journal_resource, contact_repo, {})
    return JournalResponse(data=journal_resource)


def _parse_optional_uuid(value: Any, field_name: str) -> UUID | None:
    """Parse an optional UUID field from request attributes."""
    if value is None:
        return None

    try:
        return UUID(str(value))
    except ValueError as exc:
        raise JournalValidationError(
            field_name, f"{INVALID_UUID_FORMAT_MSG}: {value}"
        ) from exc


def _require_integer(value: Any, field_name: str) -> int:
    """Validate that a field is an integer while rejecting booleans."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise JournalValidationError(field_name, "Must be an integer")
    return value


def _parse_optional_integer(value: Any, field_name: str) -> int | None:
    """Validate an optional integer field while rejecting booleans."""
    if value is None:
        return None
    return _require_integer(value, field_name)


async def _create_type_specific_data(
    journal_type: "JournalType",
    journal_id: int,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    fitness_data_repo: FitnessDataRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    canyoning_data_repo: CanyoningDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
) -> None:
    """
    Create type-specific data row with default values for the given journal type.

    Args:
        journal_type: The type of journal
        journal_id: The ID of the journal
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        skiing_data_repo: Repository for cross-country skiing data
    """
    from core_shared.models.journals import JournalType

    if journal_type == JournalType.MOOD_RATING:
        from core_shared.models.journals import MoodData

        mood_data = MoodData(journal_id=journal_id)
        await mood_data_repo.save(mood_data)
    elif journal_type == JournalType.PLAN:
        from core_shared.models.journals import PlanData

        plan_data = PlanData(journal_id=journal_id)
        await plan_data_repo.save(plan_data)
    elif journal_type == JournalType.TRAVEL:
        from core_shared.models.journals import TravelData

        travel_data = TravelData(journal_id=journal_id)
        await travel_data_repo.save(travel_data)
    elif journal_type == JournalType.FITNESS:
        from core_shared.models.journals import FitnessData

        fitness_data = FitnessData(journal_id=journal_id)
        await fitness_data_repo.save(fitness_data)
    elif journal_type == JournalType.OUTDOOR_ACTIVITY:
        from core_shared.models.journals import OutdoorActivityData

        outdoor_activity_data = OutdoorActivityData(journal_id=journal_id)
        await outdoor_activity_data_repo.save(outdoor_activity_data)
    elif journal_type == JournalType.BUSHWALKING:
        from core_shared.models.journals import BushwalkingData

        bushwalking_data = BushwalkingData(journal_id=journal_id)
        await bushwalking_data_repo.save(bushwalking_data)
    elif journal_type == JournalType.JOGGING:
        from core_shared.models.journals import JoggingData

        jogging_data = JoggingData(journal_id=journal_id)
        await jogging_data_repo.save(jogging_data)
    elif journal_type == JournalType.ABSEILING_TRIP:
        from core_shared.models.journals import AbseilingData

        abseiling_data = AbseilingData(journal_id=journal_id)
        await abseiling_data_repo.save(abseiling_data)
    elif journal_type == JournalType.CANYONING:
        from core_shared.models.journals import CanyoningData

        canyoning_data = CanyoningData(journal_id=journal_id)
        await canyoning_data_repo.save(canyoning_data)
    elif journal_type == JournalType.CLIMBING:
        from core_shared.models.journals import ClimbingData

        climbing_data = ClimbingData(journal_id=journal_id)
        await climbing_data_repo.save(climbing_data)
    elif journal_type == JournalType.KAYAKING:
        from core_shared.models.journals import KayakingData

        kayaking_data = KayakingData(journal_id=journal_id)
        await kayaking_data_repo.save(kayaking_data)
    elif journal_type == JournalType.CROSS_COUNTRY_SKIING:
        from core_shared.models.journals import (
            CrossCountrySkiingData,
        )

        skiing_data = CrossCountrySkiingData(journal_id=journal_id)
        await skiing_data_repo.save(skiing_data)
    # EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
    # These will be created when the user updates the type data


async def _delete_type_specific_data(
    journal_type: "JournalType",
    journal_id: int,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    photo_album_data_repo: PhotoAlbumDataRepository,
    fitness_data_repo: FitnessDataRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    canyoning_data_repo: CanyoningDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
) -> None:
    """
    Delete the type-specific data row for the given journal type.

    Called when a type is removed from a journal so that the type row is cleaned
    up and the type no longer appears in _enrich_journal_data() responses.

    Args:
        journal_type: The type of journal being removed
        journal_id: The ID of the journal
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
        photo_album_data_repo: Repository for photo album data
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        skiing_data_repo: Repository for cross-country skiing data
    """
    from core_shared.models.journals import JournalType

    if journal_type == JournalType.MOOD_RATING:
        await mood_data_repo.delete(journal_id)
    elif journal_type == JournalType.PLAN:
        await plan_data_repo.delete(journal_id)
    elif journal_type == JournalType.TRAVEL:
        await travel_data_repo.delete(journal_id)
    elif journal_type == JournalType.PHOTO_ALBUM:
        await photo_album_data_repo.delete(journal_id)
    elif journal_type == JournalType.FITNESS:
        await fitness_data_repo.delete(journal_id)
    elif journal_type == JournalType.OUTDOOR_ACTIVITY:
        await outdoor_activity_data_repo.delete(journal_id)
    elif journal_type == JournalType.BUSHWALKING:
        await bushwalking_data_repo.delete(journal_id)
    elif journal_type == JournalType.JOGGING:
        await jogging_data_repo.delete(journal_id)
    elif journal_type == JournalType.ABSEILING_TRIP:
        await abseiling_data_repo.delete(journal_id)
    elif journal_type == JournalType.CANYONING:
        await canyoning_data_repo.delete(journal_id)
    elif journal_type == JournalType.CLIMBING:
        await climbing_data_repo.delete(journal_id)
    elif journal_type == JournalType.KAYAKING:
        await kayaking_data_repo.delete(journal_id)
    elif journal_type == JournalType.CROSS_COUNTRY_SKIING:
        await skiing_data_repo.delete(journal_id)
    # EVENT has no dedicated type-specific table (uses calendar_info via CalendarInfo)
    # and is handled by the service layer


async def _enrich_journal_data(
    journal: Journal,
    calendar_info_repo: CalendarInfoRepository,
    calendar_repo: CalendarRepository,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    photo_album_data_repo: PhotoAlbumDataRepository,
    fitness_data_repo: FitnessDataRepository,
    contact_relationship_repo: JournalContactRelationshipRepository,
    tag_repo: JournalTagRepository,
    route_repo: RouteRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    canyoning_data_repo: CanyoningDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
    include_routes: bool = False,
) -> tuple[
    list[str],
    dict[str, Any],
    list[Any],
    list[Any],
    Any,
    list[Any] | None,
]:
    """
    Fetch all enrichment data for a journal.

    Retrieves types, type_data, contacts, tags, and calendar information.

    Returns:
        Tuple of (types, type_data, contacts, tags, calendar)
    """
    # Journal must have an ID when being enriched (it was retrieved from the database)
    assert journal.id is not None, "Journal must have an ID to fetch enrichment data"
    journal_id: int = journal.id

    types = []
    type_data = {}

    # Fetch type-specific data
    calendar_info = await calendar_info_repo.find_by_journal_id(journal_id)
    if calendar_info:
        types.append(JournalType.EVENT.value)
        calendar = await calendar_repo.find_by_id(calendar_info.calendar_id)
        type_data[JournalType.EVENT.value] = TypeDataConverter.calendar_info_to_schema(
            calendar_info
        )
    else:
        calendar = None

    mood_data = await mood_data_repo.find_by_journal_id(journal_id)
    if mood_data:
        types.append(JournalType.MOOD_RATING.value)
        type_data[JournalType.MOOD_RATING.value] = (
            TypeDataConverter.mood_data_to_schema(mood_data)
        )

    plan_data = await plan_data_repo.find_by_journal_id(journal_id)
    if plan_data:
        types.append(JournalType.PLAN.value)
        type_data[JournalType.PLAN.value] = TypeDataConverter.plan_data_to_schema(
            plan_data
        )

    travel_data = await travel_data_repo.find_by_journal_id(journal_id)
    if travel_data:
        types.append(JournalType.TRAVEL.value)
        type_data[JournalType.TRAVEL.value] = TypeDataConverter.travel_data_to_schema(
            travel_data
        )

    photo_album_data = await photo_album_data_repo.find_by_journal_id(journal_id)
    if photo_album_data:
        types.append(JournalType.PHOTO_ALBUM.value)
        type_data[JournalType.PHOTO_ALBUM.value] = (
            TypeDataConverter.photo_album_data_to_schema(photo_album_data)
        )

    fitness_data = await fitness_data_repo.find_by_journal_id(journal_id)
    if fitness_data:
        types.append(JournalType.FITNESS.value)
        type_data[JournalType.FITNESS.value] = TypeDataConverter.fitness_data_to_schema(
            fitness_data
        )

    outdoor_activity_data = await outdoor_activity_data_repo.find_by_journal_id(
        journal_id
    )
    if outdoor_activity_data:
        types.append(JournalType.OUTDOOR_ACTIVITY.value)
        type_data[JournalType.OUTDOOR_ACTIVITY.value] = (
            TypeDataConverter.outdoor_activity_data_to_schema(outdoor_activity_data)
        )

    bushwalking_data = await bushwalking_data_repo.find_by_journal_id(journal_id)
    if bushwalking_data:
        types.append(JournalType.BUSHWALKING.value)
        type_data[JournalType.BUSHWALKING.value] = (
            TypeDataConverter.bushwalking_data_to_schema(bushwalking_data)
        )

    jogging_data = await jogging_data_repo.find_by_journal_id(journal_id)
    if jogging_data:
        types.append(JournalType.JOGGING.value)
        type_data[JournalType.JOGGING.value] = TypeDataConverter.jogging_data_to_schema(
            jogging_data
        )

    abseiling_data = await abseiling_data_repo.find_by_journal_id(journal_id)
    if abseiling_data:
        types.append(JournalType.ABSEILING_TRIP.value)
        type_data[JournalType.ABSEILING_TRIP.value] = (
            TypeDataConverter.abseiling_data_to_schema(abseiling_data)
        )

    canyoning_data = await canyoning_data_repo.find_by_journal_id(journal_id)
    if canyoning_data:
        types.append(JournalType.CANYONING.value)
        type_data[JournalType.CANYONING.value] = (
            TypeDataConverter.canyoning_data_to_schema(canyoning_data)
        )

    climbing_data = await climbing_data_repo.find_by_journal_id(journal_id)
    if climbing_data:
        types.append(JournalType.CLIMBING.value)
        type_data[JournalType.CLIMBING.value] = (
            TypeDataConverter.climbing_data_to_schema(climbing_data)
        )

    kayaking_data = await kayaking_data_repo.find_by_journal_id(journal_id)
    if kayaking_data:
        types.append(JournalType.KAYAKING.value)
        type_data[JournalType.KAYAKING.value] = (
            TypeDataConverter.kayaking_data_to_schema(kayaking_data)
        )

    skiing_data = await skiing_data_repo.find_by_journal_id(journal_id)
    if skiing_data:
        types.append(JournalType.CROSS_COUNTRY_SKIING.value)
        type_data[JournalType.CROSS_COUNTRY_SKIING.value] = (
            TypeDataConverter.cross_country_skiing_data_to_schema(skiing_data)
        )

    # If no types found, it's a NOTE
    if not types:
        types.append(JournalType.NOTE.value)

    # Fetch contacts
    contacts = await contact_relationship_repo.get_by_journal(journal_id)

    # Fetch tags
    tags = await tag_repo.get_tags_for_journal(journal_id)

    # Fetch routes
    routes = await route_repo.find_by_journal_id(journal_id) if include_routes else None

    return types, type_data, contacts, tags, calendar, routes


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


async def _build_journal_list_resources(
    journals: list[Journal],
    user_id: str,
    base_url: str,
    journal_service: JournalService,
    contact_repo: ContactRepository,
    calendar_info_repo: CalendarInfoRepository,
    calendar_repo: CalendarRepository,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    photo_album_data_repo: PhotoAlbumDataRepository,
    fitness_data_repo: FitnessDataRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    canyoning_data_repo: CanyoningDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
    contact_relationship_repo: JournalContactRelationshipRepository,
    tag_repo: JournalTagRepository,
    route_repo: RouteRepository,
) -> list[JournalResource]:
    """Helper to consistently build journal list responses with enriched data.

    The number of returned resources will not exceed the size of the paginated
    `journals` input (modulo de-duplication by ID), so that callers that
    paginate based on the input list have consistent `meta` and pagination links.
    """
    seen_ids: set[int] = set()
    all_journals: list[Journal] = []
    for j in journals:
        if j.id is None:
            continue
        if j.id in seen_ids:
            continue
        seen_ids.add(j.id)
        all_journals.append(j)

    # Batch-load parents + children counts
    returned_ids = {j.id for j in all_journals if j.id is not None}
    parent_ids = list({j.parent_id for j in all_journals if j.parent_id is not None})
    missing_parent_ids = [pid for pid in parent_ids if pid not in returned_ids]
    parent_journals = await journal_service.find_journals_by_ids_for_user(
        user_id=user_id, journal_ids=missing_parent_ids
    )
    parent_by_id = {
        **{p.id: p for p in parent_journals if p.id is not None},
        **{j.id: j for j in all_journals if j.id is not None},
    }

    returned_ids_list = [j.id for j in all_journals if j.id is not None]
    children_count_by_parent_id = await journal_service.count_children_for_parents(
        user_id=user_id, parent_ids=returned_ids_list
    )

    # Enrich journals
    journal_resources = []
    for journal in all_journals:
        types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
            journal,
            calendar_info_repo,
            calendar_repo,
            mood_data_repo,
            plan_data_repo,
            travel_data_repo,
            photo_album_data_repo,
            fitness_data_repo,
            contact_relationship_repo,
            tag_repo,
            route_repo,
            outdoor_activity_data_repo,
            bushwalking_data_repo,
            jogging_data_repo,
            abseiling_data_repo,
            canyoning_data_repo,
            climbing_data_repo,
            kayaking_data_repo,
            skiing_data_repo,
            include_routes=False,
        )
        parent = parent_by_id.get(journal.parent_id) if journal.parent_id else None
        children_count = (
            children_count_by_parent_id.get(journal.id, 0) if journal.id else 0
        )
        resource = JournalConverter.to_resource(
            journal,
            base_url,
            types=types,
            type_data=type_data,
            contacts=contacts,
            tags=tags,
            calendar=calendar,
            routes=routes,
            parent=parent,
            children_count=children_count,
        )
        journal_resources.append(resource)

    # Populate contact names
    contact_cache: dict[int, str] = {}
    for resource in journal_resources:
        await _populate_contact_names(resource, contact_repo, contact_cache)

    return journal_resources


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    user: FromDishka[SessionUser],  # Require authentication
    page: Annotated[int, Query(description="Page number", ge=1)] = 1,
    limit: Annotated[int, Query(description="Items per page", ge=1, le=100)] = 20,
    journal_type: Annotated[
        str | None, Query(description="Filter by journal type", alias="type")
    ] = None,
    start_date: Annotated[
        datetime | None, Query(description="Filter by start date (inclusive)")
    ] = None,
    end_date: Annotated[
        datetime | None, Query(description="Filter by end date (inclusive)")
    ] = None,
    contact_id: Annotated[int | None, Query(description="Filter by contact ID")] = None,
    tag_id: Annotated[str | None, Query(description="Filter by tag ID")] = None,
    calendar_id: Annotated[
        str | None, Query(description="Filter by calendar ID")
    ] = None,
    parent_id: Annotated[int | None, Query(description="Filter by parent ID")] = None,
    search: Annotated[str | None, Query(description="Search query")] = None,
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
    journal_resources = await _build_journal_list_resources(
        journals=journals,
        user_id=user.id,
        base_url=base_url,
        journal_service=journal_service,
        contact_repo=contact_repo,
        calendar_info_repo=calendar_info_repo,
        calendar_repo=calendar_repo,
        mood_data_repo=mood_data_repo,
        plan_data_repo=plan_data_repo,
        travel_data_repo=travel_data_repo,
        photo_album_data_repo=photo_album_data_repo,
        fitness_data_repo=fitness_data_repo,
        outdoor_activity_data_repo=outdoor_activity_data_repo,
        bushwalking_data_repo=bushwalking_data_repo,
        jogging_data_repo=jogging_data_repo,
        abseiling_data_repo=abseiling_data_repo,
        canyoning_data_repo=canyoning_data_repo,
        climbing_data_repo=climbing_data_repo,
        kayaking_data_repo=kayaking_data_repo,
        skiing_data_repo=skiing_data_repo,
        contact_relationship_repo=contact_relationship_repo,
        tag_repo=tag_repo,
        route_repo=route_repo,
    )

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
    q: Annotated[str, Query(description="Search query", min_length=1, max_length=500)],
    page: Annotated[int, Query(description="Page number", ge=1)] = 1,
    limit: Annotated[int, Query(description="Results per page", ge=1, le=100)] = 20,
    types: Annotated[
        list[str] | None, Query(description="Filter by journal types")
    ] = None,
    sort: Annotated[list[str] | None, Query(description="Sort criteria")] = None,
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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
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
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
    )

    # Fetch parent journal if it exists
    parent = None
    if journal.parent_id:
        try:
            parent = await journal_service.get_journal(journal.parent_id)
        except JournalNotFoundError:
            pass

    # Fetch children count
    children_count = 0
    children = []
    if journal.id:
        children_counts = await journal_service.count_children_for_parents(
            user_id=user.id, parent_ids=[journal.id]
        )
        children_count = children_counts.get(journal.id, 0)

        # Fetch children summary details
        if children_count > 0:
            children = await journal_service.get_journals_paginated(
                user_id=user.id,
                offset=0,
                limit=100,
                parent_id=journal.id,
            )

    journal_resource = JournalConverter.to_resource(
        journal,
        base_url,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=tags,
        calendar=calendar,
        parent=parent,
        children=children,
        children_count=children_count,
    )

    return await _build_journal_response(journal_resource, contact_repo)


async def _process_journal_types(
    journal_id: int,
    types: list[str],
    journal_service: JournalService,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    fitness_data_repo: FitnessDataRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    canyoning_data_repo: CanyoningDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
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
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        skiing_data_repo: Repository for cross-country skiing data
        connection: Database connection
    """
    for type_str in types:
        try:
            # Convert type string to enum
            journal_type = _parse_journal_type(type_str)

            # Returns all types added, including auto-resolved dependencies
            added_types = await journal_service.add_type_to_journal(
                journal_id, journal_type, connection
            )

            # Create type-specific data rows for ALL added types (including dependencies)
            for added_type in added_types:
                await _create_type_specific_data(
                    added_type,
                    journal_id,
                    mood_data_repo,
                    plan_data_repo,
                    travel_data_repo,
                    fitness_data_repo,
                    outdoor_activity_data_repo,
                    bushwalking_data_repo,
                    jogging_data_repo,
                    abseiling_data_repo,
                    canyoning_data_repo,
                    climbing_data_repo,
                    kayaking_data_repo,
                    skiing_data_repo,
                )
        except (ValueError, KeyError):
            # Invalid type, skip
            pass


async def _process_journal_type_data(
    journal_id: int,
    type_data: dict[str, Any],
    calendar_info_repo: CalendarInfoRepository,
    photo_album_data_repo: PhotoAlbumDataRepository,
    plan_data_repo: PlanDataRepository | None = None,
    travel_data_repo: TravelDataRepository | None = None,
    mood_data_repo: MoodDataRepository | None = None,
    fitness_data_repo: FitnessDataRepository | None = None,
    outdoor_activity_data_repo: OutdoorActivityDataRepository | None = None,
    bushwalking_data_repo: BushwalkingDataRepository | None = None,
    jogging_data_repo: JoggingDataRepository | None = None,
    abseiling_data_repo: AbseilingDataRepository | None = None,
    canyoning_data_repo: CanyoningDataRepository | None = None,
    climbing_data_repo: ClimbingDataRepository | None = None,
    kayaking_data_repo: KayakingDataRepository | None = None,
    skiing_data_repo: CrossCountrySkiingDataRepository | None = None,
) -> None:
    """
    Process and save type-specific data for a journal.

    Args:
        journal_id: The ID of the journal
        type_data: Dictionary of type-specific data (keys are case-insensitive)
        calendar_info_repo: Repository for calendar info
        photo_album_data_repo: Repository for photo album data
        plan_data_repo: Optional repository for plan data
        travel_data_repo: Optional repository for travel data
        mood_data_repo: Optional repository for mood data
        fitness_data_repo: Optional repository for fitness data
        outdoor_activity_data_repo: Optional repository for outdoor activity data
        bushwalking_data_repo: Optional repository for bushwalking data
        jogging_data_repo: Optional repository for jogging data
        abseiling_data_repo: Optional repository for abseiling data
        canyoning_data_repo: Optional repository for canyoning data
        climbing_data_repo: Optional repository for climbing data
        kayaking_data_repo: Optional repository for kayaking data
        skiing_data_repo: Optional repository for cross-country skiing data
    """
    # Normalize type_data keys to lowercase for case-insensitive matching
    normalized_type_data = {k.lower(): v for k, v in type_data.items()}

    # Process EVENT type data
    if "event" in normalized_type_data:
        from datetime import time as dt_time
        from uuid import UUID

        from core_shared.models.journals import CalendarInfo

        event_data = normalized_type_data["event"]

        try:

            def _parse_time_str(time_str: str) -> dt_time:
                """Parse HH:MM or HH:MM:SS time strings from HTML time inputs."""
                parts = time_str.split(":")
                if len(parts) == 2:  # noqa: PLR2004
                    hours, minutes = map(int, parts)
                    seconds = 0
                elif len(parts) == 3:  # noqa: PLR2004
                    hours, minutes, seconds = map(int, parts)
                else:
                    raise ValueError(f"Invalid time format: {time_str!r}")
                return dt_time(hours, minutes, seconds)

            # Convert string times to time objects if provided
            start_time = None
            if event_data.get("start_time"):
                start_time = _parse_time_str(event_data["start_time"])

            end_time = None
            if event_data.get("end_time"):
                end_time = _parse_time_str(event_data["end_time"])

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
        except (ValueError, KeyError) as exc:
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail=f"Invalid EVENT type_data: {exc}",
            ) from exc

    # Process PHOTO_ALBUM type data
    if "photo_album" in normalized_type_data:
        from core_shared.models.journals import PhotoAlbumData

        photo_data = normalized_type_data["photo_album"]
        photo_album_data = PhotoAlbumData(
            journal_id=journal_id,
            immich_album_id=photo_data["immich_album_id"],
        )
        await photo_album_data_repo.save(photo_album_data)

    # Process PLAN type data
    if "plan" in normalized_type_data and plan_data_repo:
        import uuid

        from core_shared.models.journals import PlanData, PlanDocument

        plan_payload = normalized_type_data["plan"]
        plan_data = await plan_data_repo.find_by_journal_id(journal_id)
        if not plan_data:
            plan_data = PlanData(journal_id=journal_id)

        if "documents" in plan_payload:
            documents: list[PlanDocument] = []
            for doc in plan_payload["documents"]:
                doc_id = uuid.uuid4()
                # Coerce null/blank title to "Untitled"
                title_raw = doc.get("title")
                if not title_raw or (
                    isinstance(title_raw, str) and not title_raw.strip()
                ):
                    title = "Untitled"
                else:
                    title = title_raw
                # Coerce null order to sequential index
                order_raw = doc.get("order")
                order = order_raw if isinstance(order_raw, int) else len(documents)
                documents.append(
                    PlanDocument(
                        id=doc_id,
                        journal_id=journal_id,
                        url=doc["url"],
                        title=title,
                        description=doc.get("description"),
                        order=order,
                    )
                )
            plan_data.documents = documents

        # Persist PlanData itself
        await plan_data_repo.save(plan_data)

        # Persist each PlanDocument explicitly (save() does not cascade documents)
        for document in plan_data.documents:
            await plan_data_repo.save_document(document)

    # Process TRAVEL type data
    if "travel" in normalized_type_data and travel_data_repo:
        from core_shared.models.journals import TravelData

        # Payload for travel currently empty in UI, but create data if valid
        travel_data = await travel_data_repo.find_by_journal_id(journal_id)
        if not travel_data:
            travel_data = TravelData(journal_id=journal_id)
        await travel_data_repo.save(travel_data)

    # Process MOOD_RATING type data
    if "mood_rating" in normalized_type_data and mood_data_repo:
        from core_shared.models.journals import MoodData

        mood_payload = normalized_type_data["mood_rating"]
        mood_data = await mood_data_repo.find_by_journal_id(journal_id)
        if mood_data is None:
            mood_data = MoodData(journal_id=journal_id)

        mood_value_raw = mood_payload.get("mood_value")
        energy_level_raw = mood_payload.get("energy_level")

        if mood_value_raw is not None:
            try:
                mood_data.mood_value = int(mood_value_raw)
            except (TypeError, ValueError) as exc:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=400,
                    detail="mood_value must be an integer",
                ) from exc
        if energy_level_raw is not None:
            try:
                mood_data.energy_level = int(energy_level_raw)
            except (TypeError, ValueError) as exc:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=400,
                    detail="energy_level must be an integer",
                ) from exc
        mood_data.mood_label = mood_payload.get("mood_label") or mood_data.mood_label

        await mood_data_repo.save(mood_data)

    # Process FITNESS type data
    if "fitness" in normalized_type_data and fitness_data_repo:
        from core_shared.models.journals import FitnessData

        fitness_payload = normalized_type_data["fitness"]
        fitness_data = await fitness_data_repo.find_by_journal_id(journal_id)
        if fitness_data is None:
            fitness_data = FitnessData(journal_id=journal_id)

        numeric_fields = (
            "distance",
            "duration",
            "heart_rate_avg",
            "heart_rate_max",
            "elevation_gain",
            "elevation_loss",
            "calories",
        )
        for field in numeric_fields:
            if field in fitness_payload:
                value = fitness_payload[field]
                if value is None:
                    setattr(fitness_data, field, None)
                else:
                    try:
                        setattr(fitness_data, field, int(value))
                    except (TypeError, ValueError) as exc:
                        from fastapi import HTTPException

                        raise HTTPException(
                            status_code=400,
                            detail=f"{field} must be an integer",
                        ) from exc

        if "strava_activity_id" in fitness_payload:
            fitness_data.strava_activity_id = fitness_payload["strava_activity_id"]

        await fitness_data_repo.save(fitness_data)

    # Process OUTDOOR_ACTIVITY type data
    if "outdoor_activity" in normalized_type_data and outdoor_activity_data_repo:
        from core_shared.models.journals import OutdoorActivityData

        outdoor_payload = normalized_type_data["outdoor_activity"]
        outdoor_data = await outdoor_activity_data_repo.find_by_journal_id(journal_id)
        if outdoor_data is None:
            outdoor_data = OutdoorActivityData(journal_id=journal_id)

        if "activity_type" in outdoor_payload:
            outdoor_data.activity_type = outdoor_payload["activity_type"]
        if "weather_conditions" in outdoor_payload:
            outdoor_data.weather_conditions = outdoor_payload["weather_conditions"]
        if "role" in outdoor_payload:
            outdoor_data.role = outdoor_payload["role"]
        if "in_leadership_role" in outdoor_payload:
            outdoor_data.in_leadership_role = outdoor_payload["in_leadership_role"]
        if "participant_notes" in outdoor_payload:
            outdoor_data.participant_notes = outdoor_payload["participant_notes"]

        await outdoor_activity_data_repo.save(outdoor_data)

    # Process BUSHWALKING type data
    if "bushwalking" in normalized_type_data and bushwalking_data_repo:
        from core_shared.models.journals import BushwalkingData

        bushwalking_payload = normalized_type_data["bushwalking"]
        bushwalking_data = await bushwalking_data_repo.find_by_journal_id(journal_id)
        if bushwalking_data is None:
            bushwalking_data = BushwalkingData(journal_id=journal_id)

        if "track_grading" in bushwalking_payload:
            bushwalking_data.track_grading = bushwalking_payload["track_grading"]

        await bushwalking_data_repo.save(bushwalking_data)

    # Process JOGGING type data
    if "jogging" in normalized_type_data and jogging_data_repo:
        from core_shared.models.journals import JoggingData

        jogging_payload = normalized_type_data["jogging"]
        jogging_data = await jogging_data_repo.find_by_journal_id(journal_id)
        if jogging_data is None:
            jogging_data = JoggingData(journal_id=journal_id)

        if "pace" in jogging_payload:
            pace_raw = jogging_payload["pace"]
            if pace_raw is None:
                jogging_data.pace = None
            else:
                try:
                    jogging_data.pace = int(pace_raw)
                except (TypeError, ValueError) as exc:
                    from fastapi import HTTPException

                    raise HTTPException(
                        status_code=400,
                        detail="pace must be an integer (seconds per km)",
                    ) from exc

        await jogging_data_repo.save(jogging_data)

    # Process ABSEILING_TRIP type data
    if "abseiling_trip" in normalized_type_data and abseiling_data_repo:
        await _update_abseiling_type_data(
            journal_id,
            "ABSEILING_TRIP",
            normalized_type_data["abseiling_trip"],
            abseiling_data_repo,
        )

    # Process CANYONING type data
    if "canyoning" in normalized_type_data and canyoning_data_repo:
        await _update_canyoning_type_data(
            journal_id,
            "CANYONING",
            normalized_type_data["canyoning"],
            canyoning_data_repo,
        )

    # Process CLIMBING type data
    if "climbing" in normalized_type_data and climbing_data_repo:
        await _update_climbing_type_data(
            journal_id,
            "CLIMBING",
            normalized_type_data["climbing"],
            climbing_data_repo,
        )

    # Process KAYAKING type data
    if "kayaking" in normalized_type_data and kayaking_data_repo:
        await _update_kayaking_type_data(
            journal_id,
            "KAYAKING",
            normalized_type_data["kayaking"],
            kayaking_data_repo,
        )

    # Process CROSS_COUNTRY_SKIING type data
    if "cross_country_skiing" in normalized_type_data and skiing_data_repo:
        await _update_cross_country_skiing_type_data(
            journal_id,
            "CROSS_COUNTRY_SKIING",
            normalized_type_data["cross_country_skiing"],
            skiing_data_repo,
        )


async def _process_journal_contact_relationships(
    journal_id: int,
    contacts_data: list[dict[str, Any]],
    contact_relationship_repo: JournalContactRelationshipRepository,
    connection: AsyncConnection,
) -> None:
    """
    Process and create contact relationships for a journal.

    Args:
        journal_id: The ID of the journal
        contacts_data: List of contact relationship data
        contact_relationship_repo: Repository for contact relationships
        connection: Active database connection to manage savepoints
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

                # Create the relationship using a nested transaction (savepoint)
                # to prevent aborting the main transaction if
                # a contact is missing or a unique constraint is violated.
                relationship = JournalContactRelationship(
                    journal_id=journal_id,
                    contact_id=contact_id,
                    relationship_type=relationship_type,
                )
                try:
                    async with connection.begin_nested():
                        await contact_relationship_repo.create(relationship)
                except IntegrityError:
                    # Log error and ignore, the context manager handles the rollback to the savepoint
                    import structlog

                    logger = structlog.get_logger()
                    logger.warning(
                        "Invalid journal contact relationship ignored",
                        journal_id=journal_id,
                        contact_id=contact_id,
                    )

        except (ValueError, KeyError, AttributeError):
            # Invalid contact relationship payload, skip
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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
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
            fitness_data_repo,
            outdoor_activity_data_repo,
            bushwalking_data_repo,
            jogging_data_repo,
            abseiling_data_repo,
            canyoning_data_repo,
            climbing_data_repo,
            kayaking_data_repo,
            skiing_data_repo,
            connection,
        )

    # Process type_data if provided in the request
    if journal_request.data.attributes.type_data:
        await _process_journal_type_data(
            journal_id,
            journal_request.data.attributes.type_data,
            calendar_info_repo,
            photo_album_data_repo,
            plan_data_repo,
            travel_data_repo,
            mood_data_repo,
            fitness_data_repo,
            outdoor_activity_data_repo,
            bushwalking_data_repo,
            jogging_data_repo,
            abseiling_data_repo,
            canyoning_data_repo,
            climbing_data_repo,
            kayaking_data_repo,
            skiing_data_repo,
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
                connection,
            )

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        created_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    parent = (
        await journal_service.get_journal(created_journal.parent_id)
        if created_journal.parent_id
        else None
    )

    journal_resource = JournalConverter.to_resource(
        journal=created_journal,
        base_url=base_url,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=tags,
        calendar=calendar,
        parent=parent,
    )

    return await _build_journal_response(journal_resource, contact_repo)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
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
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        saved_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    parent = (
        await journal_service.get_journal(saved_journal.parent_id)
        if saved_journal.parent_id
        else None
    )

    children_count = 0
    children = []
    if saved_journal.id:
        children_counts = await journal_service.count_children_for_parents(
            user_id=user.id, parent_ids=[saved_journal.id]
        )
        children_count = children_counts.get(saved_journal.id, 0)

        # Fetch children summary details
        if children_count > 0:
            children = await journal_service.get_journals_paginated(
                user_id=user.id,
                offset=0,
                limit=100,
                parent_id=saved_journal.id,
            )

    journal_resource = JournalConverter.to_resource(
        journal=saved_journal,
        base_url=base_url,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=tags,
        calendar=calendar,
        parent=parent,
        children=children,
        children_count=children_count,
    )

    return await _build_journal_response(journal_resource, contact_repo)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
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
    from core_shared.models.journals import EventDateRange

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
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        saved_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    parent = (
        await journal_service.get_journal(saved_journal.parent_id)
        if saved_journal.parent_id
        else None
    )

    children_count = 0
    children = []
    if saved_journal.id:
        children_counts = await journal_service.count_children_for_parents(
            user_id=user.id, parent_ids=[saved_journal.id]
        )
        children_count = children_counts.get(saved_journal.id, 0)

        # Fetch children summary details
        if children_count > 0:
            children = await journal_service.get_journals_paginated(
                user_id=user.id,
                offset=0,
                limit=100,
                parent_id=saved_journal.id,
            )

    journal_resource = JournalConverter.to_resource(
        journal=saved_journal,
        base_url=base_url,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=tags,
        calendar=calendar,
        parent=parent,
        children=children,
        children_count=children_count,
    )

    return await _build_journal_response(journal_resource, contact_repo)


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


# Merge Endpoint
@router.post("/{journal_id}/merge", status_code=status.HTTP_200_OK)
@inject
async def merge_journal(
    journal_id: int,
    request: Request,
    merge_request: MergeJournalRequest,
    journal_merge_service: FromDishka[JournalMergeService],
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[PhotoAlbumDataRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Merge another journal into this one.

    Preserves data according to Phase 1 rules.
    """
    source_id = merge_request.data.attributes.source_journal_id

    # Validation against identical journal ID
    if journal_id == source_id:
        from core_shared.models.journals.exceptions import JournalMergeConflictError

        raise JournalMergeConflictError("Cannot merge a journal into itself")

    # Ownership and existence checks for both target and source journals
    target_journal_for_user = await journal_service.get_journal(journal_id)
    if not target_journal_for_user:
        raise JournalNotFoundError(journal_id)

    source_journal_for_user = await journal_service.get_journal(source_id)
    if not source_journal_for_user:
        raise JournalNotFoundError(source_id)

    # Ensure both journals belong to the authenticated user to prevent cross-tenant merges
    target_user_id = str(getattr(target_journal_for_user, "user_id", ""))
    source_user_id = str(getattr(source_journal_for_user, "user_id", ""))
    auth_user_id = str(getattr(user, "id", ""))

    if target_user_id != auth_user_id or source_user_id != auth_user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to merge these journals.",
        )

    overrides_dict = None
    if merge_request.data.attributes.overrides:
        overrides_dict = merge_request.data.attributes.overrides.model_dump(
            exclude_unset=True
        )

    await journal_merge_service.merge_journals(
        target_id=journal_id,
        source_id=source_id,
        transaction=connection,
        overrides=overrides_dict,
    )

    # Get enriched target journal to return
    target_journal = await journal_service.get_journal(journal_id)
    if not target_journal:
        raise JournalNotFoundError(journal_id)

    (
        types,
        type_data,
        contacts,
        tags,
        calendar,
        routes,
    ) = await _enrich_journal_data(
        target_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=False,
    )

    base_url = get_request_base_url(request)
    resource = JournalConverter.to_resource(
        journal=target_journal,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=tags,
        calendar=calendar,
        base_url=base_url,
    )
    return await _build_journal_response(resource, contact_repo)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
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
        from core_shared.models.journals import JournalValidationError

        raise JournalValidationError(
            "journal_type",
            f"Invalid journal type: {type_request.data.attributes.journal_type}",
        ) from e

    # Add type with automatic dependency resolution.
    # Returns all types actually added (requested type + auto-resolved dependencies).
    added_types = await journal_service.add_type_to_journal(
        journal_id, journal_type, connection
    )

    # Create type-specific data rows for ALL added types (including dependencies)
    for added_type in added_types:
        await _create_type_specific_data(
            added_type,
            journal_id,
            mood_data_repo,
            plan_data_repo,
            travel_data_repo,
            fitness_data_repo,
            outdoor_activity_data_repo,
            bushwalking_data_repo,
            jogging_data_repo,
            abseiling_data_repo,
            canyoning_data_repo,
            climbing_data_repo,
            kayaking_data_repo,
            skiing_data_repo,
        )

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
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
        from core_shared.models.journals import JournalValidationError

        raise JournalValidationError(
            "journal_type", f"Invalid journal type: {journal_type}"
        ) from e

    # Remove type (publish event)
    await journal_service.remove_type_from_journal(journal_id, jtype, connection)

    # Delete the type-specific data row so it no longer appears in the response.
    # (CASCADE only fires when the whole journal is deleted, not on type removal.)
    await _delete_type_specific_data(
        jtype,
        journal_id,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
    )

    # Get updated journal
    updated_journal = await journal_service.get_journal(journal_id)
    if not updated_journal:
        raise JournalNotFoundError(journal_id)

    # Fetch all enrichment data
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)


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


async def _update_fitness_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    fitness_data_repo: FitnessDataRepository,
) -> None:
    """Update FITNESS type-specific data."""
    fitness_data = await fitness_data_repo.find_by_journal_id(journal_id)
    if not fitness_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Update fields from request
    if "heart_rate_avg" in attrs:
        fitness_data.heart_rate_avg = attrs["heart_rate_avg"]
    if "heart_rate_max" in attrs:
        fitness_data.heart_rate_max = attrs["heart_rate_max"]
    if "distance" in attrs:
        fitness_data.distance = attrs["distance"]
    if "elevation_gain" in attrs:
        fitness_data.elevation_gain = attrs["elevation_gain"]
    if "elevation_loss" in attrs:
        fitness_data.elevation_loss = attrs["elevation_loss"]
    if "duration" in attrs:
        fitness_data.duration = attrs["duration"]
    if "calories" in attrs:
        fitness_data.calories = attrs["calories"]
    if "strava_activity_id" in attrs:
        fitness_data.strava_activity_id = attrs["strava_activity_id"]

    await fitness_data_repo.save(fitness_data)


async def _update_outdoor_activity_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
) -> None:
    """Update OUTDOOR_ACTIVITY type-specific data."""
    outdoor_activity_data = await outdoor_activity_data_repo.find_by_journal_id(
        journal_id
    )
    if not outdoor_activity_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    # This ensures domain validation (e.g. no empty/whitespace strings) is enforced.
    updates: dict[str, Any] = {}
    if "activity_type" in attrs:
        updates["activity_type"] = attrs["activity_type"]
    if "weather_conditions" in attrs:
        updates["weather_conditions"] = attrs["weather_conditions"]
    if "role" in attrs:
        updates["role"] = attrs["role"]
    if "in_leadership_role" in attrs:
        updates["in_leadership_role"] = attrs["in_leadership_role"]
    if "participant_notes" in attrs:
        updates["participant_notes"] = attrs["participant_notes"]

    validated_data = dataclasses.replace(outdoor_activity_data, **updates)
    await outdoor_activity_data_repo.save(validated_data)


async def _update_bushwalking_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    bushwalking_data_repo: BushwalkingDataRepository,
) -> None:
    """Update BUSHWALKING type-specific data."""
    bushwalking_data = await bushwalking_data_repo.find_by_journal_id(journal_id)
    if not bushwalking_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    # This ensures domain validation (e.g. valid track_grading) is enforced.
    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = _parse_optional_uuid(attrs["route_id"], "route_id")
    if "track_grading" in attrs:
        updates["track_grading"] = attrs["track_grading"]

    validated_data = dataclasses.replace(bushwalking_data, **updates)
    await bushwalking_data_repo.save(validated_data)


async def _update_jogging_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    jogging_data_repo: JoggingDataRepository,
) -> None:
    """Update JOGGING type-specific data."""
    jogging_data = await jogging_data_repo.find_by_journal_id(journal_id)
    if not jogging_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = _parse_optional_uuid(attrs["route_id"], "route_id")
    if "pace" in attrs:
        updates["pace"] = attrs["pace"]

    validated_data = dataclasses.replace(jogging_data, **updates)
    await jogging_data_repo.save(validated_data)


async def _update_abseiling_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    abseiling_data_repo: AbseilingDataRepository,
) -> None:
    """Update ABSEILING_TRIP type-specific data."""
    abseiling_data = await abseiling_data_repo.find_by_journal_id(journal_id)
    if not abseiling_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    # Validate types eagerly so mismatches return 400 rather than an unhandled TypeError.
    updates: dict[str, Any] = {}
    if "number_of_abseils" in attrs:
        updates["number_of_abseils"] = _parse_optional_integer(
            attrs["number_of_abseils"], "number_of_abseils"
        )
    if "total_length" in attrs:
        updates["total_length"] = _parse_optional_integer(
            attrs["total_length"], "total_length"
        )

    validated_data = dataclasses.replace(abseiling_data, **updates)
    await abseiling_data_repo.save(validated_data)


async def _update_canyoning_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    canyoning_data_repo: CanyoningDataRepository,
) -> None:
    """Update CANYONING type-specific data."""
    canyoning_data = await canyoning_data_repo.find_by_journal_id(journal_id)
    if not canyoning_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = _parse_optional_uuid(attrs["route_id"], "route_id")
    if "french_grade" in attrs:
        if not isinstance(attrs["french_grade"], str):
            raise JournalValidationError("french_grade", "Must be a string")
        updates["french_grade"] = attrs["french_grade"]
    if "water_guage_name" in attrs:
        updates["water_guage_name"] = attrs["water_guage_name"]
    if "water_guage_level" in attrs:
        updates["water_guage_level"] = _parse_optional_integer(
            attrs["water_guage_level"], "water_guage_level"
        )
    if "is_vertical" in attrs:
        updates["is_vertical"] = attrs["is_vertical"]
    if "is_night_canyon" in attrs:
        updates["is_night_canyon"] = attrs["is_night_canyon"]
    if "is_white_water" in attrs:
        updates["is_white_water"] = attrs["is_white_water"]

    validated_data = dataclasses.replace(canyoning_data, **updates)
    await canyoning_data_repo.save(validated_data)


async def _update_climbing_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    climbing_data_repo: ClimbingDataRepository,
) -> None:
    """Update CLIMBING type-specific data."""
    climbing_data = await climbing_data_repo.find_by_journal_id(journal_id)
    if not climbing_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = _parse_optional_uuid(attrs["route_id"], "route_id")
    if "climbing_type" in attrs:
        if not isinstance(attrs["climbing_type"], str):
            raise JournalValidationError("climbing_type", "Must be a string")
        updates["climbing_type"] = attrs["climbing_type"]
    if "grade" in attrs:
        updates["grade"] = _parse_optional_integer(attrs["grade"], "grade")
    if "length" in attrs:
        updates["length"] = _parse_optional_integer(attrs["length"], "length")

    validated_data = dataclasses.replace(climbing_data, **updates)
    await climbing_data_repo.save(validated_data)


async def _update_kayaking_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    kayaking_data_repo: KayakingDataRepository,
) -> None:
    """Update KAYAKING type-specific data."""
    kayaking_data = await kayaking_data_repo.find_by_journal_id(journal_id)
    if not kayaking_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = _parse_optional_uuid(attrs["route_id"], "route_id")
    if "water_type" in attrs:
        raw_water_type = attrs["water_type"]
        if raw_water_type is not None and not isinstance(raw_water_type, str):
            raise JournalValidationError("water_type", "Must be a string or null")
        updates["water_type"] = raw_water_type

    validated_data = dataclasses.replace(kayaking_data, **updates)
    await kayaking_data_repo.save(validated_data)


async def _update_cross_country_skiing_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    skiing_data_repo: CrossCountrySkiingDataRepository,
) -> None:
    """Update CROSS_COUNTRY_SKIING type-specific data."""
    skiing_data = await skiing_data_repo.find_by_journal_id(journal_id)
    if not skiing_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = _parse_optional_uuid(attrs["route_id"], "route_id")
    if "snow_conditions" in attrs:
        raw_snow_conditions = attrs["snow_conditions"]
        if raw_snow_conditions is not None and not isinstance(raw_snow_conditions, str):
            raise JournalValidationError("snow_conditions", "Must be a string or null")
        updates["snow_conditions"] = raw_snow_conditions

    validated_data = dataclasses.replace(skiing_data, **updates)
    await skiing_data_repo.save(validated_data)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
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
    elif jtype == JournalType.FITNESS:
        await _update_fitness_type_data(
            journal_id, journal_type, attrs, fitness_data_repo
        )
    elif jtype == JournalType.OUTDOOR_ACTIVITY:
        await _update_outdoor_activity_type_data(
            journal_id, journal_type, attrs, outdoor_activity_data_repo
        )
    elif jtype == JournalType.BUSHWALKING:
        await _update_bushwalking_type_data(
            journal_id, journal_type, attrs, bushwalking_data_repo
        )
    elif jtype == JournalType.JOGGING:
        await _update_jogging_type_data(
            journal_id, journal_type, attrs, jogging_data_repo
        )
    elif jtype == JournalType.ABSEILING_TRIP:
        await _update_abseiling_type_data(
            journal_id, journal_type, attrs, abseiling_data_repo
        )
    elif jtype == JournalType.CANYONING:
        await _update_canyoning_type_data(
            journal_id, journal_type, attrs, canyoning_data_repo
        )
    elif jtype == JournalType.CLIMBING:
        await _update_climbing_type_data(
            journal_id, journal_type, attrs, climbing_data_repo
        )
    elif jtype == JournalType.KAYAKING:
        await _update_kayaking_type_data(
            journal_id, journal_type, attrs, kayaking_data_repo
        )
    elif jtype == JournalType.CROSS_COUNTRY_SKIING:
        await _update_cross_country_skiing_type_data(
            journal_id, journal_type, attrs, skiing_data_repo
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
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
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
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Remove a contact relationship from a journal.
    """
    from core_shared.models.journals import (
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
        from core_shared.models.journals import JournalValidationError

        raise JournalValidationError("contact_id", "Invalid contact ID format") from e

    try:
        relationship_type_enum = JournalContactRelationshipType[relationship_type]
    except KeyError as e:
        from core_shared.models.journals import JournalValidationError

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
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Add a tag to a journal.
    """
    from uuid import UUID

    from core_shared.models.journals import JournalValidationError

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
    types, type_data, contacts, tags, calendar, routes = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)


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
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Remove a tag from a journal.
    """
    from uuid import UUID

    from core_shared.models.journals import JournalValidationError

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
    types, type_data, contacts, tags, calendar, _ = await _enrich_journal_data(
        updated_journal,
        calendar_info_repo,
        calendar_repo,
        mood_data_repo,
        plan_data_repo,
        travel_data_repo,
        photo_album_data_repo,
        fitness_data_repo,
        contact_relationship_repo,
        tag_repo,
        route_repo,
        outdoor_activity_data_repo,
        bushwalking_data_repo,
        jogging_data_repo,
        abseiling_data_repo,
        canyoning_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)
