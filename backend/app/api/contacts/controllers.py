"""
Contact API controllers.

Handles contact-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

import structlog
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.api.common.schemas import (
    PaginationParams,
    create_pagination_links,
    create_pagination_meta,
)
from app.api.contacts.converters import (
    ContactConverter,
    ContactRequestConverter,
    TagConverter,
)
from app.api.contacts.schemas import (
    ContactCreateRequest,
    ContactListResponse,
    ContactResponse,
    ContactUpdateRequest,
    TagAssignmentRequest,
    TagListResponse,
)
from app.api.dependencies import ContactServiceDep, get_async_db_connection
from app.core.contacts.models.exceptions import ContactNotFoundError

logger = structlog.get_logger()

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    request: Request,
    contact_service: ContactServiceDep,
    page: int = Query(default=1, description="Page number", ge=1),
    limit: int = Query(default=20, description="Items per page", ge=1, le=100),
) -> ContactListResponse:
    """
    List contacts with pagination.

    Returns a paginated list of contacts following JSON API specification.
    """
    pagination = PaginationParams(page=page, limit=limit)
    base_url = str(request.base_url).rstrip("/")

    contacts = await contact_service.get_contacts_paginated(
        offset=pagination.offset,
        limit=pagination.limit,
    )

    total_count = await contact_service.get_contacts_count()

    contact_resources = [
        ContactConverter.to_resource(contact, base_url) for contact in contacts
    ]

    meta = create_pagination_meta(total_count, page, limit)
    links = create_pagination_links(
        f"{base_url}/api/contacts", page, limit, total_count
    )

    return ContactListResponse(
        data=contact_resources,
        meta=meta,
        links=links,
    )


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_id: int,
    request: Request,
    contact_service: ContactServiceDep,
) -> ContactResponse:
    """
    Get a single contact by ID.

    Returns a single contact resource following JSON API specification.
    """
    base_url = str(request.base_url).rstrip("/")

    contact = await contact_service.get_contact_by_id(contact_id)
    if not contact:
        raise ContactNotFoundError(contact_id)

    contact_resource = ContactConverter.to_resource(contact, base_url)

    return ContactResponse(data=contact_resource)


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
async def create_contact(
    request: Request,
    contact_request: ContactCreateRequest,
    contact_service: ContactServiceDep,
    connection: AsyncConnection = Depends(get_async_db_connection),
) -> ContactResponse:
    """
    Create a new contact.

    Creates a new contact with the provided data and returns the created resource.
    """
    base_url = str(request.base_url).rstrip("/")

    contact = ContactRequestConverter.from_create_request(contact_request.data)

    created_contact = await contact_service.create_contact(contact, connection)

    contact_resource = ContactConverter.to_resource(created_contact, base_url)

    return ContactResponse(data=contact_resource)


@router.put("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: int,
    request: Request,
    contact_request: ContactUpdateRequest,
    contact_service: ContactServiceDep,
    connection: AsyncConnection = Depends(get_async_db_connection),
) -> ContactResponse:
    """
    Update an existing contact.

    Updates the contact with the provided data and returns the updated resource.
    """
    base_url = str(request.base_url).rstrip("/")

    existing_contact = await contact_service.get_contact_by_id(contact_id)
    if not existing_contact:
        raise ContactNotFoundError(contact_id)

    updated_contact = ContactRequestConverter.from_update_request(
        contact_request.data, existing_contact
    )

    saved_contact = await contact_service.update_contact(updated_contact, connection)

    contact_resource = ContactConverter.to_resource(saved_contact, base_url)

    return ContactResponse(data=contact_resource)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contact(
    contact_id: int,
    contact_service: ContactServiceDep,
    connection: AsyncConnection = Depends(get_async_db_connection),
) -> None:
    """
    Delete a contact.

    Deletes the contact and all associated data.
    """
    existing_contact = await contact_service.get_contact_by_id(contact_id)
    if not existing_contact:
        raise ContactNotFoundError(contact_id)

    await contact_service.delete_contact(contact_id, connection)


@router.post("/{contact_id}/tags", status_code=status.HTTP_204_NO_CONTENT)
async def assign_tag_to_contact(
    contact_id: int,
    tag_request: TagAssignmentRequest,
    contact_service: ContactServiceDep,
    connection: AsyncConnection = Depends(get_async_db_connection),
) -> None:
    """
    Assign a tag to a contact.

    Creates a relationship between the contact and the specified tag.
    """
    tag_id = int(tag_request.data.id)

    existing_contact = await contact_service.get_contact_by_id(contact_id)
    if not existing_contact:
        raise ContactNotFoundError(contact_id)

    await contact_service.assign_tag_to_contact(contact_id, tag_id, connection)


@router.delete("/{contact_id}/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tag_from_contact(
    contact_id: int,
    tag_id: int,
    contact_service: ContactServiceDep,
    connection: AsyncConnection = Depends(get_async_db_connection),
) -> None:
    """
    Remove a tag from a contact.

    Removes the relationship between the contact and the specified tag.
    """
    existing_contact = await contact_service.get_contact_by_id(contact_id)
    if not existing_contact:
        raise ContactNotFoundError(contact_id)

    await contact_service.remove_tag_from_contact(contact_id, tag_id, connection)


@router.get("/{contact_id}/tags", response_model=TagListResponse)
async def get_contact_tags(
    contact_id: int,
    request: Request,
    contact_service: ContactServiceDep,
) -> TagListResponse:
    """
    Get all tags assigned to a contact.

    Returns a list of tag resources assigned to the specified contact.
    """
    base_url = str(request.base_url).rstrip("/")

    existing_contact = await contact_service.get_contact_by_id(contact_id)
    if not existing_contact:
        raise ContactNotFoundError(contact_id)

    tags = existing_contact.tags or []

    tag_resources = [TagConverter.to_resource(tag, base_url) for tag in tags]

    return TagListResponse(data=tag_resources)
