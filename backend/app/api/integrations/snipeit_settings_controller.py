"""
Snipe-IT settings API controller.

Provides REST API endpoints for managing per-user Snipe-IT integration
configuration (Base URL and user mapping).
"""

from __future__ import annotations

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.integrations.snipeit_settings_schemas import (
    SnipeItSettingsRequest,
    SnipeItSettingsResponse,
)
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
    connection: FromDishka[AsyncConnection],
) -> SnipeItSettingsResponse:
    """
    Get the current Snipe-IT settings for the authenticated user.

    Returns the configured Base URL and optional user mapping.
    """
    try:
        stmt = text("""
            SELECT base_url, snipeit_user_id
            FROM snipeit_settings
            WHERE user_id = :user_id
        """)
        result = await connection.execute(stmt, {"user_id": str(user.id)})
        row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="No Snipe-IT settings found for this user",
            )

        return SnipeItSettingsResponse(
            base_url=row.base_url,
            snipeit_user_id=row.snipeit_user_id,
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
    connection: FromDishka[AsyncConnection],
) -> SnipeItSettingsResponse:
    """
    Create or update Snipe-IT settings for the authenticated user.

    Upserts the Base URL and optional user mapping. The Base URL is used
    by the OAuth flow (Phase 2) and by the worker for API calls.
    """
    try:
        # Upsert: insert or update on conflict
        stmt = text("""
            INSERT INTO snipeit_settings (user_id, base_url, snipeit_user_id, updated_at)
            VALUES (:user_id, :base_url, :snipeit_user_id, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET
                base_url = EXCLUDED.base_url,
                snipeit_user_id = EXCLUDED.snipeit_user_id,
                updated_at = NOW()
            RETURNING base_url, snipeit_user_id
        """)
        result = await connection.execute(
            stmt,
            {
                "user_id": str(user.id),
                "base_url": str(request_data.base_url),
                "snipeit_user_id": request_data.snipeit_user_id,
            },
        )
        row = result.fetchone()

        if not row:
            raise HTTPException(
                status_code=500,
                detail="Failed to save Snipe-IT settings",
            )

        logger.info(
            "Snipe-IT settings saved",
            user_id=user.id,
            base_url=str(request_data.base_url),
        )

        return SnipeItSettingsResponse(
            base_url=row.base_url,
            snipeit_user_id=row.snipeit_user_id,
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
