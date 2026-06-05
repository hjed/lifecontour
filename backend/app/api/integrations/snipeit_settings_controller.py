"""
Snipe-IT settings API controller.

Provides REST API endpoints for managing per-user Snipe-IT integration
configuration (Base URL and user mapping).
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException

from app.api.integrations.schemas import (
    SyncJobAttributes,
    SyncJobData,
    SyncJobJsonApiResponse,
    SyncJobRequest,
    SyncType,
)
from app.api.integrations.snipeit_settings_schemas import (
    SnipeItSettingsAttributes,
    SnipeItSettingsData,
    SnipeItSettingsRequest,
    SnipeItSettingsResponse,
)
from app.core.integrations.adapters.sql.snipeit_settings_repository import (
    SqlSnipeItSettingsRepository,
)
from app.core.integrations.models.snipeit import SnipeItSettings
from app.core.integrations.task_queue_service import TaskQueueService
from app.infrastructure.auth.models import SessionUser
from app.infrastructure.config import Settings

router = APIRouter(
    prefix="/integrations/snipeit",
    tags=["integrations-snipeit"],
)
logger = structlog.get_logger()


@router.get(
    "/settings",
    responses={
        404: {"description": "No Snipe-IT settings found for this user"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def get_snipeit_settings(
    user: FromDishka[SessionUser],
    repository: FromDishka[SqlSnipeItSettingsRepository],
) -> SnipeItSettingsResponse:
    """
    Get the current Snipe-IT settings for the authenticated user.

    Returns the configured Base URL and optional user mapping.
    """
    try:
        settings = await repository.get_by_user_id(str(user.id))

        if not settings:
            raise HTTPException(
                status_code=404,
                detail="No Snipe-IT settings found for this user",
            )

        return SnipeItSettingsResponse(
            data=SnipeItSettingsData(
                id=str(user.id),
                attributes=SnipeItSettingsAttributes(
                    base_url=settings.base_url,
                    snipeit_user_id=settings.snipeit_user_id,
                ),
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get Snipe-IT settings",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while retrieving Snipe-IT settings",
        ) from e


@router.put(
    "/settings",
    responses={
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def save_snipeit_settings(
    request_data: SnipeItSettingsRequest,
    user: FromDishka[SessionUser],
    repository: FromDishka[SqlSnipeItSettingsRepository],
) -> SnipeItSettingsResponse:
    """
    Create or update Snipe-IT settings for the authenticated user.

    Upserts the Base URL and optional user mapping. The Base URL is used
    by the OAuth flow (Phase 2) and by the worker for API calls.
    """
    try:
        settings = SnipeItSettings(
            user_id=str(user.id),
            base_url=str(request_data.base_url),
            snipeit_user_id=request_data.snipeit_user_id,
        )
        saved_settings = await repository.save(settings)

        logger.info(
            "Snipe-IT settings saved",
            user_id=user.id,
            base_url=saved_settings.base_url,
        )

        return SnipeItSettingsResponse(
            data=SnipeItSettingsData(
                id=str(user.id),
                attributes=SnipeItSettingsAttributes(
                    base_url=saved_settings.base_url,
                    snipeit_user_id=saved_settings.snipeit_user_id,
                ),
            )
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to save Snipe-IT settings",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while saving Snipe-IT settings",
        ) from e


@router.get(
    "/webhook-url",
    responses={
        200: {"description": "Webhook URL returned"},
        400: {"description": "Webhook base URL not configured"},
    },
)
@inject
async def get_snipeit_webhook_url(
    user: FromDishka[SessionUser],  # noqa: ARG001
    settings: FromDishka[Settings],
) -> dict[str, object]:
    """Get the webhook URL to configure in Snipe-IT.

    Snipe-IT uses an inbound-only webhook model — the webhook URL must be
    manually configured in the Snipe-IT admin UI. This endpoint returns
    the URL so the user can copy it.
    """
    from app.api.integrations.schemas import (
        WebhookUrlAttributes,
        WebhookUrlData,
        WebhookUrlResponse,
    )

    if not settings.webhook_base_url:
        raise HTTPException(
            status_code=400,
            detail="Webhook base URL is not configured on the server",
        )

    webhook_url = (
        f"{settings.webhook_base_url.rstrip('/')}/api/integrations/snipeit/webhook"
    )

    return WebhookUrlResponse(
        data=WebhookUrlData(
            id="snipeit-webhook-url",
            attributes=WebhookUrlAttributes(
                webhook_url=webhook_url,
                message=(
                    "Configure this URL in your Snipe-IT instance under "
                    "Admin > Settings > Webhooks."
                ),
            ),
        )
    ).model_dump()


@router.post(
    "/gear/sync",
    responses={
        400: {"description": "Invalid sync parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def trigger_snipeit_gear_sync(
    request: SyncJobRequest,
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """Trigger a manual Snipe-IT gear/asset sync."""
    try:
        sync_type = request.sync_type.value
        if request.force_full_sync:
            sync_type = SyncType.FULL.value

        job_id = await task_queue_service.enqueue_snipeit_sync(
            user_id=user.id,
            sync_type=sync_type,
        )

        job = await task_queue_service.get_sync_job_details(
            job_id=job_id, user_id=user.id
        )
        from app.api.integrations.controllers import _build_sync_job_data

        return SyncJobJsonApiResponse(data=_build_sync_job_data(job))

    except ValueError as e:
        logger.error("Invalid sync parameters", error=str(e), exc_info=True)
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
            "Failed to enqueue Snipe-IT gear sync job", error=str(e), exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while queueing the sync job",
        ) from e


@router.post(
    "/maintenance/sync",
    responses={
        400: {"description": "Invalid sync parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def trigger_snipeit_maintenance_sync(
    request: SyncJobRequest,
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],
) -> SyncJobJsonApiResponse:
    """Trigger a manual Snipe-IT maintenance sync."""
    try:
        sync_type = request.sync_type.value
        if request.force_full_sync:
            sync_type = SyncType.FULL.value

        job_id = await task_queue_service.enqueue_snipeit_maintenance_sync(
            user_id=user.id,
            sync_type=sync_type,
        )

        job = await task_queue_service.get_sync_job_details(
            job_id=job_id, user_id=user.id
        )
        from app.api.integrations.controllers import _build_sync_job_data

        return SyncJobJsonApiResponse(data=_build_sync_job_data(job))

    except ValueError as e:
        logger.error("Invalid sync parameters", error=str(e), exc_info=True)
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
            "Failed to enqueue Snipe-IT maintenance sync job",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while queueing the sync job",
        ) from e


@router.post(
    "/checkout/sync",
    responses={
        400: {"description": "Invalid sync parameters"},
        503: {"description": "Task queue service unavailable"},
        500: {"description": "An unexpected error occurred"},
    },
)
@inject
async def trigger_snipeit_checkout_sync(
    request: SyncJobRequest,
    user: FromDishka[SessionUser],
    task_queue_service: FromDishka[TaskQueueService],  # noqa: ARG001
) -> SyncJobJsonApiResponse:
    """Trigger a manual Snipe-IT checkout sync. Currently a no-op as checkouts are event-driven."""
    from datetime import UTC, datetime

    try:
        sync_type = request.sync_type.value
        if request.force_full_sync:
            sync_type = SyncType.FULL.value

        now = datetime.now(UTC).isoformat()
        return SyncJobJsonApiResponse(
            data=SyncJobData(
                id="dummy_checkout_sync",
                attributes=SyncJobAttributes(
                    status="completed",
                    sync_type=sync_type,
                    created_at=now,
                    started_at=now,
                    completed_at=now,
                    error_message=None,
                    contacts_processed=0,
                    contacts_created=0,
                    contacts_updated=0,
                    contacts_deleted=0,
                    progress=None,
                ),
            )
        )
    except ValueError as e:
        logger.error("Invalid sync parameters", error=str(e), exc_info=True)
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
            "Failed to handle Snipe-IT checkout sync request",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while processing the checkout sync request",
        ) from e
