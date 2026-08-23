"""Coerce JSON type-data override values to the types their columns expect.

Merge overrides travel as JSON, so a value the caller "kept" comes back as
whatever JSON can express: a clock time is the string ``'19:30:00'``, a date is
``'2026-08-23'``. The merge writes those values straight into the type tables
with a parameterised UPDATE, and asyncpg encodes each parameter against the
column's real type — a string bound to a ``TIME`` column is rejected outright
("'str' object has no attribute 'hour'"), not silently cast.

So the value has to arrive already typed. The column's own
``information_schema`` ``data_type`` is what decides, rather than the shape of
the string or a sibling row's value, so a column that is NULL on both journals
is handled the same as one that is not.
"""

from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any, NamedTuple

from core_shared.models.journals.exceptions import JournalValidationError

_TRUE_STRINGS = frozenset({"true", "t", "yes", "y", "on", "1"})
_FALSE_STRINGS = frozenset({"false", "f", "no", "n", "off", "0"})


def _parse_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in _TRUE_STRINGS:
        return True
    if lowered in _FALSE_STRINGS:
        return False
    raise ValueError(f"{raw!r} is not a boolean")


class _ColumnRule(NamedTuple):
    """How a column reads a JSON string, and what it accepts already typed."""

    parse: Callable[[str], Any]
    accepts: tuple[type, ...]


# Postgres ``information_schema.columns.data_type`` → its rule. Types absent
# here (text, uuid, jsonb, enum labels, arrays) are left alone entirely: they
# take a string as-is, and narrowing them would risk rejecting payloads that
# work today — a rule that guesses is worse than no rule.
# ``fromisoformat`` reads the ``Z`` suffix JSON producers emit as of 3.11, so no
# hand-rolled offset juggling is needed here.
_RULES: dict[str, _ColumnRule] = {
    "time without time zone": _ColumnRule(time.fromisoformat, (time,)),
    "time with time zone": _ColumnRule(time.fromisoformat, (time,)),
    "date": _ColumnRule(date.fromisoformat, (date,)),
    "timestamp without time zone": _ColumnRule(datetime.fromisoformat, (datetime,)),
    "timestamp with time zone": _ColumnRule(datetime.fromisoformat, (datetime,)),
    "numeric": _ColumnRule(Decimal, (Decimal, int, float)),
    "smallint": _ColumnRule(int, (int,)),
    "integer": _ColumnRule(int, (int,)),
    "bigint": _ColumnRule(int, (int,)),
    "real": _ColumnRule(float, (int, float)),
    "double precision": _ColumnRule(float, (int, float)),
    "boolean": _ColumnRule(_parse_bool, (bool,)),
}


def _serves_column(value: Any, accepts: tuple[type, ...]) -> bool:
    """Can ``value`` be bound to a column that accepts ``accepts`` as-is?

    ``bool`` is an ``int`` subclass to Python but not a number to Postgres, so
    it only serves a column that asked for a boolean.
    """
    if isinstance(value, bool) and bool not in accepts:
        return False
    return isinstance(value, accepts)


def coerce_type_data_override(column: str, value: Any, data_type: str | None) -> Any:
    """Return ``value`` as the Python type ``column`` takes.

    A string is read into that type. A value that already carries a type the
    column accepts is passed through untouched. Anything else — a number for a
    time column, say — cannot be bound at all, and saying so here is the
    difference between a 400 and a driver-level 500.

    Raises:
        JournalValidationError: ``value`` cannot serve that column, which is a
            bad request rather than a database failure.
    """
    if value is None or data_type is None:
        return value

    rule = _RULES.get(data_type.lower())
    if rule is None:
        return value

    if isinstance(value, str):
        try:
            return rule.parse(value)
        except (ValueError, TypeError, InvalidOperation) as exc:
            raise JournalValidationError(
                column, f"{value!r} is not a valid {data_type} value"
            ) from exc

    if _serves_column(value, rule.accepts):
        return value

    raise JournalValidationError(column, f"{value!r} is not a valid {data_type} value")
