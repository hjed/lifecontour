"""User settings API controller.

Provides REST endpoints for managing per-user preferences. Currently exposes
the default timezone, which is synced from the frontend and used by the
backend (including AI prompt generation) to render dates/times in the user's
local time.
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException

from app.api.settings.schemas import (
    UserSettingsAttributes,
    UserSettingsData,
    UserSettingsRequest,
    UserSettingsResponse,
)
from app.core.settings.models import UserSettings, UserSettingsRepository
from app.core.settings.timezone_utils import DEFAULT_TIMEZONE
from app.infrastructure.auth.models import SessionUser

router = APIRouter(prefix="/user-settings", tags=["settings"])
logger = structlog.get_logger()


@router.get("")
@inject
async def get_user_settings(
    user: FromDishka[SessionUser],
    repository: FromDishka[UserSettingsRepository],
) -> UserSettingsResponse:
    """Get the authenticated user's settings.

    Returns the stored timezone, or the default (UTC) when none is set yet,
    so the settings UI always has a value to display.
    """
    try:
        settings = await repository.get_by_user_id(str(user.id))
        timezone = settings.timezone if settings else DEFAULT_TIMEZONE

        return UserSettingsResponse(
            data=UserSettingsData(
                id=str(user.id),
                attributes=UserSettingsAttributes(timezone=timezone),
            )
        )
    except Exception as e:
        logger.error(
            "Failed to get user settings",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while retrieving user settings",
        ) from e


@router.put("")
@inject
async def save_user_settings(
    request_data: UserSettingsRequest,
    user: FromDishka[SessionUser],
    repository: FromDishka[UserSettingsRepository],
) -> UserSettingsResponse:
    """Create or update the authenticated user's settings (upsert)."""
    try:
        saved = await repository.save(
            UserSettings(user_id=str(user.id), timezone=request_data.timezone)
        )

        logger.info(
            "User settings saved",
            user_id=user.id,
            timezone=saved.timezone,
        )

        return UserSettingsResponse(
            data=UserSettingsData(
                id=str(user.id),
                attributes=UserSettingsAttributes(timezone=saved.timezone),
            )
        )
    except Exception as e:
        logger.error(
            "Failed to save user settings",
            user_id=user.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while saving user settings",
        ) from e
