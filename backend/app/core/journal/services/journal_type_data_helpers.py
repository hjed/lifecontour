"""Pure helpers for parsing and persisting journal type-specific data.

These functions contain no transaction management — they orchestrate reads and
writes against the per-type repositories and raise domain-level validation
errors. They are called from :class:`JournalWriteService` (which owns the unit
of work) and from the journal API controllers for request parsing.

Keeping them in a standalone module avoids a circular import between the write
service and the API controllers.
"""

import dataclasses
from datetime import datetime, time
from typing import Any
from uuid import UUID

from core_shared.models.journals import (
    JournalType,
    JournalValidationError,
)

from app.core.journal.adapters.sql.album_sync_read_repository import (
    AlbumSyncReadRepository,
)
from app.core.journal.models.repositories import (
    AbseilingDataRepository,
    AbseilPitchRepository,
    BushwalkingDataRepository,
    CalendarInfoRepository,
    CanoeingDataRepository,
    CanyoningDataRepository,
    CavingDataRepository,
    ClimbingDataRepository,
    CrossCountrySkiingDataRepository,
    DivingDataRepository,
    DownhillSkiingDataRepository,
    FitnessDataRepository,
    GearMaintenanceDataRepository,
    GearUsageDataRepository,
    JoggingDataRepository,
    KayakingDataRepository,
    MoodDataRepository,
    OutdoorActivityDataRepository,
    OutdoorPlanningDataRepository,
    OutdoorTrainingDataRepository,
    PlanDataRepository,
    SnorkellingDataRepository,
    TravelDataRepository,
)

INVALID_UUID_FORMAT_MSG = "Invalid UUID format"


def parse_optional_datetime(value: Any, field_name: str) -> datetime | None:
    """Parse an optional ISO datetime field from request attributes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise JournalValidationError(
                field_name, f"Invalid datetime format: {value}"
            ) from exc
    raise JournalValidationError(field_name, "Must be an ISO datetime string or null")


def parse_journal_type(type_str: str) -> JournalType:
    """
    Convert a type string to JournalType enum.

    Handles both enum value (lowercase like "mood_rating") and
    enum name (uppercase like "MOOD_RATING").

    Args:
        type_str: The type string to convert

    Returns:
        The corresponding JournalType enum value

    Raises:
        ValueError: If the type string is invalid
        KeyError: If the type string doesn't match any enum
    """
    try:
        # First try as enum value (lowercase like "mood_rating")
        return JournalType(type_str)
    except ValueError:
        # Fall back to enum name (uppercase like "MOOD_RATING")
        return JournalType[type_str.upper()]


def parse_optional_uuid(value: Any, field_name: str) -> UUID | None:
    """Parse an optional UUID field from request attributes."""
    if value is None:
        return None

    try:
        return UUID(str(value))
    except ValueError as exc:
        raise JournalValidationError(
            field_name, f"{INVALID_UUID_FORMAT_MSG}: {value}"
        ) from exc


def require_integer(value: Any, field_name: str) -> int:
    """Validate that a field is an integer while rejecting booleans."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise JournalValidationError(field_name, "Must be an integer")
    return value


def parse_optional_integer(value: Any, field_name: str) -> int | None:
    """Validate an optional integer field while rejecting booleans."""
    if value is None:
        return None
    return require_integer(value, field_name)


def parse_optional_time(value: Any, field_name: str) -> time | None:
    """Parse an optional time field from request attributes."""
    if value is None:
        return None

    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None

    try:
        parsed_time = time.fromisoformat(str(value))
    except (ValueError, TypeError) as exc:
        raise JournalValidationError(
            field_name,
            f"Invalid time format for {field_name}. Expected format: HH:MM or HH:MM:SS with no timezone",
        ) from exc

    if parsed_time.tzinfo is not None:
        raise JournalValidationError(
            field_name,
            f"Invalid time format for {field_name}. Expected format: HH:MM or HH:MM:SS with no timezone",
        )

    return parsed_time


