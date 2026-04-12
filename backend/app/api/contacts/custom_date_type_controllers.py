"""
Custom date type API controllers.

Handles custom date type HTTP endpoints following JSON API specification.
"""

from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Request, status

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
    _user: FromDishka[SessionUser],  # Require authentication
) -> CustomDateTypeListResponse:
    """
    List all custom date types.
    """
    base_url = get_request_base_url(request)

    types = await repository.list_all()

    resources = [CustomDateTypeConverter.to_resource(t, base_url) for t in types]

    return CustomDateTypeListResponse(data=resources)


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_custom_date_type(
    request: Request,
    type_request: CustomDateTypeCreateRequest,
    repository: FromDishka[CustomDateTypeRepository],
    _user: FromDishka[SessionUser],  # Require authentication
) -> CustomDateTypeResponse:
    """
    Create a new custom date type.
    """
    base_url = get_request_base_url(request)

    date_type = CustomDateTypeRequestConverter.from_create_request(type_request.data)

    created_type = await repository.create(date_type.name)

    resource = CustomDateTypeConverter.to_resource(created_type, base_url)

    return CustomDateTypeResponse(data=resource)


@router.delete("/{type_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_custom_date_type(
    type_id: int,
    repository: FromDishka[CustomDateTypeRepository],
    _user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a custom date type.
    """
    await repository.delete(type_id)
