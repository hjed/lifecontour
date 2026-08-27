"""Read ports for the dashboard's projections.

The dashboard is assembled from reads that belong to no single domain, and this
is where the ports for them live. They return **dashboard** models — an
``AgendaEntry``, not a ``Journal`` — because the projection's shape is the
dashboard's concern: a section carries what its card draws, denormalised, and
nothing else.

That is why these sit here rather than beside ``OutdoorDashboardRepository`` in
the journal domain. The outdoor one belongs there because it returns a journal
model for a journal-scoped projection; putting a port that returns dashboard
models into the journal domain would point that domain at this one, for no gain.

Every method takes the acting ``user_id`` and every implementation must scope on
it. Nothing in the dashboard is shared between users, and a read port with no
owner parameter is the shape that eventually leaks one user's day to another.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core_shared.models.journals import EventDateRange

    from app.core.dashboard.models.sections import AgendaEntry


class AgendaRepository(ABC):
    """Reads the event journals an agenda window covers."""

    @abstractmethod
    async def list_entries_in_window(
        self, user_id: str, *, window: EventDateRange
    ) -> list[AgendaEntry]:
        """The user's event journals overlapping ``window``.

        **Overlap, not containment.** An event that began before the window and
        ends after it is inside the window in the only sense the agenda cares
        about: it is happening. The same semantics the outdoor dashboard's
        upcoming query uses.

        Only journals with calendar info are returned — a journal has the EVENT
        type exactly when a ``journal_calendar_info`` row exists for it, so a
        journal without one is a note about the day rather than something
        scheduled on it. Cancelled events are returned **flagged**, not filtered:
        the specification requires them to be shown clearly marked, and a surface
        cannot mark an entry it was never sent.

        The order of the result is not part of the contract — ordering is
        ``order_agenda_entries``' job, and it belongs to the section rather than
        to the query.

        Args:
            user_id: The acting user. Implementations must scope on it.
            window: The instants the day covers, from ``local_day_window``.

        Returns:
            The matching entries with their tags and participants already
            attached, in no guaranteed order.
        """
