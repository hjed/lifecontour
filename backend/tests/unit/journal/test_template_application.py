"""Unit tests for applying an activity template to a journal's ``type_data``.

Selecting a template in the web create form does more than record the
reference: it copies the template's standard pitches into the consolidated
abseiling block, derives the abseil counts from them, and pushes the
template's type-specific fields onto the matching type block. These tests pin
that behaviour down for the server-side equivalent used by the MCP
``create_journal_entry`` tool, so the rules live in one place instead of only
in TypeScript.
"""

from typing import Any

import pytest
from core_shared.models.journals.activity_template import ActivityTemplate
from core_shared.models.journals.exceptions import JournalValidationError
from core_shared.models.journals.journal_types import JournalType
from core_shared.models.journals.template_pitch import TemplatePitch

from app.core.journal.services.template_application import (
    apply_template_to_type_data,
)

TEMPLATE_ID = "11111111-2222-3333-4444-555555555555"
USER_ID = "user-1"


def _template(template_type: str, **kwargs: Any) -> ActivityTemplate:
    """Build a template of the given type with sane defaults."""
    return ActivityTemplate(
        id=TEMPLATE_ID,
        user_id=USER_ID,
        name=f"{template_type.title()} Template",
        template_type=template_type,
        **kwargs,
    )


def _pitch(pitch_number: int, **kwargs: Any) -> TemplatePitch:
    return TemplatePitch(template_id=TEMPLATE_ID, pitch_number=pitch_number, **kwargs)


