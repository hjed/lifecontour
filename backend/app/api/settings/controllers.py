"""User settings API controller.

Provides REST endpoints for managing per-user preferences. Currently exposes
the default timezone, which is synced from the frontend and used by the
backend (including AI prompt generation) to render dates/times in the user's
local time.
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.settings.schemas import (
    UserSettingsAttributes,
    UserSettingsData,
    UserSettingsRequest,
    UserSettingsResponse,
)
from app.core.settings.models import UserSettingsRepository
from app.core.settings.services.user_settings_service import UserSettingsService
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

    Returns the stored timezone, or ``None`` when the user has not set one.
    The ``UTC`` default is deliberately *not* substituted here: the frontend
    anchors the day boundaries it writes on this value and falls back to the
    browser's zone when it is absent, so reporting a default it cannot tell
    apart from a real choice would move every unconfigured user's writes onto
    UTC midnight (issue #1401). Callers wanting a zone to resolve with should
    use the repository's ``get_timezone``, which still applies the default.
    """
    try:
        settings = await repository.get_by_user_id(str(user.id))
        timezone = settings.timezone if settings else None

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
    service: FromDishka[UserSettingsService],
    connection: FromDishka[AsyncConnection],
) -> UserSettingsResponse:
    """Create or update the authenticated user's settings (upsert)."""
    try:
        saved = await service.save_settings(
            user_id=str(user.id),
            timezone=request_data.timezone,
            transaction=connection,
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
