"""
Gear Item REST API controller.
"""

import uuid
from typing import Annotated

from core_shared.models.journals.gear_item import GearItem
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import ExternalLinksResponse
from app.api.journals.converters import GearItemConverter
from app.api.journals.schemas import (
    GearItemCreateRequest,
    GearItemListResponse,
    GearItemResponse,
    GearItemUpdateRequest,
)
from app.core.journal.models.repositories import GearItemRepository
from app.core.journal.services.gear_item_service import GearItemService
from app.infrastructure.auth.models import SessionUser

router = APIRouter(prefix="/gear-items", tags=["Gear Items"])


@router.post("", status_code=201)
@inject
async def create_gear_item(
    request: GearItemCreateRequest,
    service: FromDishka[GearItemService],
    connection: FromDishka[AsyncConnection],
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

    created = await service.create(gear_item, transaction=connection)
    resource = GearItemConverter.to_resource(created, base_url=str(req.base_url))
    return GearItemResponse(data=resource)


@router.get("")
@inject
async def get_gear_items(
    repo: FromDishka[GearItemRepository],
    user: FromDishka[SessionUser],
    req: Request,
    name: Annotated[str | None, Query(description="Filter by name")] = None,
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


@router.get("/{gear_item_id}")
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


@router.put("/{gear_item_id}")
@inject
async def update_gear_item(
    gear_item_id: uuid.UUID,
    request: GearItemUpdateRequest,
    repo: FromDishka[GearItemRepository],
    service: FromDishka[GearItemService],
    user: FromDishka[SessionUser],
    req: Request,
    transaction: FromDishka[AsyncConnection],
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
    set_fields = attrs.model_fields_set

    if "name" in set_fields:
        if attrs.name is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="name cannot be null",
            )
        item.name = attrs.name
    if "model" in set_fields:
        item.model = attrs.model
    if "serial_number" in set_fields:
        item.serial_number = attrs.serial_number
    if "purchase_date" in set_fields:
        item.purchase_date = attrs.purchase_date
    if "manufacturer" in set_fields:
        item.manufacturer = attrs.manufacturer

    try:
        item.__post_init__()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    updated = await service.update(item, transaction=transaction)

    resource = GearItemConverter.to_resource(updated, base_url=str(req.base_url))
    return GearItemResponse(data=resource)


@router.delete("/{gear_item_id}", status_code=204)
@inject
async def delete_gear_item(
    gear_item_id: uuid.UUID,
    repo: FromDishka[GearItemRepository],
    service: FromDishka[GearItemService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],
) -> None:
    """Delete a specific gear item."""
    item = await repo.find_by_id(str(gear_item_id))
    if not item or item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gear item not found"
        )

    await service.delete(str(gear_item_id), transaction=connection)


@router.get("/{gear_item_id}/external-links")
@inject
async def get_gear_item_external_links(
    gear_item_id: uuid.UUID,
    repo: FromDishka[GearItemRepository],
    user: FromDishka[SessionUser],
) -> ExternalLinksResponse:
    """Get external system links for a gear item."""
    from app.api.common.schemas import ExternalLinkAttributes, ExternalLinkResource
    from app.core.integrations.external_link_helpers import build_snipeit_asset_url

    item = await repo.find_by_id(str(gear_item_id))
    if not item or item.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Gear item not found"
        )

    links = []

    snipeit_links_data = await repo.get_snipeit_links(str(gear_item_id), user.id)

    for link_data in snipeit_links_data:
        ext_id = link_data["external_id"]
        base_url = link_data["base_url"]

        url = build_snipeit_asset_url(base_url, ext_id)
        links.append(
            ExternalLinkResource(
                id=f"snipeit-asset-{ext_id}",
                attributes=ExternalLinkAttributes(
                    source="snipeit",
                    url=url,
                    external_id=ext_id,
                ),
            )
        )

    return ExternalLinksResponse(data=links)