async def create_type_specific_data(
    journal_type: JournalType,
    journal_id: int,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    fitness_data_repo: FitnessDataRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    abseil_pitch_repo: AbseilPitchRepository,
    canyoning_data_repo: CanyoningDataRepository,
    caving_data_repo: CavingDataRepository,
    canoeing_data_repo: CanoeingDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
    snorkelling_data_repo: SnorkellingDataRepository,
    diving_data_repo: DivingDataRepository,
    downhill_skiing_data_repo: DownhillSkiingDataRepository,
    outdoor_planning_data_repo: OutdoorPlanningDataRepository,
    outdoor_training_data_repo: OutdoorTrainingDataRepository,
    gear_maintenance_data_repo: GearMaintenanceDataRepository,
    gear_usage_data_repo: GearUsageDataRepository,
) -> None:
    """
    Create type-specific data row with default values for the given journal type.

    Args:
        journal_type: The type of journal
        journal_id: The ID of the journal
        mood_data_repo: Repository for mood data
        plan_data_repo: Repository for plan data
        travel_data_repo: Repository for travel data
        fitness_data_repo: Repository for fitness data
        outdoor_activity_data_repo: Repository for outdoor activity data
        bushwalking_data_repo: Repository for bushwalking data
        jogging_data_repo: Repository for jogging data
        abseiling_data_repo: Repository for abseiling data
        canyoning_data_repo: Repository for canyoning data
        climbing_data_repo: Repository for climbing data
        kayaking_data_repo: Repository for kayaking data
        skiing_data_repo: Repository for cross-country skiing data
        snorkelling_data_repo: Repository for snorkelling data
        diving_data_repo: Repository for diving data
        downhill_skiing_data_repo: Repository for downhill skiing data
        outdoor_planning_data_repo: Repository for outdoor planning data
        outdoor_training_data_repo: Repository for outdoor training data
    """
    if journal_type == JournalType.MOOD_RATING:
        from core_shared.models.journals import MoodData

        if not await mood_data_repo.find_by_journal_id(journal_id):
            mood_data = MoodData(journal_id=journal_id)
            await mood_data_repo.save(mood_data)
    elif journal_type == JournalType.PLAN:
        from core_shared.models.journals import PlanData

        if not await plan_data_repo.find_by_journal_id(journal_id):
            plan_data = PlanData(journal_id=journal_id)
            await plan_data_repo.save(plan_data)
    elif journal_type == JournalType.TRAVEL:
        from core_shared.models.journals import TravelData

        if not await travel_data_repo.find_by_journal_id(journal_id):
            travel_data = TravelData(journal_id=journal_id)
            await travel_data_repo.save(travel_data)
    elif journal_type == JournalType.FITNESS:
        from core_shared.models.journals import FitnessData

        if not await fitness_data_repo.find_by_journal_id(journal_id):
            fitness_data = FitnessData(journal_id=journal_id)
            await fitness_data_repo.save(fitness_data)
    elif journal_type == JournalType.OUTDOOR_ACTIVITY:
        from core_shared.models.journals import OutdoorActivityData

        if not await outdoor_activity_data_repo.find_by_journal_id(journal_id):
            outdoor_activity_data = OutdoorActivityData(journal_id=journal_id)
            await outdoor_activity_data_repo.save(outdoor_activity_data)
    elif journal_type == JournalType.BUSHWALKING:
        from core_shared.models.journals import BushwalkingData

        if not await bushwalking_data_repo.find_by_journal_id(journal_id):
            bushwalking_data = BushwalkingData(journal_id=journal_id)
            await bushwalking_data_repo.save(bushwalking_data)
    elif journal_type == JournalType.JOGGING:
        from core_shared.models.journals import JoggingData

        if not await jogging_data_repo.find_by_journal_id(journal_id):
            jogging_data = JoggingData(journal_id=journal_id)
            await jogging_data_repo.save(jogging_data)
    elif journal_type == JournalType.ABSEILING_TRIP:
        from core_shared.models.journals import AbseilingData

        if not await abseiling_data_repo.find_by_journal_id(journal_id):
            abseiling_data = AbseilingData(journal_id=journal_id)
            await abseiling_data_repo.save(abseiling_data)
    elif journal_type == JournalType.CANYONING:
        from core_shared.models.journals import CanyoningData

        if not await canyoning_data_repo.find_by_journal_id(journal_id):
            canyoning_data = CanyoningData(journal_id=journal_id)
            await canyoning_data_repo.save(canyoning_data)
    elif journal_type == JournalType.CLIMBING:
        from core_shared.models.journals import ClimbingData

        if not await climbing_data_repo.find_by_journal_id(journal_id):
            climbing_data = ClimbingData(journal_id=journal_id)
            await climbing_data_repo.save(climbing_data)
    elif journal_type == JournalType.KAYAKING:
        from core_shared.models.journals import KayakingData

        if not await kayaking_data_repo.find_by_journal_id(journal_id):
            kayaking_data = KayakingData(journal_id=journal_id)
            await kayaking_data_repo.save(kayaking_data)
    elif journal_type == JournalType.CROSS_COUNTRY_SKIING:
        from core_shared.models.journals import (
            CrossCountrySkiingData,
        )

        if not await skiing_data_repo.find_by_journal_id(journal_id):
            skiing_data = CrossCountrySkiingData(journal_id=journal_id)
            await skiing_data_repo.save(skiing_data)
    elif journal_type == JournalType.CAVING:
        from core_shared.models.journals import CavingData

        if not await caving_data_repo.find_by_journal_id(journal_id):
            caving_data = CavingData(journal_id=journal_id)
            await caving_data_repo.save(caving_data)
    elif journal_type == JournalType.CANOEING:
        from core_shared.models.journals import CanoeingData

        if not await canoeing_data_repo.find_by_journal_id(journal_id):
            canoeing_data = CanoeingData(journal_id=journal_id)
            await canoeing_data_repo.save(canoeing_data)
    elif journal_type == JournalType.SNORKELLING:
        from core_shared.models.journals import SnorkellingData

        if not await snorkelling_data_repo.find_by_journal_id(journal_id):
            snorkelling_data = SnorkellingData(journal_id=journal_id)
            await snorkelling_data_repo.save(snorkelling_data)
    elif journal_type == JournalType.DIVING:
        from core_shared.models.journals import DivingData

        if not await diving_data_repo.find_by_journal_id(journal_id):
            diving_data = DivingData(journal_id=journal_id)
            await diving_data_repo.save(diving_data)
    elif journal_type == JournalType.DOWNHILL_SKIING:
        from core_shared.models.journals import DownhillSkiingData

        if not await downhill_skiing_data_repo.find_by_journal_id(journal_id):
            downhill_skiing_data = DownhillSkiingData(journal_id=journal_id)
            await downhill_skiing_data_repo.save(downhill_skiing_data)
    elif journal_type == JournalType.OUTDOOR_PLANNING:
        from core_shared.models.journals import OutdoorPlanningData

        if not await outdoor_planning_data_repo.find_by_journal_id(journal_id):
            outdoor_planning_data = OutdoorPlanningData(journal_id=journal_id)
            await outdoor_planning_data_repo.save(outdoor_planning_data)
    elif journal_type == JournalType.OUTDOOR_TRAINING:
        from core_shared.models.journals import OutdoorTrainingData

        if not await outdoor_training_data_repo.find_by_journal_id(journal_id):
            outdoor_training_data = OutdoorTrainingData(journal_id=journal_id)
            await outdoor_training_data_repo.save(outdoor_training_data)
    elif journal_type == JournalType.GEAR_MAINTENANCE:
        # GEAR_MAINTENANCE requires initial data and cannot be created with defaults.
        # Data is either populated by process_journal_type_data during creation
        # or required in add_type_to_journal.
        pass
    elif journal_type == JournalType.GEAR_USAGE:
        # GEAR_USAGE requires a gear_item_id and cannot be created with defaults.
        # Data is populated by process_journal_type_data during creation.
        pass
    # EVENT and PHOTO_ALBUM types require additional data (calendar_id, immich_album_id)
    # These will be created when the user updates the type data


