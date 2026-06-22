"""
Immich Integration Controller.

Endpoints for connecting, disconnecting, and syncing the Immich integration.
"""

import structlog
from core_shared.models.contacts.entities import Contact
from core_shared.models.contacts.value_objects import Provenance
from core_shared.repositories.pending_entity_mapping_repository import (
    PendingEntityMappingRepository,
)
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.integrations.controllers import _build_sync_job_data
from app.api.integrations.schemas import (
    ConflictResolutionAction,
    ConflictResolutionRequest,
    ImmichConflictAttributes,
    ImmichConflictCandidate,
    ImmichConflictData,
    ImmichConflictListResponse,
    ImmichConflictResponse,
    ImmichCreateAlbumRequest,
    ImmichCreateAlbumResponse,
    ImmichCreatedAlbumAttributes,
    ImmichCreatedAlbumData,
    ImmichPhotoAttributes,
    ImmichPhotoData,
    ImmichPhotoListMeta,
    ImmichSearchPhotosRequest,
    ImmichSearchPhotosResponse,
    SyncJobJsonApiResponse,
    SyncJobRequest,
    SyncType,
)
from app.core.contacts.models.repositories import ContactRepository
from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.adapters.sql.immich_auth_repository import (
    SqlImmichAuthRepository,
)
from app.core.integrations.immich.adapters.album_api_client import ImmichAlbumApiError
from app.core.integrations.immich.album_creation_service import (
    AlbumAlreadyLinkedError,
    EmptyAlbumSelectionError,
    ImmichAlbumCreationService,
    ImmichNotConnectedError,
    JournalNotFoundError,
)
from app.core.integrations.immich.asset_thumbnail_proxy_service import (
    AssetThumbnailNotFoundError,
    AssetThumbnailProxyService,
)
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.immich_token_service import (
    ImmichTokenService,
    ImmichTokenStorageError,
    ImmichValidationException,
)
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.unit_of_work import unit_of_work

logger = structlog.get_logger()

router = APIRouter(prefix="/immich", tags=["Integrations"])


class ImmichConnectRequest(BaseModel):
    """Request payload for connecting to Immich."""

    server_url: HttpUrl
    api_key: str


@router.post("/connect", summary="Connect Immich")
@inject
async def connect_immich(
    request: ImmichConnectRequest,
    user: FromDishka[SessionUser],
    token_service: FromDishka[ImmichTokenService],
) -> dict[str, str]:
    """Validate and store Immich credentials."""
    try:
        await token_service.validate_and_save_credentials(
            user_id=user.id,
            server_url=str(request.server_url).strip(),
            api_key=request.api_key.strip(),
        )
        return {"status": "success", "message": "Immich connected successfully."}
    except ImmichValidationException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ImmichTokenStorageError as e:
        raise HTTPException(
            status_code=500, detail="Immich integration is misconfigured on the server."
        ) from e


@router.post("/disconnect", summary="Disconnect Immich", status_code=204)
@inject
async def disconnect_immich(
    user: FromDishka[SessionUser],
    token_service: FromDishka[ImmichTokenService],
) -> None:
    """Disconnect Immich and remove credentials."""
    await token_service.disconnect(user.id)


# ---------- Sync Trigger Endpoint ----------


