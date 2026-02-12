"""
Journal API schemas for request and response models.

Defines Pydantic models for journal-related API endpoints following
the JSON API specification.
"""

from datetime import date, datetime, time
from typing import Any

from pydantic import BaseModel, Field

from app.api.common.schemas import (
    JsonApiCollectionResponse,
    JsonApiCreateRequest,
    JsonApiLinks,
    JsonApiResponse,
    JsonApiUpdateRequest,
)

# Constants for field descriptions
DISPLAY_ORDER_DESC = "Display order"
BOOKING_REFERENCE_DESC = "Booking reference"
RESOURCE_TYPE_DESC = "Resource type"
RESOURCE_LINKS_DESC = "Resource links"


# Event Date Range Schema
class EventDateRangeSchema(BaseModel):
    """Event date range schema."""

    start: datetime = Field(..., description="Start date and time")
    end: datetime = Field(..., description="End date and time")


# Type-specific data schemas
class CalendarInfoDataSchema(BaseModel):
    """Calendar info data for EVENT type journals."""

    calendar_id: str = Field(..., description="Calendar ID")
    start_time: time | None = Field(
        default=None,
        description="Event start time (time-of-day, null for all-day events)",
    )
    end_time: time | None = Field(
        default=None,
        description="Event end time (time-of-day, null for all-day events)",
    )
    is_all_day: bool = Field(default=False, description="Whether event is all-day")
    location: str | None = Field(default=None, description="Event location")
    sync_invitees: bool = Field(
        default=False, description="Whether to sync invitees with calendar"
    )


class MoodDataSchema(BaseModel):
    """Mood data for MOOD_RATING type journals."""

    mood_value: int | None = Field(
        default=None, description="Mood value (1-10)", ge=1, le=10
    )
    mood_label: str | None = Field(default=None, description="Mood label")
    energy_level: int | None = Field(
        default=None, description="Energy level (1-10)", ge=1, le=10
    )


class PlanDocumentSchema(BaseModel):
    """Plan document schema for PLAN type journals."""

    id: str | None = Field(default=None, description="Document ID (UUID)")
    url: str = Field(..., description="Document URL")
    title: str | None = Field(default=None, description="Document title")
    description: str | None = Field(default=None, description="Document description")
    order: int | None = Field(default=None, description=DISPLAY_ORDER_DESC)


class PlanDataSchema(BaseModel):
    """Plan data for PLAN type journals."""

    documents: list[PlanDocumentSchema] = Field(
        default_factory=list, description="Plan documents"
    )


class TravelFlightSchema(BaseModel):
    """Travel flight schema for TRAVEL type journals."""

    id: str | None = Field(default=None, description="Flight ID (UUID)")
    flight_number: str | None = Field(default=None, description="Flight number")
    airline: str | None = Field(default=None, description="Airline name")
    departure_airport: str | None = Field(default=None, description="Departure airport")
    arrival_airport: str | None = Field(default=None, description="Arrival airport")
    departure_time: datetime | None = Field(default=None, description="Departure time")
    arrival_time: datetime | None = Field(default=None, description="Arrival time")
    booking_reference: str | None = Field(
        default=None, description=BOOKING_REFERENCE_DESC
    )
    confirmation_number: str | None = Field(
        default=None, description="Confirmation number"
    )
    order: int | None = Field(default=None, description=DISPLAY_ORDER_DESC)


class TravelAccommodationSchema(BaseModel):
    """Travel accommodation schema for TRAVEL type journals."""

    id: str | None = Field(default=None, description="Accommodation ID (UUID)")
    name: str = Field(..., description="Accommodation name")
    address: str | None = Field(default=None, description="Accommodation address")
    check_in_date: date | None = Field(default=None, description="Check-in date")
    check_out_date: date | None = Field(default=None, description="Check-out date")
    booking_reference: str | None = Field(
        default=None, description=BOOKING_REFERENCE_DESC
    )
    confirmation_number: str | None = Field(
        default=None, description="Confirmation number"
    )
    order: int | None = Field(default=None, description=DISPLAY_ORDER_DESC)


