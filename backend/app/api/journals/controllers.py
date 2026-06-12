"""
Journal API controllers.

Handles journal-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

from datetime import UTC, datetime
from typing import Annotated, Any

import structlog
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    Journal,
    JournalContactRelationship,
    JournalContactRelationshipType,
    JournalNotFoundError,
    JournalType,
    JournalValidationError,
)
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from meilisearch.errors import MeilisearchError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import (
    ExternalLinkAttributes,
    ExternalLinkResource,
    ExternalLinksResponse,
    JsonApiLinks,
    PaginationParams,
    create_pagination_links,
    create_pagination_meta,
    get_request_base_url,
)
from app.api.history import HistoryConverter, HistoryListResponse
from app.api.journals.converters import (
    JournalConverter,
    JournalRequestConverter,
    TypeDataConverter,
)
from app.api.journals.schemas import (
    EventDateRangeSchema,
    JournalAttributes,
    JournalContactAddRequest,
    JournalContactRelationshipUpdateRequest,
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
    ReviewItemAttributes,
    ReviewItemCreateRequest,
    ReviewItemJournalSummary,
    ReviewItemListResponse,
    ReviewItemResource,
    ReviewItemResponse,
    ReviewSuggestionSchema,
)
from app.core.contacts.models.repositories import ContactRepository
from app.core.history.services import JournalHistoryService
from app.core.integrations.external_link_helpers import build_journal_external_links
from app.core.integrations.immich.album_cover_proxy_service import (
    AlbumCoverProxyService,
)
from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.core.journal.models.repositories import (
    AbseilingDataRepository,
    AbseilPitchRepository,
    BushwalkingDataRepository,
    CalendarInfoRepository,
    CalendarRepository,
    CanoeingDataRepository,
    CanyoningDataRepository,
    CavingDataRepository,
    ClimbingDataRepository,
    CrossCountrySkiingDataRepository,
    DivingDataRepository,
    DownhillSkiingDataRepository,
    FitnessDataRepository,
    GearMaintenanceDataRepository,
    JoggingDataRepository,
    JournalContactRelationshipRepository,
    JournalRepository,
    JournalTagRepository,
    KayakingDataRepository,
    MoodDataRepository,
    OutdoorActivityDataRepository,
    OutdoorPlanningDataRepository,
    OutdoorTrainingDataRepository,
    PlanDataRepository,
    ReviewItemRepository,
    RouteRepository,
    SnorkellingDataRepository,
    TravelDataRepository,
)
from app.core.journal.services.hierarchy_service import HierarchyService
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_type_data_helpers import parse_journal_type
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.review_item_service import ReviewItemService
from app.core.search.exceptions import SearchServiceUnavailableError
from app.infrastructure.auth.immich_token_service import ImmichTokenService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.config import Settings
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

PAGE_NUMBER_DESCRIPTION = "Page number"
ITEMS_PER_PAGE_DESCRIPTION = "Items per page"


@router.get("/{journal_id}/history")
@inject
async def get_journal_history(
    journal_id: int,
    request: Request,
    journal_service: FromDishka[JournalService],
    history_service: FromDishka[JournalHistoryService],
    _user: FromDishka[SessionUser],  # Require authentication
    page: Annotated[int, Query(description=PAGE_NUMBER_DESCRIPTION, ge=1)] = 1,
    limit: Annotated[
        int, Query(description=ITEMS_PER_PAGE_DESCRIPTION, ge=1, le=100)
    ] = 20,
) -> HistoryListResponse:
    """Get field-level change history for a journal.

    Returns a paginated JSON:API list of history entries (most recent first)
    covering the journal's own fields plus its type-specific data, routes, and
    gear, each with provenance. History is produced asynchronously by the
    projection consumer, so a just-made change may take a moment to appear.
    """
    base_url = get_request_base_url(request)

    # Verify the journal exists (404 otherwise, mirroring the contact endpoint).
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    offset = (page - 1) * limit

    history_entries = await history_service.get_journal_history(
        journal_id=journal_id,
        limit=limit,
        offset=offset,
    )
    total_count = await history_service.get_journal_history_count(
        journal_id=journal_id,
    )

    history_resources = [
        HistoryConverter.to_resource(entry) for entry in history_entries
    ]

    meta = create_pagination_meta(total_count, page, limit)
    links = create_pagination_links(
        f"{base_url}/api/journals/{journal_id}/history", page, limit, total_count
    )

    return HistoryListResponse(
        data=history_resources,
        meta=meta,
        links=links,
    )


@router.get("/{journal_id}/album-cover")
@inject
async def get_journal_album_cover(
    journal_id: int,
    album_cover_service: FromDishka[AlbumCoverProxyService],
    user: FromDishka[SessionUser],
) -> Response:
    """Proxy a PHOTO_ALBUM journal's Immich album cover thumbnail.

    Fetches the album cover from the Immich server using stored credentials and
    streams it back to the client. Returns 404 if the journal has no linked
    Immich album or the cover cannot be fetched. The image is served on-demand
    and never persisted locally.
    """
    from app.core.integrations.immich.album_cover_proxy_service import (
        AlbumCoverNotFoundError,
    )

    try:
        image_bytes, content_type = await album_cover_service.get_cover_bytes(
            journal_id=journal_id,
            user_id=user.id,
        )
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={
                "Cache-Control": "private, max-age=3600",
            },
        )
    except AlbumCoverNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album cover not available for this journal",
        ) from None


async def _populate_contact_names(
    resource: JournalResource,
    contact_repo: ContactRepository,
    contact_cache: dict[int, dict[str, str | None]],
) -> None:
    """Populate the names and avatar info of contacts in a JournalResource."""
    if not resource.attributes.contacts:
        return

    # Gather IDs that need fetching
    contact_ids_to_fetch = [
        int(cs.id)
        for cs in resource.attributes.contacts
        if int(cs.id) not in contact_cache and (not cs.name or not cs.photo_url)
    ]

    # Bulk fetch names and photo_url in a single query
    if contact_ids_to_fetch:
        name_rows = await contact_repo.find_names_by_ids(contact_ids_to_fetch)
        for cid, (first_name, last_name, photo_url) in name_rows.items():
            # Null-safe formatter: filter out None or empty name parts
            name_parts = [part for part in (first_name, last_name) if part]
            name = " ".join(name_parts)
            contact_cache[cid] = {
                "name": name if name else f"Contact {cid}",
                "first_name": first_name,
                "last_name": last_name,
                "photo_url": photo_url,
            }

        # Mark any IDs not found in the database
        for cid in contact_ids_to_fetch:
            if cid not in contact_cache:
                contact_cache[cid] = {
                    "name": f"Unknown Contact {cid}",
                    "first_name": None,
                    "last_name": None,
                    "photo_url": None,
                }

    # Set names and photo_url from cache
    for contact_schema in resource.attributes.contacts:
        contact_id = int(contact_schema.id)
        if contact_id in contact_cache:
            cache_info = contact_cache[contact_id]
            contact_schema.name = cache_info["name"]
            contact_schema.first_name = cache_info["first_name"]
            contact_schema.last_name = cache_info["last_name"]
            contact_schema.photo_url = cache_info.get("photo_url")


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


async def _enrich_journal_data(
    journal: Journal,
    calendar_info_repo: CalendarInfoRepository,
    calendar_repo: CalendarRepository,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    photo_album_data_repo: AlbumSyncReadRepository,
    fitness_data_repo: FitnessDataRepository,
    contact_relationship_repo: JournalContactRelationshipRepository,
    tag_repo: JournalTagRepository,
    route_repo: RouteRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    abseil_pitch_repo: AbseilPitchRepository,
    canyoning_data_repo: CanyoningDataRepository,
    caving_data_repo: CavingDataRepository,
    canoeing_data_repo: CanoeingDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
    snorkelling_data_repo: SnorkellingDataRepository,
    diving_data_repo: DivingDataRepository,
    downhill_skiing_data_repo: DownhillSkiingDataRepository,
    outdoor_planning_data_repo: OutdoorPlanningDataRepository,
    outdoor_training_data_repo: OutdoorTrainingDataRepository,
    gear_maintenance_data_repo: GearMaintenanceDataRepository,
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
        pitches = await abseil_pitch_repo.find_by_journal_id(journal_id)
        converted = TypeDataConverter.abseiling_data_to_schema(
            abseiling_data, pitches=pitches
        )
        type_data[JournalType.ABSEILING_TRIP.value] = converted

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

    caving_data = await caving_data_repo.find_by_journal_id(journal_id)
    if caving_data:
        types.append(JournalType.CAVING.value)
        type_data[JournalType.CAVING.value] = TypeDataConverter.caving_data_to_schema(
            caving_data
        )

    canoeing_data = await canoeing_data_repo.find_by_journal_id(journal_id)
    if canoeing_data:
        types.append(JournalType.CANOEING.value)
        type_data[JournalType.CANOEING.value] = (
            TypeDataConverter.canoeing_data_to_schema(canoeing_data)
        )

    snorkelling_data = await snorkelling_data_repo.find_by_journal_id(journal_id)
    if snorkelling_data:
        types.append(JournalType.SNORKELLING.value)
        type_data[JournalType.SNORKELLING.value] = (
            TypeDataConverter.snorkelling_data_to_schema(snorkelling_data)
        )

    diving_data = await diving_data_repo.find_by_journal_id(journal_id)
    if diving_data:
        types.append(JournalType.DIVING.value)
        type_data[JournalType.DIVING.value] = TypeDataConverter.diving_data_to_schema(
            diving_data
        )

    downhill_skiing_data = await downhill_skiing_data_repo.find_by_journal_id(
        journal_id
    )
    if downhill_skiing_data:
        types.append(JournalType.DOWNHILL_SKIING.value)
        type_data[JournalType.DOWNHILL_SKIING.value] = (
            TypeDataConverter.downhill_skiing_data_to_schema(downhill_skiing_data)
        )

    outdoor_planning_data = await outdoor_planning_data_repo.find_by_journal_id(
        journal_id
    )
    if outdoor_planning_data:
        types.append(JournalType.OUTDOOR_PLANNING.value)
        type_data[JournalType.OUTDOOR_PLANNING.value] = (
            TypeDataConverter.outdoor_planning_data_to_schema(outdoor_planning_data)
        )

    outdoor_training_data = await outdoor_training_data_repo.find_by_journal_id(
        journal_id
    )
    if outdoor_training_data:
        types.append(JournalType.OUTDOOR_TRAINING.value)
        type_data[JournalType.OUTDOOR_TRAINING.value] = (
            TypeDataConverter.outdoor_training_data_to_schema(outdoor_training_data)
        )

    gear_maintenance_data = await gear_maintenance_data_repo.find_by_journal_id(
        journal_id
    )
    if gear_maintenance_data:
        types.append(JournalType.GEAR_MAINTENANCE.value)
        type_data[JournalType.GEAR_MAINTENANCE.value] = (
            TypeDataConverter.gear_maintenance_data_to_schema(gear_maintenance_data)
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
    journal_tag_service: FromDishka[JournalTagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalTagResponse:
    """
    Create a new journal tag.

    Creates a new journal tag with the provided data and returns the created resource.
    """
    from uuid import UUID

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

    # Save tag as a committed unit of work (duplicate names map to a 400)
    created_tag = await journal_tag_service.create_tag(tag, connection)

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
    journal_tag_service: FromDishka[JournalTagService],
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

    # Delete the tag as a committed unit of work. The service raises a 409 if the
    # tag is still assigned to any journals.
    await journal_tag_service.delete_tag(tag_uuid, connection)

    return None


async def _fetch_parent_and_children(
    journal: Journal,
    user_id: str,
    journal_service: JournalService,
) -> tuple[Journal | None, list[Journal], int]:
    """Fetch parent journal, children list, and children count for a journal.

    Parent lookup is user-scoped to prevent cross-tenant data leakage.

    Returns:
        A tuple of (parent, children, children_count).
    """
    parent = None
    if journal.parent_id:
        parents = await journal_service.find_journals_by_ids_for_user(
            user_id=user_id, journal_ids=[journal.parent_id]
        )
        parent = parents[0] if parents else None

    children_count = 0
    children: list[Journal] = []
    if journal.id:
        children_counts = await journal_service.count_children_for_parents(
            user_id=user_id, parent_ids=[journal.id]
        )
        children_count = children_counts.get(journal.id, 0)

        if children_count > 0:
            children = await journal_service.get_journals_paginated(
                user_id=user_id,
                offset=0,
                limit=100,
                parent_id=journal.id,
            )

    return parent, children, children_count


async def _fetch_children_types(
    children: list[Journal],
    calendar_info_repo: CalendarInfoRepository,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    photo_album_data_repo: AlbumSyncReadRepository,
    fitness_data_repo: FitnessDataRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    canyoning_data_repo: CanyoningDataRepository,
    caving_data_repo: CavingDataRepository,
    canoeing_data_repo: CanoeingDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
    snorkelling_data_repo: SnorkellingDataRepository,
    diving_data_repo: DivingDataRepository,
    downhill_skiing_data_repo: DownhillSkiingDataRepository,
    outdoor_planning_data_repo: OutdoorPlanningDataRepository,
    outdoor_training_data_repo: OutdoorTrainingDataRepository,
    gear_maintenance_data_repo: GearMaintenanceDataRepository,
) -> dict[int, list[str]]:
    """Fetch only the type names for each child journal (lightweight).

    Unlike ``_enrich_journal_data`` this skips contacts, tags, calendar
    details, type_data, and routes — we only need the type *names* for the
    child summary shown in the UI.

    Returns:
        Mapping of journal ID to list of type name strings.
    """
    result: dict[int, list[str]] = {}

    for child in children:
        if child.id is None:
            continue
        journal_id = child.id
        types: list[str] = []

        if await calendar_info_repo.find_by_journal_id(journal_id):
            types.append(JournalType.EVENT.value)
        if await mood_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.MOOD_RATING.value)
        if await plan_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.PLAN.value)
        if await travel_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.TRAVEL.value)
        if await photo_album_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.PHOTO_ALBUM.value)
        if await fitness_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.FITNESS.value)
        if await outdoor_activity_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.OUTDOOR_ACTIVITY.value)
        if await bushwalking_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.BUSHWALKING.value)
        if await jogging_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.JOGGING.value)
        if await abseiling_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.ABSEILING_TRIP.value)
        if await canyoning_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.CANYONING.value)
        if await climbing_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.CLIMBING.value)
        if await kayaking_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.KAYAKING.value)
        if await skiing_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.CROSS_COUNTRY_SKIING.value)
        if await caving_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.CAVING.value)
        if await canoeing_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.CANOEING.value)
        if await snorkelling_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.SNORKELLING.value)
        if await diving_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.DIVING.value)
        if await downhill_skiing_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.DOWNHILL_SKIING.value)
        if await outdoor_planning_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.OUTDOOR_PLANNING.value)
        if await outdoor_training_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.OUTDOOR_TRAINING.value)
        if await gear_maintenance_data_repo.find_by_journal_id(journal_id):
            types.append(JournalType.GEAR_MAINTENANCE.value)

        result[journal_id] = types

    return result


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
    photo_album_data_repo: AlbumSyncReadRepository,
    fitness_data_repo: FitnessDataRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    abseil_pitch_repo: AbseilPitchRepository,
    canyoning_data_repo: CanyoningDataRepository,
    caving_data_repo: CavingDataRepository,
    canoeing_data_repo: CanoeingDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
    snorkelling_data_repo: SnorkellingDataRepository,
    diving_data_repo: DivingDataRepository,
    downhill_skiing_data_repo: DownhillSkiingDataRepository,
    outdoor_planning_data_repo: OutdoorPlanningDataRepository,
    outdoor_training_data_repo: OutdoorTrainingDataRepository,
    gear_maintenance_data_repo: GearMaintenanceDataRepository,
    contact_relationship_repo: JournalContactRelationshipRepository,
    tag_repo: JournalTagRepository,
    route_repo: RouteRepository,
    pending_review_journal_ids: set[int] | None = None,
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

    # Compute depth for each journal via DB queries
    depth_map = await HierarchyService.compute_depth_map(
        returned_ids_list, journal_service.journal_repo
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
            abseil_pitch_repo,
            canyoning_data_repo,
            caving_data_repo,
            canoeing_data_repo,
            climbing_data_repo,
            kayaking_data_repo,
            skiing_data_repo,
            snorkelling_data_repo,
            diving_data_repo,
            downhill_skiing_data_repo,
            outdoor_planning_data_repo,
            outdoor_training_data_repo,
            gear_maintenance_data_repo,
            include_routes=False,
        )
        parent = parent_by_id.get(journal.parent_id) if journal.parent_id else None
        children_count = (
            children_count_by_parent_id.get(journal.id, 0) if journal.id else 0
        )
        depth = depth_map.get(journal.id, 1) if journal.id else None
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
            depth=depth,
        )
        journal_resources.append(resource)

    # Set has_pending_reviews indicator
    review_ids = pending_review_journal_ids or set()
    for resource in journal_resources:
        journal_id_int = int(resource.id)
        resource.attributes.has_pending_reviews = journal_id_int in review_ids

    # Populate contact names
    contact_cache: dict[int, dict[str, str | None]] = {}
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
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    review_item_repo: FromDishka[ReviewItemRepository],
    user: FromDishka[SessionUser],  # Require authentication
    page: Annotated[int, Query(description="Page number", ge=1)] = 1,
    limit: Annotated[int, Query(description="Items per page", ge=1, le=100)] = 20,
    journal_type: Annotated[
        str | None, Query(description="Filter by journal type", alias="type")
    ] = None,
    start_date: Annotated[
        str | None, Query(description="Filter by start date (inclusive)")
    ] = None,
    end_date: Annotated[
        str | None, Query(description="Filter by end date (inclusive)")
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
        start_date=start_date if start_date else None,
        end_date=end_date if end_date else None,
        contact_id=str(contact_id) if contact_id else None,
        tag_id=tag_id,
        calendar_id=calendar_id,
        parent_id=parent_id,
        search=search,
    )

    total_count = await journal_service.get_journals_count(
        user_id=user.id,
        journal_type=journal_type,
        start_date=start_date if start_date else None,
        end_date=end_date if end_date else None,
        contact_id=str(contact_id) if contact_id else None,
        tag_id=tag_id,
        calendar_id=calendar_id,
        parent_id=parent_id,
        search=search,
    )

    # Fetch pending review journal IDs for the review indicator
    pending_review_journal_ids = (
        await review_item_repo.find_pending_journal_ids_by_user(user.id)
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
        abseil_pitch_repo=abseil_pitch_repo,
        canyoning_data_repo=canyoning_data_repo,
        caving_data_repo=caving_data_repo,
        canoeing_data_repo=canoeing_data_repo,
        climbing_data_repo=climbing_data_repo,
        kayaking_data_repo=kayaking_data_repo,
        skiing_data_repo=skiing_data_repo,
        snorkelling_data_repo=snorkelling_data_repo,
        diving_data_repo=diving_data_repo,
        downhill_skiing_data_repo=downhill_skiing_data_repo,
        outdoor_planning_data_repo=outdoor_planning_data_repo,
        outdoor_training_data_repo=outdoor_training_data_repo,
        gear_maintenance_data_repo=gear_maintenance_data_repo,
        contact_relationship_repo=contact_relationship_repo,
        tag_repo=tag_repo,
        route_repo=route_repo,
        pending_review_journal_ids=pending_review_journal_ids,
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


@router.get("/review-items")
@inject
async def list_review_items(
    request: Request,
    review_item_repo: FromDishka[ReviewItemRepository],
    journal_service: FromDishka[JournalService],
    user: FromDishka[SessionUser],
    limit: Annotated[int, Query(description="Items per page", ge=1, le=100)] = 20,
    offset: Annotated[int, Query(description="Items to skip", ge=0)] = 0,
    item_status: Annotated[
        str, Query(description="Filter by status", alias="status")
    ] = "pending",
) -> ReviewItemListResponse:
    """
    List review items for the authenticated user.

    Returns a paginated list of review items that need user attention.
    Each item includes source and candidate journal summaries.
    """
    base_url = get_request_base_url(request)

    if item_status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only 'pending' status is currently supported",
        )

    items = await review_item_repo.find_pending_by_user(
        user.id, limit=limit, offset=offset
    )
    total_count = await review_item_repo.count_pending_by_user(user.id)

    # Batch-fetch journal summaries for all source and candidate journals
    journal_ids = set()
    for item in items:
        journal_ids.add(item.source_journal_id)
        journal_ids.add(item.candidate_journal_id)

    journals = await journal_service.find_journals_by_ids_for_user(
        user_id=user.id, journal_ids=list(journal_ids)
    )
    journal_map = {j.id: j for j in journals if j.id is not None}

    # Build review item resources
    resources: list[ReviewItemResource] = []
    for item in items:
        resources.append(_build_review_item_resource(item, journal_map, base_url))

    meta = create_pagination_meta(
        total_count, 1 + offset // limit if limit else 1, limit
    )

    return ReviewItemListResponse(data=resources, meta=meta)


@router.post("/review-items/{item_id}/dismiss", status_code=status.HTTP_200_OK)
@inject
async def dismiss_review_item(
    item_id: int,
    request: Request,
    review_item_service: FromDishka[ReviewItemService],
    journal_service: FromDishka[JournalService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> ReviewItemResponse:
    """
    Dismiss a review item.
    """
    base_url = get_request_base_url(request)

    item = await review_item_service.dismiss(
        item_id,
        user.id,
        connection,
    )

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review item not found",
        )

    journals = await journal_service.find_journals_by_ids_for_user(
        user_id=user.id, journal_ids=[item.source_journal_id, item.candidate_journal_id]
    )
    journal_map = {j.id: j for j in journals if j.id is not None}

    # Convert to Resource
    resource = _build_review_item_resource(item, journal_map, base_url)

    return ReviewItemResponse(data=resource)


def _build_review_item_resource(
    item: Any,
    journal_map: dict[int, Any],
    base_url: str,
) -> ReviewItemResource:
    source_journal = journal_map.get(item.source_journal_id)
    candidate_journal = journal_map.get(item.candidate_journal_id)

    source_summary = ReviewItemJournalSummary(
        id=item.source_journal_id,
        title=source_journal.title
        if source_journal
        else f"Journal {item.source_journal_id}",
        event_date_range=EventDateRangeSchema(
            start=source_journal.event_date_range.start,
            end=source_journal.event_date_range.end,
        )
        if source_journal
        else EventDateRangeSchema(start=datetime.now(UTC), end=datetime.now(UTC)),
    )

    candidate_summary = ReviewItemJournalSummary(
        id=item.candidate_journal_id,
        title=candidate_journal.title
        if candidate_journal
        else f"Journal {item.candidate_journal_id}",
        event_date_range=EventDateRangeSchema(
            start=candidate_journal.event_date_range.start,
            end=candidate_journal.event_date_range.end,
        )
        if candidate_journal
        else EventDateRangeSchema(start=datetime.now(UTC), end=datetime.now(UTC)),
    )

    return ReviewItemResource(
        id=str(item.id),
        attributes=ReviewItemAttributes(
            reason=item.reason.value
            if hasattr(item.reason, "value")
            else str(item.reason),
            confidence_score=item.confidence_score,
            status=item.status,
            details=item.details,
            source_journal=source_summary,
            candidate_journal=candidate_summary,
            created_at=item.created_at,
        ),
        links=JsonApiLinks(
            self=f"{base_url}/api/journals/review-items/{item.id}",
        ),
    )


@router.post("/review-items/auto-merge", status_code=status.HTTP_200_OK)
@inject
async def auto_merge_review_items(
    review_item_service: FromDishka[ReviewItemService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> dict[str, Any]:
    """
    Auto-merge all pending review items that have no base-field conflicts.

    For each pending review item where the source and candidate journals
    have identical title, content, and event_date_range (no conflicts),
    automatically merge the source journal into the candidate journal.

    Returns the count of successfully merged items and remaining pending count.
    """
    (
        merged_count,
        skipped_count,
        remaining_count,
        errors,
    ) = await review_item_service.auto_merge_review_items(user.id, connection)

    return {
        "data": {
            "type": "auto-merge-result",
            "attributes": {
                "merged_count": merged_count,
                "skipped_count": skipped_count,
                "remaining_count": remaining_count,
                "errors": errors,
            },
        }
    }


@router.post("/review-items", status_code=status.HTTP_201_CREATED)
@inject
async def create_review_item(
    review_request: ReviewItemCreateRequest,
    review_item_service: FromDishka[ReviewItemService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
    settings: FromDishka[Settings],
) -> dict[str, Any]:
    """
    Create a review item (test-only endpoint).

    This endpoint is gated behind the ENABLE_TEST_REVIEW_ITEMS setting
    and is only available in test/CI environments for E2E testing.
    """
    from core_shared.models.journals.review_item import ReviewItem, ReviewReason

    if not settings.enable_test_review_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not found",
        )

    attrs = review_request.data.attributes
    review_item = ReviewItem(
        user_id=user.id,
        source_journal_id=attrs.source_journal_id,
        candidate_journal_id=attrs.candidate_journal_id,
        reason=ReviewReason(attrs.reason),
        confidence_score=attrs.confidence_score,
        details=attrs.details,
    )

    created, is_new = await review_item_service.create_review_item(
        review_item, connection
    )

    return {
        "data": {
            "type": "review-items",
            "id": str(created.id),
            "attributes": {
                "source_journal_id": created.source_journal_id,
                "candidate_journal_id": created.candidate_journal_id,
                "reason": created.reason.value,
                "confidence_score": created.confidence_score,
                "status": created.status,
                "is_new": is_new,
            },
        }
    }


@router.get("/{journal_id}/external-links")
@inject
async def get_journal_external_links(
    journal_id: int,
    journal_service: FromDishka[JournalService],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    journal_repo: FromDishka[JournalRepository],
    immich_token_service: FromDishka[ImmichTokenService],
    user: FromDishka[SessionUser],
) -> ExternalLinksResponse:
    """
    Get external system links for a journal.

    Returns links to external systems (Strava, Google Calendar, Immich) that
    are associated with this journal, derived from existing sync data.
    """
    journal = await journal_service.get_journal(journal_id)
    if not journal or journal.user_id != user.id:
        raise JournalNotFoundError(journal_id)

    # Fetch fitness data for Strava link
    strava_activity_id: str | None = None
    fitness_data = await fitness_data_repo.find_by_journal_id(journal_id)
    if fitness_data and fitness_data.strava_activity_id:
        strava_activity_id = fitness_data.strava_activity_id

    # Fetch external event links for Google Calendar links
    external_event_links = await journal_repo.get_external_event_links(journal_id)

    # Fetch Snipe-IT links (maintenance and checkout asset)
    snipeit_links = await journal_repo.get_snipeit_links(journal_id, user.id)

    # Fetch Immich album links and the user's Immich server URL
    immich_album_links = await journal_repo.get_immich_album_links(journal_id)
    immich_server_url = await immich_token_service.get_server_url(user.id)

    links = build_journal_external_links(
        strava_activity_id=strava_activity_id,
        external_event_links=external_event_links,
        snipeit_links=snipeit_links,
        immich_album_links=immich_album_links,
        immich_server_url=immich_server_url,
    )

    return ExternalLinksResponse(
        data=[
            ExternalLinkResource(
                id=f"{link.source}-{link.unique_key}",
                attributes=ExternalLinkAttributes(
                    source=link.source,
                    url=link.url,
                    external_id=link.external_id,
                ),
            )
            for link in links
        ]
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
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    review_item_repo: FromDishka[ReviewItemRepository],
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
    )

    parent, children, children_count = await _fetch_parent_and_children(
        journal, user.id, journal_service
    )

    children_types = await _fetch_children_types(
        children,
        calendar_info_repo,
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
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
    )

    # Compute depth for the journal
    depth_map = await HierarchyService.compute_depth_map(
        [journal.id] if journal.id else [], journal_service.journal_repo
    )
    depth = depth_map.get(journal.id, 1) if journal.id else None

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
        depth=depth,
        children_types=children_types,
    )

    # Embed pending review items in the detail response
    pending_review_items = await review_item_repo.find_pending_by_journal_id(
        journal_id=journal_id, user_id=user.id
    )
    if pending_review_items:
        # Fetch candidate journal titles
        candidate_ids = [ri.candidate_journal_id for ri in pending_review_items]
        candidate_journals = await journal_service.find_journals_by_ids_for_user(
            user_id=user.id, journal_ids=candidate_ids
        )
        candidate_title_map = {
            j.id: j.title for j in candidate_journals if j.id is not None
        }

        journal_resource.attributes.review_items = [
            ReviewSuggestionSchema(
                id=ri.id,  # type: ignore[arg-type]
                reason=ri.reason.value,
                confidence_score=ri.confidence_score,
                candidate_journal_id=ri.candidate_journal_id,
                candidate_journal_title=candidate_title_map.get(
                    ri.candidate_journal_id, f"Journal {ri.candidate_journal_id}"
                ),
                details=ri.details,
            ).model_dump()
            for ri in pending_review_items
        ]
        journal_resource.attributes.has_pending_reviews = True

    return await _build_journal_response(journal_resource, contact_repo)


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_journal(
    request: Request,
    journal_request: JournalCreateRequest,
    journal_service: FromDishka[JournalService],
    journal_write_service: FromDishka[JournalWriteService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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

    # Extract optional contact relationships from the request (HTTP concern).
    contacts_data: list[dict[str, Any]] | None = None
    if (
        hasattr(journal_request.data, "relationships")
        and journal_request.data.relationships
        and journal_request.data.relationships.contacts
    ):
        contacts_data = journal_request.data.relationships.contacts.get("data", [])

    # The whole composite write commits as one unit of work in the service layer.
    created_journal = await journal_write_service.create_journal(
        journal,
        journal_request.data.attributes.types,
        journal_request.data.attributes.type_data,
        contacts_data,
        connection,
        changed_by="ui",
        source=Provenance.UI,
    )

    # Ensure journal_id is not None (it should always be set after creation)
    if created_journal.id is None:
        raise ValueError(JOURNAL_ID_NOT_SET_MSG)

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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
        include_routes=True,
    )

    parent = (
        await journal_service.get_journal(created_journal.parent_id)
        if created_journal.parent_id
        else None
    )

    depth_map = await HierarchyService.compute_depth_map(
        [created_journal.id], journal_service.journal_repo
    )
    depth = depth_map.get(created_journal.id, 1)

    journal_resource = JournalConverter.to_resource(
        journal=created_journal,
        base_url=base_url,
        types=types,
        type_data=type_data,
        contacts=contacts,
        tags=tags,
        calendar=calendar,
        parent=parent,
        depth=depth,
    )

    return await _build_journal_response(journal_resource, contact_repo)


@router.put("/{journal_id}")
@inject
async def update_journal(
    journal_id: int,
    request: Request,
    journal_request: JournalUpdateRequest,
    journal_service: FromDishka[JournalService],
    journal_write_service: FromDishka[JournalWriteService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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

    # The service computes field-level changed_fields by diffing the persisted
    # journal against the merged `updated_journal`, so only genuine changes are
    # recorded as history (and the calendar sync trigger keys on those fields).
    saved_journal = await journal_write_service.update_journal(
        updated_journal,
        connection,
        changed_by="ui",
        source=Provenance.UI,
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
        include_routes=True,
    )

    parent, children, children_count = await _fetch_parent_and_children(
        saved_journal, user.id, journal_service
    )

    children_types = await _fetch_children_types(
        children,
        calendar_info_repo,
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
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
    )

    # Compute depth for the journal
    depth_map = await HierarchyService.compute_depth_map(
        [saved_journal.id] if saved_journal.id else [],
        journal_service.journal_repo,
    )
    depth = depth_map.get(saved_journal.id, 1) if saved_journal.id else None

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
        depth=depth,
        children_types=children_types,
    )

    return await _build_journal_response(journal_resource, contact_repo)


@router.patch("/{journal_id}")
@inject
async def partial_update_journal(
    journal_id: int,
    request: Request,
    journal_request: JournalUpdateRequest,
    journal_service: FromDishka[JournalService],
    journal_write_service: FromDishka[JournalWriteService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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

    # The service computes field-level changed_fields by diffing the persisted
    # journal against the merged `updated_journal`, so partial updates only record
    # the fields that genuinely changed.
    saved_journal = await journal_write_service.update_journal(
        updated_journal,
        connection,
        changed_by="ui",
        source=Provenance.UI,
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
        include_routes=True,
    )

    parent, children, children_count = await _fetch_parent_and_children(
        saved_journal, user.id, journal_service
    )

    children_types = await _fetch_children_types(
        children,
        calendar_info_repo,
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
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
    )

    # Compute depth for the journal
    depth_map = await HierarchyService.compute_depth_map(
        [saved_journal.id] if saved_journal.id else [],
        journal_service.journal_repo,
    )
    depth = depth_map.get(saved_journal.id, 1) if saved_journal.id else None

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
        depth=depth,
        children_types=children_types,
    )

    return await _build_journal_response(journal_resource, contact_repo)


@router.delete("/{journal_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_journal(
    journal_id: int,
    journal_service: FromDishka[JournalService],
    journal_write_service: FromDishka[JournalWriteService],
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

    await journal_write_service.delete_journal(
        journal_id, connection, changed_by="ui", source=Provenance.UI
    )


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
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
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
    journal_write_service: FromDishka[JournalWriteService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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
        journal_type = parse_journal_type(type_request.data.attributes.journal_type)
    except (ValueError, KeyError) as e:
        from core_shared.models.journals import JournalValidationError

        raise JournalValidationError(
            "journal_type",
            f"Invalid journal type: {type_request.data.attributes.journal_type}",
        ) from e

    # GEAR_MAINTENANCE requires initial type data to be added successfully
    if (
        journal_type == JournalType.GEAR_MAINTENANCE
        and not type_request.data.attributes.type_data
    ):
        from core_shared.models.journals.exceptions import JournalValidationError

        raise JournalValidationError(
            "type_data",
            "GEAR_MAINTENANCE type requires initial type data (gear_item_id) to be created.",
        )

    # Add the type (with dependency resolution), create its default rows, and
    # process any initial type data — all as a single committed unit of work.
    await journal_write_service.add_type(
        journal_id,
        journal_type,
        type_request.data.attributes.type_data,
        connection,
        changed_by="ui",
        source=Provenance.UI,
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
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
    journal_write_service: FromDishka[JournalWriteService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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
        jtype = parse_journal_type(journal_type)
    except (ValueError, KeyError) as e:
        from core_shared.models.journals import JournalValidationError

        raise JournalValidationError(
            "journal_type", f"Invalid journal type: {journal_type}"
        ) from e

    # PHOTO_ALBUM is managed by Immich album sync. Removing it would drop the
    # sync_metadata / external_reference link, and the next sync would re-import
    # the album as a *new* duplicate journal — so it cannot be removed manually.
    if jtype == JournalType.PHOTO_ALBUM:
        from core_shared.models.journals import JournalValidationError

        raise JournalValidationError(
            "journal_type",
            "PHOTO_ALBUM is managed by Immich sync and cannot be removed",
        )

    # Remove the type and delete its type-specific data row as one unit of work.
    # (CASCADE only fires when the whole journal is deleted, not on type removal.)
    await journal_write_service.remove_type(
        journal_id, jtype, connection, changed_by="ui", source=Provenance.UI
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)


@router.put("/{journal_id}/types/{journal_type}/data")
@inject
async def update_type_data(
    journal_id: int,
    journal_type: str,
    request: Request,
    type_data_request: JournalTypeDataUpdateRequest,
    journal_service: FromDishka[JournalService],
    journal_write_service: FromDishka[JournalWriteService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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
        jtype = parse_journal_type(journal_type)
    except (ValueError, KeyError) as e:
        raise JournalValidationError(
            "journal_type", f"Invalid journal type: {journal_type}"
        ) from e

    # Get the attributes from the request
    attrs = type_data_request.data.attributes

    # Update type-specific data as a committed unit of work. Provenance flows to
    # the JournalUpdated event the service publishes, so type-data history is
    # attributed to the UI.
    await journal_write_service.update_type_data(
        journal_id,
        jtype,
        attrs,
        connection,
        changed_by="ui",
        source=Provenance.UI,
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
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
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    connection: FromDishka[AsyncConnection],
    journal_contact_service: FromDishka[JournalContactService],
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

    # Parse status and role if present
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole

    status, role = None, None
    status_raw = contact_request.data.attributes.status
    if isinstance(status_raw, str):
        try:
            status = AttendeeStatus[status_raw.upper()]
        except KeyError as e:
            raise JournalValidationError(
                "status", f"Invalid status: {status_raw}"
            ) from e

    role_raw = contact_request.data.attributes.role
    if isinstance(role_raw, str):
        try:
            role = ContactEventRole[role_raw.upper()]
        except KeyError as e:
            raise JournalValidationError("role", f"Invalid role: {role_raw}") from e

    # Create the relationship
    relationship = JournalContactRelationship(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=relationship_type,
        status=status,
        role=role,
    )
    try:
        await journal_contact_service.add_contact_to_journal(
            relationship, transaction=connection
        )
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)


@router.patch("/{journal_id}/relationships/contacts/{contact_id}/{relationship_type}")
@inject
async def update_journal_contact_relationship(
    journal_id: int,
    contact_id: int,
    relationship_type: str,
    request: Request,
    update_request: JournalContactRelationshipUpdateRequest,
    journal_service: FromDishka[JournalService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    connection: FromDishka[AsyncConnection],
    journal_contact_service: FromDishka[JournalContactService],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Update a journal-contact relationship's status and/or role.

    Allows manual override of attendee status (e.g. ATTENDED back to ATTENDING)
    and event role.
    """
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole

    base_url = get_request_base_url(request)

    # Verify journal exists
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)

    # Parse relationship type
    try:
        rel_type_enum = JournalContactRelationshipType[relationship_type]
    except KeyError as e:
        raise JournalValidationError(
            "relationship_type",
            f"Invalid relationship type: {relationship_type}",
        ) from e

    if rel_type_enum not in [
        JournalContactRelationshipType.PARTICIPANT,
        JournalContactRelationshipType.INVITEE,
    ]:
        raise JournalValidationError(
            "relationship_type",
            f"Status and role updates are not supported for {relationship_type} relationships",
        )

    # Parse and validate status
    attrs = update_request.data.attributes
    update_status = "status" in attrs.model_fields_set
    status: AttendeeStatus | None = None
    if update_status and attrs.status is not None:
        try:
            status = AttendeeStatus[attrs.status.upper()]
        except KeyError as e:
            raise JournalValidationError(
                "status", f"Invalid status: {attrs.status}"
            ) from e

    # Parse and validate role
    update_role = "role" in attrs.model_fields_set
    role: ContactEventRole | None = None
    if update_role and attrs.role is not None:
        try:
            role = ContactEventRole[attrs.role.upper()]
        except KeyError as e:
            raise JournalValidationError("role", f"Invalid role: {attrs.role}") from e

    # Update status and role if provided
    if not update_status and not update_role:
        raise JournalValidationError(
            "attributes", "At least one of status or role must be provided"
        )

    updated = await journal_contact_service.update_attributes(
        journal_id=journal_id,
        contact_id=contact_id,
        relationship_type=rel_type_enum,
        transaction=connection,
        status=status,
        role=role,
        update_status=update_status,
        update_role=update_role,
    )
    if updated is None:
        raise JournalValidationError(
            "contact_id",
            f"Relationship not found for contact {contact_id} "
            f"with type {relationship_type}",
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
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
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
    contact_relationship_repo: FromDishka[JournalContactRelationshipRepository],
    tag_repo: FromDishka[JournalTagRepository],
    route_repo: FromDishka[RouteRepository],
    contact_repo: FromDishka[ContactRepository],
    connection: FromDishka[AsyncConnection],
    journal_contact_service: FromDishka[JournalContactService],
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
    await journal_contact_service.remove_contact_from_journal(
        journal_id, contact_id_int, relationship_type_enum, transaction=connection
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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
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
    journal_tag_service: FromDishka[JournalTagService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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

    # Assign tag to journal as a committed unit of work
    await journal_tag_service.assign_tag(journal_id, tag_uuid, connection)

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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
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
    journal_tag_service: FromDishka[JournalTagService],
    calendar_info_repo: FromDishka[CalendarInfoRepository],
    calendar_repo: FromDishka[CalendarRepository],
    mood_data_repo: FromDishka[MoodDataRepository],
    plan_data_repo: FromDishka[PlanDataRepository],
    travel_data_repo: FromDishka[TravelDataRepository],
    photo_album_data_repo: FromDishka[AlbumSyncReadRepository],
    fitness_data_repo: FromDishka[FitnessDataRepository],
    outdoor_activity_data_repo: FromDishka[OutdoorActivityDataRepository],
    bushwalking_data_repo: FromDishka[BushwalkingDataRepository],
    jogging_data_repo: FromDishka[JoggingDataRepository],
    abseiling_data_repo: FromDishka[AbseilingDataRepository],
    abseil_pitch_repo: FromDishka[AbseilPitchRepository],
    canyoning_data_repo: FromDishka[CanyoningDataRepository],
    caving_data_repo: FromDishka[CavingDataRepository],
    canoeing_data_repo: FromDishka[CanoeingDataRepository],
    climbing_data_repo: FromDishka[ClimbingDataRepository],
    kayaking_data_repo: FromDishka[KayakingDataRepository],
    skiing_data_repo: FromDishka[CrossCountrySkiingDataRepository],
    snorkelling_data_repo: FromDishka[SnorkellingDataRepository],
    diving_data_repo: FromDishka[DivingDataRepository],
    downhill_skiing_data_repo: FromDishka[DownhillSkiingDataRepository],
    outdoor_planning_data_repo: FromDishka[OutdoorPlanningDataRepository],
    outdoor_training_data_repo: FromDishka[OutdoorTrainingDataRepository],
    gear_maintenance_data_repo: FromDishka[GearMaintenanceDataRepository],
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

    # Remove tag from journal as a committed unit of work
    await journal_tag_service.remove_tag(journal_id, tag_uuid, connection)

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
        abseil_pitch_repo,
        canyoning_data_repo,
        caving_data_repo,
        canoeing_data_repo,
        climbing_data_repo,
        kayaking_data_repo,
        skiing_data_repo,
        snorkelling_data_repo,
        diving_data_repo,
        downhill_skiing_data_repo,
        outdoor_planning_data_repo,
        outdoor_training_data_repo,
        gear_maintenance_data_repo,
        include_routes=True,
    )

    journal_resource = JournalConverter.to_resource(
        updated_journal, base_url, types, type_data, contacts, tags, calendar
    )

    return await _build_journal_response(journal_resource, contact_repo)
