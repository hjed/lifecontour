"""Unit tests for type-data override coercion."""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from uuid import UUID

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

    def test_a_uuid_string_becomes_a_uuid(self):
        raw = "440b9a8c-a4f5-4f2c-bba3-a60d7de2889c"
        assert coerce_type_data_override("calendar_id", raw, "uuid") == UUID(raw)

    def test_an_unparseable_uuid_is_a_validation_error(self):
        with pytest.raises(JournalValidationError):
            coerce_type_data_override("calendar_id", "not-a-calendar", "uuid")

    def test_a_number_for_a_uuid_column_is_a_validation_error(self):
        with pytest.raises(JournalValidationError):
            coerce_type_data_override("calendar_id", 440, "uuid")

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

    def test_a_number_for_a_time_column_is_a_validation_error(self):
        """`{"start_time": 1930}` is as wrong as a bad string, and answers the same.

        The REST schema types `type_data` values as ``Any``, so a wrong-typed
        JSON value reaches the UPDATE just as a string does.
        """
        with pytest.raises(JournalValidationError) as exc_info:
            coerce_type_data_override("start_time", 1930, "time without time zone")

        assert "start_time" in str(exc_info.value)

    def test_a_number_for_a_date_column_is_a_validation_error(self):
        with pytest.raises(JournalValidationError):
            coerce_type_data_override("trip_date", 20260823, "date")

    def test_a_boolean_for_an_integer_column_is_a_validation_error(self):
        """``True`` is an ``int`` to Python, but it is not a distance."""
        with pytest.raises(JournalValidationError):
            coerce_type_data_override("distance", True, "integer")

    def test_a_fractional_number_for_an_integer_column_is_a_validation_error(self):
        with pytest.raises(JournalValidationError):
            coerce_type_data_override("distance", 8000.5, "integer")

    def test_a_number_for_a_boolean_column_is_a_validation_error(self):
        with pytest.raises(JournalValidationError):
            coerce_type_data_override("is_all_day", 1, "boolean")

    def test_a_whole_number_still_serves_a_numeric_column(self):
        """Postgres takes an int for numeric, so this is not the caller's error."""
        assert coerce_type_data_override("grade", 5, "numeric") == 5

    def test_an_int_still_serves_a_float_column(self):
        assert coerce_type_data_override("latitude", -33, "double precision") == -33

    def test_a_wrong_typed_value_for_an_unruled_column_is_left_alone(self):
        """No rule means no opinion: narrowing text/jsonb here could reject
        payloads that work today."""
        assert coerce_type_data_override("documents", [{"url": "x"}], "jsonb") == [
            {"url": "x"}
        ]

    def test_a_number_for_a_text_column_is_a_validation_error(self):
        """asyncpg's text codec takes a string and nothing else.

        `{"location": 123}` used to slip past unchecked and fail in the driver.
        """
        with pytest.raises(JournalValidationError) as exc_info:
            coerce_type_data_override("location", 123, "character varying")

        assert "location" in str(exc_info.value)

    def test_a_string_still_serves_a_text_column(self):
        assert (
            coerce_type_data_override("location", "Office", "character varying")
            == "Office"
        )
