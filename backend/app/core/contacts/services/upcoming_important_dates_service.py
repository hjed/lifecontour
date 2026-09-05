"""Assembling the important contact dates coming up in the next few days.

Three callers want the same answer and must not each build it: the home
dashboard's upcoming-dates section, the MCP tool an agent composes that view
from, and — from ITER18-005 Phase 6 — the daily summary's inputs. So the
window, the two reads and the ranking live here once.

**Two reads, and the second is keyed off the first.** The candidate query
fetches the rows whose stored ``(month, day)`` could land in the window; the
batched importance read then ranks the contacts those rows belong to. A window
that finds nothing costs one read, not two — the common case for a quiet week,
and the reason ``for_contacts`` short circuits on an empty batch.

The batch is built from the **candidates** rather than from the resolved
survivors, which keeps the recurrence rule to a single pass. The two sets are
the same set: a row can only be a candidate if its stored pair matches a day the
window covers, or the leap day standing in for one, and every such row resolves
inside the window. The rows that do *not* resolve — ``year`` precision, or a
month and day that are no calendar date — carry no matchable pair and are never
fetched, which the repository's own tests assert.

**One clock read per request, and one settings read.** ITER18-001 Phase 14
shipped a listing that sampled the clock twice — once to build its window and
once to judge its rows — so a request crossing local midnight between the two
built the window against one day and judged the rows against the next, dropping
a row from a window that claimed to include it. It then shipped a second
instance of the same shape in the same file. The lesson taken here is
structural rather than careful: the instant is sampled **once**, at the top, and
that same object decides both the day the window starts on and the instant the
importance signals measure their thirty days back from.

There are two "now"s in this read and it is easy to see only one of them. The
first attempt threaded the caller's instant into the day and left the *signals*
read to sample the clock for itself — which the PR review on #1404 caught. The
drift is microseconds and the signals are a tie-break in an already-coarse
ordering, so nothing user-visible turned on it; what did turn on it is that a
caller injecting ``now`` had pinned only half the answer, and a test asserting
on a count at the thirty-day boundary would have failed on its own schedule with
nothing to point at. A module claiming one clock read has to mean all of it.

**The window is bounded in the domain**, not only on each surface, so it cannot
be sidestepped by reaching this service another way — and the bound is refused
before either listing read runs.
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from core_shared.models.date_window import DEFAULT_UPCOMING_DAYS_AHEAD

from app.core.contacts.models.upcoming_dates import (
    UpcomingContactDates,
    select_upcoming_dates,
    upcoming_dates_window,
    window_month_days,
)

if TYPE_CHECKING:
    from app.core.contacts.models.repositories import (
        ContactImportanceRepository,
        UpcomingImportantDateRepository,
    )
    from app.core.journal.services.journal_date_resolver import JournalDateResolver


class UpcomingImportantDatesService:
    """Reads the important contact dates falling in a window of days.

    Read-only: it opens no unit of work, because there is nothing here to
    commit.

    ``JournalDateResolver`` is a journal-domain collaborator, which looks odd in
    a contacts service until one asks where else "today, in the acting user's
    timezone" would live. It reads ``UserSettingsRepository`` and nothing
    journal-shaped, the tasks domain's read service already depends on it for
    the same reason, and a second resolver in the contacts domain would be a
    second answer to what day it is.
    """

    def __init__(
        self,
        date_resolver: JournalDateResolver,
        candidate_repo: UpcomingImportantDateRepository,
        importance_repo: ContactImportanceRepository,
    ) -> None:
        self.date_resolver = date_resolver
        self.candidate_repo = candidate_repo
        self.importance_repo = importance_repo

    async def upcoming_dates(
        self,
        user_id: str,
        *,
        days_ahead: int = DEFAULT_UPCOMING_DAYS_AHEAD,
        today: datetime.date | None = None,
        now: datetime.datetime | None = None,
    ) -> UpcomingContactDates:
        """The important dates falling between today and ``days_ahead`` ahead.

        Args:
            user_id: The acting user, whose configured timezone decides where
                their day starts. Note that the *dates* are not scoped by it:
                ``contacts`` carries no owner column in this schema.
            days_ahead: How far to look, inclusive of both ends. Defaults to the
                seven days the dashboard shows.
            today: Today's date, already resolved in the user's timezone. Pass
                it when the caller has one — the dashboard resolves a single
                anchor for all four of its sections — and the clock is then not
                read here at all.
            now: The instant this read is "as at". It resolves ``today`` when
                ``today`` was not supplied, and in **either** case it is the
                instant the importance signals measure their thirty-day recency
                window back from. Injectable so a day boundary is testable, and
                supplying it pins the whole answer rather than half of it.
                Defaults to one sample of the clock, taken once and shared.

        Returns:
            The window and the dates in it, ordered by occurrence date then
            contact importance descending. **Uncapped**: the whole window
            travels with its total, and a surface applies its own cap, so a
            show-more costs no second request.

        Raises:
            ContactValidationError: ``days_ahead`` is negative or beyond the
                shared maximum.
        """
        moment = now or datetime.datetime.now(datetime.UTC)
        window = upcoming_dates_window(
            today
            if today is not None
            else await self.date_resolver.today(user_id, moment),
            days_ahead,
        )

        candidates = await self.candidate_repo.candidates_for(window_month_days(window))
        contact_ids = list(dict.fromkeys(row.contact.id for row in candidates))
        importance = await self.importance_repo.for_contacts(contact_ids, now=moment)

        return select_upcoming_dates(candidates, window, importance)
