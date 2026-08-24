"""The type_data write models are the single source of field constraints.

``list_journal_types`` publishes these models' JSON Schema and the MCP tools
validate against them, so a bound that is missing here is a limit no client can
discover and no boundary enforces — which is how a 100-character ``role`` cap
stayed invisible until a write breached it and surfaced as a 500.

These tests guard three things: every writable type has a model, every bound is
the constant the domain validates against (not a copy of its value), and every
closed vocabulary is its enum.
"""

from typing import Any

import pytest
from core_shared.models.journals import JournalType
from core_shared.models.journals.constants import (
    MAX_ENERGY_LEVEL,
    MAX_FRENCH_GRADE_LENGTH,
    MAX_LOCATION_LENGTH,
    MAX_MOOD_LABEL_LENGTH,
    MAX_MOOD_VALUE,
    MAX_PARTICIPANT_NOTES_LENGTH,
    MAX_PLAN_DOCUMENT_TITLE_LENGTH,
    MAX_PLAN_DOCUMENT_URL_LENGTH,
    MAX_RETIREMENT_REASON_LENGTH,
    MAX_ROLE_LENGTH,
    MAX_STRAVA_ACTIVITY_ID_LENGTH,
    MAX_TIMEZONE_LENGTH,
    MAX_WATER_GAUGE_NAME_LENGTH,
    MAX_WEATHER_CONDITIONS_LENGTH,
    MIN_ENERGY_LEVEL,
    MIN_MOOD_VALUE,
    VALID_ANCHOR_LOCATIONS,
    VALID_ANCHOR_TYPES,
    VALID_CLIMBING_TYPES,
    VALID_MAINTENANCE_TYPES,
    VALID_PITCH_TYPES,
    VALID_RAPIDS_GRADES,
    VALID_TRACK_GRADES,
)
from core_shared.models.journals.event_state import EventState
from core_shared.models.journals.outdoor_activity_subtypes import OutdoorActivitySubtype
from core_shared.models.journals.type_data_schemas import (
    INTEGRATION_MANAGED_TYPES,
    TYPE_DATA_MODELS,
    AbseilingTripTypeData,
    AbseilPitchTypeData,
    BushwalkingTypeData,
    CanyoningTypeData,
    ClimbingTypeData,
    EventTypeData,
    FitnessTypeData,
    GearMaintenanceTypeData,
    KayakingTypeData,
    MoodRatingTypeData,
    OutdoorActivityTypeData,
    OutdoorPlanningTypeData,
    PlanDocumentTypeData,
    TypeDataModel,
)
from pydantic import ValidationError


def _field_schema(model: type[TypeDataModel], field: str) -> dict[str, Any]:
    """One field's JSON Schema, flattened past the optional ``anyOf`` wrapper.

    Pydantic renders ``str | None`` as ``anyOf: [{...}, {"type": "null"}]``, so
    the constraints sit on the non-null branch rather than the top level.
    """
    schema: dict[str, Any] = model.model_json_schema()["properties"][field]
    if "anyOf" in schema:
        non_null = [
            branch for branch in schema["anyOf"] if branch.get("type") != "null"
        ]
        assert len(non_null) == 1, f"{field} has an ambiguous anyOf"
        return {**schema, **non_null[0]}
    return schema


class TestRegistryCoverage:
    def test_every_writable_type_has_a_model(self) -> None:
        """A type missing here accepts type_data no client can discover."""
        expected = set(JournalType) - INTEGRATION_MANAGED_TYPES
        assert set(TYPE_DATA_MODELS) == expected

    def test_photo_album_has_no_write_model(self) -> None:
        """PHOTO_ALBUM is Immich-synced; the write paths refuse it outright."""
        assert JournalType.PHOTO_ALBUM not in TYPE_DATA_MODELS

    def test_every_model_forbids_unknown_fields(self) -> None:
        """A mistyped key must be refused, not dropped in silence."""
        for journal_type, model in TYPE_DATA_MODELS.items():
            assert model.model_config.get("extra") == "forbid", journal_type


