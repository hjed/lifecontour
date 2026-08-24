"""``type_data`` is checked at the tool boundary, before anything is written.

The composite write reaches the type-data write down two branches, and only one
of them ran the domain's checks: sending ``type_data`` alone answered
``role: Role cannot exceed 100 characters``, while sending ``types`` alongside
it answered a bare ``Internal error`` because the value reached the column
instead. Checking at the boundary means every call is answered the same way,
whatever it carries.
"""

import pytest
from core_shared.models.journals import JournalValidationError
from core_shared.models.journals.constants import MAX_ROLE_LENGTH

from app.mcp.domains.journals.schemas import validate_type_data


class TestRejections:
    def test_a_value_past_its_cap_names_the_field_and_the_limit(self) -> None:
        with pytest.raises(JournalValidationError) as caught:
            validate_type_data({"OUTDOOR_ACTIVITY": {"role": "x" * 101}})

        message = caught.value.message
        assert "role" in message
        assert str(MAX_ROLE_LENGTH) in message

    def test_an_unknown_field_lists_what_the_type_accepts(self) -> None:
        """ "Extra inputs are not permitted" does not say what to write instead."""
        with pytest.raises(JournalValidationError) as caught:
            validate_type_data({"BUSHWALKING": {"track_grade": "Grade 3"}})

        message = caught.value.message
        assert "track_grade" in message
        assert "track_grading" in message

    def test_every_bad_field_is_reported_at_once(self) -> None:
        with pytest.raises(JournalValidationError) as caught:
            validate_type_data({"MOOD_RATING": {"mood_value": 99, "energy_level": 0}})

        message = caught.value.message
        assert "mood_value" in message
        assert "energy_level" in message

    def test_an_off_vocabulary_value_is_refused(self) -> None:
        with pytest.raises(JournalValidationError):
            validate_type_data({"BUSHWALKING": {"track_grading": "Grade 9"}})

    def test_an_unknown_type_is_refused(self) -> None:
        with pytest.raises(JournalValidationError) as caught:
            validate_type_data({"NOT_A_TYPE": {}})

        assert "NOT_A_TYPE" in caught.value.message

    def test_integration_managed_type_data_is_refused(self) -> None:
        """PHOTO_ALBUM comes from Immich sync; a write would be dropped."""
        with pytest.raises(JournalValidationError) as caught:
            validate_type_data({"PHOTO_ALBUM": {"immich_album_id": "abc"}})

        assert "integration" in caught.value.message

    def test_a_non_object_payload_is_refused(self) -> None:
        with pytest.raises(JournalValidationError):
            validate_type_data({"OUTDOOR_ACTIVITY": "Guide"})  # type: ignore[dict-item]


class TestUpdatesArePatches:
    """A field required to build a row is not required to edit one.

    Every update helper is explicitly partial — each reads ``if "field" in
    attrs`` — so an EVENT update that only moves the location never carried
    ``calendar_id``. Validating an update against the create model would refuse
    calls that have always worked.
    """

    @pytest.mark.parametrize(
        ("journal_type", "attrs"),
        [
            ("EVENT", {"location": "Blue Mountains"}),
            ("GEAR_USAGE", {"checkin_date": "2024-01-15T09:30:00Z"}),
            ("GEAR_MAINTENANCE", {"retirement_reason": "frayed sheath"}),
        ],
    )
    def test_a_partial_update_needs_no_creation_only_field(
        self, journal_type: str, attrs: dict[str, object]
    ) -> None:
        assert validate_type_data({journal_type: attrs}, partial=True) == {
            journal_type: attrs
        }

    def test_creation_still_demands_its_required_fields(self) -> None:
        """The create path builds the row, so it must carry them."""
        with pytest.raises(JournalValidationError) as caught:
            validate_type_data({"EVENT": {"location": "Blue Mountains"}})

        assert "calendar_id" in caught.value.message

    def test_a_supplied_field_is_still_held_to_its_rules(self) -> None:
        """Partial drops requiredness, not validation."""
        with pytest.raises(JournalValidationError):
            validate_type_data({"OUTDOOR_ACTIVITY": {"role": "x" * 101}}, partial=True)

    def test_an_unknown_field_is_still_refused_on_an_update(self) -> None:
        with pytest.raises(JournalValidationError) as caught:
            validate_type_data(
                {"BUSHWALKING": {"track_grade": "Grade 3"}}, partial=True
            )

        assert "track_grading" in caught.value.message

    def test_an_explicit_null_for_a_non_nullable_field_is_refused(self) -> None:
        """Otherwise it reaches UUID(None) downstream and fails as a 500."""
        with pytest.raises(JournalValidationError):
            validate_type_data({"EVENT": {"calendar_id": None}}, partial=True)


class TestNormalisation:
    def test_a_partial_update_stays_partial(self) -> None:
        """The trap in validating through a model.

        Dumping every field would materialise the ones the caller never
        mentioned as ``None``, turning "set the role" into "set the role and
        blank the weather, the leadership flag and the participant notes".
        """
        result = validate_type_data({"OUTDOOR_ACTIVITY": {"role": "Guide"}})

        assert result == {"OUTDOOR_ACTIVITY": {"role": "Guide"}}

    def test_an_explicit_null_is_kept(self) -> None:
        """Clearing a field is a real intention and must survive the round trip."""
        result = validate_type_data({"OUTDOOR_ACTIVITY": {"role": None}})

        assert result == {"OUTDOOR_ACTIVITY": {"role": None}}

    def test_values_reach_the_service_as_the_primitives_it_parses(self) -> None:
        """The service parses JSON primitives, so the dump stays in JSON mode."""
        result = validate_type_data(
            {
                "GEAR_USAGE": {
                    "gear_item_id": "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
                    "checkout_date": "2024-01-15T09:30:00Z",
                }
            }
        )

        assert result is not None
        usage = result["GEAR_USAGE"]
        assert isinstance(usage["gear_item_id"], str)
        assert isinstance(usage["checkout_date"], str)

    def test_a_vocabulary_value_stays_a_plain_string(self) -> None:
        result = validate_type_data({"BUSHWALKING": {"track_grading": "Grade 3"}})

        assert result == {"BUSHWALKING": {"track_grading": "Grade 3"}}

    @pytest.mark.parametrize("empty", [None, {}])
    def test_an_empty_payload_passes_through(self, empty: object) -> None:
        assert validate_type_data(empty) == empty  # type: ignore[arg-type]

    def test_the_type_key_keeps_the_caller_s_casing(self) -> None:
        """The write path matches keys case-insensitively; do not rewrite them."""
        result = validate_type_data({"outdoor_activity": {"role": "Guide"}})

        assert result is not None
        assert "outdoor_activity" in result
