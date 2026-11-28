"""Unit tests for the recurrence setting's value objects.

A recurrence setting is one of three modes (spec *Recurring Tasks*), each its
own type so a mode can never carry another mode's data. Only the interval has
rules of its own; whether a series exists and is the user's needs other rows.
"""

from typing import Any
from uuid import uuid4

import pytest
from core_shared.models.tasks import (
    TASK_RECURRENCE_TYPES,
    IntervalRecurrence,
    NoDateRecurrence,
    RecurrenceInterval,
    RecurrenceIntervalUnit,
    RecurrenceMode,
    SeriesRecurrence,
    TaskValidationError,
)

pytestmark = pytest.mark.unit


class TestRecurrenceInterval:
    """Days, weeks, months or years, at least one of them."""

    @pytest.mark.parametrize("unit", list(RecurrenceIntervalUnit))
    def test_every_unit_is_accepted(self, unit: RecurrenceIntervalUnit) -> None:
        interval = RecurrenceInterval(count=1, unit=unit)

        assert (interval.count, interval.unit) == (1, unit)

    def test_the_units_are_the_stored_keys(self) -> None:
        """Pinned: the keys are what the database CHECK accepts."""
        assert [unit.value for unit in RecurrenceIntervalUnit] == [
            "day",
            "week",
            "month",
            "year",
        ]

    @pytest.mark.parametrize("count", [0, -3])
    def test_a_count_below_one_is_refused(self, count: int) -> None:
        with pytest.raises(TaskValidationError) as exc_info:
            RecurrenceInterval(count=count, unit=RecurrenceIntervalUnit.WEEK)

        assert exc_info.value.field == "recurrence"

    @pytest.mark.parametrize("count", [True, 2.0, "2"])
    def test_a_count_that_is_not_an_int_is_refused(self, count: Any) -> None:
        """``bool`` subclasses ``int``, so it is refused by name."""
        with pytest.raises(TaskValidationError) as exc_info:
            RecurrenceInterval(count=count, unit=RecurrenceIntervalUnit.WEEK)

        assert exc_info.value.field == "recurrence"

    def test_a_bare_string_unit_is_refused(self) -> None:
        """Surfaces parse into the enum first, as they do for ``TaskIcon``."""
        with pytest.raises(TaskValidationError) as exc_info:
            RecurrenceInterval(count=2, unit="week")  # type: ignore[arg-type]

        assert exc_info.value.field == "recurrence"


class TestRecurrenceModes:
    """Each value object names its own stored mode."""

    def test_each_type_has_its_own_mode(self) -> None:
        modes = [recurrence_type.mode for recurrence_type in TASK_RECURRENCE_TYPES]

        assert sorted(modes) == sorted(RecurrenceMode)

    def test_the_modes_are_the_stored_keys(self) -> None:
        """Pinned: the keys are what the database CHECK accepts."""
        assert NoDateRecurrence.mode == "no_date"
        assert IntervalRecurrence.mode == "interval"
        assert SeriesRecurrence.mode == "series"

    def test_series_mode_carries_its_series(self) -> None:
        series_id = uuid4()

        assert SeriesRecurrence(series_id=series_id).series_id == series_id

    def test_interval_mode_carries_its_interval(self) -> None:
        interval = RecurrenceInterval(count=3, unit=RecurrenceIntervalUnit.MONTH)

        assert IntervalRecurrence(interval=interval).interval == interval

    def test_a_series_id_must_be_a_uuid(self) -> None:
        """A string id here means a caller skipped parsing it."""
        with pytest.raises(TaskValidationError) as exc_info:
            SeriesRecurrence(series_id=str(uuid4()))  # type: ignore[arg-type]

        assert exc_info.value.field == "recurrence"

    def test_interval_mode_needs_a_recurrence_interval(self) -> None:
        with pytest.raises(TaskValidationError) as exc_info:
            IntervalRecurrence(interval=(2, "week"))  # type: ignore[arg-type]

        assert exc_info.value.field == "recurrence"
