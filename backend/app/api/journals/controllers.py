"""
Journal API controllers.

Handles journal-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

import structlog
from core_shared.models.history import Provenance
from core_shared.models.journals import (
    IncompleteOutdoorActivity,
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

from app.api.common.etag import get_if_match, set_etag
from app.api.common.schemas import (
    ExternalLinkAttributes,
    ExternalLinkResource,
    ExternalLinksResponse,
    JsonApiLinks,
    PaginationParams,
    PreconditionFailedErrorResponse,
    create_pagination_links,
    create_pagination_meta,
    get_request_base_url,
)
from app.api.history import HistoryConverter, HistoryListResponse
from app.api.journals.converters import (
    JournalConverter,
    JournalRequestConverter,
)
from app.api.journals.schemas import (
    CheckedOutGearItemSchema,
    EventDateRangeSchema,
    IncompleteOutdoorActivityAttributes,
    IncompleteOutdoorActivityListResponse,
    IncompleteOutdoorActivityResource,
    JournalAttributes,
    JournalContactAddRequest,
    JournalContactRelationshipUpdateRequest,
    JournalCreateRequest,
    JournalHasAnchoredTasksErrorResponse,
    JournalListResponse,
    JournalResource,
    JournalResponse,
    JournalTagAddRequest,
    JournalTagCreateRequest,
    JournalTagListResponse,
    JournalTagMergeRequest,
    JournalTagResource,
    JournalTagResponse,
    JournalTagUpdateRequest,
    JournalTypeAddRequest,
    JournalTypeDataUpdateRequest,
    JournalUpdateRequest,
    MergeJournalRequest,
    OutdoorActivityDismissalAttributes,
    OutdoorActivityDismissalResource,
    OutdoorActivityDismissalResponse,
    OutdoorActivityTotalsSchema,
    OutdoorDashboardAttributes,
    OutdoorDashboardResource,
    OutdoorDashboardResponse,
    ReviewItemAttributes,
    ReviewItemCreateRequest,
    ReviewItemJournalSummary,
    ReviewItemListResponse,
    ReviewItemResource,
    ReviewItemResponse,
    ReviewSuggestionSchema,
    TemplateDoneSchema,
    UpcomingOutdoorActivitySchema,
)
from app.core.history.services import JournalHistoryService
from app.core.integrations.immich.album_cover_proxy_service import (
    AlbumCoverProxyService,
)
from app.core.journal.models.journal_tag import JournalTag
from app.core.journal.models.repositories import (
    JournalTagRepository,
    ReviewItemRepository,
)
from app.core.journal.services.hierarchy_service import HierarchyService
from app.core.journal.services.incomplete_outdoor_activity_service import (
    IncompleteOutdoorActivityService,
)
from app.core.journal.services.journal_contact_service import JournalContactService
from app.core.journal.services.journal_enrichment_service import (
    JournalEnrichmentService,
)
from app.core.journal.services.journal_external_link_service import (
    JournalExternalLinkService,
)
from app.core.journal.services.journal_merge_service import JournalMergeService
from app.core.journal.services.journal_service import JournalService
from app.core.journal.services.journal_tag_service import JournalTagService
from app.core.journal.services.journal_type_data_helpers import parse_journal_type
from app.core.journal.services.journal_write_service import JournalWriteService
from app.core.journal.services.outdoor_activity_dismissal_service import (
    OutdoorActivityDismissalService,
)
from app.core.journal.services.outdoor_dashboard_service import (
    OutdoorDashboardService,
)
from app.core.journal.services.review_item_service import ReviewItemService
from app.core.search.exceptions import SearchServiceUnavailableError

# The tasks domain's **read** service, never ``TaskService``: the journal list
# needs to know how many commitments a journal is waiting on, and must not be
# handed the ability to change one to find out.
from app.core.tasks.services.task_read_service import TaskReadService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.config import Settings
from app.infrastructure.di.auth import AdminAccess
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
    user: FromDishka[SessionUser],  # Require authentication
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

    # Verify the journal exists and belongs to the authenticated user; a journal
    # owned by someone else is reported as not-found so history cannot leak across
    # users (mirrors the route sub-resource endpoints).
    await _require_owned_journal(journal_service, user.id, journal_id)

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


async def _journal_resource_with_hierarchy(
    journal: Journal,
    user_id: str,
    base_url: str,
    journal_service: JournalService,
    enrichment_service: JournalEnrichmentService,
) -> JournalResource:
    """A journal's full resource: its enrichment, parent, children and depth.

    What the detail read and the whole-journal writes (PUT, PATCH) answer with.
    """
    assert journal.id is not None, "A stored journal has an id"
    enrichment = await enrichment_service.enrich(journal.id, user_id)
    parent, children, children_count = await _fetch_parent_and_children(
        journal, user_id, journal_service
    )
    children_types = await enrichment_service.types_for(
        [child.id for child in children or [] if child.id is not None]
    )
    depth_map = await HierarchyService.compute_depth_map(
        [journal.id], journal_service.journal_repo
    )
    return JournalConverter.to_enriched_resource(
        journal,
        base_url,
        enrichment,
        parent=parent,
        children=children,
        children_count=children_count,
        depth=depth_map.get(journal.id, 1),
        children_types=children_types,
    )


async def _enriched_journal_response(
    journal_id: int,
    user_id: str,
    base_url: str,
    journal_service: JournalService,
    enrichment_service: JournalEnrichmentService,
) -> JournalResponse:
    """The journal a write endpoint answers with, re-read after the write.

    Rendered from its enrichment, like every other journal response.
    """
    journal = await journal_service.get_journal(journal_id)
    if not journal:
        raise JournalNotFoundError(journal_id)
    enrichment = await enrichment_service.enrich(journal_id, user_id)
    return JournalResponse(
        data=JournalConverter.to_enriched_resource(journal, base_url, enrichment)
    )


def _journal_tag_resource(tag: JournalTag, base_url: str) -> JournalTagResource:
    """Build the JSON:API resource for a journal tag."""
    return JournalTagResource(
        type="journal-tags",
        id=str(tag.id) if tag.id else "",
        attributes={
            "name": tag.name,
            "color": tag.color,
            "description": tag.description,
            "parent_id": str(tag.parent_id) if tag.parent_id else None,
        },
        links=JsonApiLinks(
            self=f"{base_url}/api/journals/tags/{tag.id}",
        )
        if tag.id
        else None,
    )


@router.get("/tags")
@inject
async def list_journal_tags(
    request: Request,
    tag_repo: FromDishka[JournalTagRepository],
    user: FromDishka[SessionUser],
) -> JournalTagListResponse:
    """
    List the session user's journal tags.

    Returns every tag the user owns, which they can use to categorize journals.
    """
    base_url = get_request_base_url(request)

    all_tags = await tag_repo.get_all(user_id=user.id)

    # Convert to resources
    tag_resources = [_journal_tag_resource(tag, base_url) for tag in all_tags]

    return JournalTagListResponse(data=tag_resources)


@router.post("/tags", status_code=status.HTTP_201_CREATED)
@inject
async def create_journal_tag(
    request: Request,
    tag_request: JournalTagCreateRequest,
    journal_tag_service: FromDishka[JournalTagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> JournalTagResponse:
    """
    Create a new journal tag, owned by the session user.

    Creates a new journal tag with the provided data and returns the created resource.
    """
    from uuid import UUID

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
        description=tag_request.data.attributes.description,
        parent_id=parent_id,
        user_id=user.id,
    )

    # Save tag as a committed unit of work (duplicate names map to a 400)
    created_tag = await journal_tag_service.create_tag(tag, connection)

    return JournalTagResponse(data=_journal_tag_resource(created_tag, base_url))


@router.patch("/tags/{tag_id}")
@inject
async def update_journal_tag(
    tag_id: str,
    request: Request,
    tag_request: JournalTagUpdateRequest,
    journal_tag_service: FromDishka[JournalTagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalTagResponse:
    """
    Update a journal tag.

    Updates the supplied attributes and returns the updated resource. Omitted
    attributes are left unchanged; an explicit null ``parent_id`` moves the tag
    back to the root of the hierarchy.

    Raises:
        400: Invalid ID format, mismatched resource type or body ID, duplicate
             name, malformed colour, or a parent that would create a cycle.
        404: Tag not found, or the requested parent tag does not exist.
    """
    from uuid import UUID

    base_url = get_request_base_url(request)

    # Validated unconditionally: type is the JSON:API discriminator, so a falsy
    # but wrong value (an empty string) must not slip through. The schema
    # defaults it to "journal-tags" when the client omits it.
    if tag_request.data.type != "journal-tags":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid resource type, expected 'journal-tags'",
        )

    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tag ID format",
        ) from e

    if tag_request.data.id is not None:
        # Compare parsed UUIDs so equivalent ids that differ only in case or
        # hyphenation are not rejected.
        try:
            body_uuid = UUID(tag_request.data.id)
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tag ID format in request body",
            ) from e
        if body_uuid != tag_uuid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path ID does not match body ID",
            )

    attrs = tag_request.data.attributes

    # An explicit null parent_id is the wire signal for "move to the root";
    # an omitted parent_id leaves the existing parent alone.
    set_parent_null = "parent_id" in attrs.model_fields_set and attrs.parent_id is None

    parent_id = None
    if attrs.parent_id is not None:
        try:
            parent_id = UUID(attrs.parent_id)
        except ValueError as e:
            raise JournalValidationError("parent_id", INVALID_UUID_FORMAT_MSG) from e

    updated_tag = await journal_tag_service.update_tag(
        tag_id=tag_uuid,
        transaction=connection,
        user_id=user.id,
        name=attrs.name,
        color=attrs.color,
        description=attrs.description,
        parent_id=parent_id,
        set_parent_null=set_parent_null,
        source=Provenance.UI,
        changed_by="ui",
    )

    return JournalTagResponse(data=_journal_tag_resource(updated_tag, base_url))


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_journal_tag(
    tag_id: str,
    journal_tag_service: FromDishka[JournalTagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a journal tag, removing it from every journal it is assigned to.

    Matches contact tag delete: an in-use tag is deleted rather than blocked.
    Assignments cascade away and child tags are re-parented to the root.

    Only the session user's own tags can be deleted; another user's tag is
    not found.

    Args:
        tag_id: UUID of the tag to delete
        journal_tag_service: Service owning the delete unit of work
        connection: Database connection
        user: Authenticated user

    Returns:
        None (204 No Content)

    Raises:
        400: Invalid tag ID format
        404: Tag not found
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

    # Delete as a committed unit of work. The service raises
    # JournalTagNotFoundError (404) when the tag does not exist, and publishes a
    # JournalTagDeleted event for every journal that carried the tag.
    await journal_tag_service.delete_tag(
        tag_uuid,
        connection,
        user_id=user.id,
        source=Provenance.UI,
        changed_by="ui",
    )

    return None


@router.post("/tags/{tag_id}/merge", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def merge_journal_tag(
    tag_id: str,
    merge_request: JournalTagMergeRequest,
    journal_tag_service: FromDishka[JournalTagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Merge a journal tag into another tag, deleting the source.

    Every journal tagged with the source tag ends up tagged with the target
    instead; journals already carrying both keep a single assignment. Child
    tags of the source are adopted by the target rather than moved to the root.

    Args:
        tag_id: UUID of the source tag, which is merged away and deleted
        merge_request: Body carrying the target tag id
        journal_tag_service: Service owning the merge unit of work
        connection: Database connection
        user: Authenticated user

    Returns:
        None (204 No Content)

    Raises:
        400: Invalid tag ID format, wrong resource type, merging a tag into
             itself, or merging a tag into one of its own descendants.
        404: Either tag does not exist.
    """
    from uuid import UUID

    if merge_request.data.type != "journal-tags":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid resource type, expected 'journal-tags'",
        )

    try:
        source_uuid = UUID(tag_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid tag ID format",
        ) from e

    try:
        target_uuid = UUID(merge_request.data.attributes.target_tag_id)
    except ValueError as e:
        raise JournalValidationError("target_tag_id", INVALID_UUID_FORMAT_MSG) from e

    # Merge as a committed unit of work. The service validates both tags exist
    # and that the target is not a descendant of the source.
    # The service publishes a JournalTagMerged event for every journal that
    # carried the source tag.
    await journal_tag_service.merge_tag(
        source_uuid,
        target_uuid,
        connection,
        user_id=user.id,
        source=Provenance.UI,
        changed_by="ui",
    )

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


