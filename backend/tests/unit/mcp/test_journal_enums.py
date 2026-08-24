"""Closed vocabularies are published through FastMCP and list_journal_types."""

import json
from typing import Any

import pytest
from core_shared.models.journals import (
    AnchorLocation,
    AnchorType,
    CanyonType,
    ClimbingType,
    PitchType,
    TemplateType,
)
from core_shared.models.journals.constants import (
    FRENCH_CANYON_GRADE_PATTERN,
    MAX_FRENCH_GRADE_LENGTH,
    MAX_MOOD_VALUE,
    MAX_ROLE_LENGTH,
    MIN_MOOD_VALUE,
    VALID_ANCHOR_LOCATIONS,
    VALID_ANCHOR_TYPES,
    VALID_CANYON_TYPES,
    VALID_CLIMBING_TYPES,
    VALID_PITCH_TYPES,
    VALID_TEMPLATE_TYPES,
)
from core_shared.models.journals.event_state import EventState
from core_shared.models.journals.outdoor_activity_subtypes import (
    OutdoorActivitySubtype,
)

from app.mcp.domains.journals.tools import list_journal_types
from app.mcp.server import create_mcp_server


@pytest.mark.parametrize(
    ("enum", "valid"),
    [
        (AnchorType, VALID_ANCHOR_TYPES),
        (AnchorLocation, VALID_ANCHOR_LOCATIONS),
        (PitchType, VALID_PITCH_TYPES),
        (CanyonType, VALID_CANYON_TYPES),
        (ClimbingType, VALID_CLIMBING_TYPES),
        (TemplateType, VALID_TEMPLATE_TYPES),
    ],
)
def test_valid_lists_are_derived_from_the_enums(enum, valid) -> None:
    """One definition: the VALID_* lists are derived from the core_shared enums."""
    assert [member.value for member in enum] == list(valid)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["create_template", "update_template"])
async def test_template_tools_publish_enums_in_their_schema(tool_name: str) -> None:
    server = create_mcp_server()
    tool = await server.get_tool(tool_name)
    assert tool is not None
    params: dict[str, Any] = tool.parameters
    defs: dict[str, Any] = params.get("$defs", {})

    def enum_of(schema: dict[str, Any]) -> list[Any] | None:
        if "enum" in schema:
            return list(schema["enum"])
        for branch in schema.get("anyOf", []):
            if "enum" in branch:
                return list(branch["enum"])
            if "$ref" in branch:
                return enum_of(defs[branch["$ref"].rsplit("/", 1)[1]])
        if "$ref" in schema:
            return enum_of(defs[schema["$ref"].rsplit("/", 1)[1]])
        return None

    props = params["properties"]
    assert enum_of(props["canyon_type"]) == VALID_CANYON_TYPES
    assert enum_of(props["climbing_type"]) == VALID_CLIMBING_TYPES
    pitch = defs["TemplatePitchInput"]["properties"]
    assert enum_of(pitch["anchor_type"]) == VALID_ANCHOR_TYPES
    assert enum_of(pitch["anchor_location"]) == VALID_ANCHOR_LOCATIONS
    assert enum_of(pitch["pitch_type"]) == VALID_PITCH_TYPES


@pytest.mark.asyncio
async def test_list_journal_types_states_units_and_enums() -> None:
    payload = json.loads(await list_journal_types())
    by_name = {t["name"]: t for t in payload["journal_types"]}

    fitness = by_name["FITNESS"]["type_data_fields"]
    assert fitness["distance"]["unit"] == "km"
    assert fitness["distance"]["type"] == "int"
    assert fitness["duration"]["unit"] == "minutes"
    assert fitness["elevation_gain"]["unit"] == "m"
    assert fitness["distance"]["summary"] == "int in km (optional, min 0)"
    assert by_name["ABSEILING_TRIP"]["type_data_fields"]["total_length"]["unit"] == "m"
    assert by_name["CLIMBING"]["type_data_fields"]["length"]["unit"] == "m"
    assert (
        by_name["CLIMBING"]["type_data_fields"]["climbing_type"]["allowed_values"]
        == VALID_CLIMBING_TYPES
    )
    assert by_name["EVENT"]["type_data_fields"]["calendar_id"]["required"] is True
    assert "url" in by_name["PLAN"]["type_data_fields"]["documents"]["description"]
    assert by_name["OUTDOOR_TRAINING"]["type_data_fields"]["focus_areas"]["type"] == (
        "list[string]"
    )

    assert payload["enums"]["anchor_types"] == VALID_ANCHOR_TYPES
    assert payload["enums"]["canyon_types"] == VALID_CANYON_TYPES
    assert payload["enums"]["pitch_types"] == VALID_PITCH_TYPES
    assert payload["units"]["distance"].startswith("km")


