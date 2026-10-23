"""User settings API controller.

Provides REST endpoints for managing per-user preferences: the default
timezone, used by the backend (including AI prompt generation) to render
dates/times in the user's local time, and the default country, used to fill in
addresses imported without one (#1820).
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
from app.core.settings.models import UserSettings, UserSettingsRepository
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

    Returns the stored timezone and default country, each ``None`` when the
    user has not set it.
    The ``UTC`` default is deliberately *not* substituted here: the frontend
    anchors the day boundaries it writes on this value and falls back to the
    browser's zone when it is absent, so reporting a default it cannot tell
    apart from a real choice would move every unconfigured user's writes onto
    UTC midnight (issue #1401). Callers wanting a zone to resolve with should
    use the repository's ``get_timezone``, which still applies the default.
    """
    try:
        settings = await repository.get_by_user_id(str(user.id))
        return _response(str(user.id), settings)
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


@router.patch("")
@inject
async def update_user_settings(
    request_data: UserSettingsRequest,
    user: FromDishka[SessionUser],
    service: FromDishka[UserSettingsService],
    connection: FromDishka[AsyncConnection],
) -> UserSettingsResponse:
    """Update the fields the body names (upsert); omitted ones are kept."""
    try:
        saved = await service.update_settings(
            user_id=str(user.id),
            changes=request_data.to_changes(),
            transaction=connection,
        )

        logger.info(
            "User settings saved",
            user_id=user.id,
            timezone=saved.timezone,
            default_country=saved.default_country,
        )

        return _response(str(user.id), saved)
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


def _response(user_id: str, settings: UserSettings | None) -> UserSettingsResponse:
    """The settings as JSON API, ``None`` fields meaning "not chosen"."""
    return UserSettingsResponse(
        data=UserSettingsData(
            id=user_id,
            attributes=UserSettingsAttributes(
                timezone=settings.timezone if settings else None,
                default_country=settings.default_country if settings else None,
            ),
        )
    )