async def delete_type_specific_data(
    journal_type: JournalType,
    journal_id: int,
    mood_data_repo: MoodDataRepository,
    plan_data_repo: PlanDataRepository,
    travel_data_repo: TravelDataRepository,
    photo_album_data_repo: AlbumSyncReadRepository,
    fitness_data_repo: FitnessDataRepository,
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
    bushwalking_data_repo: BushwalkingDataRepository,
    jogging_data_repo: JoggingDataRepository,
    abseiling_data_repo: AbseilingDataRepository,
    abseil_pitch_repo: AbseilPitchRepository,
    canyoning_data_repo: CanyoningDataRepository,
    caving_data_repo: CavingDataRepository,
    canoeing_data_repo: CanoeingDataRepository,
    climbing_data_repo: ClimbingDataRepository,
    kayaking_data_repo: KayakingDataRepository,
    skiing_data_repo: CrossCountrySkiingDataRepository,
    snorkelling_data_repo: SnorkellingDataRepository,
    diving_data_repo: DivingDataRepository,
    downhill_skiing_data_repo: DownhillSkiingDataRepository,
    outdoor_planning_data_repo: OutdoorPlanningDataRepository,
    outdoor_training_data_repo: OutdoorTrainingDataRepository,
    gear_maintenance_data_repo: GearMaintenanceDataRepository,
    gear_usage_data_repo: GearUsageDataRepository,
) -> None:
    """
    Delete the type-specific data row for the given journal type.

    Called when a type is removed from a journal so that the type row is cleaned
    up and the type no longer appears in enrichment responses.

    Args:
        journal_type: The type of journal being removed
        journal_id: The ID of the journal
    """
    if journal_type == JournalType.MOOD_RATING:
        await mood_data_repo.delete(journal_id)
    elif journal_type == JournalType.PLAN:
        await plan_data_repo.delete(journal_id)
    elif journal_type == JournalType.TRAVEL:
        await travel_data_repo.delete(journal_id)
    elif journal_type == JournalType.PHOTO_ALBUM:
        await photo_album_data_repo.delete(journal_id)
    elif journal_type == JournalType.FITNESS:
        await fitness_data_repo.delete(journal_id)
    elif journal_type == JournalType.OUTDOOR_ACTIVITY:
        await outdoor_activity_data_repo.delete(journal_id)
    elif journal_type == JournalType.BUSHWALKING:
        await bushwalking_data_repo.delete(journal_id)
    elif journal_type == JournalType.JOGGING:
        await jogging_data_repo.delete(journal_id)
    elif journal_type == JournalType.ABSEILING_TRIP:
        await abseiling_data_repo.delete(journal_id)
    elif journal_type == JournalType.CANYONING:
        await canyoning_data_repo.delete(journal_id)
    elif journal_type == JournalType.CLIMBING:
        await climbing_data_repo.delete(journal_id)
    elif journal_type == JournalType.KAYAKING:
        await kayaking_data_repo.delete(journal_id)
    elif journal_type == JournalType.CROSS_COUNTRY_SKIING:
        await skiing_data_repo.delete(journal_id)
    elif journal_type == JournalType.CAVING:
        await caving_data_repo.delete(journal_id)
    elif journal_type == JournalType.CANOEING:
        await canoeing_data_repo.delete(journal_id)
    elif journal_type == JournalType.SNORKELLING:
        await snorkelling_data_repo.delete(journal_id)
    elif journal_type == JournalType.DIVING:
        await diving_data_repo.delete(journal_id)
    elif journal_type == JournalType.DOWNHILL_SKIING:
        await downhill_skiing_data_repo.delete(journal_id)
    elif journal_type == JournalType.OUTDOOR_PLANNING:
        await outdoor_planning_data_repo.delete(journal_id)
    elif journal_type == JournalType.OUTDOOR_TRAINING:
        await outdoor_training_data_repo.delete(journal_id)
    elif journal_type == JournalType.GEAR_MAINTENANCE:
        await gear_maintenance_data_repo.delete(journal_id)
    elif journal_type == JournalType.GEAR_USAGE:
        await gear_usage_data_repo.delete(journal_id)
    # EVENT has no dedicated type-specific table (uses calendar_info via CalendarInfo)
    # and is handled by the service layer


