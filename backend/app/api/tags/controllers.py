"""
Tag API controllers.

Handles tag-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

from typing import Annotated

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import get_request_base_url
from app.api.contacts.converters import TagConverter
from app.api.contacts.schemas import TagListResponse
from app.api.tags.schemas import (
    TagCreateRequest,
    TagMergeRequest,
    TagResponse,
    TagUpdateRequest,
)
from app.core.contacts.models.repositories import TagRepository
from app.core.contacts.services.tag_service import TagService
from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()

router = APIRouter(
    prefix="/tags",
    tags=["tags"],
)


@router.get("")
@inject
async def list_tags(
    request: Request,
    tag_repo: FromDishka[TagRepository],
    user: FromDishka[SessionUser],  # Require authentication
    limit: Annotated[int, Query(description="Items per page", ge=1, le=1000)] = 1000,
) -> TagListResponse:
    """
    List all available tags.

    Returns a list of all tags that can be used to categorize contacts.
    """
    base_url = get_request_base_url(request)

    # Get all tags from repository
    all_tags = await tag_repo.get_all()
    # Apply limit
    tags = all_tags[:limit] if limit < len(all_tags) else all_tags

    tag_resources = [TagConverter.to_resource(tag, base_url) for tag in tags]

    return TagListResponse(data=tag_resources)


@router.post("", status_code=status.HTTP_201_CREATED)
@inject
async def create_tag(
    request: Request,
    tag_request: TagCreateRequest,
    tag_service: FromDishka[TagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TagResponse:
    """
    Create a new tag.

    Creates a new tag with the provided data and returns the created resource.
    If parent_id is provided, validates that the parent tag exists.
    """
    base_url = get_request_base_url(request)
    attrs = tag_request.data.attributes

    created_tag = await tag_service.create_tag(
        name=attrs.name,
        transaction=connection,
        color=attrs.color,
        description=attrs.description,
        parent_id=attrs.parent_id,
    )

    tag_resource = TagConverter.to_resource(created_tag, base_url)

    return TagResponse(data=tag_resource)


@router.get("/{tag_id}")
@inject
async def get_tag(
    tag_id: int,
    request: Request,
    tag_repo: FromDishka[TagRepository],
    user: FromDishka[SessionUser],  # Require authentication
) -> TagResponse:
    """
    Get a specific tag by ID.

    Returns the tag resource with the specified ID.
    """
    base_url = get_request_base_url(request)

    tag = await tag_repo.find_by_id(tag_id)
    if not tag:
        from app.core.contacts.models.exceptions import ContactNotFoundError

        raise ContactNotFoundError(tag_id)

    tag_resource = TagConverter.to_resource(tag, base_url)

    return TagResponse(data=tag_resource)


@router.patch("/{tag_id}")
@inject
async def update_tag(
    tag_id: int,
    request: Request,
    tag_request: TagUpdateRequest,
    tag_service: FromDishka[TagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TagResponse:
    """
    Update a specific tag by ID.

    Updates the tag with the provided attributes and returns the updated resource.
    Supports clearing parent_id by providing explicit None.
    """
    base_url = get_request_base_url(request)
    # Validate resource type
    if tag_request.data.type and tag_request.data.type != "tags":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid resource type, expected 'tags'",
        )

    # Validate that path ID matches body ID if body ID is provided
    body_id = tag_request.data.id
    if body_id is not None:
        try:
            body_id_int = int(str(body_id))
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tag ID format in request body",
            ) from e
        if body_id_int != tag_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Path ID does not match body ID",
            )

    attrs = tag_request.data.attributes

    # Check if parent_id is explicitly set to None
    set_parent_null = False
    if "parent_id" in attrs.model_fields_set and attrs.parent_id is None:
        set_parent_null = True

    try:
        updated_tag = await tag_service.update_tag(
            tag_id=tag_id,
            transaction=connection,
            name=attrs.name,
            color=attrs.color,
            description=attrs.description,
            parent_id=attrs.parent_id,
            set_parent_null=set_parent_null,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    tag_resource = TagConverter.to_resource(updated_tag, base_url)

    return TagResponse(data=tag_resource)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_tag(
    tag_id: int,
    tag_service: FromDishka[TagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a specific tag by ID.

    Removes the tag from the system. This will also remove the tag from any contacts
    that were associated with it.
    """
    await tag_service.delete_tag(tag_id=tag_id, transaction=connection)


@router.post("/{tag_id}/merge", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def merge_tag(
    tag_id: int,
    merge_request: TagMergeRequest,
    tag_service: FromDishka[TagService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Merge a tag into another tag.

    This takes all contacts associated with the source tag, associates them with the
    target tag, and deletes the source tag.
    """
    if merge_request.data.type != "tags":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid resource type, expected 'tags'",
        )

    target_tag_id = merge_request.data.attributes.target_tag_id

    try:
        await tag_service.merge_tags(
            source_id=tag_id, target_id=target_tag_id, transaction=connection
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
