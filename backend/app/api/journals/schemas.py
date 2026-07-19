"""
Journal API schemas for request and response models.

Defines Pydantic models for journal-related API endpoints following
the JSON API specification.
"""

from datetime import date, datetime, time
from typing import Any

from core_shared.models.journals import IncompletenessReason, OutdoorActivitySubtype
from pydantic import BaseModel, Field, StrictStr, model_validator

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
CALENDAR_NAME_DESC = "Calendar name"
CALENDAR_COLOR_DESC = "Calendar color (hex code)"
JOURNAL_TITLE_DESC = "Journal title"
RESOURCE_ID_DESC = "Resource identifier"
REVIEW_REASON_DESC = (
    "Review reason (external_link_match, duplicate_journal, needs_review)"
)
MATCH_CONFIDENCE_DESC = "Match confidence (0.0-1.0)"


# Event Date Range Schema
class EventDateRangeSchema(BaseModel):
    """Event date range schema."""

    start: datetime = Field(..., description="Start date and time")
    end: datetime = Field(..., description="End date and time")


# Type-specific data schemas
class CalendarInfoDataSchema(BaseModel):
    """Calendar info data for EVENT type journals."""

    calendar_id: str = Field(..., description="Calendar ID")
    description: str | None = Field(
        default=None,
        description="Event description separate from private note",
    )
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
    timezone: str | None = Field(
        default=None,
        description="IANA timezone string (e.g. 'Australia/Sydney')",
    )
    sync_invitees: bool = Field(
        default=False, description="Whether to sync invitees with calendar"
    )
    private_description: bool = Field(
        default=False,
        description="When true, description is kept private and not synced to external calendars",
    )
    event_state: str | None = Field(
        default=None,
        description="Event participation state (invited, tentative, confirmed, cancelled)",
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
    """Photo album data for PHOTO_ALBUM type journals.

    Sourced from the Immich album sync metadata and external reference rather
    than a dedicated data table. Read-only — albums are managed by sync.
    """

    immich_album_id: str | None = Field(
        default=None, description="Immich album identifier (UUID)"
    )
    album_name: str | None = Field(default=None, description="Immich album name")
    album_url: str | None = Field(
        default=None, description="Link to the album in the Immich web UI"
    )
    asset_count: int | None = Field(
        default=None, description="Number of photos in the album"
    )
    cover_url: str | None = Field(
        default=None,
        description=(
            "Backend proxy URL for the album cover photo (served on-demand, "
            "not persisted); null when the album has no cover"
        ),
    )


class FitnessDataSchema(BaseModel):
    """Fitness data for FITNESS type journals."""

    heart_rate_avg: int | None = Field(
        default=None, description="Average heart rate (bpm)", ge=0
    )
    heart_rate_max: int | None = Field(
        default=None, description="Maximum heart rate (bpm)", ge=0
    )
    distance: int | None = Field(default=None, description="Distance (meters)", ge=0)
    elevation_gain: int | None = Field(
        default=None, description="Elevation gain (meters)", ge=0
    )
    elevation_loss: int | None = Field(
        default=None, description="Elevation loss (meters)", ge=0
    )
    duration: int | None = Field(default=None, description="Duration (seconds)", ge=0)
    calories: int | None = Field(default=None, description="Calories burned", ge=0)
    strava_activity_id: str | None = Field(
        default=None,
        description="Strava activity ID (external reference)",
        max_length=255,
    )


class OutdoorActivityDataSchema(BaseModel):
    """Outdoor activity data for OUTDOOR_ACTIVITY type journals."""

    weather_conditions: str | None = Field(
        default=None,
        description="Description of weather conditions during the activity",
        max_length=200,
    )
    role: str | None = Field(
        default=None,
        description="Participant's role in the activity",
        max_length=100,
    )
    in_leadership_role: bool | None = Field(
        default=None,
        description="Whether the participant was in a leadership role",
    )
    participant_notes: str | None = Field(
        default=None,
        description="Notes about other participants",
        max_length=2000,
    )


class BushwalkingDataSchema(BaseModel):
    """Bushwalking data for BUSHWALKING type journals."""

    track_grading: str | None = Field(
        default=None,
        description="Australian Track Grading System grade (Grade 1-5)",
    )


class JoggingDataSchema(BaseModel):
    """Jogging data for JOGGING type journals."""

    pace: int | None = Field(
        default=None,
        description="Pace in seconds per kilometre (non-negative)",
        ge=0,
    )


class AbseilPitchSchema(BaseModel):
    """Abseil pitch data schema."""

    id: int | None = Field(default=None, description="Pitch ID")
    pitch_number: int = Field(..., description="Sequence/problem number for ordering")
    height: int | None = Field(
        default=None, description="Drop height of this pitch in metres"
    )
    anchor_location: str | None = Field(
        default=None, description="TR (top right), TL (top left), Centre"
    )
    anchor_type: str | None = Field(default=None, description="Type of anchor used")
    did_rescue: bool | None = Field(
        default=None, description="Whether a rescue was performed"
    )
    did_setup: bool | None = Field(
        default=None, description="Whether the user set up the anchor"
    )
    notes: str | None = Field(
        default=None, description="Optional short notes for the pitch"
    )
    pitch_type: str | None = Field(
        default=None,
        description=(
            "How the pitch is descended: abseil, jump, or down_climb "
            "(null is treated as abseil)"
        ),
    )


class AbseilingDataSchema(BaseModel):
    """Abseiling data for ABSEILING_TRIP type journals."""

    template_id: str | None = Field(
        default=None,
        description=(
            "ID of the activity template this abseiling-derived journal was created "
            "from (consolidated reference, preserved when pitches are edited)"
        ),
    )
    number_of_abseils: int | None = Field(
        default=None,
        description="Number of abseils (non-negative)",
        ge=0,
    )
    total_length: int | None = Field(
        default=None,
        description="Total length in metres (non-negative)",
        ge=0,
    )
    number_of_setups: int | None = Field(
        default=None,
        description="Number of pitches the user set up (non-negative)",
        ge=0,
    )
    number_of_rescues: int | None = Field(
        default=None,
        description="Number of pitches where the user performed a rescue (non-negative)",
        ge=0,
    )
    pitches: list[AbseilPitchSchema] = Field(
        default_factory=list, description="Abseil pitches"
    )


class CanyoningDataSchema(BaseModel):
    """Canyoning data for CANYONING type journals."""

    french_grade: str | None = Field(
        default=None,
        description="French canyoning grade (e.g. v3a2IV**)",
    )
    water_guage_name: str | None = Field(
        default=None,
        description="Name of the water gauge",
    )
    water_guage_level: int | None = Field(
        default=None,
        description="Water gauge level reading",
    )
    is_vertical: bool | None = Field(
        default=None,
        description="Whether the canyon is primarily vertical",
    )
    is_night_canyon: bool | None = Field(
        default=None,
        description="Whether the activity was a night canyon",
    )
    is_white_water: bool | None = Field(
        default=None,
        description="Whether the activity involved white water",
    )


class CavingDataSchema(BaseModel):
    """Caving data for CAVING type journals."""

    is_vertical: bool | None = Field(
        default=None,
        description="Whether the cave is primarily vertical (requires ropes)",
    )
    is_horizontal: bool | None = Field(
        default=None,
        description="Whether the cave is primarily horizontal",
    )


class CanoeingDataSchema(BaseModel):
    """Canoeing data for CANOEING type journals."""

    water_type: str | None = Field(
        default=None,
        description="Type of water body (e.g. river, lake, sea)",
    )


class SnorkellingDataSchema(BaseModel):
    """Snorkelling data for SNORKELLING type journals."""

    pass


class DivingDataSchema(BaseModel):
    """Diving data for DIVING type journals."""

    pass


class DownhillSkiingDataSchema(BaseModel):
    """Downhill skiing data for DOWNHILL_SKIING type journals."""

    pass


class ClimbingDataSchema(BaseModel):
    """Climbing data for CLIMBING type journals."""

    climbing_type: str | None = Field(
        default=None,
        description="Type of climbing (sport, trad, bouldering, top_rope)",
    )
    grade: int | None = Field(
        default=None,
        description="Climb grade (non-negative)",
        ge=0,
    )
    length: int | None = Field(
        default=None,
        description="Climb length in metres (non-negative)",
        ge=0,
    )
    indoor: bool = Field(
        default=False,
        description="Whether the climb was indoors (independent of climbing_type)",
    )


class OutdoorPlanningDataSchema(BaseModel):
    """Outdoor planning data for OUTDOOR_PLANNING type journals."""

    topics: str | None = Field(
        default=None,
        description="Description of the topics discussed",
    )
    activity_types: list[StrictStr] | None = Field(
        default=None,
        description="List of related outdoor activity subtypes",
    )


class OutdoorTrainingDataSchema(BaseModel):
    """Outdoor training data for OUTDOOR_TRAINING type journals."""

    focus_areas: list[StrictStr] | None = Field(
        default=None,
        description="List of related outdoor activity subtypes or free-text areas",
    )


class GearMaintenanceDataSchema(BaseModel):
    """Gear maintenance data for GEAR_MAINTENANCE type journals."""

    gear_item_id: str = Field(
        ...,
        description="UUID of the gear item being maintained",
    )
    maintenance_type: str = Field(
        ...,
        description="Type of maintenance performed (e.g. routine inspection, retiring gear)",
    )
    activity_types: list[StrictStr] | None = Field(
        default=None,
        description="List of related outdoor activity subtypes",
    )
    retirement_reason: str | None = Field(
        default=None,
        description="Reason for retirement (required if maintenance_type is 'retiring gear')",
    )


class GearUsageDataSchema(BaseModel):
    """Gear usage data for GEAR_USAGE type journals."""

    gear_item_id: str = Field(
        ...,
        description="UUID of the gear item being used",
    )
    checkout_date: datetime | None = Field(
        default=None,
        description="Optional checkout buffer date",
    )
    checkin_date: datetime | None = Field(
        default=None,
        description="Optional checkin buffer date",
    )


class KayakingDataSchema(BaseModel):
    """Kayaking data for KAYAKING type journals."""

    water_type: str | None = Field(
        default=None,
        description="Type of water (e.g. river, lake, sea)",
    )
    is_white_water: bool | None = Field(
        default=None,
        description="Whether this is a white water kayaking session",
    )
    rapids_grade: str | None = Field(
        default=None,
        description="International Scale of River Difficulty (I–VI)",
    )


class CrossCountrySkiingDataSchema(BaseModel):
    """Cross-country skiing data for CROSS_COUNTRY_SKIING type journals."""

    snow_conditions: str | None = Field(
        default=None,
        description="Description of snow conditions",
    )


# Contact relationship schema
class JournalContactRelationshipSchema(BaseModel):
    """Journal contact relationship schema."""

    id: str = Field(..., description="Contact ID")
    name: str | None = Field(default=None, description="Contact name")
    relationship_type: str = Field(
        ..., description="Relationship type (PARTICIPANT, INVITEE, MENTION, ABOUT)"
    )
    status: str | None = Field(
        default=None, description="Attendee status (ATTENDING, MAYBE, etc.)"
    )
    role: str | None = Field(
        default=None, description="Event role (ORGANISER, FACILITATOR_HELPER, etc.)"
    )
    first_name: str | None = Field(default=None, description="Contact first name")
    last_name: str | None = Field(default=None, description="Contact last name")
    photo_url: str | None = Field(
        default=None, description="URL for contact avatar photo proxy"
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
    description: str | None = Field(default=None, description="Tag description")
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


# Journal Tag Update Schemas
class JournalTagUpdateAttributes(BaseModel):
    """Attributes for updating a journal tag.

    Every field is optional so a PATCH can change one attribute in isolation.
    An explicit null is rejected for the string fields (there is no way to
    "unset" a name or colour), while an explicit null ``parent_id`` is the
    wire signal for moving the tag back to the root.
    """

    name: str | None = Field(
        default=None, description="Tag name", min_length=1, max_length=100
    )
    color: str | None = Field(default=None, description="Tag color (hex code)")
    description: str | None = Field(default=None, description="Tag description")
    parent_id: str | None = Field(
        default=None,
        description=(
            "Parent tag ID (for hierarchy). Provide an explicit null to move "
            "the tag to the root."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def validate_non_nulls(cls, data: Any) -> Any:
        """Reject explicit nulls for fields that cannot be cleared."""
        if isinstance(data, dict):
            for field in ("name", "color", "description"):
                if field in data and data[field] is None:
                    raise ValueError(f"Explicit null is not allowed for '{field}'")
        return data


class JournalTagUpdateData(BaseModel):
    """Data for updating a journal tag."""

    type: str = Field(default="journal-tags", description=RESOURCE_TYPE_DESC)
    id: str | None = Field(default=None, description="Tag ID")
    attributes: JournalTagUpdateAttributes = Field(
        ..., description="Tag attributes to update"
    )


class JournalTagUpdateRequest(BaseModel):
    """Request model for updating a journal tag."""

    data: JournalTagUpdateData = Field(..., description="Tag update data")


class JournalTagMergeAttributes(BaseModel):
    """Attributes for merging a journal tag into another."""

    target_tag_id: str = Field(
        ..., description="ID of the target tag to merge into (the survivor)"
    )


class JournalTagMergeData(BaseModel):
    """Data for merging a journal tag."""

    type: str = Field(default="journal-tags", description=RESOURCE_TYPE_DESC)
    attributes: JournalTagMergeAttributes = Field(..., description="Merge attributes")


class JournalTagMergeRequest(BaseModel):
    """Request model for merging a journal tag.

    The source tag is the path parameter, so the body carries only the target.
    """

    data: JournalTagMergeData = Field(..., description="Tag merge data")


# Journal Series Schemas
class JournalSeriesResource(BaseModel):
    """Journal series resource following JSON API specification."""

    type: str = Field(default="journal-series", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Series ID")
    attributes: dict[str, Any] = Field(..., description="Series attributes")
    links: JsonApiLinks | None = Field(default=None, description=RESOURCE_LINKS_DESC)


class JournalSeriesListResponse(JsonApiCollectionResponse[JournalSeriesResource]):
    """Response model for a list of journal series."""

    pass


class JournalSeriesResponse(JsonApiResponse[JournalSeriesResource]):
    """Response model for a single journal series."""

    pass


class JournalSeriesWriteAttributes(BaseModel):
    """Attributes for creating or updating a journal series."""

    name: str = Field(..., description="Series name", min_length=1, max_length=500)
    description: str | None = Field(default=None, description="Series description")


class JournalSeriesCreateData(BaseModel):
    """Data for creating a journal series."""

    type: str = Field(default="journal-series", description=RESOURCE_TYPE_DESC)
    attributes: JournalSeriesWriteAttributes = Field(
        ..., description="Series attributes"
    )


class JournalSeriesCreateRequest(JsonApiCreateRequest[JournalSeriesCreateData]):
    """Request model for creating a journal series."""

    pass


class JournalSeriesUpdateData(BaseModel):
    """Data for updating a journal series."""

    type: str = Field(default="journal-series", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Series ID")
    attributes: JournalSeriesWriteAttributes = Field(
        ..., description="Series attributes"
    )


class JournalSeriesUpdateRequest(BaseModel):
    """Request model for updating a journal series."""

    data: JournalSeriesUpdateData = Field(..., description="Series update data")


class JournalSeriesRelationshipData(BaseModel):
    """Identifier payload linking a journal to a series."""

    type: str = Field(default="journal-series", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Series ID")


class JournalSeriesRelationshipRequest(BaseModel):
    """Request model for adding a journal to a series."""

    data: JournalSeriesRelationshipData = Field(
        ..., description="Series relationship identifier"
    )


# Calendar schema
class CalendarSchema(BaseModel):
    """Calendar schema for journal responses."""

    id: str = Field(..., description="Calendar ID")
    name: str = Field(..., description=CALENDAR_NAME_DESC)
    color: str | None = Field(default=None, description=CALENDAR_COLOR_DESC)


# Journal Attributes
class JournalAttributes(BaseModel):
    """Journal attributes."""

    title: str = Field(..., description=JOURNAL_TITLE_DESC, max_length=500)
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
    series: list[dict[str, str]] = Field(
        default_factory=list,
        description="Series memberships as {id, name} refs",
    )
    calendar: CalendarSchema | None = Field(
        default=None, description="Calendar (for EVENT type)"
    )

    # Hierarchy information
    parent: dict[str, Any] | None = Field(
        default=None, description="Parent journal summary"
    )
    children: list[dict[str, Any]] | None = Field(
        default=None, description="List of child journal summaries"
    )
    children_count: int | None = Field(
        default=None, description="Number of child journals"
    )
    depth: int | None = Field(
        default=None, description="Depth in hierarchy (1=root, 2=first-level child)"
    )

    # Review indicators
    has_pending_reviews: bool = Field(
        default=False, description="Whether this journal has pending review items"
    )
    review_items: list[dict[str, Any]] | None = Field(
        default=None,
        description="Pending review suggestions (only populated on detail view)",
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
    routes: dict[str, Any] | None = Field(default=None, description="Related routes")


class JournalResource(BaseModel):
    """Journal resource following JSON API specification."""

    type: str = Field(default="journals", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description=RESOURCE_ID_DESC)
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

    title: str | None = Field(
        default=None, description=JOURNAL_TITLE_DESC, max_length=500
    )
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
    status: str | None = Field(
        default=None, description="Attendee status (ATTENDING, MAYBE, etc.)"
    )
    role: str | None = Field(
        default=None, description="Event role (ORGANISER, FACILITATOR_HELPER, etc.)"
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


class JournalContactRelationshipUpdateAttributes(BaseModel):
    """Attributes for updating a journal-contact relationship's status/role."""

    status: str | None = Field(
        default=None, description="Attendee status (ATTENDING, ATTENDED, MAYBE, etc.)"
    )
    role: str | None = Field(
        default=None, description="Event role (ORGANISER, FACILITATOR_HELPER, etc.)"
    )


class JournalContactRelationshipUpdateData(BaseModel):
    """Data for updating a journal-contact relationship."""

    type: str = Field(
        default="journal-contact-relationships", description=RESOURCE_TYPE_DESC
    )
    attributes: JournalContactRelationshipUpdateAttributes = Field(
        ..., description="Relationship attributes to update"
    )


class JournalContactRelationshipUpdateRequest(BaseModel):
    """Request model for updating a journal-contact relationship."""

    data: JournalContactRelationshipUpdateData = Field(..., description="Update data")


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


# Merge Management Schemas
class MergeOverrides(BaseModel):
    """Explicit conflict resolution overrides."""

    title: str | None = Field(default=None, description="Explicit title to keep")
    content: str | None = Field(default=None, description="Explicit content to keep")
    event_date_range: EventDateRangeSchema | None = Field(
        default=None, description="Explicit date range to keep"
    )
    type_data: dict[str, dict[str, Any]] | None = Field(
        default=None,
        description="Type-specific data overrides (e.g. {'MOOD_RATING': {'mood_value': 8}})",
    )


class MergeJournalAttributes(BaseModel):
    """Attributes for merging a journal."""

    source_journal_id: int = Field(
        ..., description="ID of the journal to merge into this one"
    )
    overrides: MergeOverrides | None = Field(
        default=None, description="Explicit conflict resolution overrides"
    )


class MergeJournalData(BaseModel):
    """Data for merging a journal."""

    type: str = Field(default="journal-merge", description=RESOURCE_TYPE_DESC)
    attributes: MergeJournalAttributes = Field(..., description="Merge attributes")


class MergeJournalRequest(JsonApiCreateRequest[MergeJournalData]):
    """Request model for merging journals."""

    pass


# Review Item Schemas
class ReviewSuggestionSchema(BaseModel):
    """Lightweight review suggestion embedded in journal detail responses."""

    id: int = Field(..., description="Review item ID")
    reason: str = Field(
        ...,
        description=REVIEW_REASON_DESC,
    )
    confidence_score: float = Field(..., description=MATCH_CONFIDENCE_DESC)
    candidate_journal_id: int = Field(..., description="Candidate journal ID")
    candidate_journal_title: str = Field(..., description="Candidate journal title")
    details: dict[str, Any] | None = Field(
        default=None, description="Match details (matched fields, similarity scores)"
    )


class ReviewItemJournalSummary(BaseModel):
    """Lightweight journal summary embedded in review item responses."""

    id: int = Field(..., description="Journal ID")
    title: str = Field(..., description=JOURNAL_TITLE_DESC)
    event_date_range: EventDateRangeSchema = Field(
        ..., description="Journal event date range"
    )


class ReviewItemAttributes(BaseModel):
    """Review item attributes for the review queue endpoint."""

    reason: str = Field(
        ...,
        description=REVIEW_REASON_DESC,
    )
    confidence_score: float = Field(..., description=MATCH_CONFIDENCE_DESC)
    status: str = Field(..., description="Review status (pending, resolved, dismissed)")
    details: dict[str, Any] | None = Field(default=None, description="Match details")
    source_journal: ReviewItemJournalSummary = Field(
        ..., description="Source journal summary"
    )
    candidate_journal: ReviewItemJournalSummary = Field(
        ..., description="Candidate journal summary"
    )
    created_at: datetime | None = Field(default=None, description="Creation timestamp")


class ReviewItemResource(BaseModel):
    """Review item resource following JSON API specification."""

    type: str = Field(default="review-items", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description=RESOURCE_ID_DESC)
    attributes: ReviewItemAttributes = Field(..., description="Review item attributes")
    links: JsonApiLinks | None = Field(default=None, description=RESOURCE_LINKS_DESC)


class ReviewItemListResponse(JsonApiCollectionResponse[ReviewItemResource]):
    """Response model for a list of review items."""

    pass


class ReviewItemResponse(JsonApiResponse[ReviewItemResource]):
    """Response model for a single review item."""

    pass


class IncompleteOutdoorActivityAttributes(BaseModel):
    """Attributes of an entry in the incomplete outdoor activities review."""

    title: str = Field(..., description=JOURNAL_TITLE_DESC)
    event_date_range: EventDateRangeSchema = Field(
        ..., description="Journal event date range"
    )
    subtypes: list[OutdoorActivitySubtype] = Field(
        ..., description="Outdoor activity subtypes present on the journal"
    )
    reasons: list[IncompletenessReason] = Field(
        ...,
        description=(
            "Why the journal is flagged "
            "(no_attributes, missing_template, no_participants)"
        ),
    )
    dismissed: bool = Field(
        ...,
        description=(
            "Whether the journal is dismissed from the review "
            "(only true when listed with include_dismissed)"
        ),
    )


class IncompleteOutdoorActivityResource(BaseModel):
    """Incomplete outdoor activity resource following JSON API specification.

    The resource id is the flagged journal's id — the review is a projection
    over journals, not a stored entity.
    """

    type: str = Field(
        default="incomplete-outdoor-activities", description=RESOURCE_TYPE_DESC
    )
    id: str = Field(..., description="Flagged journal ID")
    attributes: IncompleteOutdoorActivityAttributes = Field(
        ..., description="Incomplete outdoor activity attributes"
    )
    links: JsonApiLinks | None = Field(default=None, description=RESOURCE_LINKS_DESC)


class IncompleteOutdoorActivityListResponse(
    JsonApiCollectionResponse[IncompleteOutdoorActivityResource]
):
    """Response model for the incomplete outdoor activities list."""

    pass


class OutdoorActivityDismissalAttributes(BaseModel):
    """Attributes describing a journal's incomplete-review dismissal state."""

    journal_id: int = Field(..., description="Journal ID")
    dismissed: bool = Field(
        ..., description="Whether the journal is dismissed from the review"
    )
    provenance: str | None = Field(
        default=None, description="Source that recorded the dismissal (e.g. ui, mcp)"
    )
    was_dismissed: bool | None = Field(
        default=None,
        description="On undismiss: whether the journal was dismissed beforehand",
    )


class OutdoorActivityDismissalResource(BaseModel):
    """Outdoor activity dismissal resource following JSON API specification."""

    type: str = Field(
        default="outdoor-activity-dismissals", description=RESOURCE_TYPE_DESC
    )
    id: str = Field(..., description="Journal ID the dismissal applies to")
    attributes: OutdoorActivityDismissalAttributes = Field(
        ..., description="Dismissal state attributes"
    )


class OutdoorActivityDismissalResponse(
    JsonApiResponse[OutdoorActivityDismissalResource]
):
    """Response model for dismiss/undismiss actions."""

    pass


class UpcomingOutdoorActivitySchema(BaseModel):
    """An upcoming outdoor activity or planning event on the dashboard."""

    journal_id: int = Field(..., description="Journal ID")
    title: str = Field(..., description=JOURNAL_TITLE_DESC)
    event_date_range: EventDateRangeSchema = Field(
        ..., description="Journal event date range"
    )
    subtypes: list[OutdoorActivitySubtype] = Field(
        ..., description="Outdoor activity subtypes present on the journal"
    )
    is_planning: bool = Field(
        ...,
        description=(
            "Whether the entry is an OUTDOOR_PLANNING event "
            "rather than an outdoor activity"
        ),
    )


class CheckedOutGearItemSchema(BaseModel):
    """A gear item currently checked out."""

    gear_item_id: str = Field(..., description="Gear item ID")
    name: str = Field(..., description="Gear item name")
    checked_out_since: datetime = Field(
        ..., description="When the item was checked out (resolved checkout date)"
    )
    journal_id: int = Field(
        ..., description="GEAR_USAGE journal recording the checkout"
    )


class OutdoorActivityTotalsSchema(BaseModel):
    """Outdoor activity counts by journal type over the rolling windows."""

    last_30_days: dict[str, int] = Field(
        ..., description="Counts by journal type over the last 30 days"
    )
    last_365_days: dict[str, int] = Field(
        ..., description="Counts by journal type over the last 365 days"
    )


class TemplateDoneSchema(BaseModel):
    """A template the user has done, with its per-template done-count.

    The template type is the ``templates_done`` mapping key, so it is not
    repeated here; ``template_id`` links to the template.
    """

    template_id: str = Field(..., description="Activity template ID")
    name: str = Field(..., description="Template name")
    done_count: int = Field(
        ...,
        description=(
            "How many of the user's abseiling activities reference the template"
        ),
    )


class OutdoorDashboardAttributes(BaseModel):
    """Attributes of the outdoor dashboard singleton resource."""

    upcoming_activities: list[UpcomingOutdoorActivitySchema] = Field(
        ...,
        description=(
            "Upcoming outdoor activities and planning events "
            "(next 30 days, soonest first, capped at 10)"
        ),
    )
    checked_out_gear: list[CheckedOutGearItemSchema] = Field(
        ..., description="Gear currently checked out, longest out first"
    )
    activity_totals: OutdoorActivityTotalsSchema = Field(
        ...,
        description=("Outdoor activity counts by type over rolling 30/365-day windows"),
    )
    templates_done: dict[str, list[TemplateDoneSchema]] = Field(
        ...,
        description=(
            "Unique templates referenced by the user's abseiling activities, "
            "grouped by template type"
        ),
    )


class OutdoorDashboardResource(BaseModel):
    """Outdoor dashboard resource following JSON API specification.

    A singleton projection over the user's outdoor journals — the resource
    id is the user's id (one dashboard per user, not a stored entity).
    """

    type: str = Field(default="outdoor-dashboards", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="User ID the dashboard belongs to")
    attributes: OutdoorDashboardAttributes = Field(
        ..., description="Outdoor dashboard attributes"
    )


class OutdoorDashboardResponse(JsonApiResponse[OutdoorDashboardResource]):
    """Response model for the outdoor dashboard."""

    pass


class ReviewItemCreateAttributes(BaseModel):
    """Attributes for creating a review item (test-only endpoint)."""

    source_journal_id: int = Field(..., description="Source journal ID")
    candidate_journal_id: int = Field(..., description="Candidate journal ID")
    reason: str = Field(
        default="duplicate_journal",
        description=REVIEW_REASON_DESC,
    )
    confidence_score: float = Field(default=0.85, description=MATCH_CONFIDENCE_DESC)
    details: dict[str, Any] | None = Field(default=None, description="Match details")


class ReviewItemCreateData(BaseModel):
    """Data for creating a review item."""

    type: str = Field(default="review-items", description=RESOURCE_TYPE_DESC)
    attributes: ReviewItemCreateAttributes = Field(
        ..., description="Review item attributes"
    )


class ReviewItemCreateRequest(JsonApiCreateRequest[ReviewItemCreateData]):
    """Request model for creating a review item (test-only endpoint)."""

    pass


# Calendar Management Schemas
class CalendarAttributes(BaseModel):
    """Calendar attributes."""

    name: str = Field(..., description=CALENDAR_NAME_DESC)
    description: str | None = Field(default=None, description="Calendar description")
    color: str | None = Field(default=None, description=CALENDAR_COLOR_DESC)
    is_synced_to_google: bool = Field(
        default=False, description="Whether calendar is synced to Google Calendar"
    )
    google_calendar_id: str | None = Field(
        default=None, description="Google Calendar ID"
    )
    access_role: str | None = Field(
        default=None,
        description="Google Calendar access role (owner, writer, reader, freeBusyReader)",
    )


class CalendarResource(BaseModel):
    """Calendar resource following JSON API specification."""

    type: str = Field(default="calendars", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description=RESOURCE_ID_DESC)
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


class CalendarUpdateAttributes(BaseModel):
    """Calendar attributes for updates."""

    name: str | None = Field(
        default=None, description=CALENDAR_NAME_DESC, min_length=1, max_length=100
    )
    description: str | None = Field(default=None, description="Calendar description")
    color: str | None = Field(
        default=None, description=CALENDAR_COLOR_DESC, pattern=r"^#[0-9A-Fa-f]{6}$"
    )
    is_synced_to_google: bool | None = Field(
        default=None, description="Whether calendar is synced to Google Calendar"
    )
    google_calendar_id: str | None = Field(
        default=None, description="Google Calendar ID"
    )

    @model_validator(mode="after")
    def validate_non_nulls(self) -> CalendarUpdateAttributes:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null when updating")
        if "color" in self.model_fields_set and self.color is None:
            raise ValueError("color cannot be null when updating")
        if (
            "is_synced_to_google" in self.model_fields_set
            and self.is_synced_to_google is None
        ):
            raise ValueError("is_synced_to_google cannot be null when updating")
        return self


class CalendarUpdateData(BaseModel):
    """Data for updating a calendar."""

    type: str = Field(default="calendars", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description="Calendar ID to update")
    attributes: CalendarUpdateAttributes = Field(
        ..., description="Calendar attributes to update"
    )


class CalendarUpdateRequest(JsonApiUpdateRequest[CalendarUpdateData]):
    """Request model for updating a calendar."""

    pass


class CalendarResponse(JsonApiResponse[CalendarResource]):
    """Response model for a single calendar."""

    pass


class CalendarListResponse(JsonApiCollectionResponse[CalendarResource]):
    """Response model for a list of calendars."""

    pass


# Activity Template Schemas
class ActivityTemplateAttributes(BaseModel):
    """Attributes for an ActivityTemplate."""

    name: str = Field(..., description="Template name")
    template_type: str = Field(
        ..., description="Type of template (canyoning, climbing, etc)"
    )
    region: str | None = Field(default=None, description="Region")
    description: str | None = Field(default=None, description="Description")
    french_grade: str | None = Field(default=None, description="French grade")
    canyon_type: str | None = Field(default=None, description="Canyon type")
    water_gauge_name: str | None = Field(default=None, description="Water gauge name")
    is_vertical: bool | None = Field(default=None, description="Is vertical")
    is_horizontal: bool | None = Field(default=None, description="Is horizontal")
    climbing_type: str | None = Field(default=None, description="Climbing type")
    grade: int | None = Field(default=None, description="Grade")
    length: int | None = Field(default=None, description="Length in metres")
    pitches: list[AbseilPitchSchema] = Field(
        default_factory=list, description="Template pitches"
    )
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(
        default=None, description="Last update timestamp"
    )


class ActivityTemplateResource(BaseModel):
    """JSON API resource for an activity template."""

    type: str = Field(default="activity-templates", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description=RESOURCE_ID_DESC)
    attributes: ActivityTemplateAttributes = Field(
        ..., description="Template attributes"
    )
    links: JsonApiLinks | None = Field(default=None, description=RESOURCE_LINKS_DESC)


class ActivityTemplateCreateAttributes(BaseModel):
    """Attributes for creating an activity template."""

    name: str = Field(..., description="Template name")
    template_type: str = Field(..., description="Type of template")
    region: str | None = Field(default=None, description="Region")
    description: str | None = Field(default=None, description="Description")
    french_grade: str | None = Field(default=None, description="French grade")
    canyon_type: str | None = Field(default=None, description="Canyon type")
    water_gauge_name: str | None = Field(default=None, description="Water gauge name")
    is_vertical: bool | None = Field(default=None, description="Is vertical")
    is_horizontal: bool | None = Field(default=None, description="Is horizontal")
    climbing_type: str | None = Field(default=None, description="Climbing type")
    grade: int | None = Field(default=None, description="Grade")
    length: int | None = Field(default=None, description="Length in metres")
    pitches: list[AbseilPitchSchema] | None = Field(
        default=None, description="Template pitches"
    )


class ActivityTemplateCreateData(BaseModel):
    """Data for creating an activity template."""

    type: str = Field(default="activity-templates", description=RESOURCE_TYPE_DESC)
    attributes: ActivityTemplateCreateAttributes


class ActivityTemplateCreateRequest(JsonApiCreateRequest[ActivityTemplateCreateData]):
    """Request to create an activity template."""

    pass


class ActivityTemplateUpdateAttributes(BaseModel):
    """Attributes for updating an activity template."""

    name: str | None = Field(default=None, description="Template name")
    template_type: str | None = Field(default=None, description="Type of template")
    region: str | None = Field(default=None, description="Region")
    description: str | None = Field(default=None, description="Description")
    french_grade: str | None = Field(default=None, description="French grade")
    canyon_type: str | None = Field(default=None, description="Canyon type")
    water_gauge_name: str | None = Field(default=None, description="Water gauge name")
    is_vertical: bool | None = Field(default=None, description="Is vertical")
    is_horizontal: bool | None = Field(default=None, description="Is horizontal")
    climbing_type: str | None = Field(default=None, description="Climbing type")
    grade: int | None = Field(default=None, description="Grade")
    length: int | None = Field(default=None, description="Length in metres")
    pitches: list[AbseilPitchSchema] | None = Field(
        default=None, description="Template pitches"
    )


class ActivityTemplateUpdateData(BaseModel):
    """Data for updating an activity template."""

    type: str = Field(default="activity-templates", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description=RESOURCE_ID_DESC)
    attributes: ActivityTemplateUpdateAttributes


class ActivityTemplateUpdateRequest(JsonApiUpdateRequest[ActivityTemplateUpdateData]):
    """Request to update an activity template."""

    pass


class ActivityTemplateResponse(JsonApiResponse[ActivityTemplateResource]):
    """Response containing a single activity template."""

    pass


class ActivityTemplateListResponse(JsonApiCollectionResponse[ActivityTemplateResource]):
    """Response containing multiple activity templates."""

    pass


# Gear Item Schemas
class GearItemAttributes(BaseModel):
    """Attributes for a GearItem."""

    name: str = Field(..., description="Gear item name")
    model: str | None = Field(default=None, description="Model name/number")
    serial_number: str | None = Field(default=None, description="Serial number")
    purchase_date: date | None = Field(default=None, description="Date of purchase")
    manufacturer: str | None = Field(default=None, description="Manufacturer name")
    created_at: datetime | None = Field(default=None, description="Creation timestamp")
    updated_at: datetime | None = Field(
        default=None, description="Last update timestamp"
    )


class GearItemResource(BaseModel):
    """JSON API resource for a gear item."""

    type: str = Field(default="gear-items", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description=RESOURCE_ID_DESC)
    attributes: GearItemAttributes = Field(..., description="Gear item attributes")
    links: JsonApiLinks | None = Field(default=None, description=RESOURCE_LINKS_DESC)


class GearItemCreateAttributes(BaseModel):
    """Attributes for creating a gear item."""

    name: str = Field(..., description="Gear item name", min_length=1, max_length=200)
    model: str | None = Field(
        default=None, description="Model name/number", max_length=200
    )
    serial_number: str | None = Field(
        default=None, description="Serial number", max_length=200
    )
    purchase_date: date | None = Field(default=None, description="Date of purchase")
    manufacturer: str | None = Field(
        default=None, description="Manufacturer name", max_length=200
    )


class GearItemCreateData(BaseModel):
    """Data for creating a gear item."""

    type: str = Field(default="gear-items", description=RESOURCE_TYPE_DESC)
    attributes: GearItemCreateAttributes


class GearItemCreateRequest(JsonApiCreateRequest[GearItemCreateData]):
    """Request to create a gear item."""

    pass


class GearItemUpdateAttributes(BaseModel):
    """Attributes for updating a gear item."""

    name: str | None = Field(
        default=None, description="Gear item name", min_length=1, max_length=200
    )
    model: str | None = Field(
        default=None, description="Model name/number", max_length=200
    )
    serial_number: str | None = Field(
        default=None, description="Serial number", max_length=200
    )
    purchase_date: date | None = Field(default=None, description="Date of purchase")
    manufacturer: str | None = Field(
        default=None, description="Manufacturer name", max_length=200
    )


class GearItemUpdateData(BaseModel):
    """Data for updating a gear item."""

    type: str = Field(default="gear-items", description=RESOURCE_TYPE_DESC)
    id: str = Field(..., description=RESOURCE_ID_DESC)
    attributes: GearItemUpdateAttributes


class GearItemUpdateRequest(JsonApiUpdateRequest[GearItemUpdateData]):
    """Request to update a gear item."""

    pass


class GearItemResponse(JsonApiResponse[GearItemResource]):
    """Response containing a single gear item."""

    pass


class GearItemListResponse(JsonApiCollectionResponse[GearItemResource]):
    """Response containing multiple gear items."""

    pass
