"""Discovery metadata for journal types: descriptions, type_data fields, units
and closed vocabularies, as published by the MCP ``list_journal_types`` tool.

Units are stated per field so a client never has to infer them, and
``allowed_values`` / ``JOURNAL_ENUMS`` are derived from the core_shared enums so
there is a single source of truth. ``tests/unit/journal/test_journal_type_coverage.py``
fails if a :class:`JournalType` has no description here.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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
from core_shared.models.journals.event_state import EventState
from core_shared.models.journals.outdoor_activity_subtypes import OutdoorActivitySubtype
from core_shared.models.journals.type_data_schemas import TYPE_DATA_MODELS

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
    "GEAR_USAGE": "The gear items used, each with an optional checkout/checkin window",
}


# JSON Schema's own vocabulary, translated to the short type names this tool
# has always published. A caller reads "int" and "uuid", not "integer" with a
# format keyword.
_JSON_TYPE_NAMES: dict[str, str] = {
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "string": "string",
    "object": "object",
}

_FORMAT_TYPE_NAMES: dict[str, str] = {
    "uuid": "uuid",
    "date-time": "datetime",
    "date": "date",
    "time": "time",
}

# Constraint keywords worth publishing, and the name each is published under.
# JSON Schema's names are kept where they are already plain (``pattern``);
# ``maxLength`` becomes ``max_length`` to match the snake_case of everything
# else in the payload.
_CONSTRAINT_KEYS: dict[str, str] = {
    "maxLength": "max_length",
    "minLength": "min_length",
    "minimum": "minimum",
    "maximum": "maximum",
    "pattern": "pattern",
}


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Flatten one property's schema to the branch that carries its rules.

    Pydantic renders an optional field as ``anyOf: [{...}, {"type": "null"}]``
    and an enum or nested model as a ``$ref`` into ``$defs``, so the constraints
    a caller needs are never on the property itself.
    """
    own = {k: v for k, v in node.items() if k not in ("$ref", "anyOf")}

    if "$ref" in node:
        target = defs.get(node["$ref"].rsplit("/", 1)[1], {})
        # The field's own keys win: a ``$ref`` to an enum carries that enum
        # class's docstring as ``description``, which would otherwise replace
        # what the field says about itself.
        return {**target, **own}

    if "anyOf" in node:
        for branch in node["anyOf"]:
            if branch.get("type") == "null":
                continue
            return {**_resolve(branch, defs), **own}

    return node


def _type_name(schema: dict[str, Any], defs: dict[str, Any]) -> str:
    """The short type name for a resolved property schema."""
    if "enum" in schema:
        return "string"

    json_type = schema.get("type")
    if json_type == "array":
        item = _resolve(schema.get("items", {}), defs)
        return f"list[{_type_name(item, defs)}]"

    fmt = schema.get("format")
    if json_type == "string" and fmt in _FORMAT_TYPE_NAMES:
        return _FORMAT_TYPE_NAMES[fmt]

    return str(_JSON_TYPE_NAMES.get(str(json_type), "any"))


def _summarise(spec: dict[str, Any]) -> str:
    """The one-line human summary, now carrying the field's limits.

    An agent that reads only this line still learns the cap it would otherwise
    discover by breaching it.
    """
    summary: str = str(spec["type"])
    if spec.get("unit"):
        summary += f" in {spec['unit']}"
    summary += " (required" if spec["required"] else " (optional"

    limits: list[str] = []
    if spec.get("max_length") is not None:
        limits.append(f"max {spec['max_length']} chars")
    minimum, maximum = spec.get("minimum"), spec.get("maximum")
    if minimum is not None and maximum is not None:
        limits.append(f"{minimum}-{maximum}")
    elif minimum is not None:
        limits.append(f"min {minimum}")
    elif maximum is not None:
        limits.append(f"max {maximum}")
    if spec.get("pattern"):
        limits.append("must match pattern")
    if spec.get("allowed_values"):
        limits.append(f"one of {len(spec['allowed_values'])} values")

    if limits:
        summary += ", " + ", ".join(limits)
    return summary + ")"


def _describe_field(
    name: str,
    node: dict[str, Any],
    defs: dict[str, Any],
    required: set[str],
) -> dict[str, Any]:
    """Publish one type_data field from its JSON Schema."""
    schema = _resolve(node, defs)

    spec: dict[str, Any] = {
        "type": _type_name(schema, defs),
        "unit": schema.get("unit"),
        "required": name in required,
        "description": schema.get("description", ""),
    }

    for json_key, published in _CONSTRAINT_KEYS.items():
        if json_key in schema:
            spec[published] = schema[json_key]

    if "enum" in schema:
        spec["allowed_values"] = list(schema["enum"])
    elif schema.get("type") == "array":
        item = _resolve(schema.get("items", {}), defs)
        if "enum" in item:
            spec["allowed_values"] = list(item["enum"])
        elif "properties" in item:
            spec["fields"] = _describe_fields(item, defs)

    if "properties" in schema and spec["type"] == "object":
        spec["fields"] = _describe_fields(schema, defs)

    spec["summary"] = _summarise(spec)
    return spec


def _describe_fields(
    schema: dict[str, Any], defs: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Publish every field of one model's JSON Schema."""
    required = set(schema.get("required", []))
    return {
        name: _describe_field(name, node, defs, required)
        for name, node in schema.get("properties", {}).items()
    }


def describe_type_data_fields(journal_type: JournalType) -> dict[str, Any] | None:
    """The published field metadata for one type, or None when it takes no data."""
    model = TYPE_DATA_MODELS.get(journal_type)
    if model is None:
        return None

    schema = model.model_json_schema()
    fields = _describe_fields(schema, schema.get("$defs", {}))
    return fields or None


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
    # Both are validated by the domain but were never published, so an agent
    # could only discover them by guessing a value and being refused.
    "event_states": [state.value for state in EventState],
    "activity_subtypes": [subtype.value for subtype in OutdoorActivitySubtype],
}


def _collect_units() -> dict[str, str]:
    """Every field that states a unit, gathered from the models themselves.

    Published as a flat block as well as per-field so a caller can look a name
    up once rather than hunting through the type it belongs to.
    """
    units: dict[str, str] = {}

    def walk(schema: dict[str, Any], defs: dict[str, Any]) -> None:
        for name, node in schema.get("properties", {}).items():
            resolved = _resolve(node, defs)
            unit = resolved.get("unit")
            if unit:
                units[name] = unit
            # Recurse through nested models: a pitch's height is only reachable
            # via ABSEILING_TRIP.pitches, and the flat block is documented as
            # the place to look a field name up without knowing its type.
            item = _resolve(resolved.get("items", {}), defs)
            for nested in (resolved, item):
                if "properties" in nested and nested is not schema:
                    walk(nested, defs)

    for model in TYPE_DATA_MODELS.values():
        schema = model.model_json_schema()
        walk(schema, schema.get("$defs", {}))
    return units


JOURNAL_UNITS: dict[str, str] = _collect_units()


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
        entry["type_data_fields"] = describe_type_data_fields(jt)

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
            "unit, whether it is required, and every limit it is held to: "
            "allowed_values for a closed vocabulary, max_length for text, "
            "minimum/maximum for numbers, and pattern where the format is "
            "fixed. A value outside those limits is refused with the field "
            "named, so there is no need to probe for them. 'enums' repeats "
            "every closed vocabulary."
        ),
    }

    return result
