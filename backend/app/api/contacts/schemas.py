"""
JSON API compliant schemas for contacts endpoints.

Follows the JSON API specification for request and response formats.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.api.common.schemas import JsonApiLinks, JsonApiMeta
from app.core.contacts.models.entities import MethodType


# Contact method schemas
class ContactMethodAttributes(BaseModel):
    """Contact method attributes."""

    method_type: MethodType
    value: str
    label: str | None = None
    is_primary: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContactMethodData(BaseModel):
    """Contact method data object."""

    type: str = Field(default="contact_method", description="Resource type")
    id: str | None = None
    attributes: ContactMethodAttributes





# Contact address schemas
class ContactAddressAttributes(BaseModel):
    """Contact address attributes."""

    label: str | None = None  # 'home', 'work', 'billing'
    street_line_1: str
    street_line_2: str | None = None
    locality: str | None = None  # city/town
    region: str | None = None  # state/province/region
    postal_code: str | None = None
    country_code: str
    is_primary: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContactAddressData(BaseModel):
    """Contact address data object."""

    type: str = Field(default="contact_address", description="Resource type")
    id: str | None = None
    attributes: ContactAddressAttributes





# Contact note schemas
class ContactNoteAttributes(BaseModel):
    """Contact note attributes."""

    content: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContactNoteData(BaseModel):
    """Contact note data object."""

    type: str = Field(default="contact_note", description="Resource type")
    id: str | None = None
    attributes: ContactNoteAttributes


class ContactNoteRequest(BaseModel):
    """Request to create/update a contact note."""

    data: ContactNoteData


class ContactNoteResponse(BaseModel):
    """Response for a single contact note."""

    data: ContactNoteData
    meta: JsonApiMeta | None = None


# Tag schemas
class TagAttributes(BaseModel):
    """Tag attributes."""

    name: str
    color: str | None = None
    parent_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class TagData(BaseModel):
    """Tag data object."""

    type: str = Field(default="tag", description="Resource type")
    id: str | None = None
    attributes: TagAttributes


class TagResponse(BaseModel):
    """Response for a single tag."""

    data: TagData
    meta: JsonApiMeta | None = None


class TagListResponse(BaseModel):
    """Response for multiple tags."""

    data: list[TagData]
    meta: JsonApiMeta | None = None
    links: JsonApiLinks | None = None


# Contact relationships for requests (can include full data)
class ContactRelationshipsRequest(BaseModel):
    """Contact relationships for create/update requests."""

    methods: list[ContactMethodData] | None = None
    addresses: list[ContactAddressData] | None = None
    notes: list[ContactNoteData] | None = None
    tags: list[TagData] | None = None


# Contact relationships for responses (references only)
class ContactRelationships(BaseModel):
    """Contact relationships for responses."""

    methods: dict[str, Any] | None = None
    addresses: dict[str, Any] | None = None
    notes: dict[str, Any] | None = None
    tags: dict[str, Any] | None = None


# Main contact schemas
class ContactAttributes(BaseModel):
    """Contact attributes."""

    first_name: str
    last_name: str | None = None
    middle_name: str | None = None
    nick_name: str | None = None
    full_name: str | None = None  # Computed field
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ContactDataRequest(BaseModel):
    """Contact data object for requests."""

    type: str = Field(default="contact", description="Resource type")
    id: str | None = None
    attributes: ContactAttributes
    relationships: ContactRelationshipsRequest | None = None


class ContactData(BaseModel):
    """Contact data object for responses."""

    type: str = Field(default="contact", description="Resource type")
    id: str | None = None
    attributes: ContactAttributes
    relationships: ContactRelationships | None = None


class ContactRequest(BaseModel):
    """Request to create/update a contact."""

    data: ContactDataRequest


class ContactResponse(BaseModel):
    """Response for a single contact."""

    data: ContactData
    included: list[ContactMethodData | ContactAddressData | ContactNoteData | TagData] | None = None
    meta: JsonApiMeta | None = None
    links: JsonApiLinks | None = None


class ContactListResponse(BaseModel):
    """Response for multiple contacts."""

    data: list[ContactData]
    included: list[ContactMethodData | ContactAddressData | ContactNoteData | TagData] | None = None
    meta: JsonApiMeta | None = None
    links: JsonApiLinks | None = None


# Tag assignment schemas
class TagAssignmentRequest(BaseModel):
    """Request to assign/remove tags."""

    data: list[TagData]


class TagAssignmentResponse(BaseModel):
    """Response for tag assignment operations."""

    data: list[TagData]
    meta: JsonApiMeta | None = None
