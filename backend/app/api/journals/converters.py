"""
Converters for transforming journal domain entities to API resources.

Handles the conversion between domain models and JSON API resources,
ensuring proper separation between domain and API layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core_shared.models.journals import (
    AbseilingData,
    BushwalkingData,
    Calendar,
    CalendarInfo,
    CanyoningData,
    ClimbingData,
    CrossCountrySkiingData,
    FitnessData,
    JoggingData,
    Journal,
    JournalContactRelationship,
    KayakingData,
    MoodData,
    OutdoorActivityData,
    PhotoAlbumData,
    PlanData,
    TravelData,
)
from core_shared.models.route import Route

from app.api.common.schemas import JsonApiLinks
from app.api.journals.schemas import (
    AbseilingDataSchema,
    BushwalkingDataSchema,
    CalendarInfoDataSchema,
    CalendarSchema,
    CanyoningDataSchema,
    ClimbingDataSchema,
    CrossCountrySkiingDataSchema,
    EventDateRangeSchema,
    FitnessDataSchema,
    JoggingDataSchema,
    JournalAttributes,
    JournalContactRelationshipSchema,
    JournalRelationships,
    JournalResource,
    JournalTagSchema,
    KayakingDataSchema,
    MoodDataSchema,
    OutdoorActivityDataSchema,
    PhotoAlbumDataSchema,
    PlanDataSchema,
    PlanDocumentSchema,
    TravelAccommodationSchema,
    TravelDataSchema,
    TravelFlightSchema,
    TravelTransportationSchema,
)
from app.core.journal.models.journal_tag import JournalTag

if TYPE_CHECKING:
    from app.api.journals.schemas import (
        JournalCreateData,
        JournalUpdateData,
    )


def _validate_entity_id(entity_id: int | None, entity_type: str) -> None:
    """Validate that an entity has an ID before serialization."""
    if entity_id is None:
        raise ValueError(
            f"Cannot serialize {entity_type} without ID - {entity_type} must be persisted first"
        )


class JournalConverter:
    """Converter for Journal domain entities to API resources."""

    @staticmethod
    def to_event_date_range_schema(
        journal: Journal,
    ) -> EventDateRangeSchema:
        """Convert EventDateRange value object to API schema."""
        return EventDateRangeSchema(
            start=journal.event_date_range.start,
            end=journal.event_date_range.end,
        )

    @staticmethod
    def _convert_contacts(
        contacts: list[JournalContactRelationship] | None,
    ) -> list[JournalContactRelationshipSchema]:
        """Convert contact relationships to schemas."""
        if not contacts:
            return []

        return [
            JournalContactRelationshipSchema(
                id=str(contact_rel.contact_id),
                name=None,  # Will be populated by controller
                relationship_type=contact_rel.relationship_type.value,
            )
            for contact_rel in contacts
        ]

    @staticmethod
    def _convert_tags(tags: list[JournalTag] | None) -> list[JournalTagSchema]:
        """Convert tags to schemas."""
        if not tags:
            return []

        return [
            JournalTagSchema(
                id=str(tag.id) if tag.id else "",
                name=tag.name,
                color=tag.color,
            )
            for tag in tags
        ]

    @staticmethod
    def _convert_calendar(calendar: Calendar | None) -> CalendarSchema | None:
        """Convert calendar to schema."""
        if not calendar:
            return None

        return CalendarSchema(
            id=str(calendar.id) if calendar.id else "",
            name=calendar.name,
            color=calendar.color,
        )

    @staticmethod
    def _convert_routes(routes: list[Route] | None) -> list[dict[str, Any]]:
        """Convert routes to dictionaries."""
        if not routes:
            return []

        return [
            {
                "id": str(route.id),
                "name": route.name,
                "description": route.description,
            }
            for route in routes
        ]

    @staticmethod
    def _convert_parent(parent: Journal | None) -> dict[str, str] | None:
        """Convert parent journal to summary."""
        if not parent:
            return None

        return {
            "id": str(parent.id),
            "title": parent.title,
        }

    @staticmethod
    def _create_relationships(
        tags: list[JournalTag] | None,
        contacts: list[JournalContactRelationship] | None,
        calendar: Calendar | None,
        routes: list[Route] | None = None,
    ) -> JournalRelationships | None:
        """Create relationships object."""
        if not (tags or contacts or calendar or routes):
            return None

        tags_data = None
        if tags:
            tags_data = {
                "data": [{"type": "tags", "id": str(tag.id)} for tag in tags if tag.id]
            }

        contacts_data = None
        if contacts:
            contacts_data = {
                "data": [
                    {"type": "contacts", "id": str(c.contact_id)} for c in contacts
                ]
            }

        calendar_data = None
        if calendar and calendar.id:
            calendar_data = {"data": {"type": "calendars", "id": str(calendar.id)}}

        routes_data = None
        if routes:
            routes_data = {
                "data": [{"type": "routes", "id": str(r.id)} for r in routes]
            }

        return JournalRelationships(
            tags=tags_data,
            contacts=contacts_data,
            calendar=calendar_data,
            routes=routes_data,
        )

    @staticmethod
    def to_resource(
        journal: Journal,
        base_url: str = "",
        types: list[str] | None = None,
        type_data: dict[str, Any] | None = None,
        contacts: list[JournalContactRelationship] | None = None,
        tags: list[JournalTag] | None = None,
        calendar: Calendar | None = None,
        parent: Journal | None = None,
        children_count: int | None = None,
        routes: list[Route] | None = None,
    ) -> JournalResource:
        """
        Convert Journal domain entity to API resource.

        Args:
            journal: Journal domain entity
            base_url: Base URL for links
            types: List of journal types
            type_data: Type-specific data organized by type
            contacts: Contact relationships
            tags: Journal tags
            calendar: Calendar (for EVENT type)
            parent: Parent journal
            children_count: Number of child journals

        Returns:
            JournalResource following JSON API specification
        """
        _validate_entity_id(journal.id, "journal")

        # Convert embedded data
        contact_schemas = JournalConverter._convert_contacts(contacts)
        tag_schemas = JournalConverter._convert_tags(tags)
        calendar_schema = JournalConverter._convert_calendar(calendar)
        parent_summary = JournalConverter._convert_parent(parent)

        # Create attributes
        attributes = JournalAttributes(
            title=journal.title,
            content=journal.content,
            event_date_range=JournalConverter.to_event_date_range_schema(journal),
            parent_id=journal.parent_id,
            order=journal.order,
            created_at=journal.created_at,
            updated_at=journal.updated_at,
            types=types or [],
            type_data=type_data or {},
            contacts=contact_schemas,
            tags=tag_schemas,
            calendar=calendar_schema,
            parent=parent_summary,
            children_count=children_count,
        )

        # Create relationships
        relationships = JournalConverter._create_relationships(
            tags, contacts, calendar, routes
        )

        # Create links
        links = None
        if base_url:
            links = JsonApiLinks(
                self=f"{base_url}/api/journals/{journal.id}",
            )

        return JournalResource(
            id=str(journal.id),
            attributes=attributes,
            relationships=relationships,
            links=links,
        )


class TypeDataConverter:
    """Converter for type-specific data."""

    @staticmethod
    def calendar_info_to_schema(calendar_info: CalendarInfo) -> dict[str, Any]:
        """Convert CalendarInfo domain entity to API schema."""
        return CalendarInfoDataSchema(
            calendar_id=str(calendar_info.calendar_id),
            start_time=calendar_info.start_time,
            end_time=calendar_info.end_time,
            is_all_day=calendar_info.is_all_day,
            location=calendar_info.location,
            sync_invitees=calendar_info.sync_invitees,
        ).model_dump(exclude_none=True)

    @staticmethod
    def mood_data_to_schema(mood_data: MoodData) -> dict[str, Any]:
        """Convert MoodData domain entity to API schema."""
        return MoodDataSchema(
            mood_value=mood_data.mood_value,
            mood_label=mood_data.mood_label,
            energy_level=mood_data.energy_level,
        ).model_dump(exclude_none=True)

    @staticmethod
    def plan_data_to_schema(plan_data: PlanData) -> dict[str, Any]:
        """Convert PlanData domain entity to API schema."""
        documents = [
            PlanDocumentSchema(
                id=str(doc.id),
                url=doc.url,
                title=doc.title,
                description=doc.description,
                order=doc.order,
            )
            for doc in plan_data.documents
        ]
        return PlanDataSchema(documents=documents).model_dump(exclude_none=True)

    @staticmethod
    def travel_data_to_schema(travel_data: TravelData) -> dict[str, Any]:
        """Convert TravelData domain entity to API schema."""
        flights = [
            TravelFlightSchema(
                id=str(flight.id),
                flight_number=flight.flight_number,
                airline=flight.airline,
                departure_airport=flight.departure_airport,
                arrival_airport=flight.arrival_airport,
                departure_time=flight.departure_time,
                arrival_time=flight.arrival_time,
                booking_reference=flight.booking_reference,
                confirmation_number=flight.confirmation_number,
                order=flight.order,
            )
            for flight in travel_data.flights
        ]

        accommodations = [
            TravelAccommodationSchema(
                id=str(acc.id),
                name=acc.name,
                address=acc.address,
                check_in_date=acc.check_in_date,
                check_out_date=acc.check_out_date,
                booking_reference=acc.booking_reference,
                confirmation_number=acc.confirmation_number,
                order=acc.order,
            )
            for acc in travel_data.accommodations
        ]

        transportation = [
            TravelTransportationSchema(
                id=str(trans.id),
                type=trans.type,
                details=trans.details,
                booking_reference=trans.booking_reference,
                order=trans.order,
            )
            for trans in travel_data.transportation
        ]

        return TravelDataSchema(
            flights=flights,
            accommodations=accommodations,
            transportation=transportation,
        ).model_dump(exclude_none=True)

    @staticmethod
    def photo_album_data_to_schema(photo_album_data: PhotoAlbumData) -> dict[str, Any]:
        """Convert PhotoAlbumData domain entity to API schema."""
        return PhotoAlbumDataSchema(
            immich_album_id=photo_album_data.immich_album_id,
        ).model_dump(exclude_none=True)

    @staticmethod
    def fitness_data_to_schema(fitness_data: FitnessData) -> dict[str, Any]:
        """Convert FitnessData domain entity to API schema."""
        return FitnessDataSchema(
            heart_rate_avg=fitness_data.heart_rate_avg,
            heart_rate_max=fitness_data.heart_rate_max,
            distance=fitness_data.distance,
            elevation_gain=fitness_data.elevation_gain,
            elevation_loss=fitness_data.elevation_loss,
            duration=fitness_data.duration,
            calories=fitness_data.calories,
            strava_activity_id=fitness_data.strava_activity_id,
        ).model_dump(exclude_none=True)

    @staticmethod
    def outdoor_activity_data_to_schema(
        data: OutdoorActivityData,
    ) -> dict[str, Any]:
        """Convert OutdoorActivityData domain entity to API schema."""
        return OutdoorActivityDataSchema(
            activity_type=data.activity_type,
            weather_conditions=data.weather_conditions,
            role=data.role,
            in_leadership_role=data.in_leadership_role,
            participant_notes=data.participant_notes,
        ).model_dump(exclude_none=True)

    @staticmethod
    def bushwalking_data_to_schema(data: BushwalkingData) -> dict[str, Any]:
        """Convert BushwalkingData domain entity to API schema."""
        return BushwalkingDataSchema(
            track_grading=data.track_grading,
        ).model_dump(exclude_none=True)

    @staticmethod
    def jogging_data_to_schema(data: JoggingData) -> dict[str, Any]:
        """Convert JoggingData domain entity to API schema."""
        return JoggingDataSchema(
            pace=data.pace,
        ).model_dump(exclude_none=True)

    @staticmethod
    def abseiling_data_to_schema(data: AbseilingData) -> dict[str, Any]:
        """Convert AbseilingData domain entity to API schema."""
        return AbseilingDataSchema(
            number_of_abseils=data.number_of_abseils,
            total_length=data.total_length,
        ).model_dump(exclude_none=True)

    @staticmethod
    def canyoning_data_to_schema(data: CanyoningData) -> dict[str, Any]:
        """Convert CanyoningData domain entity to API schema."""
        return CanyoningDataSchema(
            french_grade=data.french_grade,
            water_guage_name=data.water_guage_name,
            water_guage_level=data.water_guage_level,
            is_vertical=data.is_vertical,
            is_night_canyon=data.is_night_canyon,
            is_white_water=data.is_white_water,
        ).model_dump(exclude_none=True)

    @staticmethod
    def climbing_data_to_schema(data: ClimbingData) -> dict[str, Any]:
        """Convert ClimbingData domain entity to API schema."""
        return ClimbingDataSchema(
            climbing_type=data.climbing_type,
            grade=data.grade,
            length=data.length,
        ).model_dump(exclude_none=True)

    @staticmethod
    def kayaking_data_to_schema(data: KayakingData) -> dict[str, Any]:
        """Convert KayakingData domain entity to API schema."""
        return KayakingDataSchema(
            water_type=data.water_type,
        ).model_dump(exclude_none=True)

    @staticmethod
    def cross_country_skiing_data_to_schema(
        data: CrossCountrySkiingData,
    ) -> dict[str, Any]:
        """Convert CrossCountrySkiingData domain entity to API schema."""
        return CrossCountrySkiingDataSchema(
            snow_conditions=data.snow_conditions,
        ).model_dump(exclude_none=True)


class JournalRequestConverter:
    """Converter for API requests to domain entities."""

    @staticmethod
    def from_create_request(data: JournalCreateData, user_id: str) -> Journal:
        """Convert API create request to Journal domain entity.

        Args:
            data: The journal create request data
            user_id: The user ID from the session

        Returns:
            Journal domain entity
        """
        from core_shared.models.journals import EventDateRange

        event_date_range = EventDateRange(
            start=data.attributes.event_date_range.start,
            end=data.attributes.event_date_range.end,
        )

        return Journal(
            user_id=user_id,
            title=data.attributes.title,
            content=data.attributes.content,
            event_date_range=event_date_range,
            parent_id=data.attributes.parent_id,
            order=data.attributes.order,
        )

    @staticmethod
    def from_update_request(data: JournalUpdateData, existing: Journal) -> Journal:
        """Convert API update request to Journal domain entity.

        Supports partial updates - only provided fields are updated.
        """
        from core_shared.models.journals import EventDateRange

        # For partial update (PATCH), only update provided fields
        # Use existing values if not provided
        if data.attributes.event_date_range is not None:
            event_date_range = EventDateRange(
                start=data.attributes.event_date_range.start,
                end=data.attributes.event_date_range.end,
            )
        else:
            event_date_range = existing.event_date_range

        return Journal(
            id=existing.id,
            user_id=existing.user_id,
            title=data.attributes.title
            if data.attributes.title is not None
            else existing.title,
            content=data.attributes.content
            if data.attributes.content is not None
            else existing.content,
            event_date_range=event_date_range,
            parent_id=data.attributes.parent_id
            if data.attributes.parent_id is not None
            else existing.parent_id,
            order=data.attributes.order
            if data.attributes.order is not None
            else existing.order,
            created_at=existing.created_at,
            updated_at=existing.updated_at,
        )
