"""Unit tests for type-data override coercion."""

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from core_shared.models.journals.exceptions import JournalValidationError

from app.core.journal.services.type_data_coercion import coerce_type_data_override


class TestCoerceTypeDataOverride:
    """A JSON value is bound to a column, so it must carry the column's type."""

    def test_a_clock_time_string_becomes_a_time(self):
        assert coerce_type_data_override(
            "start_time", "19:30:00", "time without time zone"
        ) == time(19, 30)

    def test_a_time_without_seconds_is_accepted(self):
        assert coerce_type_data_override(
            "start_time", "19:30", "time without time zone"
        ) == time(19, 30)

    def test_a_date_string_becomes_a_date(self):
        assert coerce_type_data_override("trip_date", "2026-08-23", "date") == date(
            2026, 8, 23
        )

    def test_a_timestamp_string_becomes_a_datetime(self):
        assert coerce_type_data_override(
            "recorded_at", "2026-08-23T19:30:00Z", "timestamp with time zone"
        ) == datetime(2026, 8, 23, 19, 30, tzinfo=UTC)

    def test_a_numeric_string_becomes_a_decimal(self):
        assert coerce_type_data_override("grade", "5.5", "numeric") == Decimal("5.5")

    def test_an_integer_string_becomes_an_int(self):
        value = coerce_type_data_override("distance", "8000", "integer")
        assert value == 8000
        assert isinstance(value, int)

    def test_a_float_string_becomes_a_float(self):
        value = coerce_type_data_override("latitude", "-33.85", "double precision")
        assert value == pytest.approx(-33.85)
        assert isinstance(value, float)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("true", True), ("false", False), ("t", True), ("0", False)],
    )
    def test_a_boolean_string_becomes_a_bool(self, raw, expected):
        assert coerce_type_data_override("is_all_day", raw, "boolean") is expected

    def test_a_uuid_string_is_left_for_the_driver(self):
        """asyncpg encodes a uuid from a string already — do not second-guess it."""
        raw = "440b9a8c-a4f5-4f2c-bba3-a60d7de2889c"
        assert coerce_type_data_override("calendar_id", raw, "uuid") == raw

    def test_text_is_untouched(self):
        assert coerce_type_data_override("location", "Office", "text") == "Office"

    def test_a_non_string_value_is_untouched(self):
        """JSON numbers, booleans and null already match their columns."""
        assert coerce_type_data_override("mood_value", 8, "integer") == 8
        assert coerce_type_data_override("is_all_day", True, "boolean") is True
        assert (
            coerce_type_data_override("start_time", None, "time without time zone")
            is None
        )

    def test_an_already_typed_value_is_untouched(self):
        assert coerce_type_data_override(
            "start_time", time(19, 30), "time without time zone"
        ) == time(19, 30)

    def test_an_unknown_column_type_is_untouched(self):
        """A type we have no rule for is passed through rather than mangled."""
        assert coerce_type_data_override("tags", "{a,b}", "ARRAY") == "{a,b}"
        assert coerce_type_data_override("note", "hi", None) == "hi"

    def test_an_unparseable_value_is_a_validation_error(self):
        """The caller sent nonsense: answer 400, not a driver crash."""
        with pytest.raises(JournalValidationError) as exc_info:
            coerce_type_data_override(
                "start_time", "half past seven", "time without time zone"
            )

        assert "start_time" in str(exc_info.value)

    def test_an_unparseable_boolean_is_a_validation_error(self):
        with pytest.raises(JournalValidationError):
            coerce_type_data_override("is_all_day", "maybe", "boolean")
