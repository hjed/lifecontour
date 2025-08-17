"""
Contact API controllers.

Handles contact-related HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

import structlog
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.api.common.schemas import (
    PaginationParams,
    create_pagination_links,
    create_pagination_meta,
    get_request_base_url,
)
from app.api.contacts.converters import (
    ContactConverter,
    ContactRequestConverter,
    TagConverter,
)
from app.api.contacts.schemas import (
    AddressFieldUpdateRequest,
    ContactCreateRequest,
    ContactFieldResponse,
    ContactListResponse,
    ContactResponse,
    ContactUpdateRequest,
    FieldUpdateRequest,
    MethodFieldUpdateRequest,
    NoteFieldUpdateRequest,
    TagAssignmentRequest,
    TagListResponse,
)
from app.core.contacts.models.exceptions import (
    ContactNotFoundError,
    ContactValidationError,
)
from app.core.contacts.services import ContactService
from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()

# Constants for error messages
CONTACT_NOT_FOUND_ERROR = "Contact not found"
FIELD_VALUE_REQUIRED_ERROR = "Field value is required"

router = APIRouter(
    prefix="/contacts",
    tags=["contacts"],
)


@router.get("", response_model=ContactListResponse)
@inject
async def list_contacts(
    request: Request,
    contact_service: FromDishka[ContactService],
    user: FromDishka[SessionUser],  # Require authentication
    page: int = Query(default=1, description="Page number", ge=1),
    limit: int = Query(default=20, description="Items per page", ge=1, le=100),
    favourite: bool | None = Query(
        default=None, description="Filter by favourite status"
    ),
    tag_ids: list[int] | None = Query(default=None, description="Filter by tag IDs"),
) -> ContactListResponse:
    """
    List contacts with pagination.

    Returns a paginated list of contacts following JSON API specification.
    """
    pagination = PaginationParams(page=page, limit=limit)
    base_url = get_request_base_url(request)

    contacts = await contact_service.get_contacts_paginated(
        offset=pagination.offset,
        limit=pagination.limit,
        is_favourite=favourite,
        tag_ids=tag_ids,
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
@inject
async def get_contact(
    contact_id: int,
    request: Request,
    contact_service: FromDishka[ContactService],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactResponse:
    """
    Get a single contact by ID.

    Returns a single contact resource following JSON API specification.
    """
    base_url = get_request_base_url(request)

    contact = await contact_service.get_contact_by_id(contact_id)
    if not contact:
        raise ContactNotFoundError(contact_id)

    contact_resource = ContactConverter.to_resource(contact, base_url)

    return ContactResponse(data=contact_resource)


@router.post("", response_model=ContactResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_contact(
    request: Request,
    contact_request: ContactCreateRequest,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactResponse:
    """
    Create a new contact.

    Creates a new contact with the provided data and returns the created resource.
    """
    base_url = get_request_base_url(request)

    contact = ContactRequestConverter.from_create_request(contact_request.data)

    created_contact = await contact_service.create_contact(contact, connection)

    contact_resource = ContactConverter.to_resource(created_contact, base_url)

    return ContactResponse(data=contact_resource)


@router.put("/{contact_id}", response_model=ContactResponse)
@inject
async def update_contact(
    contact_id: int,
    request: Request,
    contact_request: ContactUpdateRequest,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactResponse:
    """
    Update an existing contact.

    Updates the contact with the provided data and returns the updated resource.
    """
    base_url = get_request_base_url(request)

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
@inject
async def delete_contact(
    contact_id: int,
    contact_service: FromDishka[ContactService],
    engine: FromDishka[AsyncEngine],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a contact.

    Deletes the contact and all associated data.
    Uses a fresh transaction to avoid aborted transaction issues.
    """
    # Use a fresh transaction for the delete operation to avoid
    # issues with aborted transactions from previous operations
    async with engine.begin() as fresh_connection:
        await contact_service.delete_contact(contact_id, fresh_connection)