async def update_event_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    calendar_info_repo: CalendarInfoRepository,
) -> None:
    """Update EVENT type-specific data."""
    from core_shared.models.journals.event_state import EventState

    calendar_info = await calendar_info_repo.find_by_journal_id(journal_id)
    if not calendar_info:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    updates: dict[str, Any] = {}

    if "calendar_id" in attrs:
        updates["calendar_id"] = UUID(attrs["calendar_id"])
    if "is_all_day" in attrs:
        is_all_day = attrs["is_all_day"]
        updates["is_all_day"] = is_all_day
        if is_all_day:
            # All-day updates must clear times if they aren't explicitly provided as None
            if "start_time" not in attrs:
                updates["start_time"] = None
            if "end_time" not in attrs:
                updates["end_time"] = None
    if "start_time" in attrs:
        updates["start_time"] = parse_optional_time(attrs["start_time"], "start_time")
    if "end_time" in attrs:
        updates["end_time"] = parse_optional_time(attrs["end_time"], "end_time")
    if "location" in attrs:
        updates["location"] = attrs["location"]
    if "timezone" in attrs:
        updates["timezone"] = attrs["timezone"]
    if "description" in attrs:
        updates["description"] = attrs["description"]
    if "sync_invitees" in attrs:
        updates["sync_invitees"] = attrs["sync_invitees"]
    if "private_description" in attrs:
        updates["private_description"] = attrs["private_description"]
    if "event_state" in attrs:
        try:
            updates["event_state"] = EventState(attrs["event_state"])
        except (ValueError, KeyError, TypeError) as e:
            raise JournalValidationError(
                "event_state",
                f"Invalid event state: {attrs['event_state']}. "
                f"Must be one of: {', '.join(e.value for e in EventState)}",
            ) from e

    try:
        from core_shared.models.journals.exceptions import CalendarInfoValidationError

        calendar_info = dataclasses.replace(calendar_info, **updates)
    except CalendarInfoValidationError as e:
        raise JournalValidationError("event_data", str(e.message)) from e

    await calendar_info_repo.save(calendar_info)


async def update_mood_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    mood_data_repo: MoodDataRepository,
) -> None:
    """Update MOOD_RATING type-specific data."""
    mood_data = await mood_data_repo.find_by_journal_id(journal_id)
    if not mood_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Update fields from request
    if "mood_value" in attrs:
        mood_data.mood_value = attrs["mood_value"]
    if "mood_label" in attrs:
        mood_data.mood_label = attrs["mood_label"]
    if "energy_level" in attrs:
        mood_data.energy_level = attrs["energy_level"]

    await mood_data_repo.save(mood_data)


async def update_fitness_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    fitness_data_repo: FitnessDataRepository,
) -> None:
    """Update FITNESS type-specific data."""
    fitness_data = await fitness_data_repo.find_by_journal_id(journal_id)
    if not fitness_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Update fields from request
    if "heart_rate_avg" in attrs:
        fitness_data.heart_rate_avg = attrs["heart_rate_avg"]
    if "heart_rate_max" in attrs:
        fitness_data.heart_rate_max = attrs["heart_rate_max"]
    if "distance" in attrs:
        fitness_data.distance = attrs["distance"]
    if "elevation_gain" in attrs:
        fitness_data.elevation_gain = attrs["elevation_gain"]
    if "elevation_loss" in attrs:
        fitness_data.elevation_loss = attrs["elevation_loss"]
    if "duration" in attrs:
        fitness_data.duration = attrs["duration"]
    if "calories" in attrs:
        fitness_data.calories = attrs["calories"]
    if "strava_activity_id" in attrs:
        fitness_data.strava_activity_id = attrs["strava_activity_id"]

    await fitness_data_repo.save(fitness_data)


async def update_outdoor_activity_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    outdoor_activity_data_repo: OutdoorActivityDataRepository,
) -> None:
    """Update OUTDOOR_ACTIVITY type-specific data."""
    outdoor_activity_data = await outdoor_activity_data_repo.find_by_journal_id(
        journal_id
    )
    if not outdoor_activity_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    # This ensures domain validation (e.g. no empty/whitespace strings) is enforced.
    updates: dict[str, Any] = {}
    if "weather_conditions" in attrs:
        updates["weather_conditions"] = attrs["weather_conditions"]
    if "role" in attrs:
        updates["role"] = attrs["role"]
    if "in_leadership_role" in attrs:
        updates["in_leadership_role"] = attrs["in_leadership_role"]
    if "participant_notes" in attrs:
        updates["participant_notes"] = attrs["participant_notes"]

    validated_data = dataclasses.replace(outdoor_activity_data, **updates)
    await outdoor_activity_data_repo.save(validated_data)


async def update_bushwalking_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    bushwalking_data_repo: BushwalkingDataRepository,
) -> None:
    """Update BUSHWALKING type-specific data."""
    bushwalking_data = await bushwalking_data_repo.find_by_journal_id(journal_id)
    if not bushwalking_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    # This ensures domain validation (e.g. valid track_grading) is enforced.
    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = parse_optional_uuid(attrs["route_id"], "route_id")
    if "track_grading" in attrs:
        updates["track_grading"] = attrs["track_grading"]

    validated_data = dataclasses.replace(bushwalking_data, **updates)
    await bushwalking_data_repo.save(validated_data)