def _abseiling(result: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return result[JournalType.ABSEILING_TRIP.name]


class TestTemplateReference:
    """The durable reference is always recorded on the abseiling block."""

    def test_pitchless_template_only_links_the_reference(self) -> None:
        result = apply_template_to_type_data(
            _template("abseiling"), ["ABSEILING_TRIP"], {}
        )

        assert _abseiling(result) == {"template_id": TEMPLATE_ID}

    def test_reference_is_recorded_for_a_derived_type(self) -> None:
        """CANYONING pulls in ABSEILING_TRIP through type dependencies."""
        result = apply_template_to_type_data(_template("canyoning"), ["CANYONING"], {})

        assert _abseiling(result)["template_id"] == TEMPLATE_ID

    def test_untouched_type_data_is_preserved(self) -> None:
        result = apply_template_to_type_data(
            _template("abseiling"),
            ["ABSEILING_TRIP", "MOOD_RATING"],
            {"MOOD_RATING": {"mood_value": 7}},
        )

        assert result["MOOD_RATING"] == {"mood_value": 7}

    def test_input_type_data_is_not_mutated(self) -> None:
        type_data: dict[str, dict[str, Any]] = {"ABSEILING_TRIP": {}}

        apply_template_to_type_data(
            _template("abseiling"), ["ABSEILING_TRIP"], type_data
        )

        assert type_data == {"ABSEILING_TRIP": {}}

    def test_journal_without_an_abseiling_type_is_rejected(self) -> None:
        """A template cannot silently turn a note into an abseiling trip."""
        with pytest.raises(JournalValidationError) as exc_info:
            apply_template_to_type_data(_template("abseiling"), ["NOTE"], {})

        assert exc_info.value.field == "template_id"

    def test_journal_with_no_types_at_all_is_rejected(self) -> None:
        with pytest.raises(JournalValidationError) as exc_info:
            apply_template_to_type_data(_template("abseiling"), [], {})

        assert exc_info.value.field == "template_id"


class TestPitchSeeding:
    """The template's standard pitches become the journal's pitches."""

    def test_pitches_are_copied_with_all_their_fields(self) -> None:
        template = _template(
            "abseiling",
            pitches=[
                _pitch(
                    1,
                    height=30,
                    anchor_location="TR",
                    anchor_type="double bolt",
                    did_rescue=True,
                    did_setup=False,
                    notes="Wet start",
                    pitch_type="abseil",
                )
            ],
        )

        result = apply_template_to_type_data(template, ["ABSEILING_TRIP"], {})

        assert _abseiling(result)["pitches"] == [
            {
                "pitch_number": 1,
                "height": 30,
                "anchor_location": "TR",
                "anchor_type": "double bolt",
                "did_rescue": True,
                "did_setup": False,
                "notes": "Wet start",
                "pitch_type": "abseil",
            }
        ]

    def test_pitches_carry_no_identity_from_the_template(self) -> None:
        """The journal's pitches are copies, not references to template rows."""
        template = _template("abseiling", pitches=[_pitch(1, height=10)])
        template.pitches[0].id = 99

        result = apply_template_to_type_data(template, ["ABSEILING_TRIP"], {})

        pitch = _abseiling(result)["pitches"][0]
        assert "id" not in pitch
        assert "template_id" not in pitch

    def test_pitches_are_ordered_by_pitch_number(self) -> None:
        template = _template(
            "abseiling",
            pitches=[_pitch(3, height=5), _pitch(1, height=30), _pitch(2, height=15)],
        )

        result = apply_template_to_type_data(template, ["ABSEILING_TRIP"], {})

        assert [p["pitch_number"] for p in _abseiling(result)["pitches"]] == [1, 2, 3]

    def test_counts_are_left_to_the_abseiling_service(self) -> None:
        """AbseilingService derives the counts from the pitches it is given.

        Seeding them here as well would only give the two answers a chance to
        disagree, so the block carries the pitches and nothing else.
        """
        template = _template(
            "abseiling",
            pitches=[_pitch(1, height=30), _pitch(2, height=15, pitch_type="jump")],
        )

        result = apply_template_to_type_data(template, ["ABSEILING_TRIP"], {})

        assert "number_of_abseils" not in _abseiling(result)
        assert "total_length" not in _abseiling(result)

    def test_pitchless_template_leaves_the_caller_counts_alone(self) -> None:
        """Linking a pitchless template must not disturb manual counts."""
        result = apply_template_to_type_data(
            _template("abseiling"),
            ["ABSEILING_TRIP"],
            {"ABSEILING_TRIP": {"number_of_abseils": 5, "total_length": 200}},
        )

        assert _abseiling(result) == {
            "template_id": TEMPLATE_ID,
            "number_of_abseils": 5,
            "total_length": 200,
        }


class TestCallerPrecedence:
    """Whatever the caller supplied in ``type_data`` wins over the template."""

    def test_caller_pitches_replace_the_template_pitches(self) -> None:
        template = _template(
            "abseiling", pitches=[_pitch(1, height=30), _pitch(2, height=15)]
        )

        result = apply_template_to_type_data(
            template,
            ["ABSEILING_TRIP"],
            {"ABSEILING_TRIP": {"pitches": [{"pitch_number": 1, "height": 8}]}},
        )

        assert _abseiling(result)["pitches"] == [{"pitch_number": 1, "height": 8}]

    def test_caller_manual_counts_survive_alongside_template_pitches(self) -> None:
        """A manual count is an override; the template still supplies the pitches."""
        template = _template(
            "abseiling", pitches=[_pitch(1, height=30), _pitch(2, height=15)]
        )

        result = apply_template_to_type_data(
            template,
            ["ABSEILING_TRIP"],
            {"ABSEILING_TRIP": {"number_of_abseils": 1}},
        )

        assert _abseiling(result)["number_of_abseils"] == 1
        assert len(_abseiling(result)["pitches"]) == 2

    def test_caller_template_id_wins(self) -> None:
        other = "99999999-8888-7777-6666-555555555555"

        result = apply_template_to_type_data(
            _template("abseiling"),
            ["ABSEILING_TRIP"],
            {"ABSEILING_TRIP": {"template_id": other}},
        )

        assert _abseiling(result)["template_id"] == other

    def test_caller_type_data_keys_are_matched_case_insensitively(self) -> None:
        """The tool accepts lower-case type_data keys, so merging must too."""
        template = _template("canyoning", french_grade="v4a3IV")

        result = apply_template_to_type_data(
            template,
            ["CANYONING"],
            {"canyoning": {"is_night_canyon": True}, "abseiling_trip": {}},
        )

        assert result["canyoning"]["french_grade"] == "v4a3IV"
        assert result["canyoning"]["is_night_canyon"] is True
        assert result["abseiling_trip"]["template_id"] == TEMPLATE_ID
        assert "CANYONING" not in result
        assert "ABSEILING_TRIP" not in result


class TestCanyoningFields:
    """A canyoning template contributes to the CANYONING block."""

    def test_grade_and_gauge_are_seeded(self) -> None:
        template = _template(
            "canyoning", french_grade="v4a3IV", water_gauge_name="Kanangra Creek"
        )

        result = apply_template_to_type_data(template, ["CANYONING"], {})

        assert result["CANYONING"] == {
            "french_grade": "v4a3IV",
            "water_guage_name": "Kanangra Creek",
        }

    def test_vertical_canyon_type_implies_the_vertical_flag(self) -> None:
        result = apply_template_to_type_data(
            _template("canyoning", canyon_type="vertical"), ["CANYONING"], {}
        )

        assert result["CANYONING"]["is_vertical"] is True

    def test_mixed_canyon_type_is_left_to_the_user(self) -> None:
        result = apply_template_to_type_data(
            _template("canyoning", canyon_type="mixed"), ["CANYONING"], {}
        )

        assert "CANYONING" not in result

    def test_no_canyoning_block_when_the_journal_is_not_canyoning(self) -> None:
        """A canyoning template on a plain abseiling journal seeds pitches only."""
        template = _template("canyoning", french_grade="v4a3IV")

        result = apply_template_to_type_data(template, ["ABSEILING_TRIP"], {})

        assert "CANYONING" not in result
        assert _abseiling(result)["template_id"] == TEMPLATE_ID


class TestCavingFields:
    """A caving template contributes to the CAVING block."""

    def test_vertical_and_horizontal_flags_are_seeded(self) -> None:
        template = _template("caving", is_vertical=True, is_horizontal=False)

        result = apply_template_to_type_data(template, ["CAVING"], {})

        assert result["CAVING"] == {"is_vertical": True, "is_horizontal": False}

    def test_unset_flags_are_not_seeded(self) -> None:
        result = apply_template_to_type_data(
            _template("caving", is_vertical=True), ["CAVING"], {}
        )

        assert result["CAVING"] == {"is_vertical": True}


class TestClimbingFields:
    """A climbing template contributes to the CLIMBING block."""

    def test_type_grade_and_length_are_seeded(self) -> None:
        template = _template("climbing", climbing_type="sport", grade=21, length=30)

        result = apply_template_to_type_data(template, ["CLIMBING"], {})

        assert result["CLIMBING"] == {
            "climbing_type": "sport",
            "grade": 21,
            "length": 30,
        }

    def test_climbing_fields_never_reach_the_abseiling_block(self) -> None:
        """The per-subtype template_id columns were retired; grade is not abseiling data."""
        template = _template("climbing", grade=21)

        result = apply_template_to_type_data(template, ["CLIMBING"], {})

        assert "grade" not in _abseiling(result)