async def _build_journal_list_resources(
    journals: list[Journal],
    user_id: str,
    base_url: str,
    journal_service: JournalService,
    enrichment_service: JournalEnrichmentService,
    pending_review_journal_ids: set[int] | None = None,
    tasks_due_counts: dict[int, int] | None = None,
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

    journal_resources = []
    for journal in all_journals:
        assert journal.id is not None, "De-duplicated journals all have ids"
        parent = parent_by_id.get(journal.parent_id) if journal.parent_id else None
        journal_resources.append(
            JournalConverter.to_enriched_resource(
                journal,
                base_url,
                await enrichment_service.enrich(journal.id, user_id),
                parent=parent,
                children_count=children_count_by_parent_id.get(journal.id, 0),
                depth=depth_map.get(journal.id, 1),
            )
        )

    # Set the list-level indicators, both of them read once for the whole page
    # and zipped on here rather than fetched per row.
    review_ids = pending_review_journal_ids or set()
    for resource in journal_resources:
        journal_id_int = int(resource.id)
        resource.attributes.has_pending_reviews = journal_id_int in review_ids
        # **The two `None`s have to agree.** ``tasks_due_count`` is nullable
        # precisely so a payload nobody ran the count for says so instead of
        # claiming zero — so a caller that passed no mapping must leave the
        # field alone rather than stamp a zero on every row. An `or {}` here
        # would collapse "not computed" into "computed, nothing due" and
        # reintroduce the false claim the nullable field exists to prevent.
        #
        # Within a mapping that *was* computed, a missing key really does mean
        # none: the count read omits journals with nothing due rather than
        # returning a zero for each, so a page holding no tasks costs no rows.
        if tasks_due_counts is not None:
            resource.attributes.tasks_due_count = tasks_due_counts.get(
                journal_id_int, 0
            )

    return journal_resources


@router.get("")
@inject
async def list_journals(
    request: Request,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    review_item_repo: FromDishka[ReviewItemRepository],
    task_read_service: FromDishka[TaskReadService],
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
    tag_id: Annotated[
        UUID | None,
        Query(description="Filter by tag ID (deprecated: use tag_ids)"),
    ] = None,
    tag_ids: Annotated[
        list[UUID] | None,
        Query(
            description=(
                "Filter by tag IDs. Repeat the parameter for multiple tags; a "
                "journal matching any of them (or any of their descendant tags) "
                "is returned."
            )
        ),
    ] = None,
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

    # `tag_id` predates the repeatable `tag_ids` param and is still sent by the
    # journal list UI; the two are unioned so either spelling works. Both are
    # parsed as UUIDs here, so a malformed id is a 400 rather than a 500.
    requested_tag_ids = list(
        dict.fromkeys(
            str(value) for value in [*(tag_ids or []), *([tag_id] if tag_id else [])]
        )
    )

    # Get all journals for the user
    journals = await journal_service.get_journals_paginated(
        user_id=user.id,
        offset=pagination.offset,
        limit=pagination.limit,
        journal_type=journal_type,
        start_date=start_date or None,
        end_date=end_date or None,
        contact_id=str(contact_id) if contact_id else None,
        tag_ids=requested_tag_ids or None,
        calendar_id=calendar_id,
        parent_id=parent_id,
        search=search,
    )

    total_count = await journal_service.get_journals_count(
        user_id=user.id,
        journal_type=journal_type,
        start_date=start_date or None,
        end_date=end_date or None,
        contact_id=str(contact_id) if contact_id else None,
        tag_ids=requested_tag_ids or None,
        calendar_id=calendar_id,
        parent_id=parent_id,
        search=search,
    )

    # Fetch pending review journal IDs for the review indicator
    pending_review_journal_ids = (
        await review_item_repo.find_pending_journal_ids_by_user(user.id)
    )

    # And the tasks-due indicator, for this page's journals only. The read is
    # given the journals rather than their ids because judging whether a
    # journal's commitments have lapsed needs its date, which is already loaded
    # here — and it costs a single statement when nothing is due, which is what
    # nearly every page will find.
    tasks_due_counts = await task_read_service.due_task_counts(user.id, journals)

    # Convert to resources with enriched data
    journal_resources = await _build_journal_list_resources(
        journals=journals,
        user_id=user.id,
        base_url=base_url,
        journal_service=journal_service,
        enrichment_service=enrichment_service,
        pending_review_journal_ids=pending_review_journal_ids,
        tasks_due_counts=tasks_due_counts,
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


@router.get("/incomplete-outdoor-activities")
@inject
async def list_incomplete_outdoor_activities(
    request: Request,
    incomplete_service: FromDishka[IncompleteOutdoorActivityService],
    user: FromDishka[SessionUser],
    include_dismissed: Annotated[
        bool,
        Query(
            description=(
                "Also return dismissed journals, flagged dismissed=true "
                "(default false: dismissed journals are excluded)"
            )
        ),
    ] = False,
) -> IncompleteOutdoorActivityListResponse:
    """
    List the user's incomplete outdoor activity journals with their reasons.

    An advisory, unpaginated projection over the user's outdoor journals:
    each entry names the rule(s) it matches (no_attributes, missing_template,
    no_participants). Only activities that have already started are reviewed —
    a journal beginning after the end of today (in the user's timezone) is a
    plan, not a gap. Dismissed journals are excluded unless
    ``include_dismissed`` is set, in which case they are returned flagged
    ``dismissed: true`` (so the UI can offer un-dismiss).
    """
    base_url = get_request_base_url(request)

    entries = await incomplete_service.list_incomplete(
        user.id, include_dismissed=include_dismissed
    )

    resources = [
        _build_incomplete_outdoor_activity_resource(entry, base_url)
        for entry in entries
    ]
    return IncompleteOutdoorActivityListResponse(data=resources)


@router.post(
    "/incomplete-outdoor-activities/{journal_id}/dismiss",
    status_code=status.HTTP_200_OK,
)
@inject
async def dismiss_incomplete_outdoor_activity(
    journal_id: int,
    dismissal_service: FromDishka[OutdoorActivityDismissalService],
    journal_service: FromDishka[JournalService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> OutdoorActivityDismissalResponse:
    """
    Dismiss a journal from the incomplete outdoor activities review.

    Idempotent: re-dismissing refreshes the recorded provenance. The dismissed
    journal no longer appears in the review regardless of matched rules.
    """
    await _require_owned_journal(journal_service, user.id, journal_id)

    dismissal = await dismissal_service.dismiss(
        journal_id, user.id, Provenance.UI, connection
    )

    return OutdoorActivityDismissalResponse(
        data=OutdoorActivityDismissalResource(
            id=str(journal_id),
            attributes=OutdoorActivityDismissalAttributes(
                journal_id=journal_id,
                dismissed=True,
                provenance=dismissal.provenance.value,
            ),
        )
    )


@router.post(
    "/incomplete-outdoor-activities/{journal_id}/undismiss",
    status_code=status.HTTP_200_OK,
)
@inject
async def undismiss_incomplete_outdoor_activity(
    journal_id: int,
    dismissal_service: FromDishka[OutdoorActivityDismissalService],
    journal_service: FromDishka[JournalService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> OutdoorActivityDismissalResponse:
    """
    Un-dismiss a journal, restoring it to the incomplete review when flagged.

    Idempotent: un-dismissing a journal that was never dismissed is a no-op
    (``was_dismissed`` is false).
    """
    await _require_owned_journal(journal_service, user.id, journal_id)

    was_dismissed = await dismissal_service.undismiss(journal_id, user.id, connection)

    return OutdoorActivityDismissalResponse(
        data=OutdoorActivityDismissalResource(
            id=str(journal_id),
            attributes=OutdoorActivityDismissalAttributes(
                journal_id=journal_id,
                dismissed=False,
                was_dismissed=was_dismissed,
            ),
        )
    )


@router.get("/outdoor-dashboard")
@inject
async def get_outdoor_dashboard(
    dashboard_service: FromDishka[OutdoorDashboardService],
    user: FromDishka[SessionUser],
) -> OutdoorDashboardResponse:
    """
    The outdoor logbook dashboard: all four widget sections in one call.

    A read-only singleton projection over the user's outdoor journals —
    upcoming activities (next 30 days, soonest first, capped at 10), gear
    currently checked out, activity totals by type over rolling 30/365-day
    windows and the templates done with per-template counts. Windows are
    anchored on "today" in the user's configured timezone server-side, so
    the endpoint takes no date parameters.

    Alongside the per-type mappings the totals carry distinct-journal counts,
    and ``templates_done_last_30_days`` counts the distinct templates done
    recently; neither can be derived from the mappings they sit beside.
    """
    upcoming = await dashboard_service.list_upcoming_activities(user.id)
    totals = await dashboard_service.activity_totals(user.id)
    checked_out = await dashboard_service.list_checked_out_gear(user.id)
    templates_done = await dashboard_service.templates_done(user.id)

    return OutdoorDashboardResponse(
        data=OutdoorDashboardResource(
            id=user.id,
            attributes=OutdoorDashboardAttributes(
                upcoming_activities=[
                    UpcomingOutdoorActivitySchema(
                        journal_id=entry.journal_id,
                        title=entry.title,
                        event_date_range=EventDateRangeSchema(
                            start=entry.event_date_range.start,
                            end=entry.event_date_range.end,
                        ),
                        subtypes=entry.subtypes,
                        is_planning=entry.is_planning,
                    )
                    for entry in upcoming
                ],
                checked_out_gear=[
                    CheckedOutGearItemSchema(
                        gear_item_id=item.gear_item_id,
                        name=item.name,
                        checked_out_since=item.checked_out_since,
                        journal_id=item.journal_id,
                    )
                    for item in checked_out
                ],
                activity_totals=OutdoorActivityTotalsSchema(
                    last_30_days=totals.last_30_days,
                    last_365_days=totals.last_365_days,
                    total_last_30_days=totals.total_last_30_days,
                    total_last_365_days=totals.total_last_365_days,
                ),
                templates_done={
                    template_type: [
                        TemplateDoneSchema(
                            template_id=template.template_id,
                            name=template.name,
                            done_count=template.done_count,
                        )
                        for template in templates
                    ]
                    for template_type, templates in templates_done.by_type.items()
                },
                templates_done_last_30_days=templates_done.recent_unique_count,
            ),
        )
    )


async def _require_owned_journal(
    journal_service: JournalService, user_id: str, journal_id: int
) -> Journal:
    """Return the journal, or raise ``JournalNotFoundError`` if it is not yours.

    Every handler taking a ``{journal_id}`` needs the journal anyway, so going
    through here costs nothing: the read is the one the handler was already
    doing, only scoped to the owner in SQL. That is the whole of issue #1267 —
    eleven handlers fetched the journal by id alone and never compared its
    ``user_id``, so a stranger could read, rewrite and strip any journal.

    A journal belonging to somebody else raises exactly as a missing one does,
    so the refusal cannot be used to discover that the id is real.
    """
    journal = await journal_service.get_journal_for_user(journal_id, user_id)
    if journal is None:
        raise JournalNotFoundError(journal_id)
    return journal


def _build_incomplete_outdoor_activity_resource(
    entry: IncompleteOutdoorActivity, base_url: str
) -> IncompleteOutdoorActivityResource:
    return IncompleteOutdoorActivityResource(
        id=str(entry.journal_id),
        attributes=IncompleteOutdoorActivityAttributes(
            title=entry.title,
            event_date_range=EventDateRangeSchema(
                start=entry.event_date_range.start,
                end=entry.event_date_range.end,
            ),
            subtypes=entry.subtypes,
            reasons=entry.reasons,
            dismissed=entry.dismissed,
        ),
        links=JsonApiLinks(
            self=f"{base_url}/api/journals/{entry.journal_id}",
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
    ) = await review_item_service.auto_merge_review_items(
        user.id,
        connection,
        # "Auto" is how the pairs were chosen, not who chose to merge them: a
        # person pressed this, so the tasks these merges move say so.
        source=Provenance.UI,
        changed_by="ui",
    )

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
    _admin: FromDishka[AdminAccess],
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
    link_service: FromDishka[JournalExternalLinkService],
    user: FromDishka[SessionUser],
) -> ExternalLinksResponse:
    """
    Get external system links for a journal.

    Returns links to external systems (Strava, Google Calendar, Snipe-IT,
    Immich) that are associated with this journal, derived from existing sync
    data: the same links the MCP journal tools report.
    """
    await _require_owned_journal(journal_service, user.id, journal_id)

    links = await link_service.links_for_journal(journal_id, user.id)

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
    response: Response,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    review_item_repo: FromDishka[ReviewItemRepository],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Get a single journal by ID.

    Returns a single journal resource following JSON API specification.
    """
    base_url = get_request_base_url(request)

    journal = await _require_owned_journal(journal_service, user.id, journal_id)
    set_etag(response, "journals", journal_id, journal.updated_at)

    journal_resource = await _journal_resource_with_hierarchy(
        journal, user.id, base_url, journal_service, enrichment_service
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

    return JournalResponse(data=journal_resource)


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_journal(
    request: Request,
    journal_request: JournalCreateRequest,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    journal_write_service: FromDishka[JournalWriteService],
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

    enrichment = await enrichment_service.enrich(created_journal.id, user.id)

    parent = (
        await journal_service.get_journal(created_journal.parent_id)
        if created_journal.parent_id
        else None
    )

    depth_map = await HierarchyService.compute_depth_map(
        [created_journal.id], journal_service.journal_repo
    )
    depth = depth_map.get(created_journal.id, 1)

    journal_resource = JournalConverter.to_enriched_resource(
        created_journal,
        base_url,
        enrichment,
        parent=parent,
        depth=depth,
    )

    return JournalResponse(data=journal_resource)


@router.put(
    "/{journal_id}",
    responses={
        412: {
            "model": PreconditionFailedErrorResponse,
            "description": (
                "The `If-Match` precondition named a version this journal has "
                "already moved on from — somebody else wrote to it since the "
                "caller read it. Nothing was written. The JSON:API error "
                "carries code `PRECONDITION_FAILED` and a `meta.current_etag` "
                "to retry with after re-reading and re-applying the change."
            ),
        },
    },
)
@inject
async def update_journal(
    journal_id: int,
    request: Request,
    response: Response,
    journal_request: JournalUpdateRequest,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    journal_write_service: FromDishka[JournalWriteService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Update an existing journal (full replacement).

    Updates the journal with the provided data and returns the updated resource.
    """
    base_url = get_request_base_url(request)

    existing_journal = await _require_owned_journal(
        journal_service, user.id, journal_id
    )

    # The precondition is handed to the service untouched: it is checked inside
    # the write's unit of work, under the row lock, so a comparison made here
    # would be one the write could not honour.
    saved_journal = await journal_write_service.update_journal(
        JournalRequestConverter.from_update_request(
            journal_request.data, existing_journal
        ),
        connection,
        changed_by="ui",
        source=Provenance.UI,
        expected_etags=get_if_match(request),
    )
    set_etag(response, "journals", journal_id, saved_journal.updated_at)

    journal_resource = await _journal_resource_with_hierarchy(
        saved_journal, user.id, base_url, journal_service, enrichment_service
    )

    return JournalResponse(data=journal_resource)


@router.patch(
    "/{journal_id}",
    responses={
        412: {
            "model": PreconditionFailedErrorResponse,
            "description": (
                "The `If-Match` precondition named a version this journal has "
                "already moved on from — somebody else wrote to it since the "
                "caller read it. Nothing was written. The JSON:API error "
                "carries code `PRECONDITION_FAILED` and a `meta.current_etag` "
                "to retry with after re-reading and re-applying the change."
            ),
        },
    },
)
@inject
async def partial_update_journal(
    journal_id: int,
    request: Request,
    response: Response,
    journal_request: JournalUpdateRequest,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    journal_write_service: FromDishka[JournalWriteService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Partially update an existing journal.

    Updates only the provided fields and returns the updated resource.
    """
    base_url = get_request_base_url(request)

    existing_journal = await _require_owned_journal(
        journal_service, user.id, journal_id
    )

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

    # The precondition is handed to the service untouched: it is checked inside
    # the write's unit of work, under the row lock, so a comparison made here
    # would be one the write could not honour.
    saved_journal = await journal_write_service.update_journal(
        updated_journal,
        connection,
        changed_by="ui",
        source=Provenance.UI,
        expected_etags=get_if_match(request),
    )
    set_etag(response, "journals", journal_id, saved_journal.updated_at)

    journal_resource = await _journal_resource_with_hierarchy(
        saved_journal, user.id, base_url, journal_service, enrichment_service
    )

    return JournalResponse(data=journal_resource)


@router.delete(
    "/{journal_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        404: {"description": "No such journal, or it belongs to somebody else"},
        409: {
            "model": JournalHasAnchoredTasksErrorResponse,
            "description": (
                "A task is anchored to this journal as its creating or due "
                "journal. The JSON:API error carries code "
                "`JOURNAL_HAS_ANCHORED_TASKS`, an explanatory `detail`, and a "
                "`meta` object listing each blocking task — its id, text, "
                "status and blocking roles — with the id and title of the "
                "journal it can be actioned from."
            ),
        },
    },
)
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

    Refused with 409 when a task is anchored to this journal as its creating or
    due journal, whatever that task's status; cancel, complete or retarget those
    tasks first, or cancel the journal instead of deleting it. The refusal names
    each blocking task and the journal it can be actioned from, both in prose
    and as data under the error's ``meta``, so a client can render a working
    link without a further lookup.

    Somebody else's journal is reported as missing rather than forbidden, so the
    refusal cannot be used to discover that it exists — the stance the MCP read
    already takes, and the one the task domain's ports document.
    """
    await _require_owned_journal(journal_service, user.id, journal_id)

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
    enrichment_service: FromDishka[JournalEnrichmentService],
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

    # Both journals are read owner-scoped: a merge reads two journals by id and
    # writes one of them, so either being somebody else's is a refusal.
    #
    # This used to answer 403, which told the caller their id was real — the one
    # surface that distinguished "not yours" from "does not exist". It now
    # answers 404 like every other journal-by-id route (#1267).
    await _require_owned_journal(journal_service, user.id, journal_id)
    await _require_owned_journal(journal_service, user.id, source_id)

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
        fitness_merge_mode=merge_request.data.attributes.fitness_merge_mode,
        # A person merged these journals in the browser, so the tasks the merge
        # moves record it as theirs rather than as the system's.
        source=Provenance.UI,
        changed_by="ui",
    )

    # Get enriched target journal to return
    target_journal = await journal_service.get_journal(journal_id)
    if not target_journal:
        raise JournalNotFoundError(journal_id)

    enrichment = await enrichment_service.enrich(journal_id, user.id)

    # A merge keeps the survivor's own parent and adopts the source's children,
    # so the response has to describe that hierarchy — reporting neither reads
    # as though the merge orphaned the survivor.
    #
    # The children themselves are summarised by the detail route, which has the
    # per-type repositories needed to label them; listing them here without
    # their types would report every adopted child as typeless. This carries
    # the count instead, as the list route does.
    parent, _, children_count = await _fetch_parent_and_children(
        target_journal, user.id, journal_service
    )

    depth_map = await HierarchyService.compute_depth_map(
        [journal_id], journal_service.journal_repo
    )
    depth = depth_map.get(journal_id, 1)

    base_url = get_request_base_url(request)
    resource = JournalConverter.to_enriched_resource(
        target_journal,
        base_url,
        enrichment,
        parent=parent,
        children_count=children_count,
        depth=depth,
    )
    return JournalResponse(data=resource)


# Type Management Endpoints
@router.post("/{journal_id}/types")
@inject
async def add_type_to_journal(
    journal_id: int,
    request: Request,
    type_request: JournalTypeAddRequest,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    journal_write_service: FromDishka[JournalWriteService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Add a type to a journal with automatic dependency resolution.

    When a type is added, all its dependent types are automatically added as well.
    """
    base_url = get_request_base_url(request)

    # Verify the journal exists *and* is the caller's, before anything reads or
    # writes it. Somebody else's is reported as missing, never as forbidden.
    await _require_owned_journal(journal_service, user.id, journal_id)

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

    # GEAR_USAGE requires initial type data (gear_item_id) to be added successfully
    if (
        journal_type == JournalType.GEAR_USAGE
        and not type_request.data.attributes.type_data
    ):
        from core_shared.models.journals.exceptions import JournalValidationError

        raise JournalValidationError(
            "type_data",
            "GEAR_USAGE type requires initial type data (gear_item_id) to be created.",
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

    return await _enriched_journal_response(
        journal_id, user.id, base_url, journal_service, enrichment_service
    )


@router.delete("/{journal_id}/types/{journal_type}")
@inject
async def remove_type_from_journal(
    journal_id: int,
    journal_type: str,
    request: Request,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    journal_write_service: FromDishka[JournalWriteService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Remove a type from a journal.

    Validates that removing the type won't break dependencies.
    """
    base_url = get_request_base_url(request)

    # Verify the journal exists *and* is the caller's, before anything reads or
    # writes it. Somebody else's is reported as missing, never as forbidden.
    await _require_owned_journal(journal_service, user.id, journal_id)

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

    return await _enriched_journal_response(
        journal_id, user.id, base_url, journal_service, enrichment_service
    )


@router.put("/{journal_id}/types/{journal_type}/data")
@inject
async def update_type_data(
    journal_id: int,
    journal_type: str,
    request: Request,
    type_data_request: JournalTypeDataUpdateRequest,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    journal_write_service: FromDishka[JournalWriteService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Update type-specific data for a journal.

    The journal must already have the specified type.
    """
    base_url = get_request_base_url(request)

    # Verify the journal exists *and* is the caller's, before anything reads or
    # writes it. Somebody else's is reported as missing, never as forbidden.
    await _require_owned_journal(journal_service, user.id, journal_id)

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

    return await _enriched_journal_response(
        journal_id, user.id, base_url, journal_service, enrichment_service
    )


# Relationship Management Endpoints
@router.post("/{journal_id}/relationships/contacts")
@inject
async def add_contact_to_journal(
    journal_id: int,
    request: Request,
    contact_request: JournalContactAddRequest,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    connection: FromDishka[AsyncConnection],
    journal_contact_service: FromDishka[JournalContactService],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Add a contact relationship to a journal.
    """
    base_url = get_request_base_url(request)

    # Verify the journal exists *and* is the caller's, before anything reads or
    # writes it. Somebody else's is reported as missing, never as forbidden.
    await _require_owned_journal(journal_service, user.id, journal_id)

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

    return await _enriched_journal_response(
        journal_id, user.id, base_url, journal_service, enrichment_service
    )


@router.patch("/{journal_id}/relationships/contacts/{contact_id}/{relationship_type}")
@inject
async def update_journal_contact_relationship(
    journal_id: int,
    contact_id: int,
    relationship_type: str,
    request: Request,
    update_request: JournalContactRelationshipUpdateRequest,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
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

    # Verify the journal exists *and* is the caller's, before anything reads or
    # writes it. Somebody else's is reported as missing, never as forbidden.
    await _require_owned_journal(journal_service, user.id, journal_id)

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

    return await _enriched_journal_response(
        journal_id, user.id, base_url, journal_service, enrichment_service
    )


@router.delete("/{journal_id}/relationships/contacts/{contact_id}/{relationship_type}")
@inject
async def remove_contact_from_journal(
    journal_id: int,
    contact_id: int,
    relationship_type: str,
    request: Request,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
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

    # Verify the journal exists *and* is the caller's, before anything reads or
    # writes it. Somebody else's is reported as missing, never as forbidden.
    await _require_owned_journal(journal_service, user.id, journal_id)

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

    return await _enriched_journal_response(
        journal_id, user.id, base_url, journal_service, enrichment_service
    )


@router.post("/{journal_id}/relationships/tags")
@inject
async def add_tag_to_journal(
    journal_id: int,
    request: Request,
    tag_request: JournalTagAddRequest,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    journal_tag_service: FromDishka[JournalTagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> JournalResponse:
    """
    Add one of the session user's tags to one of their journals.

    Another user's journal or tag answers 404, exactly as a missing one does.
    """
    from uuid import UUID

    from core_shared.models.journals import JournalValidationError

    base_url = get_request_base_url(request)

    # Verify the journal exists *and* is the caller's, before anything reads or
    # writes it. Somebody else's is reported as missing, never as forbidden.
    await _require_owned_journal(journal_service, user.id, journal_id)

    # Parse tag_id
    try:
        tag_uuid = UUID(tag_request.data.attributes.tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", INVALID_UUID_FORMAT_MSG) from e

    # Assign tag to journal as a committed unit of work. The service raises
    # JournalTagNotFoundError (404) unless the tag is the user's, and publishes the
    # JournalTagAssigned history event with this provenance in the same transaction.
    await journal_tag_service.assign_tag(
        journal_id,
        tag_uuid,
        connection,
        user_id=user.id,
        changed_by="ui",
        source=Provenance.UI,
    )

    return await _enriched_journal_response(
        journal_id, user.id, base_url, journal_service, enrichment_service
    )


@router.delete("/{journal_id}/relationships/tags/{tag_id}")
@inject
async def remove_tag_from_journal(
    journal_id: int,
    tag_id: str,
    request: Request,
    journal_service: FromDishka[JournalService],
    enrichment_service: FromDishka[JournalEnrichmentService],
    journal_tag_service: FromDishka[JournalTagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> JournalResponse:
    """
    Remove a tag from a journal.
    """
    from uuid import UUID

    from core_shared.models.journals import JournalValidationError

    base_url = get_request_base_url(request)

    # Verify the journal exists *and* is the caller's, before anything reads or
    # writes it. Somebody else's is reported as missing, never as forbidden.
    await _require_owned_journal(journal_service, user.id, journal_id)

    # Parse tag_id
    try:
        tag_uuid = UUID(tag_id)
    except ValueError as e:
        raise JournalValidationError("tag_id", INVALID_UUID_FORMAT_MSG) from e

    # Remove tag from journal as a committed unit of work; the service publishes the
    # JournalTagRemoved history event with this provenance in the same transaction.
    await journal_tag_service.remove_tag(
        journal_id,
        tag_uuid,
        connection,
        user_id=user.id,
        changed_by="ui",
        source=Provenance.UI,
    )

    return await _enriched_journal_response(
        journal_id, user.id, base_url, journal_service, enrichment_service
    )
