"""
Immich Authentication Controller.

Endpoints for connecting and disconnecting the Immich integration.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from app.infrastructure.auth.immich_token_service import (
    ImmichTokenService,
    ImmichValidationException,
)
from app.infrastructure.auth.models import SessionUser

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
            server_url=str(request.server_url),
            api_key=request.api_key.strip(),
        )
        return {"status": "success", "message": "Immich connected successfully."}
    except ImmichValidationException as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/disconnect", summary="Disconnect Immich", status_code=204)
@inject
async def disconnect_immich(
    user: FromDishka[SessionUser],
    token_service: FromDishka[ImmichTokenService],
) -> None:
    """Disconnect Immich and remove credentials."""
    await token_service.disconnect(user.id)
