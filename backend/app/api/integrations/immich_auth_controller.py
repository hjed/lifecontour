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
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.integrations.controllers import _build_sync_job_data
from app.api.integrations.schemas import (
    ConflictResolutionAction,
    ConflictResolutionRequest,
    ImmichConflictAttributes,
    ImmichConflictData,
    ImmichConflictListResponse,
    ImmichConflictResponse,
    SyncJobJsonApiResponse,
    SyncJobRequest,
    SyncType,
)
from app.core.contacts.services.contact_service import ContactService
from app.core.integrations.adapters.sql.immich_auth_repository import (
    SqlImmichAuthRepository,
)
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.immich_token_service import (
    ImmichTokenService,
    ImmichTokenStorageError,
    ImmichValidationException,
)
from app.infrastructure.auth.models import SessionUser

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
) -> ImmichConflictListResponse:
    """Get a list of unresolved Immich synchronization conflicts."""
    repo = PendingEntityMappingRepository(connection)
    conflicts = await repo.find_unresolved(
        user_id=str(user.id), integration_source="immich"
    )

    data = []
    for c in conflicts:
        data.append(
            ImmichConflictData(
                id=str(c["id"]),
                attributes=ImmichConflictAttributes(
                    external_entity_id=c["external_entity_id"],
                    external_entity_name=c["external_entity_name"],
                    candidate_contact_ids=c["candidate_contact_ids"],
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
    from app.core.integrations.external_reference_service import (
        ExternalReferenceService,
    )

    repo = PendingEntityMappingRepository(connection)
    ext_ref_service = ExternalReferenceService(connection)

    # NOTE: commit-as-you-go (issue #945) — create_contact commits its own
    # unit of work; the conflict-resolution writes below are committed by the
    # CommitOnResponseMiddleware backstop before the response is sent.
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
        if not await ext_ref_service.contact_exists(contact_id):
            raise HTTPException(
                status_code=404,
                detail=f"Contact {contact_id} not found",
            )

    # Resolve the conflict in pending_entity_mappings
    updated_conflict = await repo.resolve(
        conflict_id=conflict_id, resolved_contact_id=contact_id
    )

    if not updated_conflict:
        raise HTTPException(status_code=404, detail=f"Conflict {conflict_id} not found")

    # Upsert external reference (find-or-create/update)
    await ext_ref_service.upsert_contact_reference(
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
