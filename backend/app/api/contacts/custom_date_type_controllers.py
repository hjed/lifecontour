"""
Custom date type API controllers.

Handles custom date type HTTP endpoints following JSON API specification.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import get_request_base_url
from app.api.contacts.converters import (
    CustomDateTypeConverter,
    CustomDateTypeRequestConverter,
)
from app.api.contacts.schemas import (
    CustomDateTypeCreateRequest,
    CustomDateTypeListResponse,
    CustomDateTypeResponse,
)
from app.core.contacts.models.repositories import CustomDateTypeRepository
from app.core.contacts.services import CustomDateTypeService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(
    prefix="/custom-date-types",
    tags=["contacts"],
)


@router.get("")
@inject
async def list_custom_date_types(
    request: Request,
    repository: FromDishka[CustomDateTypeRepository],
    user: FromDishka[SessionUser],
) -> CustomDateTypeListResponse:
    """
    List the session user's custom date types.
    """
    base_url = get_request_base_url(request)

    types = await repository.list_all(user_id=user.id)

    resources = [CustomDateTypeConverter.to_resource(t, base_url) for t in types]

    return CustomDateTypeListResponse(data=resources)


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_custom_date_type(
    request: Request,
    type_request: CustomDateTypeCreateRequest,
    service: FromDishka[CustomDateTypeService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> CustomDateTypeResponse:
    """
    Create a new custom date type owned by the session user.
    """
    base_url = get_request_base_url(request)

    date_type = CustomDateTypeRequestConverter.from_create_request(type_request.data)

    created_type = await service.create(
        date_type.name, transaction=connection, user_id=user.id
    )

    resource = CustomDateTypeConverter.to_resource(created_type, base_url)

    return CustomDateTypeResponse(data=resource)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_custom_date_type(
    type_id: int,
    service: FromDishka[CustomDateTypeService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> None:
    """
    Delete one of the session user's custom date types.

    Another user's type answers 404, exactly as a missing one does.
    """
    await service.delete(type_id, transaction=connection, user_id=user.id)