@pytest.mark.asyncio
async def test_units_block_still_covers_every_measured_field() -> None:
    """The flat ``units`` block is a documented lookup — it must not shrink.

    Deriving it from the models dropped ``height``, which lives on a pitch and
    is only reachable through ABSEILING_TRIP.pitches, so a caller looking a
    bare field name up lost its unit.
    """
    payload = json.loads(await list_journal_types())
    units = payload["units"]

    for field in (
        "distance",
        "duration",
        "elevation_gain",
        "elevation_loss",
        "total_length",
        "length",
        "height",
        "heart_rate_avg",
        "heart_rate_max",
        "calories",
    ):
        assert field in units, f"{field} lost its unit in the flat block"

    assert units["height"] == "m"


@pytest.mark.asyncio
async def test_list_journal_types_publishes_every_field_limit() -> None:
    """A limit a caller cannot read is one they can only find by breaching it.

    ``role`` capping at 100 characters was invisible until a write breached it
    and came back as an opaque 500, so every bound the domain enforces is
    published: text caps, numeric ranges, fixed formats and closed vocabularies.
    """
    payload = json.loads(await list_journal_types())
    by_name = {t["name"]: t for t in payload["journal_types"]}

    role = by_name["OUTDOOR_ACTIVITY"]["type_data_fields"]["role"]
    assert role["max_length"] == MAX_ROLE_LENGTH
    assert "max 100 chars" in role["summary"]

    mood = by_name["MOOD_RATING"]["type_data_fields"]["mood_value"]
    assert (mood["minimum"], mood["maximum"]) == (MIN_MOOD_VALUE, MAX_MOOD_VALUE)
    assert "1-10" in mood["summary"]

    french_grade = by_name["CANYONING"]["type_data_fields"]["french_grade"]
    assert french_grade["pattern"] == FRENCH_CANYON_GRADE_PATTERN
    assert french_grade["max_length"] == MAX_FRENCH_GRADE_LENGTH


@pytest.mark.asyncio
async def test_list_journal_types_publishes_the_undocumented_vocabularies() -> None:
    """event_state and activity_types are validated but were never published."""
    payload = json.loads(await list_journal_types())
    by_name = {t["name"]: t for t in payload["journal_types"]}

    assert payload["enums"]["event_states"] == [state.value for state in EventState]
    assert payload["enums"]["activity_subtypes"] == [
        subtype.value for subtype in OutdoorActivitySubtype
    ]
    assert by_name["EVENT"]["type_data_fields"]["event_state"]["allowed_values"] == [
        state.value for state in EventState
    ]
    assert by_name["OUTDOOR_PLANNING"]["type_data_fields"]["activity_types"][
        "allowed_values"
    ] == [subtype.value for subtype in OutdoorActivitySubtype]


@pytest.mark.asyncio
async def test_pitch_fields_are_structured_rather_than_prose() -> None:
    """The pitch shape used to be one prose blob a caller had to parse."""
    payload = json.loads(await list_journal_types())
    by_name = {t["name"]: t for t in payload["journal_types"]}

    pitches = by_name["ABSEILING_TRIP"]["type_data_fields"]["pitches"]
    assert pitches["fields"]["pitch_number"]["required"] is True
    assert pitches["fields"]["anchor_type"]["allowed_values"] == VALID_ANCHOR_TYPES
    assert pitches["fields"]["height"]["unit"] == "m"


@pytest.mark.asyncio
async def test_jogging_pace_is_published_as_the_integer_it_is() -> None:
    """It was published as a '5:30/km' string; the column is seconds per km."""
    payload = json.loads(await list_journal_types())
    by_name = {t["name"]: t for t in payload["journal_types"]}

    pace = by_name["JOGGING"]["type_data_fields"]["pace"]
    assert pace["type"] == "int"
    assert pace["unit"] == "seconds per km"