class TravelTransportationSchema(BaseModel):
    """Travel transportation schema for TRAVEL type journals."""

    id: str | None = Field(default=None, description="Transportation ID (UUID)")
    type: str = Field(..., description="Transportation type (car, train, bus, etc.)")
    details: str | None = Field(default=None, description="Transportation details")
    booking_reference: str | None = Field(
        default=None, description=BOOKING_REFERENCE_DESC
    )
    order: int | None = Field(default=None, description=DISPLAY_ORDER_DESC)


class TravelDataSchema(BaseModel):
    """Travel data for TRAVEL type journals."""

    flights: list[TravelFlightSchema] = Field(
        default_factory=list, description="Travel flights"
    )
    accommodations: list[TravelAccommodationSchema] = Field(
        default_factory=list, description="Travel accommodations"
    )
    transportation: list[TravelTransportationSchema] = Field(
        default_factory=list, description="Travel transportation"
    )


class PhotoAlbumDataSchema(BaseModel):
    """Photo album data for PHOTO_ALBUM type journals."""

    immich_album_id: str | None = Field(
        default=None, description="Immich album identifier"
    )


# Contact relationship schema
class JournalContactRelationshipSchema(BaseModel):
    """Journal contact relationship schema."""

    id: str = Field(..., description="Contact ID")
    name: str | None = Field(default=None, description="Contact name")
    relationship_type: str = Field(
        ..., description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"
    )


# Tag schema
class JournalTagSchema(BaseModel):
    """Journal tag schema."""

    id: str = Field(..., description="Tag ID")
    name: str = Field(..., description="Tag name")
    color: str | None = Field(default=None, description="Tag color (hex code)")


# Tag resource (for standalone tag endpoints)
class JournalTagResource(BaseModel):
    """Journal tag resource following JSON API specification."""

    type: str = Field(default="journal-tags", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Tag ID")
    attributes: dict[str, Any] = Field(..., description="Tag attributes")
    links: JsonApiLinks | None = Field(default=None, description=RESOURCE_LINKS_DESC)


class JournalTagListResponse(JsonApiCollectionResponse[JournalTagResource]):
    """Response model for a list of journal tags."""

    pass


class JournalTagResponse(JsonApiResponse[JournalTagResource]):
    """Response model for a single journal tag."""

    pass


# Journal Tag Creation Schemas
class JournalTagCreateAttributes(BaseModel):
    """Attributes for creating a journal tag."""

    name: str = Field(..., description="Tag name", min_length=1, max_length=100)
    color: str | None = Field(default=None, description="Tag color (hex code)")
    parent_id: str | None = Field(
        default=None, description="Parent tag ID (for hierarchy)"
    )


class JournalTagCreateData(BaseModel):
    """Data for creating a journal tag."""

    type: str = Field(default="journal-tags", description=RESOURCE_TYPE_DESC)
    attributes: JournalTagCreateAttributes = Field(..., description="Tag attributes")


class JournalTagCreateRequest(JsonApiCreateRequest[JournalTagCreateData]):
    """Request model for creating a journal tag."""

    pass


# Calendar schema
class CalendarSchema(BaseModel):
    """Calendar schema for journal responses."""

    id: str = Field(..., description="Calendar ID")
    name: str = Field(..., description="Calendar name")
    color: str | None = Field(default=None, description="Calendar color (hex code)")


# Journal Attributes
class JournalAttributes(BaseModel):
    """Journal attributes."""

    title: str = Field(..., description="Journal title", max_length=500)
    content: str = Field(..., description="Journal content (markdown)")
    event_date_range: EventDateRangeSchema = Field(..., description="Event date range")
    parent_id: int | None = Field(default=None, description="Parent journal ID")
    order: int | None = Field(default=None, description="Order among siblings")
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(
        default=None, description="Last update timestamp"
    )

    # Type information
    types: list[str] = Field(default_factory=list, description="List of journal types")
    type_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific data organized by type (EVENT, MOOD_RATING, etc.)",
    )

    # Embedded relationships
    contacts: list[JournalContactRelationshipSchema] = Field(
        default_factory=list, description="Contact relationships"
    )
    tags: list[JournalTagSchema] = Field(
        default_factory=list, description="Journal tags"
    )
    calendar: CalendarSchema | None = Field(
        default=None, description="Calendar (for EVENT type)"
    )

    # Hierarchy information
    parent: dict[str, Any] | None = Field(
        default=None, description="Parent journal summary"
    )
    children_count: int | None = Field(
        default=None, description="Number of child journals"
    )