async def update_jogging_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    jogging_data_repo: JoggingDataRepository,
) -> None:
    """Update JOGGING type-specific data."""
    jogging_data = await jogging_data_repo.find_by_journal_id(journal_id)
    if not jogging_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = parse_optional_uuid(attrs["route_id"], "route_id")
    if "pace" in attrs:
        updates["pace"] = attrs["pace"]

    validated_data = dataclasses.replace(jogging_data, **updates)
    await jogging_data_repo.save(validated_data)


def _build_plan_document(
    journal_id: int,
    doc: dict[str, Any],
    *,
    document_id: UUID,
    order_fallback: int,
) -> Any:
    """Build a PlanDocument from a request payload, coercing blank title/order.

    Shared by the create and update paths so both apply identical coercion (blank
    title -> "Untitled", missing order -> sequential index).
    """
    from core_shared.models.journals import PlanDocument

    title_raw = doc.get("title")
    if title_raw is not None and not isinstance(title_raw, str):
        raise JournalValidationError("documents", "document title must be a string")
    if not title_raw or not title_raw.strip():
        title = "Untitled"
    else:
        title = title_raw
    description = doc.get("description")
    if description is not None and not isinstance(description, str):
        raise JournalValidationError(
            "documents", "document description must be a string"
        )
    order_raw = doc.get("order")
    order = order_raw if isinstance(order_raw, int) else order_fallback
    return PlanDocument(
        id=document_id,
        journal_id=journal_id,
        url=doc["url"],
        title=title,
        description=description,
        order=order,
    )


async def update_plan_type_data(
    journal_id: int,
    attrs: dict[str, Any],
    plan_data_repo: PlanDataRepository,
) -> None:
    """Update PLAN type data, replacing its document collection.

    Ensures the ``PlanData`` row exists, then (when ``documents`` is provided)
    replaces the document set: incoming documents are matched to existing ones by
    ``url`` and **reuse the existing id** so per-row history reads as edits rather
    than churn (and new urls get a fresh id); documents whose url is absent from
    the payload are deleted. With no existing documents this matches the original
    create behaviour (fresh ids, no deletes).
    """
    import uuid

    from core_shared.models.journals import PlanData

    plan_data = await plan_data_repo.find_by_journal_id(journal_id)
    if plan_data is None:
        plan_data = PlanData(journal_id=journal_id)
        await plan_data_repo.save(plan_data)

    if "documents" not in attrs:
        return

    # The type-data update payload is a free-form dict, so validate the shape and
    # surface clean JournalValidationErrors (400) rather than letting a malformed
    # body raise TypeError/KeyError/AttributeError as a 500.
    documents_payload = attrs["documents"] or []
    if not isinstance(documents_payload, list):
        raise JournalValidationError("documents", "documents must be a list")

    existing = await plan_data_repo.get_documents(journal_id)
    existing_by_url = {d.url: d for d in existing}

    new_documents: list[Any] = []
    seen_urls: set[str] = set()
    for doc in documents_payload:
        if not isinstance(doc, dict):
            raise JournalValidationError("documents", "each document must be an object")
        url = doc.get("url")
        if not isinstance(url, str) or not url.strip():
            raise JournalValidationError(
                "documents", "each document requires a non-empty string 'url'"
            )
        if url in seen_urls:
            raise JournalValidationError(
                "documents", f"duplicate document url in payload: {url}"
            )
        match = existing_by_url.get(url)
        document_id = match.id if match is not None else uuid.uuid4()
        new_documents.append(
            _build_plan_document(
                journal_id,
                doc,
                document_id=document_id,
                order_fallback=len(new_documents),
            )
        )
        seen_urls.add(url)

    for document in new_documents:
        await plan_data_repo.save_document(document)

    # Delete documents that are no longer present in the payload.
    for document in existing:
        if document.url not in seen_urls:
            await plan_data_repo.delete_document(document.id)


