"""The recurrence a Google recurring instance's journal series is keyed on.

Editing a recurring event with "this and following events" ends the original
recurrence at that occurrence and starts a new one carrying the rest. Google
gives the new recurrence the original's id plus ``_R<start>`` — ``_R`` and the
split occurrence's start as ``YYYYMMDD`` (all-day) or ``YYYYMMDDTHHMMSS``,
optionally ``Z``. Splitting again appends another suffix.

To the user every split is still the same meeting, so they all belong in one
journal series. Folding the suffixes away gives the id they share. Event ids
are base32hex — lowercase ``a``-``v`` and digits — so an uppercase ``_R``
followed by a date can only be a split marker, never part of an id.

The per-split id stays on each external event link: a split deleted upstream
must cancel its own instances and no other split's.
"""

import re

# Kept identical to the regex migration 0122 used to fold existing series.
_SPLIT_SUFFIXES = re.compile(r"(?:_R\d{8}(?:T\d{6}Z?)?)+$")


def root_recurring_event_id(recurring_event_id: str | None) -> str | None:
    """Return the id of the recurrence ``recurring_event_id`` was split from.

    Args:
        recurring_event_id: An instance's ``recurringEventId``, or ``None``
            for an event that is not part of a recurrence.

    Returns:
        The original recurrence's id with every split suffix removed; the id
        unchanged when it was never split; ``None`` for ``None``.
    """
    if recurring_event_id is None:
        return None
    return _SPLIT_SUFFIXES.sub("", recurring_event_id)
