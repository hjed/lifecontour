"""
Contacts API controllers.

Handles contact-related HTTP endpoints following JSON API specification.
No business logic - delegates to ContactService for all operations.
"""

import structlog
from fastapi import APIRouter, HTTPException, Path, Query

from app.api.contacts.converters import (
    build_included_data,
    contact_to_json_api,
    json_api_to_contact,
)
from app.api.contacts.schemas import (
    ContactListResponse,
    ContactRequest,
    ContactResponse,
    JsonApiLinks,
    JsonApiMeta,
)
from app.api.dependencies import ContactServiceDep

logger = structlog.get_logger()

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=ContactListResponse)
async def list_contacts(
    contact_service: ContactServiceDep,
    limit: int = Query(default=20, description="Maximum results", ge=1, le=100),
    offset: int = Query(default=0, description="Results offset", ge=0),
) -> ContactListResponse:
    """
    List all contacts with pagination.

    Returns a paginated list of contacts following JSON API specification.
    """
    try:
        # Get contacts from service
        contacts = await contact_service.get_all_contacts(limit=limit, offset=offset)

        # Convert to JSON API format
        data = []
        included = []

        for contact in contacts:
            contact_data = contact_to_json_api(contact, include_relationships=True)
            data.append(contact_data)

            # Add included data
            included.extend(build_included_data(contact))

        # Build pagination links (simplified for now)
        links = JsonApiLinks(
            self=f"/api/contacts?limit={limit}&offset={offset}",
            next=f"/api/contacts?limit={limit}&offset={offset + limit}" if len(contacts) == limit else None,
            prev=f"/api/contacts?limit={limit}&offset={max(0, offset - limit)}" if offset > 0 else None,
        )

        # Build meta information
        meta = JsonApiMeta(
            current_page=(offset // limit) + 1 if limit > 0 else 1,
        )

        return ContactListResponse(
            data=data,
            included=included if included else None,
            meta=meta,
            links=links,
        )

    except Exception as e:
        logger.error("Error listing contacts", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.get("/{contact_id}", response_model=ContactResponse)
async def get_contact(
    contact_service: ContactServiceDep,
    contact_id: int = Path(..., description="Contact ID", ge=1),
) -> ContactResponse:
    """
    Get a single contact by ID.

    Returns the contact with all related data (methods, addresses, notes, tags).
    """
    try:
        # Get contact from service
        contact = await contact_service.get_contact_by_id(contact_id)

        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")

        # Convert to JSON API format
        contact_data = contact_to_json_api(contact, include_relationships=True)
        included = build_included_data(contact)

        return ContactResponse(
            data=contact_data,
            included=included if included else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error getting contact", contact_id=contact_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.post("", response_model=ContactResponse, status_code=201)
async def create_contact(
    contact_service: ContactServiceDep,
    request: ContactRequest,
) -> ContactResponse:
    """
    Create a new contact.

    Creates a contact with the provided data. Methods, addresses, notes, and tags
    should be added separately using their respective endpoints.
    """
    try:
        # Convert from JSON API format to domain entity
        contact = json_api_to_contact(request.data)

        # Create contact using service
        created_contact = await contact_service.create_contact_api(contact)

        # Convert back to JSON API format
        contact_data = contact_to_json_api(created_contact, include_relationships=True)
        included = build_included_data(created_contact)

        return ContactResponse(
            data=contact_data,
            included=included if included else None,
        )

    except Exception as e:
        logger.error("Error creating contact", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.put("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_service: ContactServiceDep,
    request: ContactRequest,
    contact_id: int = Path(..., description="Contact ID", ge=1),
) -> ContactResponse:
    """
    Update an existing contact.

    Updates the contact with the provided data. Only the fields in the request
    will be updated.
    """
    try:
        # Get existing contact
        existing_contact = await contact_service.get_contact_by_id(contact_id)

        if not existing_contact:
            raise HTTPException(status_code=404, detail="Contact not found")

        # Convert request to domain entity, updating the existing contact
        updated_contact = json_api_to_contact(request.data, existing_contact)

        # Update contact using service (service will calculate changed fields internally)
        saved_contact = await contact_service.update_contact_api(updated_contact)

        # Convert back to JSON API format
        contact_data = contact_to_json_api(saved_contact, include_relationships=True)
        included = build_included_data(saved_contact)

        return ContactResponse(
            data=contact_data,
            included=included if included else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating contact", contact_id=contact_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e


@router.delete("/{contact_id}", status_code=204)
async def delete_contact(
    contact_service: ContactServiceDep,
    contact_id: int = Path(..., description="Contact ID", ge=1),
) -> None:
    """
    Delete a contact.

    Permanently deletes the contact and all related data (methods, addresses, notes).
    Tags are not deleted as they may be used by other contacts.
    """
    try:
        # Delete contact using service
        await contact_service.delete_contact_api(contact_id)

        # Return 204 No Content (no response body)
        return None

    except Exception as e:
        logger.error("Error deleting contact", contact_id=contact_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e





@router.get("/{contact_id}/notes", response_model=list[dict])
async def list_contact_notes(
    contact_service: ContactServiceDep,
    contact_id: int = Path(..., description="Contact ID", ge=1),
) -> list[dict]:
    """
    List all notes for a contact.

    Returns all contact notes for the specified contact.
    """
    try:
        # Get contact to ensure it exists and get notes
        contact = await contact_service.get_contact_by_id(contact_id)

        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")

        # Convert notes to JSON API format
        from app.api.contacts.converters import contact_note_to_json_api

        notes_data = [contact_note_to_json_api(note).model_dump() for note in contact.notes]

        return notes_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error listing contact notes", contact_id=contact_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e





@router.delete("/{contact_id}/relationships/tags/{tag_id}", status_code=204)
async def remove_tag_from_contact(
    contact_service: ContactServiceDep,
    contact_id: int = Path(..., description="Contact ID", ge=1),
    tag_id: int = Path(..., description="Tag ID", ge=1),
) -> None:
    """
    Remove a tag from a contact.

    Removes the relationship between the contact and the specified tag.
    """
    try:
        # Remove tag from contact using service
        await contact_service.remove_tag_from_contact_api(contact_id, tag_id)

        # Return 204 No Content (no response body)
        return None

    except Exception as e:
        logger.error("Error removing tag from contact", contact_id=contact_id, tag_id=tag_id, error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error") from e