async def update_abseiling_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    abseiling_data_repo: AbseilingDataRepository,
    abseil_pitch_repo: AbseilPitchRepository,
) -> None:
    """Update ABSEILING_TRIP type-specific data."""
    abseiling_data = await abseiling_data_repo.find_by_journal_id(journal_id)
    if not abseiling_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    # Validate types eagerly so mismatches return 400 rather than an unhandled TypeError.
    updates: dict[str, Any] = {}
    # The consolidated template reference (ITER16-001) lives here for every
    # abseiling-derived journal. Only touched when supplied, so a pitch-only edit
    # preserves it (read-modify-write via dataclasses.replace below).
    if "template_id" in attrs:
        updates["template_id"] = parse_optional_uuid(
            attrs["template_id"], "template_id"
        )
    if "number_of_abseils" in attrs:
        updates["number_of_abseils"] = parse_optional_integer(
            attrs["number_of_abseils"], "number_of_abseils"
        )
    if "total_length" in attrs:
        updates["total_length"] = parse_optional_integer(
            attrs["total_length"], "total_length"
        )
    if "number_of_setups" in attrs:
        updates["number_of_setups"] = parse_optional_integer(
            attrs["number_of_setups"], "number_of_setups"
        )
    if "number_of_rescues" in attrs:
        updates["number_of_rescues"] = parse_optional_integer(
            attrs["number_of_rescues"], "number_of_rescues"
        )

    validated_data = dataclasses.replace(abseiling_data, **updates)

    from core_shared.models.journals.abseil_pitch import AbseilPitch
    from pydantic import ValidationError

    from app.api.journals.schemas import AbseilPitchSchema
    from app.core.journal.services.abseiling_service import AbseilingService

    pitches: list[AbseilPitch] | None = None
    if "pitches" in attrs:
        raw_pitches = attrs["pitches"]
        if raw_pitches is None:
            pitches = []
        elif not isinstance(raw_pitches, list):
            raise JournalValidationError("pitches", "pitches must be an array")
        else:
            pitches = []
            for i, pitch_data in enumerate(raw_pitches):
                try:
                    parsed_pitch = AbseilPitchSchema.model_validate(pitch_data)
                    pitches.append(
                        AbseilPitch(
                            journal_id=journal_id,
                            pitch_number=parsed_pitch.pitch_number,
                            height=parsed_pitch.height,
                            anchor_location=parsed_pitch.anchor_location,
                            anchor_type=parsed_pitch.anchor_type,
                            did_rescue=parsed_pitch.did_rescue,
                            did_setup=parsed_pitch.did_setup,
                        )
                    )
                except ValidationError as e:
                    raise JournalValidationError(
                        f"pitches[{i}]", f"Invalid pitch data: {str(e)}"
                    ) from e

    service = AbseilingService()
    await service.update_abseiling_data(
        abseiling_data_repo, abseil_pitch_repo, validated_data, pitches
    )


async def update_canyoning_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    canyoning_data_repo: CanyoningDataRepository,
) -> None:
    """Update CANYONING type-specific data."""
    canyoning_data = await canyoning_data_repo.find_by_journal_id(journal_id)
    if not canyoning_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = parse_optional_uuid(attrs["route_id"], "route_id")
    if "template_id" in attrs:
        updates["template_id"] = parse_optional_uuid(
            attrs["template_id"], "template_id"
        )
    if "french_grade" in attrs:
        if not isinstance(attrs["french_grade"], str):
            raise JournalValidationError("french_grade", "Must be a string")
        updates["french_grade"] = attrs["french_grade"]
    if "water_guage_name" in attrs:
        updates["water_guage_name"] = attrs["water_guage_name"]
    if "water_guage_level" in attrs:
        updates["water_guage_level"] = parse_optional_integer(
            attrs["water_guage_level"], "water_guage_level"
        )
    if "is_vertical" in attrs:
        raw_is_vertical = attrs["is_vertical"]
        if raw_is_vertical is not None and not isinstance(raw_is_vertical, bool):
            raise JournalValidationError("is_vertical", "Must be a boolean or null")
        updates["is_vertical"] = raw_is_vertical
    if "is_night_canyon" in attrs:
        raw_is_night_canyon = attrs["is_night_canyon"]
        if raw_is_night_canyon is not None and not isinstance(
            raw_is_night_canyon, bool
        ):
            raise JournalValidationError("is_night_canyon", "Must be a boolean or null")
        updates["is_night_canyon"] = raw_is_night_canyon
    if "is_white_water" in attrs:
        raw_is_white_water = attrs["is_white_water"]
        if raw_is_white_water is not None and not isinstance(raw_is_white_water, bool):
            raise JournalValidationError("is_white_water", "Must be a boolean or null")
        updates["is_white_water"] = raw_is_white_water

    validated_data = dataclasses.replace(canyoning_data, **updates)
    await canyoning_data_repo.save(validated_data)


async def update_outdoor_training_type_data(
    journal_id: int,
    data: dict[str, Any],
    outdoor_training_data_repo: OutdoorTrainingDataRepository,
) -> None:
    """Update outdoor training specific data."""
    if not data:
        return

    entity = await outdoor_training_data_repo.find_by_journal_id(journal_id)
    if not entity:
        raise JournalValidationError(
            "type_data", f"Journal {journal_id} is missing OUTDOOR_TRAINING type data"
        )

    from pydantic import ValidationError

    from app.api.journals.schemas import OutdoorTrainingDataSchema

    try:
        validated_data = OutdoorTrainingDataSchema.model_validate(data)
    except ValidationError as e:
        error = e.errors()[0]
        field_path = ".".join(str(loc) for loc in error["loc"])
        raise JournalValidationError(field_path, error["msg"]) from e

    if "focus_areas" in data:
        from core_shared.models.journals.exceptions import (
            OutdoorTrainingDataValidationError,
        )

        try:
            entity = dataclasses.replace(entity, focus_areas=validated_data.focus_areas)
        except OutdoorTrainingDataValidationError as e:
            # e.message already contains the 'field: ' prefix, so we split it off
            message_without_prefix = e.message.split(": ", 1)[-1]
            raise JournalValidationError("focus_areas", message_without_prefix) from e

    await outdoor_training_data_repo.save(entity)