class TestLengthBounds:
    """Each cap is the constant the entity validates against, not a copy."""

    @pytest.mark.parametrize(
        ("model", "field", "expected"),
        [
            (OutdoorActivityTypeData, "role", MAX_ROLE_LENGTH),
            (
                OutdoorActivityTypeData,
                "weather_conditions",
                MAX_WEATHER_CONDITIONS_LENGTH,
            ),
            (
                OutdoorActivityTypeData,
                "participant_notes",
                MAX_PARTICIPANT_NOTES_LENGTH,
            ),
            (EventTypeData, "location", MAX_LOCATION_LENGTH),
            (EventTypeData, "timezone", MAX_TIMEZONE_LENGTH),
            (MoodRatingTypeData, "mood_label", MAX_MOOD_LABEL_LENGTH),
            (FitnessTypeData, "strava_activity_id", MAX_STRAVA_ACTIVITY_ID_LENGTH),
            (PlanDocumentTypeData, "url", MAX_PLAN_DOCUMENT_URL_LENGTH),
            (PlanDocumentTypeData, "title", MAX_PLAN_DOCUMENT_TITLE_LENGTH),
            (CanyoningTypeData, "french_grade", MAX_FRENCH_GRADE_LENGTH),
            (CanyoningTypeData, "water_guage_name", MAX_WATER_GAUGE_NAME_LENGTH),
            (
                GearMaintenanceTypeData,
                "retirement_reason",
                MAX_RETIREMENT_REASON_LENGTH,
            ),
        ],
    )
    def test_max_length_is_published(
        self, model: type[TypeDataModel], field: str, expected: int
    ) -> None:
        assert _field_schema(model, field)["maxLength"] == expected

    def test_role_rejects_a_value_past_the_cap(self) -> None:
        """The reported failure, refused at the boundary instead of the column."""
        with pytest.raises(ValidationError) as caught:
            OutdoorActivityTypeData.model_validate(
                {"role": "x" * (MAX_ROLE_LENGTH + 1)}
            )

        error = caught.value.errors()[0]
        assert error["loc"] == ("role",)
        assert str(MAX_ROLE_LENGTH) in error["msg"]


class TestNumericBounds:
    @pytest.mark.parametrize(
        ("model", "field", "minimum", "maximum"),
        [
            (MoodRatingTypeData, "mood_value", MIN_MOOD_VALUE, MAX_MOOD_VALUE),
            (MoodRatingTypeData, "energy_level", MIN_ENERGY_LEVEL, MAX_ENERGY_LEVEL),
        ],
    )
    def test_scaled_fields_publish_both_bounds(
        self, model: type[TypeDataModel], field: str, minimum: int, maximum: int
    ) -> None:
        schema = _field_schema(model, field)
        assert schema["minimum"] == minimum
        assert schema["maximum"] == maximum

    @pytest.mark.parametrize(
        ("model", "field"),
        [
            (FitnessTypeData, "distance"),
            (FitnessTypeData, "duration"),
            (FitnessTypeData, "elevation_gain"),
            (FitnessTypeData, "elevation_loss"),
            (FitnessTypeData, "heart_rate_avg"),
            (FitnessTypeData, "heart_rate_max"),
            (FitnessTypeData, "calories"),
            (ClimbingTypeData, "grade"),
            (ClimbingTypeData, "length"),
            (AbseilingTripTypeData, "number_of_abseils"),
            (AbseilingTripTypeData, "total_length"),
            (AbseilingTripTypeData, "number_of_setups"),
            (AbseilingTripTypeData, "number_of_rescues"),
            (AbseilPitchTypeData, "height"),
        ],
    )
    def test_measured_fields_are_non_negative(
        self, model: type[TypeDataModel], field: str
    ) -> None:
        """The entities reject negatives; the schema must say so up front."""
        assert _field_schema(model, field)["minimum"] == 0


class TestUnitsArePublished:
    """A bare int cannot tell a caller metres from kilometres."""

    @pytest.mark.parametrize(
        ("field", "unit"),
        [
            ("distance", "km"),
            ("duration", "minutes"),
            ("elevation_gain", "m"),
            ("elevation_loss", "m"),
            ("heart_rate_avg", "bpm"),
            ("calories", "kcal"),
        ],
    )
    def test_fitness_fields_state_their_unit(self, field: str, unit: str) -> None:
        assert _field_schema(FitnessTypeData, field)["unit"] == unit

    def test_pace_is_seconds_per_kilometre(self) -> None:
        """Published as a '5:30/km' string until now; the column is an int."""
        from core_shared.models.journals.type_data_schemas import JoggingTypeData

        schema = _field_schema(JoggingTypeData, "pace")
        assert schema["type"] == "integer"
        assert schema["unit"] == "seconds per km"


