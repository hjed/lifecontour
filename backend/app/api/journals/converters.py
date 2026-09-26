"""
Converters for transforming journal domain entities to API resources.

Handles the conversion between domain models and JSON API resources,
ensuring proper separation between domain and API layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core_shared.models.journals import (
    AbseilingData,
    AbseilPitch,
    ActivityTemplate,
    BushwalkingData,
    Calendar,
    CalendarInfo,
    CanoeingData,
    CanyoningData,
    CavingData,
    ClimbingData,
    CrossCountrySkiingData,
    DivingData,
    DownhillSkiingData,
    FitnessData,
    GearItem,
    GearMaintenanceData,
    GearUsageData,
    JoggingData,
    Journal,
    JournalContactRelationship,
    KayakingData,
    MoodData,
    OutdoorActivityData,
    OutdoorPlanningData,
    OutdoorTrainingData,
    PlanData,
    SnorkellingData,
    TravelData,
)
from core_shared.models.route import Route

from app.api.common.schemas import JsonApiLinks
from app.api.journals.schemas import (
    AbseilingDataSchema,
    AbseilPitchSchema,
    ActivityTemplateResource,
    BushwalkingDataSchema,
    CalendarInfoDataSchema,
    CalendarSchema,
    CanoeingDataSchema,
    CanyoningDataSchema,
    CavingDataSchema,
    ClimbingDataSchema,
    CrossCountrySkiingDataSchema,
    DivingDataSchema,
    DownhillSkiingDataSchema,
    EventDateRangeSchema,
    FitnessDataSchema,
    GearItemAttributes,
    GearItemResource,
    GearMaintenanceDataSchema,
    GearUsageDataSchema,
    JoggingDataSchema,
    JournalAttributes,
    JournalContactRelationshipSchema,
    JournalRelationships,
    JournalResource,
    JournalTagSchema,
    KayakingDataSchema,
    MoodDataSchema,
    OutdoorActivityDataSchema,
    OutdoorPlanningDataSchema,
    OutdoorTrainingDataSchema,
    PhotoAlbumDataSchema,
    PlanDataSchema,
    PlanDocumentSchema,
    SnorkellingDataSchema,
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
                status=contact_rel.status.value if contact_rel.status else None,
                role=contact_rel.role.value if contact_rel.role else None,
                first_name=None,
                last_name=None,
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
    def _convert_calendars(
        calendars: list[Calendar] | None,
    ) -> list[CalendarSchema]:
        """Every calendar the event lives in, display calendar first."""
        return [
            schema
            for schema in (
                JournalConverter._convert_calendar(entry) for entry in (calendars or [])
            )
            if schema is not None
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
    def _convert_children(
        children: list[Journal] | None,
        children_types: dict[int, list[str]] | None = None,
    ) -> list[dict[str, Any]] | None:
        """Convert child journals to summaries.

        Args:
            children: Child journal entities.
            children_types: Mapping of journal ID to list of type strings.
        """
        if children is None:
            return None

        types_map = children_types or {}
        return [
            {
                "id": str(child.id),
                "title": child.title,
                "types": types_map.get(child.id, []) if child.id else [],
                "date": (
                    child.event_date_range.start.isoformat()
                    if child.event_date_range and child.event_date_range.start
                    else None
                ),
            }
            for child in children
        ]

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
        calendars: list[Calendar] | None = None,
        parent: Journal | None = None,
        children: list[Journal] | None = None,
        children_count: int | None = None,
        depth: int | None = None,
        routes: list[Route] | None = None,
        children_types: dict[int, list[str]] | None = None,
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
            calendars: Every calendar the event lives in, display calendar
                first (for EVENT type). The display calendar is its first
                entry, and is what the response's ``calendar`` field reports.
            parent: Parent journal
            children: Child journals
            children_count: Number of child journals
            depth: Depth in hierarchy (1=root, 2=first-level child)
            children_types: Mapping of child journal ID to type lists

        Returns:
            JournalResource following JSON API specification
        """
        _validate_entity_id(journal.id, "journal")

        # Convert embedded data
        contact_schemas = JournalConverter._convert_contacts(contacts)
        tag_schemas = JournalConverter._convert_tags(tags)
        calendar_schemas = JournalConverter._convert_calendars(calendars)
        # The calendar the journal is displayed in leads the list, and is
        # what the long-standing single-calendar field reports.
        calendar = calendars[0] if calendars else None
        calendar_schema = calendar_schemas[0] if calendar_schemas else None
        parent_summary = JournalConverter._convert_parent(parent)
        children_summaries = JournalConverter._convert_children(
            children, children_types
        )

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
            calendars=calendar_schemas,
            parent=parent_summary,
            children=children_summaries,
            children_count=children_count,
            depth=depth,
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
            description=calendar_info.description,
            start_time=calendar_info.start_time,
            end_time=calendar_info.end_time,
            is_all_day=calendar_info.is_all_day,
            location=calendar_info.location,
            timezone=calendar_info.timezone,
            sync_invitees=calendar_info.sync_invitees,
            private_description=calendar_info.private_description,
            event_state=calendar_info.event_state.value,
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
    def photo_album_data_to_schema(
        photo_album_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Convert Immich album sync data (a dict) to the API schema.

        ``photo_album_data`` comes from ``AlbumSyncReadRepository`` and may
        contain ``immich_album_id`` plus optional ``album_name``, ``album_url``
        and ``asset_count``.
        """
        return PhotoAlbumDataSchema(**photo_album_data).model_dump(exclude_none=True)

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
    def abseiling_data_to_schema(
        data: AbseilingData, pitches: list[AbseilPitch] | None = None
    ) -> dict[str, Any]:
        """Convert AbseilingData domain entity to API schema."""
        pitch_schemas = []
        if pitches:
            pitch_schemas = [
                AbseilPitchSchema(
                    id=pitch.id,
                    pitch_number=pitch.pitch_number,
                    height=pitch.height,
                    anchor_location=pitch.anchor_location,
                    anchor_type=pitch.anchor_type,
                    did_rescue=pitch.did_rescue,
                    did_setup=pitch.did_setup,
                    notes=pitch.notes,
                    pitch_type=pitch.pitch_type,
                )
                for pitch in pitches
            ]

        return AbseilingDataSchema(
            template_id=str(data.template_id) if data.template_id else None,
            number_of_abseils=data.number_of_abseils,
            total_length=data.total_length,
            number_of_setups=data.number_of_setups,
            number_of_rescues=data.number_of_rescues,
            pitches=pitch_schemas,
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
    def caving_data_to_schema(data: CavingData) -> dict[str, Any]:
        """Convert CavingData domain entity to API schema."""
        return CavingDataSchema(
            is_vertical=data.is_vertical,
            is_horizontal=data.is_horizontal,
        ).model_dump(exclude_none=True)

    @staticmethod
    def canoeing_data_to_schema(data: CanoeingData) -> dict[str, Any]:
        """Convert CanoeingData domain entity to API schema."""
        return CanoeingDataSchema(
            water_type=data.water_type,
        ).model_dump(exclude_none=True)

    @staticmethod
    def snorkelling_data_to_schema(data: SnorkellingData) -> dict[str, Any]:
        """Convert SnorkellingData domain entity to API schema."""
        return SnorkellingDataSchema().model_dump(exclude_none=True)

    @staticmethod
    def diving_data_to_schema(data: DivingData) -> dict[str, Any]:
        """Convert DivingData domain entity to API schema."""
        return DivingDataSchema().model_dump(exclude_none=True)

    @staticmethod
    def downhill_skiing_data_to_schema(data: DownhillSkiingData) -> dict[str, Any]:
        """Convert DownhillSkiingData domain entity to API schema."""
        return DownhillSkiingDataSchema().model_dump(exclude_none=True)

    @staticmethod
    def climbing_data_to_schema(data: ClimbingData) -> dict[str, Any]:
        """Convert ClimbingData domain entity to API schema."""
        return ClimbingDataSchema(
            climbing_type=data.climbing_type,
            grade=data.grade,
            length=data.length,
            indoor=data.indoor,
        ).model_dump(exclude_none=True)

    @staticmethod
    def kayaking_data_to_schema(data: KayakingData) -> dict[str, Any]:
        """Convert KayakingData domain entity to API schema."""
        return KayakingDataSchema(
            water_type=data.water_type,
            is_white_water=data.is_white_water,
            rapids_grade=data.rapids_grade,
        ).model_dump(exclude_none=True)

    @staticmethod
    def cross_country_skiing_data_to_schema(
        data: CrossCountrySkiingData,
    ) -> dict[str, Any]:
        """Convert CrossCountrySkiingData domain entity to API schema."""
        return CrossCountrySkiingDataSchema(
            snow_conditions=data.snow_conditions,
        ).model_dump(exclude_none=True)

    @staticmethod
    def outdoor_planning_data_to_schema(data: OutdoorPlanningData) -> dict[str, Any]:
        """Convert OutdoorPlanningData domain entity to API schema."""
        return OutdoorPlanningDataSchema(
            topics=data.topics,
            activity_types=data.activity_types,
        ).model_dump(exclude_none=True)

    @staticmethod
    def outdoor_training_data_to_schema(data: OutdoorTrainingData) -> dict[str, Any]:
        """Convert OutdoorTrainingData domain entity to API schema."""
        return OutdoorTrainingDataSchema(
            focus_areas=data.focus_areas,
        ).model_dump(exclude_none=True)

    @staticmethod
    def gear_maintenance_data_to_schema(data: GearMaintenanceData) -> dict[str, Any]:
        """Convert GearMaintenanceData domain entity to API schema."""
        return GearMaintenanceDataSchema(
            gear_item_id=str(data.gear_item_id),
            maintenance_type=data.maintenance_type,
            activity_types=data.activity_types,
            retirement_reason=data.retirement_reason,
        ).model_dump(exclude_none=True)

    @staticmethod
    def gear_usage_data_to_schema(data: GearUsageData) -> dict[str, Any]:
        """Convert GearUsageData domain entity to API schema (its first item)."""
        item = data.items[0] if data.items else None
        if item is None:
            return GearUsageDataSchema().model_dump(exclude_none=True)
        return GearUsageDataSchema(
            gear_item_id=str(item.gear_item_id),
            checkout_date=item.checkout_date,
            checkin_date=item.checkin_date,
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


class ActivityTemplateConverter:
    """Converter for ActivityTemplate models to API schemas."""

    @staticmethod
    def to_resource(
        template: ActivityTemplate, base_url: str = ""
    ) -> ActivityTemplateResource:
        """Convert a template domain model to JSON API resource."""
        from app.api.common.schemas import JsonApiLinks
        from app.api.journals.schemas import (
            AbseilPitchSchema,
            ActivityTemplateAttributes,
            ActivityTemplateResource,
        )

        pitches_schema = []
        if template.pitches:
            for p in template.pitches:
                pitches_schema.append(
                    AbseilPitchSchema(
                        id=p.id,
                        pitch_number=p.pitch_number,
                        height=p.height,
                        anchor_location=p.anchor_location,
                        anchor_type=p.anchor_type,
                        did_rescue=p.did_rescue,
                        did_setup=p.did_setup,
                        notes=p.notes,
                        pitch_type=p.pitch_type,
                    )
                )

        attributes = ActivityTemplateAttributes(
            name=template.name,
            template_type=template.template_type,
            region=template.region,
            description=template.description,
            french_grade=template.french_grade,
            canyon_type=template.canyon_type,
            water_gauge_name=template.water_gauge_name,
            is_vertical=template.is_vertical,
            is_horizontal=template.is_horizontal,
            climbing_type=template.climbing_type,
            grade=template.grade,
            length=template.length,
            pitches=pitches_schema,
            created_at=template.created_at,
            updated_at=template.updated_at,
        )

        clean_base_url = base_url.rstrip("/") if base_url else ""
        links = JsonApiLinks(self=f"{clean_base_url}/api/templates/{template.id}")

        return ActivityTemplateResource(
            type="activity-templates",
            id=str(template.id),
            attributes=attributes,
            links=links,
        )


class GearItemConverter:
    """Converter for GearItem models to API schemas."""

    @staticmethod
    def to_resource(gear_item: GearItem, base_url: str = "") -> GearItemResource:
        """Convert a GearItem domain model to JSON API resource."""
        from app.api.common.schemas import JsonApiLinks

        attributes = GearItemAttributes(
            name=gear_item.name,
            model=gear_item.model,
            serial_number=gear_item.serial_number,
            purchase_date=gear_item.purchase_date,
            manufacturer=gear_item.manufacturer,
            created_at=gear_item.created_at,
            updated_at=gear_item.updated_at,
        )

        clean_base_url = base_url.rstrip("/") if base_url else ""
        links = JsonApiLinks(self=f"{clean_base_url}/api/gear-items/{gear_item.id}")

        return GearItemResource(
            type="gear-items",
            id=str(gear_item.id),
            attributes=attributes,
            links=links,
        )
