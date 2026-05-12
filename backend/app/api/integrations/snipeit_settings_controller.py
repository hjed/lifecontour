"""
Snipe-IT settings API controller.

Provides REST API endpoints for managing per-user Snipe-IT integration
configuration (Base URL and user mapping).
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException

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
from app.infrastructure.auth.models import SessionUser

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
