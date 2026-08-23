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
from typing import Any

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


# Postgres ``information_schema.columns.data_type`` → how to read a JSON string
# into the value that column takes. Types absent here (text, uuid, jsonb, enum
# labels, arrays) already encode from a string, so they are left alone: a rule
# that guesses is worse than no rule.
# ``fromisoformat`` reads the ``Z`` suffix JSON producers emit as of 3.11, so no
# hand-rolled offset juggling is needed here.
_PARSERS: dict[str, Callable[[str], Any]] = {
    "time without time zone": time.fromisoformat,
    "time with time zone": time.fromisoformat,
    "date": date.fromisoformat,
    "timestamp without time zone": datetime.fromisoformat,
    "timestamp with time zone": datetime.fromisoformat,
    "numeric": Decimal,
    "smallint": int,
    "integer": int,
    "bigint": int,
    "real": float,
    "double precision": float,
    "boolean": _parse_bool,
}


def coerce_type_data_override(column: str, value: Any, data_type: str | None) -> Any:
    """Return ``value`` as the Python type ``column`` takes.

    Only strings are converted: a JSON number, boolean or null already matches
    its column, and re-parsing one could only lose information.

    Raises:
        JournalValidationError: the string cannot be read as that column's
            type, which is a bad request rather than a database failure.
    """
    if not isinstance(value, str) or data_type is None:
        return value

    parser = _PARSERS.get(data_type.lower())
    if parser is None:
        return value

    try:
        return parser(value)
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise JournalValidationError(
            column, f"{value!r} is not a valid {data_type} value"
        ) from exc