async def update_outdoor_planning_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    outdoor_planning_data_repo: OutdoorPlanningDataRepository,
) -> None:
    """Update OUTDOOR_PLANNING type-specific data."""
    data = await outdoor_planning_data_repo.find_by_journal_id(journal_id)
    if not data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    updates: dict[str, Any] = {}
    if "topics" in attrs:
        raw_topics = attrs["topics"]
        if raw_topics is not None and not isinstance(raw_topics, str):
            raise JournalValidationError("topics", "Must be a string or null")
        updates["topics"] = raw_topics
    if "activity_types" in attrs:
        raw_activity_types = attrs["activity_types"]
        if raw_activity_types is not None:
            if not isinstance(raw_activity_types, list):
                raise JournalValidationError("activity_types", "Must be a list or null")
            if not all(isinstance(x, str) for x in raw_activity_types):
                raise JournalValidationError(
                    "activity_types", "All items must be strings"
                )
        updates["activity_types"] = raw_activity_types

    validated_data = dataclasses.replace(data, **updates)
    await outdoor_planning_data_repo.save(validated_data)


async def update_gear_maintenance_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    gear_maintenance_data_repo: GearMaintenanceDataRepository,
) -> None:
    """Update or create GEAR_MAINTENANCE type-specific data."""
    from core_shared.models.journals import GearMaintenanceData
    from core_shared.models.journals.exceptions import (
        GearMaintenanceDataValidationError,
    )

    data = await gear_maintenance_data_repo.find_by_journal_id(journal_id)

    updates: dict[str, Any] = {}
    if "gear_item_id" in attrs:
        raw_gear_item_id = attrs["gear_item_id"]
        if not isinstance(raw_gear_item_id, str):
            raise JournalValidationError("gear_item_id", "Must be a string")
        try:
            updates["gear_item_id"] = UUID(raw_gear_item_id)
        except ValueError:
            raise JournalValidationError(
                "gear_item_id", "Must be a valid UUID"
            ) from None
    elif not data:
        raise JournalValidationError("gear_item_id", "Required")

    if "maintenance_type" in attrs:
        raw_maintenance_type = attrs["maintenance_type"]
        if not isinstance(raw_maintenance_type, str):
            raise JournalValidationError("maintenance_type", "Must be a string")
        updates["maintenance_type"] = raw_maintenance_type
    elif not data:
        raise JournalValidationError("maintenance_type", "Required")

    if "activity_types" in attrs:
        raw_activity_types = attrs["activity_types"]
        if raw_activity_types is not None:
            if not isinstance(raw_activity_types, list):
                raise JournalValidationError("activity_types", "Must be a list or null")
            if not all(isinstance(x, str) for x in raw_activity_types):
                raise JournalValidationError(
                    "activity_types", "All items must be strings"
                )
        updates["activity_types"] = raw_activity_types

    if "retirement_reason" in attrs:
        raw_retirement_reason = attrs["retirement_reason"]
        if raw_retirement_reason is not None and not isinstance(
            raw_retirement_reason, str
        ):
            raise JournalValidationError(
                "retirement_reason", "Must be a string or null"
            )
        updates["retirement_reason"] = raw_retirement_reason

    try:
        if data:
            new_params = dataclasses.asdict(data)
            new_params.update(updates)
            new_data = data.__class__(**new_params)
        else:
            new_data = GearMaintenanceData(journal_id=journal_id, **updates)
        await gear_maintenance_data_repo.save(new_data)
    except GearMaintenanceDataValidationError as e:
        # Extract the original message to prevent "field: field: message" duplication
        raw_msg = str(e)
        prefix = f"{e.field}: "
        if raw_msg.startswith(prefix):
            raw_msg = raw_msg[len(prefix) :]
        raise JournalValidationError(e.field, raw_msg) from e


async def update_gear_usage_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    gear_usage_data_repo: GearUsageDataRepository,
) -> None:
    """Update or create GEAR_USAGE type-specific data.

    Mirrors the behaviour previously inlined in the MCP ``update_journal_entry``
    tool: ``gear_item_id`` is required to create a new row, and the
    ``checkout_date`` / ``checkin_date`` ISO strings are parsed to ``datetime``.
    """
    from core_shared.models.journals.exceptions import GearUsageDataValidationError
    from core_shared.models.journals.gear_usage_data import GearUsageData

    data = await gear_usage_data_repo.find_by_journal_id(journal_id)

    updates: dict[str, Any] = {}
    if "gear_item_id" in attrs and attrs["gear_item_id"]:
        raw_gear_item_id = attrs["gear_item_id"]
        if not isinstance(raw_gear_item_id, str):
            raise JournalValidationError("gear_item_id", "Must be a string")
        try:
            updates["gear_item_id"] = UUID(raw_gear_item_id)
        except ValueError:
            raise JournalValidationError(
                "gear_item_id", "Must be a valid UUID"
            ) from None
    elif not data:
        raise JournalValidationError("gear_item_id", "Required")

    if "checkout_date" in attrs:
        updates["checkout_date"] = parse_optional_datetime(
            attrs["checkout_date"], "checkout_date"
        )
    if "checkin_date" in attrs:
        updates["checkin_date"] = parse_optional_datetime(
            attrs["checkin_date"], "checkin_date"
        )

    try:
        if data:
            new_data = dataclasses.replace(data, **updates)
        else:
            new_data = GearUsageData(journal_id=journal_id, **updates)
        await gear_usage_data_repo.save(new_data)
    except GearUsageDataValidationError as e:
        raw_msg = str(e)
        prefix = f"{e.field}: "
        if raw_msg.startswith(prefix):
            raw_msg = raw_msg[len(prefix) :]
        raise JournalValidationError(e.field, raw_msg) from e


