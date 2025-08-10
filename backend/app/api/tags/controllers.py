"""
Tag API controllers.

Handles tag-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import get_request_base_url
from app.api.contacts.converters import TagConverter
from app.api.contacts.schemas import TagListResponse
from app.api.tags.schemas import TagCreateRequest, TagResponse
from app.core.contacts.models.entities import Tag
from app.core.contacts.models.repositories import TagRepository
from app.core.contacts.models.value_objects import TagName
from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()

router = APIRouter(
    prefix="/tags",
    tags=["tags"],
)


@router.get("", response_model=TagListResponse)
@inject
async def list_tags(
    request: Request,
    tag_repo: FromDishka[TagRepository],
    user: FromDishka[SessionUser],  # Require authentication
    limit: int = Query(default=50, description="Items per page", ge=1, le=100),
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


@router.post("", response_model=TagResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_tag(
    request: Request,
    tag_request: TagCreateRequest,
    tag_repo: FromDishka[TagRepository],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> TagResponse:
    """
    Create a new tag.

    Creates a new tag with the provided data and returns the created resource.
    """
    base_url = get_request_base_url(request)

    # Create tag entity
    tag = Tag(
        name=TagName(tag_request.data.attributes.name),
        color=tag_request.data.attributes.color,
        description=tag_request.data.attributes.description,
    )

    # Save tag
    created_tag = await tag_repo.save(tag)

    tag_resource = TagConverter.to_resource(created_tag, base_url)

    return TagResponse(data=tag_resource)


@router.get("/{tag_id}", response_model=TagResponse)
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


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_tag(
    tag_id: int,
    tag_repo: FromDishka[TagRepository],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a specific tag by ID.

    Removes the tag from the system. This will also remove the tag from any contacts
    that were associated with it.
    """
    tag = await tag_repo.find_by_id(tag_id)
    if not tag:
        from app.core.contacts.models.exceptions import ContactNotFoundError

        raise ContactNotFoundError(tag_id)

    await tag_repo.delete(tag_id)
