"""
Contact relationship API controllers.

Handles contact relationship HTTP endpoints following JSON API specification.
Controllers act as adapters between HTTP and domain services.
"""

import structlog
from core_shared.models.contacts.exceptions import ContactValidationError
from dishka.integrations.fastapi import FromDishka, inject
from fastapi import APIRouter, Request, status

from app.api.common.schemas import get_request_base_url
from app.api.contacts.converters import (
    ContactRelationshipConverter,
    ContactRelationshipRequestConverter,
)
from app.api.contacts.schemas import (
    ContactRelationshipCreateRequest,
    ContactRelationshipListResponse,
    ContactRelationshipResponse,
    ContactRelationshipUpdateRequest,
)
from app.core.contacts.services import ContactRelationshipService
from app.infrastructure.auth.models import SessionUser

logger = structlog.get_logger()

# Create router for relationship endpoints
router = APIRouter(
    prefix="/contacts/{contact_id}/relationships", tags=["relationships"]
)


@router.get("", response_model=ContactRelationshipListResponse)
@inject
async def get_contact_relationships(
    contact_id: int,
    request: Request,
    relationship_service: FromDishka[ContactRelationshipService],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactRelationshipListResponse:
    """
    Get all relationships for a contact.

    Returns a list of relationship resources following JSON API specification.
    """
    base_url = get_request_base_url(request)

    relationships = await relationship_service.get_relationships_for_contact(contact_id)

    # Resolve contact names for display
    relationships = await relationship_service.resolve_relationship_contact_names(
        relationships, contact_id
    )

    relationship_resources = [
        ContactRelationshipConverter.to_resource(relationship, base_url)
        for relationship in relationships
    ]

    return ContactRelationshipListResponse(data=relationship_resources)


@router.get("/{relationship_id}", response_model=ContactRelationshipResponse)
@inject
async def get_contact_relationship(
    contact_id: int,
    relationship_id: int,
    request: Request,
    relationship_service: FromDishka[ContactRelationshipService],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactRelationshipResponse:
    """
    Get a specific relationship by ID.

    Returns a single relationship resource following JSON API specification.
    """
    base_url = get_request_base_url(request)

    relationship = await relationship_service.get_relationship_by_id(relationship_id)
    if not relationship:
        raise ContactValidationError(
            "relationship", f"Relationship with ID {relationship_id} not found"
        )

    # Verify the relationship belongs to the specified contact
    if (
        relationship.from_contact_id != contact_id
        and relationship.to_contact_id != contact_id
    ):
        raise ContactValidationError(
            "relationship",
            f"Relationship {relationship_id} does not belong to contact {contact_id}",
        )

    # Resolve contact name for display
    [relationship] = await relationship_service.resolve_relationship_contact_names(
        [relationship], contact_id
    )

    relationship_resource = ContactRelationshipConverter.to_resource(
        relationship, base_url
    )

    return ContactRelationshipResponse(data=relationship_resource)


@router.post(
    "", response_model=ContactRelationshipResponse, status_code=status.HTTP_201_CREATED
)
@inject
async def create_contact_relationship(
    contact_id: int,
    request: Request,
    relationship_request: ContactRelationshipCreateRequest,
    relationship_service: FromDishka[ContactRelationshipService],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactRelationshipResponse:
    """
    Create a new relationship for a contact.

    Creates a new relationship with the provided data and returns the created resource.
    """
    base_url = get_request_base_url(request)

    # Validate that from_contact_id matches the URL parameter
    if relationship_request.data.attributes.from_contact_id != contact_id:
        raise ContactValidationError(
            "relationship",
            f"from_contact_id in request body ({relationship_request.data.attributes.from_contact_id}) "
            f"must match contact_id in URL ({contact_id})",
        )

    relationship = ContactRelationshipRequestConverter.from_create_request(
        relationship_request.data
    )

    created_relationship = await relationship_service.create_relationship(
        from_contact_id=relationship.from_contact_id,
        to_contact_id=relationship.to_contact_id,
        relationship_type=relationship.relationship_type,
    )

    # Handle both single relationship and list of relationships
    if isinstance(created_relationship, list):
        # For now, just return the first relationship (the primary one)
        # In the future, we might want to return both relationships
        primary_relationship = created_relationship[0]
    else:
        primary_relationship = created_relationship

    # Resolve contact name for display consistency
    [
        primary_relationship
    ] = await relationship_service.resolve_relationship_contact_names(
        [primary_relationship], contact_id
    )

    relationship_resource = ContactRelationshipConverter.to_resource(
        primary_relationship, base_url
    )

    return ContactRelationshipResponse(data=relationship_resource)


@router.put("/{relationship_id}", response_model=ContactRelationshipResponse)
@inject
async def update_contact_relationship(
    contact_id: int,
    relationship_id: int,
    request: Request,
    relationship_request: ContactRelationshipUpdateRequest,
    relationship_service: FromDishka[ContactRelationshipService],
    user: FromDishka[SessionUser],  # Require authentication
) -> ContactRelationshipResponse:
    """
    Update an existing relationship.

    Updates the relationship with the provided data and returns the updated resource.
    """
    base_url = get_request_base_url(request)

    # Validate that the relationship ID matches
    if int(relationship_request.data.id) != relationship_id:
        raise ContactValidationError(
            "relationship",
            f"Relationship ID in request body ({relationship_request.data.id}) "
            f"must match relationship_id in URL ({relationship_id})",
        )

    # Get existing relationship to verify ownership
    existing_relationship = await relationship_service.get_relationship_by_id(
        relationship_id
    )
    if not existing_relationship:
        raise ContactValidationError(
            "relationship", f"Relationship with ID {relationship_id} not found"
        )

    # Verify the relationship belongs to the specified contact
    if (
        existing_relationship.from_contact_id != contact_id
        and existing_relationship.to_contact_id != contact_id
    ):
        raise ContactValidationError(
            "relationship",
            f"Relationship {relationship_id} does not belong to contact {contact_id}",
        )

    from core_shared.models.contacts.entities import RelationshipType

    updated_relationship = await relationship_service.update_relationship(
        relationship_id=relationship_id,
        relationship_type=RelationshipType(
            relationship_request.data.attributes.relationship_type
        ),
    )

    # Resolve contact name for display consistency
    [
        updated_relationship
    ] = await relationship_service.resolve_relationship_contact_names(
        [updated_relationship], contact_id
    )

    relationship_resource = ContactRelationshipConverter.to_resource(
        updated_relationship, base_url
    )

    return ContactRelationshipResponse(data=relationship_resource)


@router.delete("/{relationship_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_contact_relationship(
    contact_id: int,
    relationship_id: int,
    relationship_service: FromDishka[ContactRelationshipService],
    user: FromDishka[SessionUser],  # Require authentication
) -> None:
    """
    Delete a relationship.

    Removes the relationship from the system.
    """
    # Get existing relationship to verify ownership
    existing_relationship = await relationship_service.get_relationship_by_id(
        relationship_id
    )
    if not existing_relationship:
        raise ContactValidationError(
            "relationship", f"Relationship with ID {relationship_id} not found"
        )

    # Verify the relationship belongs to the specified contact
    if (
        existing_relationship.from_contact_id != contact_id
        and existing_relationship.to_contact_id != contact_id
    ):
        raise ContactValidationError(
            "relationship",
            f"Relationship {relationship_id} does not belong to contact {contact_id}",
        )

    await relationship_service.delete_relationship(
        relationship_id=relationship_id,
    )