async def update_caving_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    caving_data_repo: CavingDataRepository,
) -> None:
    """Update CAVING type-specific data."""
    caving_data = await caving_data_repo.find_by_journal_id(journal_id)
    if not caving_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    updates: dict[str, Any] = {}
    if "template_id" in attrs:
        updates["template_id"] = parse_optional_uuid(
            attrs["template_id"], "template_id"
        )
    if "is_vertical" in attrs:
        raw_is_vertical = attrs["is_vertical"]
        if raw_is_vertical is not None and not isinstance(raw_is_vertical, bool):
            raise JournalValidationError("is_vertical", "Must be a boolean or null")
        updates["is_vertical"] = raw_is_vertical
    if "is_horizontal" in attrs:
        raw_is_horizontal = attrs["is_horizontal"]
        if raw_is_horizontal is not None and not isinstance(raw_is_horizontal, bool):
            raise JournalValidationError("is_horizontal", "Must be a boolean or null")
        updates["is_horizontal"] = raw_is_horizontal

    validated_data = dataclasses.replace(caving_data, **updates)
    await caving_data_repo.save(validated_data)


async def update_canoeing_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    canoeing_data_repo: CanoeingDataRepository,
) -> None:
    """Update CANOEING type-specific data."""
    canoeing_data = await canoeing_data_repo.find_by_journal_id(journal_id)
    if not canoeing_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    updates: dict[str, Any] = {}
    if "water_type" in attrs:
        raw_water_type = attrs["water_type"]
        if raw_water_type is not None and not isinstance(raw_water_type, str):
            raise JournalValidationError("water_type", "Must be a string or null")
        updates["water_type"] = raw_water_type

    validated_data = dataclasses.replace(canoeing_data, **updates)
    await canoeing_data_repo.save(validated_data)


async def update_climbing_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    climbing_data_repo: ClimbingDataRepository,
) -> None:
    """Update CLIMBING type-specific data."""
    climbing_data = await climbing_data_repo.find_by_journal_id(journal_id)
    if not climbing_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    # Build update kwargs and use dataclasses.replace() to trigger __post_init__ validation.
    updates: dict[str, Any] = {}
    if "template_id" in attrs:
        updates["template_id"] = parse_optional_uuid(
            attrs["template_id"], "template_id"
        )
    if "climbing_type" in attrs:
        if not isinstance(attrs["climbing_type"], str):
            raise JournalValidationError("climbing_type", "Must be a string")
        updates["climbing_type"] = attrs["climbing_type"]
    if "grade" in attrs:
        updates["grade"] = parse_optional_integer(attrs["grade"], "grade")
    if "length" in attrs:
        updates["length"] = parse_optional_integer(attrs["length"], "length")
    if "indoor" in attrs:
        raw_indoor = attrs["indoor"]
        if not isinstance(raw_indoor, bool):
            raise JournalValidationError("indoor", "Must be a boolean")
        updates["indoor"] = raw_indoor

    validated_data = dataclasses.replace(climbing_data, **updates)
    await climbing_data_repo.save(validated_data)


async def update_kayaking_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    kayaking_data_repo: KayakingDataRepository,
) -> None:
    """Update KAYAKING type-specific data."""
    kayaking_data = await kayaking_data_repo.find_by_journal_id(journal_id)
    if not kayaking_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    updates: dict[str, Any] = {}
    if "water_type" in attrs:
        raw_water_type = attrs["water_type"]
        if raw_water_type is not None and not isinstance(raw_water_type, str):
            raise JournalValidationError("water_type", "Must be a string or null")
        updates["water_type"] = raw_water_type
    if "is_white_water" in attrs:
        raw_is_white_water = attrs["is_white_water"]
        if raw_is_white_water is not None and not isinstance(raw_is_white_water, bool):
            raise JournalValidationError("is_white_water", "Must be a boolean or null")
        updates["is_white_water"] = raw_is_white_water
    if "rapids_grade" in attrs:
        raw_rapids_grade = attrs["rapids_grade"]
        if raw_rapids_grade is not None and not isinstance(raw_rapids_grade, str):
            raise JournalValidationError("rapids_grade", "Must be a string or null")
        updates["rapids_grade"] = raw_rapids_grade

    validated_data = dataclasses.replace(kayaking_data, **updates)
    await kayaking_data_repo.save(validated_data)


async def update_cross_country_skiing_type_data(
    journal_id: int,
    journal_type: str,
    attrs: dict[str, Any],
    skiing_data_repo: CrossCountrySkiingDataRepository,
) -> None:
    """Update CROSS_COUNTRY_SKIING type-specific data."""
    skiing_data = await skiing_data_repo.find_by_journal_id(journal_id)
    if not skiing_data:
        raise JournalValidationError(
            "journal_type", f"Journal does not have type {journal_type}"
        )

    updates: dict[str, Any] = {}
    if "route_id" in attrs:
        updates["route_id"] = parse_optional_uuid(attrs["route_id"], "route_id")
    if "snow_conditions" in attrs:
        raw_snow_conditions = attrs["snow_conditions"]
        if raw_snow_conditions is not None and not isinstance(raw_snow_conditions, str):
            raise JournalValidationError("snow_conditions", "Must be a string or null")
        updates["snow_conditions"] = raw_snow_conditions

    validated_data = dataclasses.replace(skiing_data, **updates)
    await skiing_data_repo.save(validated_data)
