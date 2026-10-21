"""A partial update of a journal's own fields, applied to the journal as it stands.

See :mod:`app.shared.patch` for why a caller names its changes instead of
handing over a whole journal built from a read of its own.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from core_shared.models.journals import EventDateRange, Journal

from app.shared.patch import UNSET, FieldPatch, Unset

#: Builds the journal to save from the journal as stored, read under its row
#: lock - or returns ``None`` to write nothing.
type JournalMutation = Callable[[Journal], Awaitable[Journal | None]]


@dataclass(frozen=True, kw_only=True)
class JournalPatch(FieldPatch):
    """The journal's own fields a caller changes."""

    title: str | Unset = UNSET
    content: str | Unset = UNSET
    event_date_range: EventDateRange | Unset = UNSET
    parent_id: int | None | Unset = UNSET
    order: int | None | Unset = UNSET
