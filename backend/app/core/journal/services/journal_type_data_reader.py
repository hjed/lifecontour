"""Read a journal's types and type_data from the per-type data repositories.

Type membership is the presence of a type-data row. ``TYPE_DATA_READERS`` maps
every type except NOTE to the repository attribute holding its row and the
function rendering that row as a plain dict; a type missing here is written
but never read back, so ``tests/unit/journal/test_journal_type_coverage.py``
enforces completeness.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from core_shared.models.journals import JournalType


def _build_calendar_data(calendar_info: Any) -> dict[str, Any]:
    """Build calendar event data dictionary."""
    return {
        "calendar_id": str(calendar_info.calendar_id),
        "start_time": calendar_info.start_time.isoformat()
        if calendar_info.start_time
        else None,
        "end_time": calendar_info.end_time.isoformat()
        if calendar_info.end_time
        else None,
        "is_all_day": calendar_info.is_all_day,
        "location": calendar_info.location,
        "description": calendar_info.description,
        "timezone": calendar_info.timezone,
        "sync_invitees": calendar_info.sync_invitees,
        "private_description": calendar_info.private_description,
        "event_state": calendar_info.event_state.value
        if hasattr(calendar_info.event_state, "value")
        else calendar_info.event_state,
    }


def _build_mood_data(mood_data: Any) -> dict[str, Any]:
    """Build mood rating data dictionary."""
    return {
        "mood_value": mood_data.mood_value,
        "mood_label": mood_data.mood_label,
        "energy_level": mood_data.energy_level,
    }


def _build_plan_data(plan_data: Any) -> dict[str, Any]:
    """Build plan data dictionary."""
    return {
        "documents": [
            {
                "title": doc.title,
                "url": doc.url,
                "description": doc.description,
            }
            for doc in plan_data.documents
        ]
        if plan_data.documents
        else [],
    }


def _build_travel_data(travel_data: Any) -> dict[str, Any]:
    """Build travel data dictionary."""
    return {
        "flights": [
            {
                "airline": flight.airline,
                "flight_number": flight.flight_number,
                "departure_airport": flight.departure_airport,
                "arrival_airport": flight.arrival_airport,
                "departure_time": flight.departure_time.isoformat()
                if flight.departure_time
                else None,
                "arrival_time": flight.arrival_time.isoformat()
                if flight.arrival_time
                else None,
                "booking_reference": flight.booking_reference,
            }
            for flight in travel_data.flights
        ]
        if travel_data.flights
        else [],
        "accommodations": [
            {
                "name": acc.name,
                "address": acc.address,
                "check_in_date": acc.check_in_date.isoformat()
                if acc.check_in_date
                else None,
                "check_out_date": acc.check_out_date.isoformat()
                if acc.check_out_date
                else None,
                "booking_reference": acc.booking_reference,
            }
            for acc in travel_data.accommodations
        ]
        if travel_data.accommodations
        else [],
        "transportation": [
            {
                "type": trans.type,
                "details": trans.details,
                "booking_reference": trans.booking_reference,
            }
            for trans in travel_data.transportation
        ]
        if travel_data.transportation
        else [],
    }


def _build_photo_album_data(photo_album_data: dict[str, Any]) -> dict[str, Any]:
    """Build photo album data dictionary from Immich album sync data.

    ``photo_album_data`` comes from ``AlbumSyncReadRepository.find_by_journal_id``
    and contains ``immich_album_id`` plus optional album display fields.
    """
    return dict(photo_album_data)


def _build_fitness_data(fitness_data: Any) -> dict[str, Any]:
    """Build fitness data dictionary."""
    return {
        "heart_rate_avg": fitness_data.heart_rate_avg,
        "heart_rate_max": fitness_data.heart_rate_max,
        "distance": fitness_data.distance,
        "elevation_gain": fitness_data.elevation_gain,
        "elevation_loss": fitness_data.elevation_loss,
        "duration": fitness_data.duration,
        "calories": fitness_data.calories,
        "strava_activity_id": fitness_data.strava_activity_id,
    }


def _build_outdoor_activity_data(outdoor_activity_data: Any) -> dict[str, Any]:
    """Build outdoor activity data dictionary."""
    return {
        "weather_conditions": outdoor_activity_data.weather_conditions,
        "role": outdoor_activity_data.role,
        "in_leadership_role": outdoor_activity_data.in_leadership_role,
        "participant_notes": outdoor_activity_data.participant_notes,
    }


def _build_bushwalking_data(bushwalking_data: Any) -> dict[str, Any]:
    """Build bushwalking data dictionary."""
    return {
        "track_grading": bushwalking_data.track_grading,
    }


def _build_jogging_data(jogging_data: Any) -> dict[str, Any]:
    """Build jogging data dictionary."""
    return {
        "pace": jogging_data.pace,
    }


def _build_abseiling_data(abseiling_data: Any) -> dict[str, Any]:
    """Build abseiling data dictionary."""
    return {
        "template_id": str(abseiling_data.template_id)
        if abseiling_data.template_id
        else None,
        "number_of_abseils": abseiling_data.number_of_abseils,
        "total_length": abseiling_data.total_length,
        "number_of_setups": abseiling_data.number_of_setups,
        "number_of_rescues": abseiling_data.number_of_rescues,
    }


def _build_caving_data(caving_data: Any) -> dict[str, Any]:
    """Build caving data dictionary."""
    return {
        "is_vertical": caving_data.is_vertical,
        "is_horizontal": caving_data.is_horizontal,
    }


def _build_canyoning_data(canyoning_data: Any) -> dict[str, Any]:
    """Build canyoning data dictionary."""
    return {
        "french_grade": canyoning_data.french_grade,
        "water_guage_name": canyoning_data.water_guage_name,
        "water_guage_level": canyoning_data.water_guage_level,
        "is_vertical": canyoning_data.is_vertical,
        "is_night_canyon": canyoning_data.is_night_canyon,
        "is_white_water": canyoning_data.is_white_water,
    }


def _build_climbing_data(climbing_data: Any) -> dict[str, Any]:
    """Build climbing data dictionary."""
    return {
        "climbing_type": climbing_data.climbing_type,
        "grade": climbing_data.grade,
        "length": climbing_data.length,
        "indoor": climbing_data.indoor,
    }


def _build_kayaking_data(kayaking_data: Any) -> dict[str, Any]:
    """Build kayaking data dictionary."""
    return {
        "water_type": kayaking_data.water_type,
        "is_white_water": kayaking_data.is_white_water,
        "rapids_grade": kayaking_data.rapids_grade,
    }


def _build_cross_country_skiing_data(
    cross_country_skiing_data: Any,
) -> dict[str, Any]:
    """Build cross-country skiing data dictionary."""
    return {
        "snow_conditions": cross_country_skiing_data.snow_conditions,
    }


def _build_canoeing_data(canoeing_data: Any) -> dict[str, Any]:
    """Build canoeing data dictionary."""
    return {"water_type": canoeing_data.water_type}


def _build_presence_only_data(_data: Any) -> dict[str, Any]:
    """Types whose row records membership only (no editable fields)."""
    return {}


def _build_outdoor_planning_data(outdoor_planning_data: Any) -> dict[str, Any]:
    """Build outdoor planning data dictionary."""
    return {
        "topics": outdoor_planning_data.topics,
        "activity_types": list(outdoor_planning_data.activity_types or []),
    }


def _build_outdoor_training_data(outdoor_training_data: Any) -> dict[str, Any]:
    """Build outdoor training data dictionary."""
    return {"focus_areas": list(outdoor_training_data.focus_areas or [])}


def _build_gear_maintenance_data(gear_maint_data: Any) -> dict[str, Any]:
    """Build gear maintenance data dictionary."""
    return {
        "gear_item_id": str(gear_maint_data.gear_item_id)
        if gear_maint_data.gear_item_id
        else None,
        "maintenance_type": gear_maint_data.maintenance_type,
        "activity_types": gear_maint_data.activity_types,
        "retirement_reason": gear_maint_data.retirement_reason,
    }


def _build_gear_usage_data(gear_usage_data: Any) -> dict[str, Any]:
    """Build gear usage data dictionary."""
    return {
        "gear_item_id": str(gear_usage_data.gear_item_id)
        if gear_usage_data.gear_item_id
        else None,
        "checkout_date": gear_usage_data.checkout_date.isoformat()
        if gear_usage_data.checkout_date
        else None,
        "checkin_date": gear_usage_data.checkin_date.isoformat()
        if gear_usage_data.checkin_date
        else None,
    }


class TypeDataReader(NamedTuple):
    """How to detect one journal type and render its type_data for MCP."""

    repo_attr: str
    build: Callable[[Any], dict[str, Any]]


# Every journal type except NOTE (which is the absence of typed rows), in the
# order types are reported. A type missing here is written but never read back,
# so tests/unit/journal/test_journal_type_coverage.py enforces completeness.
TYPE_DATA_READERS: dict[JournalType, TypeDataReader] = {
    JournalType.EVENT: TypeDataReader("calendar_info_repo", _build_calendar_data),
    JournalType.MOOD_RATING: TypeDataReader("mood_data_repo", _build_mood_data),
    JournalType.PLAN: TypeDataReader("plan_data_repo", _build_plan_data),
    JournalType.TRAVEL: TypeDataReader("travel_data_repo", _build_travel_data),
    JournalType.PHOTO_ALBUM: TypeDataReader(
        "photo_album_data_repo", _build_photo_album_data
    ),
    JournalType.FITNESS: TypeDataReader("fitness_data_repo", _build_fitness_data),
    JournalType.OUTDOOR_ACTIVITY: TypeDataReader(
        "outdoor_activity_data_repo", _build_outdoor_activity_data
    ),
    JournalType.BUSHWALKING: TypeDataReader(
        "bushwalking_data_repo", _build_bushwalking_data
    ),
    JournalType.JOGGING: TypeDataReader("jogging_data_repo", _build_jogging_data),
    JournalType.ABSEILING_TRIP: TypeDataReader(
        "abseiling_data_repo", _build_abseiling_data
    ),
    JournalType.CAVING: TypeDataReader("caving_data_repo", _build_caving_data),
    JournalType.CANYONING: TypeDataReader("canyoning_data_repo", _build_canyoning_data),
    JournalType.CLIMBING: TypeDataReader("climbing_data_repo", _build_climbing_data),
    JournalType.KAYAKING: TypeDataReader("kayaking_data_repo", _build_kayaking_data),
    JournalType.CROSS_COUNTRY_SKIING: TypeDataReader(
        "cross_country_skiing_data_repo", _build_cross_country_skiing_data
    ),
    JournalType.CANOEING: TypeDataReader("canoeing_data_repo", _build_canoeing_data),
    JournalType.SNORKELLING: TypeDataReader(
        "snorkelling_data_repo", _build_presence_only_data
    ),
    JournalType.DIVING: TypeDataReader("diving_data_repo", _build_presence_only_data),
    JournalType.DOWNHILL_SKIING: TypeDataReader(
        "downhill_skiing_data_repo", _build_presence_only_data
    ),
    JournalType.OUTDOOR_PLANNING: TypeDataReader(
        "outdoor_planning_data_repo", _build_outdoor_planning_data
    ),
    JournalType.OUTDOOR_TRAINING: TypeDataReader(
        "outdoor_training_data_repo", _build_outdoor_training_data
    ),
    JournalType.GEAR_MAINTENANCE: TypeDataReader(
        "gear_maintenance_data_repo", _build_gear_maintenance_data
    ),
    JournalType.GEAR_USAGE: TypeDataReader(
        "gear_usage_data_repo", _build_gear_usage_data
    ),
}


async def read_journal_types_and_data(
    journal_id: int, repos: Any
) -> tuple[list[str], dict[str, Any]]:
    """Fetch a journal's types and type-specific data via ``TYPE_DATA_READERS``.

    Returns:
        Tuple of (types list, type_data dict keyed by type value)
    """
    types: list[str] = []
    type_data: dict[str, Any] = {}

    for journal_type, reader in TYPE_DATA_READERS.items():
        repo = getattr(repos, reader.repo_attr)
        data = await repo.find_by_journal_id(journal_id)
        if data:
            types.append(journal_type.value)
            type_data[journal_type.value] = reader.build(data)

    # No typed row at all means the journal is a plain NOTE.
    if not types:
        types.append(JournalType.NOTE.value)

    return types, type_data
