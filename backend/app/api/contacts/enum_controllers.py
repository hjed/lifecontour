"""
Contact enum controllers for providing enum values and display names.

Provides API endpoints for retrieving enum values with their display names
to ensure consistency between frontend and backend.
"""

from core_shared.models.contacts.entities import RelationshipType
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class EnumValue(BaseModel):
    """Enum value with display name."""

    value: str
    display_name: str


class RelationshipTypesResponse(BaseModel):
    """Response containing all relationship types with display names."""

    relationship_types: list[EnumValue]


@router.get("/relationship-types", response_model=RelationshipTypesResponse)
async def get_relationship_types() -> RelationshipTypesResponse:
    """
    Get all available relationship types with their display names.

    Returns:
        RelationshipTypesResponse: List of relationship types with display names
    """
    # Define display names for each relationship type
    display_names = {
        RelationshipType.PARENT: "Parent",
        RelationshipType.CHILD: "Child",
        RelationshipType.SIBLING: "Sibling",
        RelationshipType.PARTNER: "Partner",
        RelationshipType.FRIEND: "Friend",
        RelationshipType.COLLEAGUE: "Colleague",
        RelationshipType.FAMILY: "Family Member",
        RelationshipType.OTHER: "Other",
    }

    relationship_types = [
        EnumValue(value=rel_type.value, display_name=display_names[rel_type])
        for rel_type in RelationshipType
    ]

    return RelationshipTypesResponse(relationship_types=relationship_types)