@router.post(
    "/contacts/sync",
    summary="Trigger Immich contacts (people) sync",
    responses={
        400: {"description": "Immich not connected or invalid parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@router.post(
    "/sync",
    summary="Trigger Immich sync",
    responses={
        400: {"description": "Immich not connected or invalid parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def trigger_immich_sync(
    request: SyncJobRequest,
    user: FromDishka[SessionUser],
    connection: FromDishka[AsyncConnection],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """
    Trigger an Immich people sync job.

    Enqueues a background sync job that syncs people from Immich. The sync
    type may be ``full`` (all data) or ``smart`` (only changes since last
    sync). Use ``/album/sync`` to trigger album import.
    """
    return await _enqueue_immich_sync(
        request,
        user,
        connection,
        task_queue_service,
        task_name="sync_immich_people",
        integration_source="immich",
    )


@router.post(
    "/album/sync",
    summary="Trigger Immich album sync",
    responses={
        400: {"description": "Immich not connected or invalid parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def trigger_immich_album_sync(
    request: SyncJobRequest,
    user: FromDishka[SessionUser],
    connection: FromDishka[AsyncConnection],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """
    Trigger an Immich album sync job.

    Enqueues a background job that imports Immich albums as PHOTO_ALBUM
    journals (ITER11-004).
    """
    return await _enqueue_immich_sync(
        request,
        user,
        connection,
        task_queue_service,
        task_name="sync_immich_albums",
        integration_source="immich_album",
    )


async def _enqueue_immich_sync(
    request: SyncJobRequest,
    user: SessionUser,
    connection: AsyncConnection,
    task_queue_service: TaskQueueService,
    *,
    task_name: str,
    integration_source: str,
) -> SyncJobJsonApiResponse:
    """Shared logic for the Immich people and album sync trigger endpoints."""
    try:
        # Verify Immich is connected via repository
        repo = SqlImmichAuthRepository(connection)
        is_connected = await repo.is_connected(str(user.id))
        if not is_connected:
            raise HTTPException(
                status_code=400,
                detail="Immich is not connected. Please connect Immich first.",
            )

        # Determine sync type
        sync_type = request.sync_type.value
        if request.force_full_sync:
            sync_type = SyncType.FULL.value

        # Enqueue the sync job
        job_id = await task_queue_service.enqueue_immich_sync(
            user_id=user.id,
            sync_type=sync_type,
            task_name=task_name,
            integration_source=integration_source,
        )

        job = await task_queue_service.get_sync_job_details(
            job_id=job_id, user_id=user.id
        )

        return SyncJobJsonApiResponse(data=_build_sync_job_data(job))

    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Invalid Immich sync parameters", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sync parameters: {str(e)}",
        ) from e
    except ConnectionError as e:
        logger.error("Task queue connection failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Task queue service is temporarily unavailable",
        ) from e
    except Exception as e:
        logger.error(
            "Failed to enqueue Immich sync job",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while queueing the sync job",
        ) from e


# ---------- Conflict Resolution Endpoints ----------


@router.get(
    "/conflicts",
    summary="List Immich synchronization conflicts",
    response_model=ImmichConflictListResponse,
)
@inject
async def list_immich_conflicts(
    user: FromDishka[SessionUser],
    connection: FromDishka[AsyncConnection],
    contact_repo: FromDishka[ContactRepository],
) -> ImmichConflictListResponse:
    """Get a list of unresolved Immich synchronization conflicts."""
    repo = PendingEntityMappingRepository(connection)
    conflicts = await repo.find_unresolved(
        user_id=str(user.id), integration_source="immich"
    )

    # Batch-fetch display names for every candidate across all conflicts so the
    # UI can show real contact names instead of raw IDs (single query).
    all_candidate_ids = {
        cid for c in conflicts for cid in (c["candidate_contact_ids"] or [])
    }
    name_rows = await contact_repo.find_names_by_ids(list(all_candidate_ids))

    def _candidate(contact_id: int) -> ImmichConflictCandidate:
        first_name, last_name, photo_url = name_rows.get(contact_id, (None, None, None))
        name = " ".join(part for part in (first_name, last_name) if part)
        return ImmichConflictCandidate(
            id=contact_id,
            name=name if name else f"Contact {contact_id}",
            photo_url=photo_url,
        )

    data = []
    for c in conflicts:
        candidate_ids = c["candidate_contact_ids"] or []
        data.append(
            ImmichConflictData(
                id=str(c["id"]),
                attributes=ImmichConflictAttributes(
                    external_entity_id=c["external_entity_id"],
                    external_entity_name=c["external_entity_name"],
                    candidate_contact_ids=candidate_ids,
                    candidate_contacts=[_candidate(cid) for cid in candidate_ids],
                    status=c["status"],
                    created_at=c["created_at"].isoformat() if c["created_at"] else "",
                ),
            )
        )

    return ImmichConflictListResponse(data=data)


@router.post(
    "/conflicts/{conflict_id}/resolve",
    summary="Resolve an Immich synchronization conflict",
    response_model=ImmichConflictResponse,
)
@inject
async def resolve_immich_conflict(
    conflict_id: int,
    request: ConflictResolutionRequest,
    user: FromDishka[SessionUser],
    connection: FromDishka[AsyncConnection],
    contact_service: FromDishka[ContactService],
) -> ImmichConflictResponse:
    """Resolve a conflict by linking to an existing contact or creating a new one."""
    from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
    from app.core.integrations.adapters.sql.sync_metadata_repository import (
        SyncMetadataRepository,
    )

    repo = PendingEntityMappingRepository(connection)
    contact_repo = SqlContactRepository(connection)
    sync_metadata_repo = SyncMetadataRepository(connection)

    # Atomic unit of work (issue #945): create_contact joins re-entrantly,
    # and the conflict-resolution writes commit together before the response.
    async with unit_of_work(connection):
        # Verify the conflict belongs to this user, is for immich, and is unresolved
        conflict_row = await repo.get_unresolved_by_id(
            conflict_id=conflict_id,
            user_id=str(user.id),
            integration_source="immich",
        )

        if not conflict_row:
            raise HTTPException(
                status_code=404, detail="Conflict not found or already resolved"
            )

        external_id = conflict_row["external_entity_id"]
        external_name = conflict_row["external_entity_name"]

        contact_id = request.contact_id

        if request.action == ConflictResolutionAction.CREATE:
            # Create a new contact
            # Strip whitespace and handle edge cases
            name = (external_name or "").strip()
            parts = name.split(" ", 1) if name else []
            first_name = parts[0] if parts else "Unnamed"
            last_name = parts[1].strip() if len(parts) > 1 else ""

            new_contact = Contact(
                first_name=first_name,
                last_name=last_name,
            )
            saved_contact = await contact_service.create_contact(
                contact=new_contact,
                transaction=connection,
                changed_by=str(user.id),
                source=Provenance.UI,
            )
            contact_id = saved_contact.id

        if contact_id is None:
            raise HTTPException(
                status_code=400, detail="contact_id is required when action is 'link'"
            )

        # Validate the contact exists before linking
        if request.action == ConflictResolutionAction.LINK:
            if not await contact_repo.contact_exists(contact_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Contact {contact_id} not found",
                )

        # Resolve the conflict in pending_entity_mappings
        updated_conflict = await repo.resolve(
            conflict_id=conflict_id, resolved_contact_id=contact_id
        )

        if not updated_conflict:
            raise HTTPException(
                status_code=404, detail=f"Conflict {conflict_id} not found"
            )

        # Upsert the canonical integration link (find-or-create/update)
        await sync_metadata_repo.upsert_contact_link(
            contact_id=contact_id,
            external_system="immich",
            external_entity_type="person",
            external_entity_id=external_id,
        )

        data = ImmichConflictData(
            id=str(updated_conflict["id"]),
            attributes=ImmichConflictAttributes(
                external_entity_id=updated_conflict["external_entity_id"],
                external_entity_name=updated_conflict["external_entity_name"],
                candidate_contact_ids=updated_conflict["candidate_contact_ids"],
                status=updated_conflict["status"],
                created_at=updated_conflict["created_at"].isoformat()
                if updated_conflict["created_at"]
                else "",
            ),
        )

        return ImmichConflictResponse(data=data)


# ---------- Album Creation Endpoints (ITER11-006) ----------


@router.post(
    "/search-photos",
    summary="Search Immich photos for a journal's date range",
    response_model=ImmichSearchPhotosResponse,
    responses={
        400: {"description": "Immich not connected"},
        404: {"description": "Journal not found"},
        502: {"description": "Immich API error"},
    },
)
@inject
async def search_immich_photos(
    request: ImmichSearchPhotosRequest,
    user: FromDishka[SessionUser],
    service: FromDishka[ImmichAlbumCreationService],
) -> ImmichSearchPhotosResponse:
    """Return Immich photos taken within a journal's (timezone-expanded) range.

    Used by the album-creation UI to populate the photo-selection dialog. Photo
    thumbnails are exposed as backend proxy URLs so the browser never sees the
    Immich server URL or API key.
    """
    try:
        photos = await service.search_photos(request.journal_id, user.id)
    except JournalNotFoundError as e:
        raise HTTPException(status_code=404, detail="Journal not found") from e
    except ImmichNotConnectedError as e:
        raise HTTPException(status_code=400, detail="Immich is not connected.") from e
    except ImmichAlbumApiError as e:
        raise HTTPException(
            status_code=502, detail="Failed to search Immich photos."
        ) from e

    return ImmichSearchPhotosResponse(
        data=[
            ImmichPhotoData(
                id=photo.asset_id,
                attributes=ImmichPhotoAttributes(
                    thumbnail_url=photo.thumbnail_url,
                    original_file_name=photo.original_file_name,
                    taken_at=photo.taken_at,
                ),
            )
            for photo in photos
        ],
        meta=ImmichPhotoListMeta(count=len(photos)),
    )


@router.post(
    "/create-album",
    summary="Create an Immich album from a journal's selected photos",
    response_model=ImmichCreateAlbumResponse,
    responses={
        400: {"description": "Immich not connected"},
        404: {"description": "Journal not found"},
        409: {"description": "Journal already has a linked album"},
        502: {"description": "Immich API error"},
    },
)
@inject
async def create_immich_album(
    request: ImmichCreateAlbumRequest,
    user: FromDishka[SessionUser],
    service: FromDishka[ImmichAlbumCreationService],
) -> ImmichCreateAlbumResponse:
    """Create an Immich album from the selected photos and link it to the journal.

    Optionally creates a public shared link. Writes the SyncMetadata +
    ExternalReference records that link the journal to the album (which also
    marks the journal as a PHOTO_ALBUM).
    """
    try:
        result = await service.create_album(
            request.journal_id,
            user.id,
            asset_ids=request.asset_ids,
            create_shared_link=request.create_shared_link,
        )
    except JournalNotFoundError as e:
        raise HTTPException(status_code=404, detail="Journal not found") from e
    except EmptyAlbumSelectionError as e:
        raise HTTPException(
            status_code=400, detail="At least one photo must be selected."
        ) from e
    except AlbumAlreadyLinkedError as e:
        raise HTTPException(
            status_code=409, detail="Journal already has a linked Immich album."
        ) from e
    except ImmichNotConnectedError as e:
        raise HTTPException(status_code=400, detail="Immich is not connected.") from e
    except ImmichAlbumApiError as e:
        raise HTTPException(
            status_code=502, detail="Failed to create Immich album."
        ) from e

    return ImmichCreateAlbumResponse(
        data=ImmichCreatedAlbumData(
            id=result.album_id,
            attributes=ImmichCreatedAlbumAttributes(
                journal_id=result.journal_id,
                asset_count=result.asset_count,
                shared_link_url=result.shared_link_url,
            ),
        )
    )


@router.get("/assets/{asset_id}/thumbnail", summary="Proxy an Immich asset thumbnail")
@inject
async def get_immich_asset_thumbnail(
    asset_id: str,
    user: FromDishka[SessionUser],
    proxy: FromDishka[AssetThumbnailProxyService],
) -> Response:
    """Proxy an Immich asset thumbnail using the user's stored credentials.

    Backs the thumbnails returned by ``/search-photos`` so the browser never
    sees the Immich server URL or API key. Returns 404 if Immich is not
    configured or the thumbnail cannot be fetched.
    """
    try:
        image_bytes, content_type = await proxy.get_thumbnail_bytes(
            asset_id=asset_id, user_id=user.id
        )
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "private, max-age=3600"},
        )
    except AssetThumbnailNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not available",
        ) from None