class TestClosedVocabularies:
    @pytest.mark.parametrize(
        ("model", "field", "valid"),
        [
            (BushwalkingTypeData, "track_grading", VALID_TRACK_GRADES),
            (ClimbingTypeData, "climbing_type", VALID_CLIMBING_TYPES),
            (KayakingTypeData, "rapids_grade", VALID_RAPIDS_GRADES),
            (GearMaintenanceTypeData, "maintenance_type", VALID_MAINTENANCE_TYPES),
            (AbseilPitchTypeData, "anchor_type", VALID_ANCHOR_TYPES),
            (AbseilPitchTypeData, "anchor_location", VALID_ANCHOR_LOCATIONS),
            (AbseilPitchTypeData, "pitch_type", VALID_PITCH_TYPES),
        ],
    )
    def test_vocabulary_is_published_as_an_enum(
        self, model: type[TypeDataModel], field: str, valid: list[str]
    ) -> None:
        """Derived from the enum, so the schema cannot drift from the domain."""
        schema = model.model_json_schema()
        assert _enum_values(schema, field) == list(valid)

    def test_event_state_is_published(self) -> None:
        """Accepted by the write path but never documented before."""
        schema = EventTypeData.model_json_schema()
        assert _enum_values(schema, "event_state") == [s.value for s in EventState]

    def test_activity_types_are_published(self) -> None:
        """OUTDOOR_PLANNING validates these; the vocabulary was undocumented."""
        schema = OutdoorPlanningTypeData.model_json_schema()
        assert _enum_values(schema, "activity_types") == [
            s.value for s in OutdoorActivitySubtype
        ]

    def test_off_vocabulary_track_grading_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            BushwalkingTypeData.model_validate({"track_grading": "Grade 9"})

    def test_focus_areas_stay_open(self) -> None:
        """OUTDOOR_TRAINING deliberately accepts free text beyond the subtypes."""
        from core_shared.models.journals.type_data_schemas import (
            OutdoorTrainingTypeData,
        )

        assert OutdoorTrainingTypeData(
            focus_areas=["bushwalking", "knot tying"]
        ).focus_areas == ["bushwalking", "knot tying"]


def _enum_values(schema: dict[str, Any], field: str) -> list[str]:
    """Resolve a field's enum values through $ref / anyOf / array items."""
    defs = schema.get("$defs", {})

    def resolve(node: dict[str, Any]) -> list[str] | None:
        if "enum" in node:
            return list(node["enum"])
        if "$ref" in node:
            return resolve(defs[node["$ref"].rsplit("/", 1)[1]])
        if "items" in node:
            return resolve(node["items"])
        for branch in node.get("anyOf", []):
            found = resolve(branch)
            if found is not None:
                return found
        return None

    values = resolve(schema["properties"][field])
    assert values is not None, f"{field} publishes no enum"
    return values


class TestUnboundedStringsAreDeliberate:
    """Every string field either carries a cap or is named as free text.

    A ``VARCHAR(n)`` column reached with a longer value is a driver error the
    API can only report as a 500, so a new string field must make a choice.
    The columns behind these names are ``TEXT`` — genuinely unbounded.
    """

    FREE_TEXT = {
        ("EventTypeData", "description"),
        ("PlanDocumentTypeData", "description"),
        ("KayakingTypeData", "water_type"),
        ("CanoeingTypeData", "water_type"),
        ("CrossCountrySkiingTypeData", "snow_conditions"),
        ("OutdoorPlanningTypeData", "topics"),
        ("OutdoorTrainingTypeData", "focus_areas"),
        ("AbseilPitchTypeData", "notes"),
    }

    def test_no_accidental_unbounded_string(self) -> None:
        unbounded: set[tuple[str, str]] = set()
        models: list[type[TypeDataModel]] = [
            *TYPE_DATA_MODELS.values(),
            PlanDocumentTypeData,
            AbseilPitchTypeData,
        ]
        for model in models:
            schema = model.model_json_schema()
            for field, spec in schema["properties"].items():
                flat = _field_schema(model, field)
                is_string = flat.get("type") == "string" or (
                    flat.get("type") == "array"
                    and flat.get("items", {}).get("type") == "string"
                )
                # A format (uuid, date-time, time) is its own bound.
                if not is_string or "enum" in flat or "format" in flat:
                    continue
                if "$ref" in str(spec):
                    continue
                if "maxLength" not in flat and "pattern" not in flat:
                    unbounded.add((model.__name__, field))

        assert unbounded == self.FREE_TEXT, (
            "a string field gained or lost a cap: add the cap, or add it to "
            "FREE_TEXT if its column is TEXT"
        )
