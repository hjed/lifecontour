"""
Snipe-IT API key authentication controller.

Provides REST API endpoints for Snipe-IT API key connection
and disconnection. Users generate a personal access token in
their Snipe-IT admin panel and provide it here for encrypted
storage.
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.auth.snipeit_token_service import SnipeItTokenService
from app.infrastructure.config import Settings

logger = structlog.get_logger()

router = APIRouter(prefix="/integrations/snipeit", tags=["integrations-snipeit"])


# ---------- Request / Response Schemas ----------


class SnipeItConnectRequest(BaseModel):
    """Request body for connecting Snipe-IT with an API key."""

    api_key: str


class SnipeItConnectResponse(BaseModel):
    """Response after successful Snipe-IT connection."""

    success: bool
    message: str


class SnipeItDisconnectResponse(BaseModel):
    """Response after Snipe-IT disconnection."""

    success: bool
    message: str


# ---------- Endpoints ----------


@router.post(
    "/connect",
    responses={
        400: {"description": "Missing API key"},
        500: {"description": "Failed to connect Snipe-IT"},
    },
)
@inject
async def snipeit_connect(
    request_data: SnipeItConnectRequest,
    user: FromDishka[SessionUser],
    snipeit_token_service: FromDishka[SnipeItTokenService],
    settings: FromDishka[Settings],
    task_queue_service: FromDishka[TaskQueueService],
) -> SnipeItConnectResponse:
    """
    Connect Snipe-IT integration using a personal access token (API key).

    Encrypts and stores the API key, then triggers an initial full sync.
    """
    try:
        if not settings.snipeit_encryption_key:
            raise HTTPException(
                status_code=500,
                detail="Snipe-IT integration is not configured on the server",
            )

        if not request_data.api_key.strip():
            raise HTTPException(
                status_code=400,
                detail="API key is required",
            )

        # Store encrypted API key. The service commits before this handler
        # returns, so the worker can read the key.
        await snipeit_token_service.store_api_key(
            user_id=str(user.id),
            api_key=request_data.api_key.strip(),
        )

        # Trigger initial full sync of assets
        try:
            await task_queue_service.enqueue_snipeit_sync(
                user_id=user.id,
                sync_type="full",
            )
            logger.info("Triggered initial Snipe-IT full sync", user_id=user.id)
        except Exception as sync_err:  # noqa: BLE001
            logger.warning(
                "Failed to enqueue Snipe-IT initial sync during connect",
                user_id=user.id,
                error=str(sync_err),
            )

        logger.info(
            "Snipe-IT API key connected successfully",
            user_id=user.id,
        )

        return SnipeItConnectResponse(
            success=True,
            message="Snipe-IT connected successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to connect Snipe-IT",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to connect Snipe-IT integration",
        ) from e


@router.delete(
    "/connect",
    responses={
        500: {"description": "Failed to disconnect Snipe-IT"},
    },
)
@inject
async def snipeit_disconnect(
    user: FromDishka[SessionUser],
    snipeit_token_service: FromDishka[SnipeItTokenService],
) -> SnipeItDisconnectResponse:
    """
    Disconnect Snipe-IT integration for the authenticated user.

    Removes the stored API key. Imported data remains.
    """
    try:
        deleted = await snipeit_token_service.delete_tokens(str(user.id))

        if deleted:
            logger.info(
                "Snipe-IT disconnected successfully",
                user_id=user.id,
            )
            return SnipeItDisconnectResponse(
                success=True,
                message="Snipe-IT disconnected successfully",
            )
        else:
            logger.info(
                "No Snipe-IT connection found to disconnect",
                user_id=user.id,
            )
            return SnipeItDisconnectResponse(
                success=True,
                message="No Snipe-IT connection found",
            )

    except Exception as e:
        logger.error(
            "Failed to disconnect Snipe-IT",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to disconnect Snipe-IT integration",
        ) from e