class JournalRelationships(BaseModel):
    """Journal relationships to other resources."""

    tags: dict[str, Any] | None = Field(default=None, description="Related tags")
    contacts: dict[str, Any] | None = Field(
        default=None, description="Related contacts"
    )
    calendar: dict[str, Any] | None = Field(
        default=None, description="Related calendar"
    )


class JournalResource(BaseModel):
    """Journal resource following JSON API specification."""

    type: str = Field(default="journals", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Resource identifier")
    attributes: JournalAttributes = Field(..., description="Journal attributes")
    relationships: JournalRelationships | None = Field(
        default=None, description="Journal relationships"
    )
    links: JsonApiLinks | None = Field(default=None, description=RESOURCE_LINKS_DESC)
    meta: dict[str, Any] | None = Field(default=None, description="Resource metadata")


# Request/Response Models
class JournalCreateData(BaseModel):
    """Data for creating a new journal."""

    type: str = Field(default="journals", description=RESOURCE_TYPE_DESC)
    attributes: JournalAttributes = Field(
        ..., description="Journal attributes to create"
    )
    relationships: JournalRelationships | None = Field(
        default=None, description="Journal relationships (optional)"
    )


class JournalUpdateAttributes(BaseModel):
    """Journal attributes for partial updates (all fields optional)."""

    title: str | None = Field(default=None, description="Journal title", max_length=500)
    content: str | None = Field(default=None, description="Journal content (markdown)")
    event_date_range: EventDateRangeSchema | None = Field(
        default=None, description="Event date range"
    )
    parent_id: int | None = Field(default=None, description="Parent journal ID")
    order: int | None = Field(default=None, description="Order among siblings")

    # Type information
    types: list[str] | None = Field(default=None, description="List of journal types")
    type_data: dict[str, Any] | None = Field(
        default=None,
        description="Type-specific data organized by type (EVENT, MOOD_RATING, etc.)",
    )

    # Embedded relationships
    contacts: list[JournalContactRelationshipSchema] | None = Field(
        default=None, description="Contact relationships"
    )
    tags: list[JournalTagSchema] | None = Field(
        default=None, description="Journal tags"
    )


class JournalUpdateData(BaseModel):
    """Data for updating an existing journal."""

    type: str = Field(default="journals", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Journal ID to update")
    attributes: JournalUpdateAttributes = Field(
        ..., description="Journal attributes to update"
    )


class JournalCreateRequest(JsonApiCreateRequest[JournalCreateData]):
    """Request model for creating a journal."""

    pass


class JournalUpdateRequest(JsonApiUpdateRequest[JournalUpdateData]):
    """Request model for updating a journal."""

    pass


class JournalResponse(JsonApiResponse[JournalResource]):
    """Response model for a single journal."""

    pass


class JournalListResponse(JsonApiCollectionResponse[JournalResource]):
    """Response model for a list of journals."""

    pass


# Type Management Schemas
class JournalTypeAddAttributes(BaseModel):
    """Attributes for adding a type to a journal."""

    journal_type: str = Field(
        ..., description="Journal type to add (EVENT, MOOD_RATING, etc.)"
    )
    type_data: dict[str, Any] = Field(
        default_factory=dict, description="Type-specific data"
    )


class JournalTypeAddData(BaseModel):
    """Data for adding a type to a journal."""

    type: str = Field(default="journal-types", description=RESOURCE_TYPE_DESC)
    attributes: JournalTypeAddAttributes = Field(
        ..., description="Type addition attributes"
    )


class JournalTypeAddRequest(JsonApiCreateRequest[JournalTypeAddData]):
    """Request model for adding a type to a journal."""

    pass


class JournalTypeDataUpdateAttributes(BaseModel):
    """Attributes for updating type-specific data."""

    # This will be a flexible dict that accepts any type-specific fields
    # The actual validation happens at the service layer
    pass


class JournalTypeDataUpdateData(BaseModel):
    """Data for updating type-specific data."""

    type: str = Field(default="journal-type-data", description=RESOURCE_TYPE_DESC)
    attributes: dict[str, Any] = Field(..., description="Type-specific data to update")


class JournalTypeDataUpdateRequest(JsonApiUpdateRequest[JournalTypeDataUpdateData]):
    """Request model for updating type-specific data."""

    pass


# Contact Relationship Management Schemas
class JournalContactRelationshipAddAttributes(BaseModel):
    """Attributes for adding a contact relationship to a journal."""

    contact_id: str = Field(..., description="Contact ID")
    relationship_type: str = Field(
        ..., description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"
    )


class JournalContactRelationshipAddData(BaseModel):
    """Data for adding a contact relationship to a journal."""

    type: str = Field(
        default="journal-contact-relationships", description=RESOURCE_TYPE_DESC
    )
    attributes: JournalContactRelationshipAddAttributes = Field(
        ..., description="Relationship attributes"
    )


class JournalContactRelationshipAddRequest(
    JsonApiCreateRequest[JournalContactRelationshipAddData]
):
    """Request model for adding a contact relationship to a journal."""

    pass


# Alias for backward compatibility
JournalContactAddRequest = JournalContactRelationshipAddRequest


# Tag Management Schemas
class JournalTagAddAttributes(BaseModel):
    """Attributes for adding a tag to a journal."""

    tag_id: str = Field(..., description="ID of the tag to add")


class JournalTagAddData(BaseModel):
    """Data model for adding a tag to a journal."""

    type: str = Field(default="journal-tag", description=RESOURCE_TYPE_DESC)
    attributes: JournalTagAddAttributes = Field(
        ..., description="Tag addition attributes"
    )


class JournalTagAddRequest(JsonApiCreateRequest[JournalTagAddData]):
    """Request model for adding a tag to a journal."""

    pass


# Calendar Management Schemas
class CalendarAttributes(BaseModel):
    """Calendar attributes."""

    name: str = Field(..., description="Calendar name")
    description: str | None = Field(default=None, description="Calendar description")
    color: str | None = Field(default=None, description="Calendar color (hex code)")
    is_synced_to_google: bool = Field(
        default=False, description="Whether calendar is synced to Google Calendar"
    )
    google_calendar_id: str | None = Field(
        default=None, description="Google Calendar ID"
    )


class CalendarResource(BaseModel):
    """Calendar resource following JSON API specification."""

    type: str = Field(default="calendars", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Resource identifier")
    attributes: CalendarAttributes = Field(..., description="Calendar attributes")
    links: JsonApiLinks | None = Field(default=None, description=RESOURCE_LINKS_DESC)
    meta: dict[str, Any] | None = Field(default=None, description="Resource metadata")


class CalendarCreateData(BaseModel):
    """Data for creating a new calendar."""

    type: str = Field(default="calendars", description=RESOURCE_TYPE_DESC)
    attributes: CalendarAttributes = Field(
        ..., description="Calendar attributes to create"
    )


class CalendarCreateRequest(JsonApiCreateRequest[CalendarCreateData]):
    """Request model for creating a calendar."""

    pass


class CalendarResponse(JsonApiResponse[CalendarResource]):
    """Response model for a single calendar."""

    pass


class CalendarListResponse(JsonApiCollectionResponse[CalendarResource]):
    """Response model for a list of calendars."""

    pass