@router.delete("/test/cleanup", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def test_cleanup_contacts(
    contact_service: FromDishka[ContactService],
    engine: FromDishka[AsyncEngine],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Test-only endpoint: Bulk delete all contacts for test cleanup.

    This endpoint is designed for test environments to efficiently clean up
    test data without transaction conflicts. It deletes all contacts in a
    single transaction with minimal event publishing overhead.

    WARNING: This will delete ALL contacts for the authenticated user.
    Only use in test environments.
    """
    async with engine.begin() as fresh_connection:
        await contact_service.bulk_delete_all_contacts(fresh_connection)


@router.post("/{contact_id}/tags", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def assign_tag_to_contact(
    contact_id: int,
    tag_request: TagAssignmentRequest,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
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
@inject
async def remove_tag_from_contact(
    contact_id: int,
    tag_id: int,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
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
@inject
async def get_contact_tags(
    contact_id: int,
    request: Request,
    contact_service: FromDishka[ContactService],
    user: FromDishka[SessionUser],  # Require authentication
) -> TagListResponse:
    """
    Get all tags assigned to a contact.

    Returns a list of tag resources assigned to the specified contact.
    """
    base_url = get_request_base_url(request)

    existing_contact = await contact_service.get_contact_by_id(contact_id)
    if not existing_contact:
        raise ContactNotFoundError(contact_id)

    tags = existing_contact.tags or []

    tag_resources = [TagConverter.to_resource(tag, base_url) for tag in tags]

    return TagListResponse(data=tag_resources)


@router.post("/{contact_id}/favourite", response_model=ContactResponse)
@inject
async def toggle_contact_favourite(
    contact_id: int,
    request: Request,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactResponse:
    """
    Toggle the favourite status of a contact.

    Toggles the is_favourite field of the specified contact.
    Returns the updated contact with the new favourite status.
    """
    base_url = get_request_base_url(request)

    try:
        updated_contact = await contact_service.toggle_contact_favourite(
            contact_id, connection
        )

        return ContactResponse(
            data=ContactConverter.to_resource(updated_contact, base_url)
        )
    except ContactValidationError as e:
        if CONTACT_NOT_FOUND_ERROR in str(e):
            raise ContactNotFoundError(contact_id) from e
        raise


@router.patch("/{contact_id}/fields/{field_name}", response_model=ContactFieldResponse)
@inject
async def update_contact_field(
    contact_id: int,
    field_name: str,
    field_request: FieldUpdateRequest,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactFieldResponse:
    """
    Update a single contact field.

    Updates only the specified field of a contact and returns the field update details.
    This endpoint is optimized for inline editing functionality where only one field
    is changed at a time.

    Supported fields: first_name, last_name, middle_name, nick_name, is_favourite
    """
    # Extract the field value from the request
    field_value = field_request.data.attributes.get("value")
    if field_value is None:
        raise ContactValidationError("value", FIELD_VALUE_REQUIRED_ERROR)

    try:
        old_value, new_value = await contact_service.update_contact_field(
            contact_id, field_name, field_value, connection
        )

        # Create response
        from datetime import datetime

        from app.api.contacts.schemas import (
            ContactFieldAttributes,
            ContactFieldResource,
        )

        field_resource = ContactFieldResource(
            id=f"{contact_id}:{field_name}",
            attributes=ContactFieldAttributes(
                field_name=field_name,
                field_type="basic",
                old_value=old_value,
                new_value=new_value,
                updated_at=datetime.now(),
            ),
        )

        return ContactFieldResponse(data=field_resource)

    except ContactValidationError as e:
        if CONTACT_NOT_FOUND_ERROR in str(e):
            raise ContactNotFoundError(contact_id) from e
        raise


@router.patch(
    "/{contact_id}/methods/{method_id}/fields/{field_name}",
    response_model=ContactFieldResponse,
)
@inject
async def update_contact_method_field(
    contact_id: int,
    method_id: int,
    field_name: str,
    field_request: MethodFieldUpdateRequest,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactFieldResponse:
    """
    Update a single contact method field.

    Updates only the specified field of a contact method (email/phone).
    Supported fields: value, label, is_primary
    """
    # Extract the field value from the request
    field_value = field_request.data.attributes.get("value")
    if field_value is None:
        raise ContactValidationError("value", FIELD_VALUE_REQUIRED_ERROR)

    try:
        old_value, new_value = await contact_service.update_contact_method_field(
            contact_id, method_id, field_name, field_value, connection
        )

        # Create response
        from datetime import datetime

        from app.api.contacts.schemas import (
            ContactFieldAttributes,
            ContactFieldResource,
        )

        field_resource = ContactFieldResource(
            id=f"{contact_id}:method:{method_id}:{field_name}",
            attributes=ContactFieldAttributes(
                field_name=field_name,
                field_type="method",
                entity_id=method_id,
                old_value=old_value,
                new_value=new_value,
                updated_at=datetime.now(),
            ),
        )

        return ContactFieldResponse(data=field_resource)

    except ContactValidationError as e:
        if CONTACT_NOT_FOUND_ERROR in str(e):
            raise ContactNotFoundError(contact_id) from e
        raise


@router.patch(
    "/{contact_id}/addresses/{address_id}/fields/{field_name}",
    response_model=ContactFieldResponse,
)
@inject
async def update_contact_address_field(
    contact_id: int,
    address_id: int,
    field_name: str,
    field_request: AddressFieldUpdateRequest,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactFieldResponse:
    """
    Update a single contact address field.

    Updates only the specified field of a contact address.
    Supported fields: label, street_line_1, street_line_2, locality, region, postal_code, country_code, is_primary
    """
    # Extract the field value from the request
    field_value = field_request.data.attributes.get("value")
    if field_value is None:
        raise ContactValidationError("value", FIELD_VALUE_REQUIRED_ERROR)

    try:
        old_value, new_value = await contact_service.update_contact_address_field(
            contact_id, address_id, field_name, field_value, connection
        )

        # Create response
        from datetime import datetime

        from app.api.contacts.schemas import (
            ContactFieldAttributes,
            ContactFieldResource,
        )

        field_resource = ContactFieldResource(
            id=f"{contact_id}:address:{address_id}:{field_name}",
            attributes=ContactFieldAttributes(
                field_name=field_name,
                field_type="address",
                entity_id=address_id,
                old_value=old_value,
                new_value=new_value,
                updated_at=datetime.now(),
            ),
        )

        return ContactFieldResponse(data=field_resource)

    except ContactValidationError as e:
        if CONTACT_NOT_FOUND_ERROR in str(e):
            raise ContactNotFoundError(contact_id) from e
        raise


@router.patch(
    "/{contact_id}/notes/{note_id}/fields/{field_name}",
    response_model=ContactFieldResponse,
)
@inject
async def update_contact_note_field(
    contact_id: int,
    note_id: int,
    field_name: str,
    field_request: NoteFieldUpdateRequest,
    contact_service: FromDishka[ContactService],
    connection: FromDishka[AsyncConnection],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactFieldResponse:
    """
    Update a single contact note field.

    Updates only the specified field of a contact note.
    Supported fields: content
    """
    # Extract the field value from the request
    field_value = field_request.data.attributes.get("value")
    if field_value is None:
        raise ContactValidationError("value", FIELD_VALUE_REQUIRED_ERROR)

    try:
        old_value, new_value = await contact_service.update_contact_note_field(
            contact_id, note_id, field_name, field_value, connection
        )

        # Create response
        from datetime import datetime

        from app.api.contacts.schemas import (
            ContactFieldAttributes,
            ContactFieldResource,
        )

        field_resource = ContactFieldResource(
            id=f"{contact_id}:note:{note_id}:{field_name}",
            attributes=ContactFieldAttributes(
                field_name=field_name,
                field_type="note",
                entity_id=note_id,
                old_value=old_value,
                new_value=new_value,
                updated_at=datetime.now(),
            ),
        )

        return ContactFieldResponse(data=field_resource)

    except ContactValidationError as e:
        if CONTACT_NOT_FOUND_ERROR in str(e):
            raise ContactNotFoundError(contact_id) from e
        raise
