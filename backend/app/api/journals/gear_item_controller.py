"""
Gear Item REST API controller.
"""

import uuid

from core_shared.models.journals.gear_item import GearItem
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, status

from app.api.journals.converters import GearItemConverter
from app.api.journals.schemas import (
    GearItemCreateRequest,
    GearItemListResponse,
    GearItemResponse,
    GearItemUpdateRequest,
)
from app.core.journal.models.repositories import GearItemRepository
from app.infrastructure.auth.models import SessionUser

router = APIRouter(prefix="/gear-items", tags=["Gear Items"])


@router.post("", response_model=GearItemResponse, status_code=201)
@inject
async def create_gear_item(
    request: GearItemCreateRequest,
    repo: FromDishka[GearItemRepository],
    user: FromDishka[SessionUser],
    req: Request,
) -> GearItemResponse:
    """Create a new gear item."""
    attrs = request.data.attributes
    try:
        gear_item = GearItem(
            user_id=user.id,
            name=attrs.name,
            model=attrs.model,
            serial_number=attrs.serial_number,
            purchase_date=attrs.purchase_date,
            manufacturer=attrs.manufacturer,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    created = await repo.save(gear_item)
    resource = GearItemConverter.to_resource(created, base_url=str(req.base_url))
    return GearItemResponse(data=resource)


@router.get("", response_model=GearItemListResponse)
@inject
async def get_gear_items(
    repo: FromDishka[GearItemRepository],
    user: FromDishka[SessionUser],
    req: Request,
    name: str | None = Query(None, description="Filter by name"),
) -> GearItemListResponse:
    """Get list of gear items for the current user."""
    if name:
        items = await repo.search_by_name(user_id=user.id, query=name)
    else:
        items = await repo.find_by_user(user_id=user.id)

    resources = [
        GearItemConverter.to_resource(item, base_url=str(req.base_url))
        for item in items
    ]
    return GearItemListResponse(data=resources)


@router.get("/{gear_item_id}", response_model=GearItemResponse)
@inject
async def get_gear_item(
    gear_item_id: uuid.UUID,
    repo: FromDishka[GearItemRepository],
    user: FromDishka[SessionUser],
    req: Request,
) -> GearItemResponse:
    """Get a specific gear item."""
    item = await repo.find_by_id(str(gear_item_id))
    if not item or item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gear item not found"
        )

    resource = GearItemConverter.to_resource(item, base_url=str(req.base_url))
    return GearItemResponse(data=resource)


@router.put("/{gear_item_id}", response_model=GearItemResponse)
@inject
async def update_gear_item(
    gear_item_id: uuid.UUID,
    request: GearItemUpdateRequest,
    repo: FromDishka[GearItemRepository],
    user: FromDishka[SessionUser],
    req: Request,
) -> GearItemResponse:
    """Update a specific gear item."""
    gear_item_id_str = str(gear_item_id)
    if request.data.id != gear_item_id_str:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL ID does not match request body ID",
        )

    item = await repo.find_by_id(gear_item_id_str)
    if not item or item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gear item not found"
        )

    attrs = request.data.attributes
    if attrs.name is not None:
        item.name = attrs.name
    if attrs.model is not None:
        item.model = attrs.model
    if attrs.serial_number is not None:
        item.serial_number = attrs.serial_number
    if attrs.purchase_date is not None:
        item.purchase_date = attrs.purchase_date
    if attrs.manufacturer is not None:
        item.manufacturer = attrs.manufacturer

    try:
        item.__post_init__()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    updated = await repo.save(item)
    resource = GearItemConverter.to_resource(updated, base_url=str(req.base_url))
    return GearItemResponse(data=resource)


@router.delete("/{gear_item_id}", status_code=204)
@inject
async def delete_gear_item(
    gear_item_id: uuid.UUID,
    repo: FromDishka[GearItemRepository],
    user: FromDishka[SessionUser],
) -> None:
    """Delete a specific gear item."""
    item = await repo.find_by_id(str(gear_item_id))
    if not item or item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gear item not found"
        )

    await repo.delete(str(gear_item_id))
