"""The series key of a Google recurring event id.

Google marks a "this and following" split by appending ``_R<start>`` to the
recurrence's id (``_R`` plus the split occurrence's start as ``YYYYMMDD`` or
``YYYYMMDDTHHMMSS[Z]``, repeated for a split of a split). Every split shares
one journal series, keyed on the id with those suffixes removed.

The Google worker computes the same key (``recurrence.root_recurring_event_id``)
and migration 0122 folded existing series with it; the three must agree.
"""

import re

_SPLIT_SUFFIXES = re.compile(r"(?:_R\d{8}(?:T\d{6}Z?)?)+$")


def root_recurring_event_id(recurring_event_id: str) -> str:
    """The id of the recurrence ``recurring_event_id`` was split from."""
    return _SPLIT_SUFFIXES.sub("", recurring_event_id)
