"""
Immich Integration Controller.

Endpoints for connecting, disconnecting, and syncing the Immich integration.
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.integrations.controllers import _build_sync_job_data
from app.api.integrations.schemas import (
    SyncJobJsonApiResponse,
    SyncJobRequest,
    SyncType,
)
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
    "/album/sync",
    summary="Trigger Immich album sync",
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
    Trigger an Immich sync job.

    Enqueues a background sync job that syncs people and albums from Immich.
    The sync type may be ``full`` (all data) or ``smart`` (only changes
    since last sync).

    Note: All capability routes (``/contacts/sync``, ``/album/sync``,
    ``/sync``) currently enqueue the same ``sync_immich_people`` task.
    Capability-specific task routing will be added in ITER11-002+.
    """
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
