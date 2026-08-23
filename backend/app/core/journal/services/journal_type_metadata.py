"""Discovery metadata for journal types: descriptions, type_data fields, units
and closed vocabularies, as published by the MCP ``list_journal_types`` tool.

Units are stated per field so a client never has to infer them, and
``allowed_values`` / ``JOURNAL_ENUMS`` are derived from the core_shared enums so
there is a single source of truth. ``tests/unit/journal/test_journal_type_coverage.py``
fails if a :class:`JournalType` has no description here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

from core_shared.models.journals import JournalContactRelationshipType, JournalType
from core_shared.models.journals.constants import (
    VALID_ANCHOR_LOCATIONS,
    VALID_ANCHOR_TYPES,
    VALID_CANYON_TYPES,
    VALID_CLIMBING_TYPES,
    VALID_MAINTENANCE_TYPES,
    VALID_PITCH_TYPES,
    VALID_RAPIDS_GRADES,
    VALID_TEMPLATE_TYPES,
    VALID_TRACK_GRADES,
)

JOURNAL_TYPE_DESCRIPTIONS: dict[str, str] = {
    "NOTE": "Simple text note using only base journal fields (no type_data needed)",
    "EVENT": "Calendar event with time and location",
    "MOOD_RATING": "Mood and energy level tracking",
    "PLAN": "Event planning with a list of linked documents",
    "TRAVEL": "Travel itinerary (no specific type_data fields)",
    "PHOTO_ALBUM": "Photo album linked to Immich",
    "FITNESS": "Base fitness activity with optional metrics",
    "OUTDOOR_ACTIVITY": "Outdoor activity extending FITNESS",
    "BUSHWALKING": "Bushwalking/hiking activity",
    "JOGGING": "Jogging/running activity",
    "ABSEILING_TRIP": "Abseiling/rappelling trip",
    "CANYONING": "Canyoning trip (combines bushwalking + abseiling)",
    "CLIMBING": "Climbing activity (includes abseiling pitches via dependency)",
    "KAYAKING": "Kayaking activity (with optional white water tracking)",
    "CROSS_COUNTRY_SKIING": "Cross-country skiing activity",
    "CAVING": "Caving trip (includes abseiling pitches via dependency)",
    "CANOEING": "Canoeing activity",
    "SNORKELLING": "Snorkelling activity (no specific type_data fields)",
    "DIVING": "Diving activity (no specific type_data fields)",
    "DOWNHILL_SKIING": "Downhill skiing activity (no specific type_data fields)",
    "OUTDOOR_PLANNING": "Outdoor planning meeting (an EVENT about upcoming activities)",
    "OUTDOOR_TRAINING": "Outdoor skills training session",
    "GEAR_MAINTENANCE": "Maintenance or retirement of a gear item",
    "GEAR_USAGE": "Checkout/checkin of a gear item",
}


class TypeDataFieldSpec(NamedTuple):
    """Discovery metadata for one type_data field (see list_journal_types)."""

    type: str
    description: str = ""
    unit: str | None = None
    required: bool = False
    allowed_values: Sequence[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        summary = self.type
        if self.unit:
            summary += f" in {self.unit}"
        summary += " (required)" if self.required else " (optional)"
        spec: dict[str, Any] = {
            "type": self.type,
            "unit": self.unit,
            "required": self.required,
            "description": self.description,
            "summary": summary,
        }
        if self.allowed_values is not None:
            spec["allowed_values"] = list(self.allowed_values)
        return spec


PITCH_FIELDS_DESCRIPTION = (
    "list of pitch objects. pitch_number (int) is required. Optional: height "
    "(int, metres), anchor_location (see enums.anchor_locations), anchor_type "
    "(see enums.anchor_types), did_rescue (bool), did_setup (bool), notes (str)"
)

# Keyed by JournalType name; every field the type_data for that type accepts.
# Units are stated explicitly so an agent never has to infer them.
JOURNAL_TYPE_DATA_FIELDS: dict[str, dict[str, TypeDataFieldSpec]] = {
    "EVENT": {
        "calendar_id": TypeDataFieldSpec("uuid", "UUID of the calendar", required=True),
        "start_time": TypeDataFieldSpec("string", "Start time (HH:MM or ISO datetime)"),
        "end_time": TypeDataFieldSpec("string", "End time (HH:MM or ISO datetime)"),
        "is_all_day": TypeDataFieldSpec("bool", "All-day event (default false)"),
        "location": TypeDataFieldSpec("string", "Free-text location"),
        "timezone": TypeDataFieldSpec("string", "IANA timezone name"),
        "event_state": TypeDataFieldSpec("string", "Event state (default 'confirmed')"),
    },
    "MOOD_RATING": {
        "mood_value": TypeDataFieldSpec(
            "int", "Mood on a 1-10 scale", unit="1-10 scale"
        ),
        "mood_label": TypeDataFieldSpec("string", "Free-text mood label"),
        "energy_level": TypeDataFieldSpec(
            "int", "Energy on a 1-10 scale", unit="1-10 scale"
        ),
    },
    "PLAN": {
        "documents": TypeDataFieldSpec(
            "list",
            "Linked documents, replacing the whole list. Each: url (str, "
            "required), title (str), description (str), order (int)",
        ),
    },
    "PHOTO_ALBUM": {
        "immich_album_id": TypeDataFieldSpec("uuid", "Immich album UUID"),
    },
    "FITNESS": {
        "heart_rate_avg": TypeDataFieldSpec("int", "Average heart rate", unit="bpm"),
        "heart_rate_max": TypeDataFieldSpec("int", "Maximum heart rate", unit="bpm"),
        "distance": TypeDataFieldSpec(
            "int",
            "Distance in whole kilometres (fractions are truncated)",
            unit="km",
        ),
        "elevation_gain": TypeDataFieldSpec("int", "Total ascent", unit="m"),
        "elevation_loss": TypeDataFieldSpec("int", "Total descent", unit="m"),
        "duration": TypeDataFieldSpec("int", "Elapsed time", unit="minutes"),
        "calories": TypeDataFieldSpec("int", "Energy expended", unit="kcal"),
        "strava_activity_id": TypeDataFieldSpec(
            "string", "Linked Strava activity id (creates the Strava external link)"
        ),
    },
    "OUTDOOR_ACTIVITY": {
        "weather_conditions": TypeDataFieldSpec(
            "string", "Weather during the activity"
        ),
        "role": TypeDataFieldSpec(
            "string",
            "User's role on trip. Max 5 words. E.g. 'Guide', 'Organiser', 'Course Leader'.",
        ),
        "in_leadership_role": TypeDataFieldSpec("bool", "Whether you led the trip"),
        "participant_notes": TypeDataFieldSpec(
            "string", "Notes about participants not listed via contact relationships"
        ),
    },
    "BUSHWALKING": {
        "track_grading": TypeDataFieldSpec(
            "string",
            "Australian Walking Track Grading System grade",
            allowed_values=VALID_TRACK_GRADES,
        ),
    },
    "JOGGING": {
        "pace": TypeDataFieldSpec("string", "Pace, e.g. '5:30/km'", unit="min/km"),
    },
    "ABSEILING_TRIP": {
        "template_id": TypeDataFieldSpec(
            "uuid",
            "Activity template this abseiling-derived journal was created from "
            "(preserved when pitches are edited)",
        ),
        "number_of_abseils": TypeDataFieldSpec("int", "Count of abseils"),
        "total_length": TypeDataFieldSpec("int", "Total abseiled length", unit="m"),
        "number_of_setups": TypeDataFieldSpec("int", "Anchors you set up"),
        "number_of_rescues": TypeDataFieldSpec("int", "Rescues performed"),
        "pitches": TypeDataFieldSpec("list", PITCH_FIELDS_DESCRIPTION),
    },
    "CANYONING": {
        "french_grade": TypeDataFieldSpec(
            "string", "French canyon grade, e.g. 'v3a2IV**' (v1-7, a1-7, I-VI, *-***)"
        ),
        "water_guage_name": TypeDataFieldSpec("string", "Name of the water gauge used"),
        "water_guage_level": TypeDataFieldSpec(
            "int", "Gauge reading at the time of the trip", unit="gauge units"
        ),
        "is_vertical": TypeDataFieldSpec("bool", "Primarily vertical canyon"),
        "is_night_canyon": TypeDataFieldSpec("bool", "Done at night"),
        "is_white_water": TypeDataFieldSpec("bool", "Significant white water"),
    },
    "CLIMBING": {
        "template_id": TypeDataFieldSpec("uuid", "Activity template reference"),
        "climbing_type": TypeDataFieldSpec(
            "string", "Climbing discipline", allowed_values=VALID_CLIMBING_TYPES
        ),
        "grade": TypeDataFieldSpec("int", "Ewbank (Australian) grade"),
        "length": TypeDataFieldSpec("int", "Route length", unit="m"),
        "indoor": TypeDataFieldSpec(
            "bool", "Indoor climb (default false) — independent of climbing_type"
        ),
    },
    "KAYAKING": {
        "water_type": TypeDataFieldSpec(
            "string", "Type of water body (river, lake, sea)"
        ),
        "is_white_water": TypeDataFieldSpec("bool", "White-water paddle"),
        "rapids_grade": TypeDataFieldSpec(
            "string",
            "International Scale of River Difficulty",
            allowed_values=VALID_RAPIDS_GRADES,
        ),
    },
    "CROSS_COUNTRY_SKIING": {
        "snow_conditions": TypeDataFieldSpec("string", "Snow conditions"),
    },
    "CAVING": {
        "is_vertical": TypeDataFieldSpec("bool", "Vertical cave (SRT)"),
        "is_horizontal": TypeDataFieldSpec("bool", "Horizontal cave"),
    },
    "CANOEING": {
        "water_type": TypeDataFieldSpec(
            "string", "Type of water body (river, lake, sea)"
        ),
    },
    "OUTDOOR_PLANNING": {
        "topics": TypeDataFieldSpec("string", "Meeting topics"),
        "activity_types": TypeDataFieldSpec(
            "list[string]", "Outdoor activity types the meeting relates to"
        ),
    },
    "OUTDOOR_TRAINING": {
        "focus_areas": TypeDataFieldSpec(
            "list[string]", "Activity subtypes trained, or free text"
        ),
    },
    "GEAR_MAINTENANCE": {
        "gear_item_id": TypeDataFieldSpec("uuid", "Gear item", required=True),
        "maintenance_type": TypeDataFieldSpec(
            "string",
            "Kind of maintenance",
            required=True,
            allowed_values=VALID_MAINTENANCE_TYPES,
        ),
        "activity_types": TypeDataFieldSpec("list[string]", "Related activity types"),
        "retirement_reason": TypeDataFieldSpec("string", "Why the item was retired"),
    },
    "GEAR_USAGE": {
        "gear_item_id": TypeDataFieldSpec("uuid", "Gear item", required=True),
        "checkout_date": TypeDataFieldSpec("datetime", "ISO datetime checked out"),
        "checkin_date": TypeDataFieldSpec("datetime", "ISO datetime checked in"),
    },
}

# Closed vocabularies surfaced by list_journal_types so an agent can discover
# valid values up front instead of through validation failures.
JOURNAL_ENUMS: dict[str, Sequence[str]] = {
    "anchor_types": VALID_ANCHOR_TYPES,
    "anchor_locations": VALID_ANCHOR_LOCATIONS,
    "pitch_types": VALID_PITCH_TYPES,
    "canyon_types": VALID_CANYON_TYPES,
    "climbing_types": VALID_CLIMBING_TYPES,
    "template_types": VALID_TEMPLATE_TYPES,
    "track_grades": VALID_TRACK_GRADES,
    "rapids_grades": VALID_RAPIDS_GRADES,
    "maintenance_types": VALID_MAINTENANCE_TYPES,
}


JOURNAL_UNITS: dict[str, str] = {
    "distance": "km (whole kilometres)",
    "elevation_gain": "m",
    "elevation_loss": "m",
    "duration": "minutes",
    "total_length": "m",
    "length": "m",
    "height": "m",
    "heart_rate_avg": "bpm",
    "heart_rate_max": "bpm",
    "calories": "kcal",
}


def describe_journal_types() -> dict[str, Any]:
    """The full type catalogue an agent needs before writing type_data."""
    from core_shared.models.journals.attendee_status import AttendeeStatus
    from core_shared.models.journals.contact_event_role import ContactEventRole

    types_info: list[dict[str, Any]] = []

    for jt in JournalType:
        type_name = jt.name
        deps = JournalType.get_dependencies(jt)
        dep_names = [d.name for d in deps]

        entry: dict[str, Any] = {
            "name": type_name,
            "description": JOURNAL_TYPE_DESCRIPTIONS.get(type_name, ""),
            "dependencies": dep_names,
        }
        fields = JOURNAL_TYPE_DATA_FIELDS.get(type_name)
        entry["type_data_fields"] = (
            {name: spec.as_dict() for name, spec in fields.items()} if fields else None
        )

        types_info.append(entry)

    # Also include contact_relationship enum info
    contact_enums = {
        "relationship_types": [t.name for t in JournalContactRelationshipType],
        "attendee_statuses": [s.name for s in AttendeeStatus],
        "contact_event_roles": [r.name for r in ContactEventRole],
    }

    result = {
        "journal_types": types_info,
        "contact_relationship_enums": contact_enums,
        "enums": {name: list(values) for name, values in JOURNAL_ENUMS.items()},
        "units": dict(JOURNAL_UNITS),
        "usage_hint": (
            "Pass type names in the 'types' field of create/update journal_data. "
            "Dependencies are added automatically; NOTE is implicit and ignored "
            "when combined with other types. Pass type-specific data in the "
            "'type_data' field keyed by type name. Each field lists its type, "
            "unit, whether it is required, and allowed_values where the "
            "vocabulary is closed; 'enums' repeats every closed vocabulary."
        ),
    }

    return result
