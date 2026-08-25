"""
Contact API schemas for request and response models.

Defines Pydantic models for contact-related API endpoints following
the JSON API specification.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.api.common.schemas import (
    JsonApiCollectionResponse,
    JsonApiCreateRequest,
    JsonApiLinks,
    JsonApiResponse,
    JsonApiUpdateRequest,
)


# Contact Method Schemas (embedded in contact)
class ContactMethodAttributes(BaseModel):
    """Contact method attributes for embedding in contact resource."""

    method_type: str = Field(..., description="Type of contact method (email, phone)")
    value: str = Field(..., description="Contact method value")
    label: str | None = Field(default=None, description="Optional label for the method")
    is_primary: bool = Field(
        default=False, description="Whether this is the primary method of its type"
    )


class ContactMethodResource(BaseModel):
    """Contact method resource for embedding in contact."""

    id: int | None = Field(default=None, description="Method ID (null for new methods)")
    attributes: ContactMethodAttributes = Field(..., description="Method attributes")


# Contact Address Schemas (embedded in contact)
class ContactAddressAttributes(BaseModel):
    """Contact address attributes for embedding in contact resource."""

    label: str | None = Field(
        default=None, description="Optional label for the address"
    )
    street_line_1: str = Field(..., description="First line of street address")
    street_line_2: str | None = Field(
        default=None, description="Second line of street address"
    )
    locality: str | None = Field(default=None, description="City or locality")
    region: str | None = Field(default=None, description="State, province, or region")
    postal_code: str | None = Field(default=None, description="Postal or ZIP code")
    country_code: str = Field(..., description="Two-letter ISO country code")
    is_primary: bool = Field(
        default=False, description="Whether this is the primary address"
    )


class ContactAddressResource(BaseModel):
    """Contact address resource for embedding in contact."""

    id: int | None = Field(
        default=None, description="Address ID (null for new addresses)"
    )
    attributes: ContactAddressAttributes = Field(..., description="Address attributes")


# Contact Note Schemas (embedded in contact)
class ContactNoteAttributes(BaseModel):
    """Contact note attributes for embedding in contact resource."""

    content: str = Field(..., description="Note content")
    created_at: datetime | None = Field(
        default=None, description="Note creation timestamp"
    )
    updated_at: datetime | None = Field(
        default=None, description="Note last update timestamp"
    )


class ContactNoteResource(BaseModel):
    """Contact note resource for embedding in contact."""

    id: int | None = Field(default=None, description="Note ID (null for new notes)")
    attributes: ContactNoteAttributes = Field(..., description="Note attributes")


# Contact Important Date Schemas (embedded in contact)
class ImportantDateAttributes(BaseModel):
    """Important date attributes for embedding in contact resource."""

    date_type: str = Field(..., description="Type of important date")
    precision: str = Field(
        ..., description="Precision of the date (year, day_month, full)"
    )
    year: int | None = Field(default=None, description="Year component")
    month: int | None = Field(default=None, description="Month component")
    day: int | None = Field(default=None, description="Day component")
    custom_date_type_id: int | None = Field(
        default=None, description="ID of global custom date type"
    )
    custom_date_type_name: str | None = Field(
        default=None, description="Read-only name of custom date type"
    )
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(
        default=None, description="Last update timestamp"
    )

    @model_validator(mode="after")
    def validate_precision_components(self) -> ImportantDateAttributes:
        """Validate that the given components match the precision requirements."""
        if self.precision == "full":
            if self.year is None or self.month is None or self.day is None:
                raise ValueError("Full precision requires year, month, and day")
        elif self.precision == "day_month":
            if self.month is None or self.day is None:
                raise ValueError("Day/Month precision requires month and day")
            if self.year is not None:
                raise ValueError("Day/Month precision does not allow year")
        elif self.precision == "year":
            if self.year is None:
                raise ValueError("Year precision requires year")
            if self.month is not None or self.day is not None:
                raise ValueError("Year precision does not allow month or day")
        else:
            raise ValueError(
                "Unsupported precision; expected one of: year, day_month, full"
            )

        if self.date_type == "custom" and self.custom_date_type_id is None:
            raise ValueError("custom_date_type_id is required for custom date types")
        elif self.date_type != "custom" and self.custom_date_type_id is not None:
            raise ValueError(
                "custom_date_type_id must not be provided for non-custom date types"
            )

        if self.month is not None and not (1 <= self.month <= 12):
            raise ValueError("Month must be between 1 and 12")
        if self.day is not None and not (1 <= self.day <= 31):
            raise ValueError("Day must be between 1 and 31")

        return self


class ImportantDateResource(BaseModel):
    """Important date resource for embedding in contact."""

    id: int | None = Field(default=None, description="Date ID (null for new dates)")
    attributes: ImportantDateAttributes = Field(..., description="Date attributes")


# Tag Schemas (for relationships)
class TagAttributes(BaseModel):
    """Tag attributes."""

    name: str = Field(..., description="Tag name")
    color: str | None = Field(default=None, description="Tag color (hex code)")
    description: str | None = Field(default=None, description="Tag description")
    parent_id: int | None = Field(
        default=None, description="Parent tag ID for hierarchical tags"
    )


class TagResource(BaseModel):
    """Tag resource following JSON API specification."""

    type: str = Field(default="tags", description="Resource type")
    id: str = Field(..., description="Resource identifier")
    attributes: TagAttributes = Field(..., description="Tag attributes")
    links: JsonApiLinks | None = Field(default=None, description="Resource links")
    meta: dict[str, Any] | None = Field(default=None, description="Resource metadata")


# Contact Relationship Schemas
class ContactRelationshipAttributes(BaseModel):
    """Contact relationship attributes for create/update requests."""

    relationship_type: str = Field(..., description="Type of relationship")
    from_contact_id: int = Field(
        ..., description="ID of the contact initiating the relationship"
    )
    to_contact_id: int | None = Field(
        default=None,
        description="ID of the contact receiving the relationship (required when to_user is False)",
    )
    to_user: bool = Field(
        default=False,
        description="Whether this relationship targets the user (if True, to_contact_id must be None)",
    )
    created_at: datetime | None = Field(
        default=None, description="Relationship creation timestamp"
    )
    updated_at: datetime | None = Field(
        default=None, description="Relationship last update timestamp"
    )


class ContactRelationshipResponseAttributes(ContactRelationshipAttributes):
    """Contact relationship attributes for API responses.

    Extends the base attributes with server-derived fields that are
    not client-writable.
    """

    to_contact_name: str | None = Field(
        default=None,
        description="Display name of the related contact (server-derived, read-only)",
    )


class ContactRelationshipResource(BaseModel):
    """Contact relationship resource following JSON API specification."""

    type: str = Field(default="contact_relationships", description="Resource type")
    id: str = Field(..., description="Resource identifier")
    attributes: ContactRelationshipResponseAttributes = Field(
        ..., description="Relationship attributes"
    )
    links: JsonApiLinks | None = Field(default=None, description="Resource links")
    meta: dict[str, Any] | None = Field(default=None, description="Resource metadata")


# Contact Summary Schemas (embedded in contact)
class ContactSummaryAttributes(BaseModel):
    """Contact summary attributes for AI-generated interaction summaries."""

    summary_text: str | None = Field(
        default=None, description="AI-generated summary text"
    )
    follow_up_suggestions: list[str] = Field(
        default_factory=list, description="List of follow-up suggestions"
    )
    status: str = Field(
        ...,
        description="Summary status (pending, generating, generated, failed, disabled)",
    )
    is_disabled: bool = Field(
        default=False, description="Whether AI generation is disabled for this contact"
    )
    is_user_override: bool = Field(
        default=False, description="Whether user has provided a manual override"
    )
    user_override_text: str | None = Field(
        default=None, description="User-provided override text"
    )
    generated_at: datetime | None = Field(
        default=None, description="When the summary was last generated"
    )


class ContactSummaryResource(BaseModel):
    """Contact summary resource for embedding in contact."""

    type: str = Field(default="contact_summaries", description="Resource type")
    id: str = Field(..., description="Summary ID")
    attributes: ContactSummaryAttributes = Field(..., description="Summary attributes")


class ContactSummaryUpdateData(BaseModel):
    """Data for updating a contact summary (disable/override)."""

    is_disabled: bool | None = Field(
        default=None, description="Set to disable/enable AI generation"
    )
    user_override_text: str | None = Field(
        default=None,
        max_length=10000,
        description="User override text (set to null to clear)",
    )


class ContactSummaryUpdateRequest(BaseModel):
    """Request model for updating a contact summary."""

    data: ContactSummaryUpdateData = Field(..., description="Summary update data")


# Contact Schemas
class ContactAttributes(BaseModel):
    """Contact attributes."""

    first_name: str = Field(..., description="Contact first name")
    last_name: str | None = Field(default=None, description="Contact last name")
    middle_name: str | None = Field(default=None, description="Contact middle name")
    nick_name: str | None = Field(default=None, description="Contact nickname")
    company: str | None = Field(
        default=None, max_length=200, description="Company or organization name"
    )
    job_title: str | None = Field(
        default=None, max_length=200, description="Job title or position"
    )
    is_favourite: bool = Field(
        default=False, description="Whether contact is marked as favourite"
    )
    photo_url: str | None = Field(
        default=None, description="URL for contact avatar photo proxy"
    )
    created_at: datetime | None = Field(
        default=None, description="Contact creation timestamp"
    )
    updated_at: datetime | None = Field(
        default=None, description="Contact last update timestamp"
    )

    # Embedded related data (not separate resources for REST API)
    contact_methods: list[ContactMethodResource] = Field(
        default_factory=list, description="Contact methods"
    )
    addresses: list[ContactAddressResource] = Field(
        default_factory=list, description="Contact addresses"
    )
    notes: list[ContactNoteResource] = Field(
        default_factory=list, description="Contact notes"
    )
    relationships: list[ContactRelationshipResource] = Field(
        default_factory=list, description="Contact relationships"
    )
    important_dates: list[ImportantDateResource] = Field(
        default_factory=list, description="Contact important dates"
    )
    summary: ContactSummaryResource | None = Field(
        default=None, description="AI-generated interaction summary"
    )


class ContactRelationships(BaseModel):
    """Contact relationships to other resources."""

    tags: dict[str, Any] | None = Field(default=None, description="Related tags")


class ContactResource(BaseModel):
    """Contact resource following JSON API specification."""

    type: str = Field(default="contacts", description="Resource type")
    id: str = Field(..., description="Resource identifier")
    attributes: ContactAttributes = Field(..., description="Contact attributes")
    relationships: ContactRelationships | None = Field(
        default=None, description="Contact relationships"
    )
    links: JsonApiLinks | None = Field(default=None, description="Resource links")
    meta: dict[str, Any] | None = Field(default=None, description="Resource metadata")


# Request/Response Models
class ContactCreateData(BaseModel):
    """Data for creating a new contact."""

    type: str = Field(default="contacts", description="Resource type")
    attributes: ContactAttributes = Field(
        ..., description="Contact attributes to create"
    )


class ContactUpdateData(BaseModel):
    """Data for updating an existing contact."""

    type: str = Field(default="contacts", description="Resource type")
    id: str = Field(..., description="Contact ID to update")
    attributes: ContactAttributes = Field(
        ..., description="Contact attributes to update"
    )


class ContactCreateRequest(JsonApiCreateRequest[ContactCreateData]):
    """Request model for creating a contact."""

    pass


class ContactUpdateRequest(JsonApiUpdateRequest[ContactUpdateData]):
    """Request model for updating a contact."""

    pass


class ContactResponse(JsonApiResponse[ContactResource]):
    """Response model for a single contact."""

    pass


class ContactListResponse(JsonApiCollectionResponse[ContactResource]):
    """Response model for a list of contacts."""

    pass


# Contact Merge Request Models (ITER13-001 Phase 3; overrides ITER13-002 Phase 1)
class MergeContactOverrides(BaseModel):
    """Explicit per-field conflict resolution for a contact merge.

    Each field is the concrete value to apply to the surviving contact (the
    caller has already resolved the survivor / source / custom choice). Omitted
    fields fall back to the default policy (survivor wins, prefer non-empty).
    Mirrors the journal ``MergeOverrides`` schema.
    """

    first_name: str | None = Field(default=None, description="Explicit first name")
    last_name: str | None = Field(default=None, description="Explicit last name")
    middle_name: str | None = Field(default=None, description="Explicit middle name")
    nick_name: str | None = Field(default=None, description="Explicit nickname")
    company: str | None = Field(default=None, description="Explicit company")
    job_title: str | None = Field(default=None, description="Explicit job title")
    photo_url: str | None = Field(default=None, description="Explicit photo URL")
    is_favourite: bool | None = Field(
        default=None, description="Explicit favourite flag"
    )


class MergeContactAttributes(BaseModel):
    """Attributes for merging a contact (survivor-wins by default; per-field overrides)."""

    source_contact_id: int = Field(
        ...,
        description="ID of the contact to absorb into this one (it will be deleted)",
    )
    overrides: MergeContactOverrides | None = Field(
        default=None,
        description="Explicit per-field conflict resolution overrides",
    )


class MergeContactData(BaseModel):
    """Data for merging a contact."""

    type: str = Field(default="contact-merge", description="Resource type")
    attributes: MergeContactAttributes = Field(..., description="Merge attributes")


class MergeContactRequest(JsonApiCreateRequest[MergeContactData]):
    """Request model for merging contacts."""

    pass


# Contact Relationship Request/Response Models
class ContactRelationshipCreateData(BaseModel):
    """Data for creating a new contact relationship."""

    type: str = Field(default="contact_relationships", description="Resource type")
    attributes: ContactRelationshipAttributes = Field(
        ..., description="Relationship attributes to create"
    )


class ContactRelationshipUpdateData(BaseModel):
    """Data for updating an existing contact relationship."""

    type: str = Field(default="contact_relationships", description="Resource type")
    id: str = Field(..., description="Relationship ID to update")
    attributes: ContactRelationshipAttributes = Field(
        ..., description="Relationship attributes to update"
    )


class ContactRelationshipCreateRequest(
    JsonApiCreateRequest[ContactRelationshipCreateData]
):
    """Request model for creating a contact relationship."""

    pass


class ContactRelationshipUpdateRequest(
    JsonApiUpdateRequest[ContactRelationshipUpdateData]
):
    """Request model for updating a contact relationship."""

    pass


class ContactRelationshipResponse(JsonApiResponse[ContactRelationshipResource]):
    """Response model for a single contact relationship."""

    pass


class ContactRelationshipListResponse(
    JsonApiCollectionResponse[ContactRelationshipResource]
):
    """Response model for a list of contact relationships."""

    pass


# Tag Assignment Schemas
class TagAssignmentData(BaseModel):
    """Data for assigning a tag to a contact."""

    type: str = Field(default="tags", description="Resource type")
    id: str = Field(..., description="Tag ID to assign")


class TagAssignmentRequest(BaseModel):
    """Request model for assigning a tag to a contact."""

    data: TagAssignmentData = Field(..., description="Tag assignment data")


class TagListResponse(JsonApiCollectionResponse[TagResource]):
    """Response model for a list of tags."""

    pass


# Field Update Schemas
class FieldUpdateData(BaseModel):
    """Data for updating a single contact field."""

    type: str = Field(default="contact_fields", description="Resource type")
    attributes: dict[str, Any] = Field(..., description="Field update attributes")


class FieldUpdateRequest(BaseModel):
    """Request model for updating a single contact field."""

    data: FieldUpdateData = Field(..., description="Field update data")


class ContactFieldAttributes(BaseModel):
    """Attributes for a contact field response."""

    field_name: str = Field(..., description="Name of the updated field")
    field_type: str = Field(
        ..., description="Type of field (basic, method, address, note)"
    )
    entity_id: int | None = Field(
        default=None,
        description="ID of the related entity (for methods, addresses, notes)",
    )
    old_value: str | None = Field(default=None, description="Previous field value")
    new_value: str | None = Field(default=None, description="New field value")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC),
        description="Timestamp of the update",
    )


class ContactFieldResource(BaseModel):
    """Resource model for a contact field update."""

    type: str = Field(default="contact_fields", description="Resource type")
    id: str = Field(..., description="Field identifier")
    attributes: ContactFieldAttributes = Field(..., description="Field attributes")


class ContactFieldResponse(JsonApiResponse[ContactFieldResource]):
    """Response model for a single field update."""

    pass


# Method Field Update Schemas
class MethodFieldUpdateData(BaseModel):
    """Data for updating a contact method field."""

    type: str = Field(default="contact_method_fields", description="Resource type")
    attributes: dict[str, Any] = Field(
        ..., description="Method field update attributes"
    )


class MethodFieldUpdateRequest(BaseModel):
    """Request model for updating a contact method field."""

    data: MethodFieldUpdateData = Field(..., description="Method field update data")


# Address Field Update Schemas
class AddressFieldUpdateData(BaseModel):
    """Data for updating a contact address field."""

    type: str = Field(default="contact_address_fields", description="Resource type")
    attributes: dict[str, Any] = Field(
        ..., description="Address field update attributes"
    )


class AddressFieldUpdateRequest(BaseModel):
    """Request model for updating a contact address field."""

    data: AddressFieldUpdateData = Field(..., description="Address field update data")


# Note Field Update Schemas
class NoteFieldUpdateData(BaseModel):
    """Data for updating a contact note field."""

    type: str = Field(default="contact_note_fields", description="Resource type")
    attributes: dict[str, Any] = Field(..., description="Note field update attributes")


class NoteFieldUpdateRequest(BaseModel):
    """Request model for updating a contact note field."""

    data: NoteFieldUpdateData = Field(..., description="Note field update data")


# Contact History Schemas
class ContactHistoryAttributes(BaseModel):
    """Attributes for a contact history entry."""

    entity_type: str = Field(..., description="Type of entity that was changed")
    entity_id: int = Field(..., description="ID of the entity that was changed")
    field_name: str = Field(..., description="Name of the field that was changed")
    old_value: str | None = Field(
        default=None, description="Previous value of the field"
    )
    new_value: str | None = Field(default=None, description="New value of the field")
    changed_by: str | None = Field(
        default=None, description="User or system that made the change"
    )
    source: str = Field(default="system", description="Provenance source of the change")
    created_at: datetime | None = Field(
        default=None, description="Timestamp when the change was recorded"
    )
    entity_label: str | None = Field(
        default=None,
        description=(
            "The name of the entity this entry is about, when the entry's own "
            "values do not carry it. Populated for the task rows a linked task "
            "puts on this feed — both of their values are this contact's id, "
            "and a task has no route of its own to link to. Null for every row "
            "that names itself, and for a task whose history has not been "
            "projected yet."
        ),
    )


class ContactHistoryResource(BaseModel):
    """JSON API resource for a contact history entry."""

    type: str = Field(default="contact_history", description="Resource type")
    id: str = Field(..., description="History entry ID")
    attributes: ContactHistoryAttributes = Field(
        ..., description="History entry attributes"
    )


class ContactHistoryListResponse(BaseModel):
    """JSON API list response for contact history."""

    data: list[ContactHistoryResource] = Field(
        ..., description="List of history entries"
    )
    meta: Any = Field(default=None, description="Response metadata")
    links: Any = Field(default=None, description="Response links")


# Contact Method Add/Delete Schemas
class ContactMethodCreateData(BaseModel):
    """Data for creating a new contact method."""

    type: str = Field(default="contact_methods", description="Resource type")
    attributes: ContactMethodAttributes = Field(
        ..., description="Method attributes to create"
    )


class ContactMethodCreateRequest(BaseModel):
    """Request model for creating a contact method."""

    data: ContactMethodCreateData = Field(..., description="Method creation data")


# Contact Address Add/Delete Schemas
class ContactAddressCreateData(BaseModel):
    """Data for creating a new contact address."""

    type: str = Field(default="contact_addresses", description="Resource type")
    attributes: ContactAddressAttributes = Field(
        ..., description="Address attributes to create"
    )


class ContactAddressCreateRequest(BaseModel):
    """Request model for creating a contact address."""

    data: ContactAddressCreateData = Field(..., description="Address creation data")


# Contact Important Date Add/Delete Schemas
class ImportantDateCreateData(BaseModel):
    """Data for creating a new important date."""

    type: str = Field(default="contact_important_dates", description="Resource type")
    attributes: ImportantDateAttributes = Field(
        ..., description="Date attributes to create"
    )


class ImportantDateCreateRequest(BaseModel):
    """Request model for creating an important date."""

    data: ImportantDateCreateData = Field(..., description="Date creation data")


# Custom Date Type Schemas
class CustomDateTypeAttributes(BaseModel):
    """Attributes for custom date type."""

    name: str = Field(..., description="Name of custom date type")
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(
        default=None, description="Last update timestamp"
    )


class CustomDateTypeResource(BaseModel):
    """Resource model for custom date type."""

    type: str = Field(default="custom_date_types", description="Resource type")
    id: str = Field(..., description="Resource ID")
    attributes: CustomDateTypeAttributes = Field(..., description="Attributes")
    links: JsonApiLinks | None = Field(default=None, description="Resource links")
    meta: dict[str, Any] | None = Field(default=None, description="Metadata")


class CustomDateTypeListResponse(JsonApiCollectionResponse[CustomDateTypeResource]):
    """Response model for a list of custom date types."""

    pass


class CustomDateTypeResponse(JsonApiResponse[CustomDateTypeResource]):
    """Response model for a custom date type."""

    pass


class CustomDateTypeCreateData(BaseModel):
    """Data for creating custom date type."""

    type: str = Field(default="custom_date_types", description="Resource type")
    attributes: CustomDateTypeAttributes = Field(..., description="Attributes")


class CustomDateTypeCreateRequest(JsonApiCreateRequest[CustomDateTypeCreateData]):
    """Request model for creating a custom date type."""

    pass
