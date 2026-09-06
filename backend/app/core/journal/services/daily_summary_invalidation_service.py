"""Marking the days a change makes stale, and never generating one.

ITER18-005 Phase 7's invalidation: an event arrives, this decides which days it
makes stale, and those rows are moved to ``PENDING``. The next read of such a
day regenerates it — which is the whole of the phase's laziness requirement.
Four task ticks in a row cost one regeneration because four invalidations of one
day are four ``UPDATE``\\ s and no generations, and a summary is never
regenerated underneath a user because **nothing that could generate one is
injected here**.

It reads three things and writes one: the journal (for the days it occupies),
the user's timezone (because a day is local, never UTC's), and the summary
repository (to mark the span). The day arithmetic itself lives in
:mod:`app.core.journal.services.daily_summary_invalidation_targets`, which is
pure.

**Every payload reaching this class is data, not a call.** It arrives as JSON
through a Redis stream, may have been published by an older deploy, and is
replayed on retry — so a missing key, an unparseable range or a journal that has
since been deleted is answered with "nothing to invalidate" and a log line,
never an exception. An exception here would leave the event unacknowledged and
retry it to the dead-letter table, which costs the invalidations that *were*
possible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from app.core.journal.models.events import parse_event_date_range
from app.core.journal.services.daily_summary_invalidation_targets import (
    DaySpan,
    InvalidationTarget,
    day_span_of,
    targets_for_journal,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from app.core.journal.models.repositories import JournalRepository
    from app.core.journal.services.daily_summary_repository import (
        JournalDailySummaryRepository,
    )
    from app.core.journal.services.journal_date_resolver import JournalDateResolver

logger = structlog.get_logger()

#: Journal events whose subject is a journal that still exists, so its days can
#: be read from the row. ``JournalUpdated`` is here and does one thing more: it
#: may also carry the days the journal *left*.
#:
#: The type events are in the set although the handler this replaces ignored
#: them: ``event_count`` is derived from a journal's types, and removing the
#: EVENT type takes the journal off the day's agenda altogether.
JOURNAL_SPAN_EVENTS = frozenset(
    {
        "JournalCreated",
        "JournalUpdated",
        "JournalTypeAdded",
        "JournalTypeRemoved",
    }
)

#: The deleted journal's days come from the event, because the row is gone.
JOURNAL_DELETED_EVENT = "JournalDeleted"

#: Attaching or detaching a contact on a journal publishes only this, and the
#: summary's ``contact_count`` and contact names are gathered from exactly those
#: relationships. The journal travels on the payload; see the event's docstring.
JOURNAL_CONTACT_EVENT = "ContactSummaryRefreshRequested"

#: Everything this service handles, in one place so a consumer's subscription
#: and a test's negatives can both be written against it rather than against a
#: list somebody has to remember to extend.
HANDLED_EVENT_TYPES = frozenset(
    JOURNAL_SPAN_EVENTS | {JOURNAL_DELETED_EVENT, JOURNAL_CONTACT_EVENT}
)


class DailySummaryInvalidationService:
    """Turns a domain event into the days whose summaries are now stale.

    Deliberately without a generator, a prompt builder or a
    ``DailySummaryService``: the phase requires that an input change never costs
    an AI call, and a class that cannot make one satisfies that by construction
    rather than by discipline.
    """

    def __init__(
        self,
        journal_repo: JournalRepository,
        date_resolver: JournalDateResolver,
        summary_repo: JournalDailySummaryRepository,
    ) -> None:
        self.journal_repo = journal_repo
        self.date_resolver = date_resolver
        self.summary_repo = summary_repo

    async def invalidate_for_event(
        self, event_type: str, event_data: Mapping[str, Any]
    ) -> None:
        """Mark stale every day this event changes. A no-op for anything else.

        Args:
            event_type: The domain event's type
            event_data: Its payload, exactly as it came off the stream
        """
        if event_type in JOURNAL_SPAN_EVENTS:
            targets = await self._targets_for_journal_event(event_type, event_data)
        elif event_type == JOURNAL_DELETED_EVENT:
            targets = await self._targets_for_deleted_journal(event_data)
        elif event_type == JOURNAL_CONTACT_EVENT:
            targets = await self._targets_for_journal_contact_change(event_data)
        else:
            return

        await self._invalidate(targets)

    async def _invalidate(self, targets: frozenset[InvalidationTarget]) -> None:
        """One guarded statement per span; nothing is created and nothing generates."""
        for target in targets:
            await self.summary_repo.invalidate_for_range(
                target.user_id, target.span.first_day, target.span.last_day
            )
            logger.info(
                "Marked daily summaries stale",
                user_id=target.user_id,
                first_day=target.span.first_day.isoformat(),
                last_day=target.span.last_day.isoformat(),
            )

    async def _targets_for_journal_event(
        self, event_type: str, event_data: Mapping[str, Any]
    ) -> frozenset[InvalidationTarget]:
        """The journal's days now, plus the days it left when they moved."""
        journal_id = event_data.get("journal_id")
        if journal_id is None:
            logger.debug("No journal_id on the event; nothing to invalidate")
            return frozenset()

        journal = await self.journal_repo.find_by_id(int(journal_id))
        if journal is None:
            # Deleted between the write and this consumer running. Its own
            # deletion event carries the days, so nothing is lost by returning.
            logger.debug(
                "Journal no longer exists; its deletion event carries the days",
                journal_id=journal_id,
            )
            return frozenset()

        tz = await self.date_resolver.timezone_for(journal.user_id)
        spans = [day_span_of(journal.event_date_range, tz)]

        previous = self._previous_span(event_type, event_data, tz)
        if previous is not None:
            spans.append(previous)

        return targets_for_journal(journal.user_id, *spans)

    @staticmethod
    def _previous_span(
        event_type: str, event_data: Mapping[str, Any], tz: Any
    ) -> DaySpan | None:
        """The days a journal occupied *before* an update moved it, if it did.

        ``JournalUpdated`` names only what actually changed, so the absence of
        an ``event_date_range`` pair is the statement that the journal did not
        move — no second span, and one statement rather than two.
        """
        if event_type != "JournalUpdated":
            return None
        changed_fields = event_data.get("changed_fields") or {}
        if not isinstance(changed_fields, dict):
            return None
        pair = changed_fields.get("event_date_range")
        if not isinstance(pair, list | tuple) or len(pair) != 2:
            return None
        previous = parse_event_date_range(pair[0])
        if previous is None:
            return None
        return day_span_of(previous, tz)

    async def _targets_for_deleted_journal(
        self, event_data: Mapping[str, Any]
    ) -> frozenset[InvalidationTarget]:
        """The days a deleted journal occupied, read from the event itself."""
        user_id = event_data.get("user_id")
        event_date_range = parse_event_date_range(event_data.get("event_date_range"))
        if not user_id or event_date_range is None:
            # Published before the range was carried, or by a caller that had no
            # journal loaded. The day keeps its counters until something else
            # changes on it; recorded as a limitation rather than guessed at.
            logger.debug(
                "Deleted journal event carries no days; nothing to invalidate",
                journal_id=event_data.get("journal_id"),
            )
            return frozenset()

        tz = await self.date_resolver.timezone_for(str(user_id))
        return targets_for_journal(str(user_id), day_span_of(event_date_range, tz))

    async def _targets_for_journal_contact_change(
        self, event_data: Mapping[str, Any]
    ) -> frozenset[InvalidationTarget]:
        """A day's people changed, so its counters and its agenda did."""
        if event_data.get("journal_id") is None:
            # A contact edit or a manual refresh: no journal, no day.
            return frozenset()
        return await self._targets_for_journal_event(
            "ContactSummaryRefreshRequested", event_data
        )
