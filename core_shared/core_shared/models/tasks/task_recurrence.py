"""A task's recurrence setting: how its next copy is dated (spec *Recurring Tasks*).

A recurring task makes a new copy of itself when it is completed. The setting
is one of three modes, each its own frozen type, so a mode can never carry
another mode's data:

- :class:`NoDateRecurrence` — the copy is undated;
- :class:`IntervalRecurrence` — the copy is due a stored interval after the
  completion day;
- :class:`SeriesRecurrence` — the copy is due in the next journal of a series.

Each type names its stored :class:`RecurrenceMode`, the value of
``tasks.recurrence_mode``. Code that branches on the setting ``match``-es over
:data:`TaskRecurrence` and ends in ``assert_never``, so a new mode cannot be
missed silently. :data:`TASK_RECURRENCE_TYPES` is the same union for runtime
``isinstance`` checks, which a ``type`` alias cannot serve.

Only what a value alone can know is validated here. Whether a series exists and
belongs to the task's owner needs other rows, so it is the service layer's.
"""

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import ClassVar
from uuid import UUID

from .exceptions import TaskValidationError

_FIELD = "recurrence"


@unique
class RecurrenceMode(StrEnum):
    """The stored mode of a recurrence setting (``tasks.recurrence_mode``)."""

    NO_DATE = "no_date"
    INTERVAL = "interval"
    SERIES = "series"


@unique
class RecurrenceIntervalUnit(StrEnum):
    """The unit of an interval after completion (``recurrence_interval_unit``)."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


@dataclass(frozen=True, kw_only=True)
class RecurrenceInterval:
    """An interval as the user entered it: "2 weeks" stays two weeks.

    Kept as a count and a unit rather than a ``timedelta``, because a month or a
    year is not a fixed number of days.
    """

    count: int
    unit: RecurrenceIntervalUnit

    def __post_init__(self) -> None:
        """Refuse a count below one and anything not already parsed."""
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TaskValidationError(
                _FIELD, f"Interval count must be a whole number, got {self.count!r}"
            )
        if self.count < 1:
            raise TaskValidationError(_FIELD, "Interval count must be at least 1")
        if not isinstance(self.unit, RecurrenceIntervalUnit):
            raise TaskValidationError(
                _FIELD,
                f"Interval unit must be a RecurrenceIntervalUnit, got {self.unit!r}",
            )


@dataclass(frozen=True)
class NoDateRecurrence:
    """Each copy is undated."""

    mode: ClassVar[RecurrenceMode] = RecurrenceMode.NO_DATE


@dataclass(frozen=True, kw_only=True)
class IntervalRecurrence:
    """Each copy is due ``interval`` after the day its predecessor was completed."""

    mode: ClassVar[RecurrenceMode] = RecurrenceMode.INTERVAL
    interval: RecurrenceInterval

    def __post_init__(self) -> None:
        """Refuse an interval that was not built as one."""
        if not isinstance(self.interval, RecurrenceInterval):
            raise TaskValidationError(
                _FIELD, f"Interval must be a RecurrenceInterval, got {self.interval!r}"
            )


@dataclass(frozen=True, kw_only=True)
class SeriesRecurrence:
    """Each copy is due in the next journal of the series ``series_id``."""

    mode: ClassVar[RecurrenceMode] = RecurrenceMode.SERIES
    series_id: UUID

    def __post_init__(self) -> None:
        """Refuse a series id that was not parsed into a ``UUID``."""
        if not isinstance(self.series_id, UUID):
            raise TaskValidationError(
                _FIELD, f"Series id must be a UUID, got {self.series_id!r}"
            )


type TaskRecurrence = NoDateRecurrence | IntervalRecurrence | SeriesRecurrence

TASK_RECURRENCE_TYPES: tuple[
    type[NoDateRecurrence], type[IntervalRecurrence], type[SeriesRecurrence]
] = (
    NoDateRecurrence,
    IntervalRecurrence,
    SeriesRecurrence,
)
