"""Marking the days a change makes stale, and never generating one.

ITER18-005 Phase 7's invalidation: an event arrives, this decides which days it
makes stale, and those rows are moved to ``PENDING``. The next read of such a
day regenerates it — which is the whole of the phase's laziness requirement.
Four task ticks in a row cost one regeneration because four invalidations of one
day are four ``UPDATE``\\ s and no generations, and a summary is never
regenerated underneath a user because **nothing that could generate one is
injected here**.

It reads four things and writes one: the journal (for the days it occupies), the
task (for the due journal a payload does not name), the contact's dates (to tell
a birthday this week from one in November), and the user's timezone (because a
day is local, never UTC's). The day arithmetic itself lives in
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

import datetime
from typing import TYPE_CHECKING, Any

import structlog
from core_shared.models.contacts.important_date_occurrence import resolve_occurrence
from core_shared.models.date_window import DEFAULT_UPCOMING_DAYS_AHEAD, upcoming_window

from app.core.journal.models.events import parse_event_date_range
from app.core.journal.services.daily_summary_invalidation_targets import (
    DaySpan,
    InvalidationTarget,
    day_span_of,
    targets_for_journal,
    targets_for_task_due_span,
)
from app.core.journal.services.journal_date_resolver import today_in

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from zoneinfo import ZoneInfo

    from app.core.contacts.models.repositories import ContactRepository
    from app.core.journal.models.repositories import JournalRepository
    from app.core.journal.services.daily_summary_repository import (
        JournalDailySummaryRepository,
    )
    from app.core.journal.services.journal_date_resolver import JournalDateResolver
    from app.core.tasks.models.repositories import TaskRepository

logger = structlog.get_logger()


def _utc_now() -> datetime.datetime:
    """The clock, read **once** per event and handed down from there.

    Module-level so tests can pin it, and read once because an event that
    sampled it twice could build a window against one local day and judge the
    task's own day against the next — the defect ITER18-001 Phase 14 found and
    ITER18-004 Phase 11's review found twice more.
    """
    return datetime.datetime.now(tz=datetime.UTC)


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

#: Task events whose subject still exists and whose **due** journal decides the
#: days. ``TaskJournalLinked``/``TaskJournalUnlinked`` are deliberately absent:
#: a task's intermediate journals are populated on the read model and never
#: rendered, so attaching one cannot change a prompt.
TASK_SPAN_EVENTS = frozenset(
    {
        "TaskCreated",
        "TaskUpdated",
        "TaskDueJournalRetargeted",
        "TaskJournalLinksRepointed",
    }
)

#: A deleted task has no row and a deliberately minimal payload, so its day
#: cannot be resolved at all; see :meth:`_targets_for_deleted_task`.
TASK_DELETED_EVENT = "TaskDeleted"

#: Important-date events. The app publishes ``ImportantDateAdded`` for every
#: surviving date whenever a contact is saved — ``update_contact`` deletes them
#: all and re-adds them — so these fire on an add, an edit *and* a delete.
IMPORTANT_DATE_ADDED_EVENT = "ImportantDateAdded"
IMPORTANT_DATE_DELETED_EVENT = "ImportantDateDeleted"

#: A contact save that changed how many dates it has. This is the **only**
#: announcement that a date was removed: the re-add above publishes nothing for
#: the one that went, and ``ImportantDateDeleted`` has no production caller.
CONTACT_UPDATED_EVENT = "ContactUpdated"

#: Deleting a contact takes its important dates with it, by cascade, and
#: publishes only this — so a summary listing one of those dates would otherwise
#: go on naming a contact that no longer exists. Raised by review.
CONTACT_DELETED_EVENT = "ContactDeleted"

#: The ``changed_fields`` keys that mean a contact's dates are not what the
#: summary was generated from.
#:
#: ``important_dates`` is a ``"count:N"`` **string** pair, written only when the
#: count moved. ``merged_from`` is a contact merge, which re-points the absorbed
#: contact's date rows onto the survivor and deletes the absorbed row: the dates
#: survive but the **name** rendered beside them does not, and a date line
#: renders ``entry.contact.display_name``. Raised by review.
IMPORTANT_DATE_FIELDS = frozenset({"important_dates", "merged_from"})

#: Everything this service handles, in one place so a consumer's subscription
#: and a test's negatives can both be written against it rather than against a
#: list somebody has to remember to extend.
HANDLED_EVENT_TYPES = frozenset(
    JOURNAL_SPAN_EVENTS
    | TASK_SPAN_EVENTS
    | {
        JOURNAL_DELETED_EVENT,
        JOURNAL_CONTACT_EVENT,
        TASK_DELETED_EVENT,
        IMPORTANT_DATE_ADDED_EVENT,
        IMPORTANT_DATE_DELETED_EVENT,
        CONTACT_UPDATED_EVENT,
        CONTACT_DELETED_EVENT,
    }
)


async def invalidate_days_of_journal(
    journal: Any,
    *,
    date_resolver: JournalDateResolver,
    summary_repo: JournalDailySummaryRepository,
) -> None:
    """Mark stale every day this journal occupies.

    The same rule :class:`DailySummaryInvalidationService` applies to a journal
    event, exposed for the write paths that **publish no event for it to
    consume**. The inbound Google sync has three: a calendar-info-only update, an
    attendee-only update and an upstream cancellation, each of which changes the
    day's agenda through raw SQL with nothing announced.

    Publishing ``JournalUpdated`` from those paths would have been tidier and is
    deliberately not done: the Google worker consumes that event to sync a
    journal *out*, so an inbound change would echo straight back upstream.
    """
    tz = await date_resolver.timezone_for(journal.user_id)
    span = day_span_of(journal.event_date_range, tz)
    await summary_repo.invalidate_for_range(
        journal.user_id, span.first_day, span.last_day
    )
    logger.info(
        "Marked daily summaries stale for a change that publishes no event",
        user_id=journal.user_id,
        first_day=span.first_day.isoformat(),
        last_day=span.last_day.isoformat(),
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
        task_repo: TaskRepository,
        contact_repo: ContactRepository,
    ) -> None:
        self.journal_repo = journal_repo
        self.date_resolver = date_resolver
        self.summary_repo = summary_repo
        self.task_repo = task_repo
        self.contact_repo = contact_repo

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
        elif event_type in TASK_SPAN_EVENTS:
            targets = await self._targets_for_task_event(event_type, event_data)
        elif event_type == TASK_DELETED_EVENT:
            targets = await self._targets_for_deleted_task(event_data)
        elif event_type in (
            IMPORTANT_DATE_ADDED_EVENT,
            IMPORTANT_DATE_DELETED_EVENT,
            CONTACT_UPDATED_EVENT,
            CONTACT_DELETED_EVENT,
        ):
            targets = await self._targets_for_important_date_event(
                event_type, event_data
            )
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
            # Deleted between the write and this consumer running. The deletion
            # event carries the days the journal held *at deletion*, so the only
            # thing lost is the span an update said it had **left** — a journal
            # moved to another day and then deleted before either event was
            # consumed. That day cannot be attributed here: ``JournalUpdated``
            # names no ``user_id`` (unlike ``JournalCreated`` and
            # ``JournalDeleted``), and the row that would have answered is gone.
            # Recorded as a limitation of ITER18-005 Phase 7 rather than closed,
            # because closing it means adding ``user_id`` to that payload across
            # its six publishers. Raised by review.
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

    async def _targets_for_task_event(
        self, event_type: str, event_data: Mapping[str, Any]
    ) -> frozenset[InvalidationTarget]:
        """The days a task change makes stale, via its **due** journal.

        A retarget names two journals and yields two answers — the day that lost
        the task and the day that gained it, which is the criterion in its own
        words. Everything else names at most one, and ``TaskUpdated`` names
        none: it carries only what changed, never an anchor it kept, so the task
        is read for it.
        """
        user_id = event_data.get("user_id")
        if not user_id:
            logger.debug("No user_id on the task event; nothing to invalidate")
            return frozenset()

        journal_ids = self._due_journal_ids(event_type, event_data)
        if not journal_ids:
            task_id = event_data.get("task_id")
            if task_id is None:
                return frozenset()
            task = await self.task_repo.find_by_id(int(task_id), str(user_id))
            if task is None:
                # Deleted between the write and this consumer running; its own
                # deletion event is what speaks for it.
                logger.debug("Task no longer exists", task_id=task_id)
                return frozenset()
            journal_ids = [task.due_journal_id]

        now = _utc_now()
        tz = await self.date_resolver.timezone_for(str(user_id))
        today = today_in(tz, now)
        window = upcoming_window(today, DEFAULT_UPCOMING_DAYS_AHEAD)

        targets: set[InvalidationTarget] = set()
        for journal_id in journal_ids:
            journal = await self.journal_repo.find_by_id(journal_id)
            if journal is None:
                # A merge's absorbed journal is deleted by the merge itself, so
                # this is expected rather than exceptional — and the day it was
                # on is covered by its own ``JournalDeleted``, which carries the
                # days it occupied.
                continue
            targets |= targets_for_task_due_span(
                str(user_id),
                day_span_of(journal.event_date_range, tz),
                today=today,
                window=window,
            )
        return frozenset(targets)

    @staticmethod
    def _due_journal_ids(event_type: str, event_data: Mapping[str, Any]) -> list[int]:
        """The due journals a payload names, which is none, one or two.

        ``TaskCreated`` carries the anchor outright. A retarget and a journal
        merge both carry an ``(old, new)`` pair under ``due_journal_id`` — and
        the merge's is conditional, because only some merges move the anchor, so
        its absence means the task's due journal did not change.
        """
        if event_type == "TaskCreated":
            due_journal_id = event_data.get("due_journal_id")
            return [int(due_journal_id)] if due_journal_id is not None else []

        changed_fields = event_data.get("changed_fields") or {}
        if not isinstance(changed_fields, dict):
            return []
        pair = changed_fields.get("due_journal_id")
        if not isinstance(pair, list | tuple):
            return []
        return [int(journal_id) for journal_id in pair if journal_id is not None]

    async def _targets_for_deleted_task(
        self, event_data: Mapping[str, Any]
    ) -> frozenset[InvalidationTarget]:
        """Today, and only today, because no day can be resolved.

        ``TaskDeleted``'s payload is deliberately minimal — that domain's
        standing decision, so a delete costs one statement and no read — and the
        row is gone, so its due journal is unknowable. Today is marked because a
        task the user has deleted still named in today's prose is the visible
        harm. **A past day that named it goes on doing so**, and that is
        recorded as a limitation of this phase rather than hidden here.
        """
        user_id = event_data.get("user_id")
        if not user_id:
            return frozenset()
        today = today_in(
            await self.date_resolver.timezone_for(str(user_id)), _utc_now()
        )
        return frozenset({InvalidationTarget.for_day(str(user_id), today)})

    async def _targets_for_important_date_event(
        self, event_type: str, event_data: Mapping[str, Any]
    ) -> frozenset[InvalidationTarget]:
        """The current day of every user who has a summary to make stale.

        **Whose day?** ``contacts`` carries no owner column, so none of these
        events names a user. Invalidation only ever touches rows that exist, so
        the set that can possibly be affected *is* the users who already have a
        summary row — which is a bound rather than a scan, and where the users
        come from.

        **Which of them?** Only those whose week the date falls in, when there
        is a row left to ask. There usually is: ``update_contact`` re-adds every
        date on every contact save, so without the window test editing a phone
        number would cost an AI call for a birthday six months away. When the
        row is gone — a deletion, or the count pair that is a deletion's only
        announcement — there is no before-image to test and today is marked
        unconditionally.
        """
        if event_type == CONTACT_UPDATED_EVENT and not self._touched_important_dates(
            event_data
        ):
            return frozenset()

        stored = None
        if event_type == IMPORTANT_DATE_ADDED_EVENT:
            stored = await self._stored_date(event_data)

        now = _utc_now()
        targets: set[InvalidationTarget] = set()
        for user_id in await self.summary_repo.user_ids_with_summaries():
            tz: ZoneInfo = await self.date_resolver.timezone_for(user_id)
            today = today_in(tz, now)
            window = upcoming_window(today, DEFAULT_UPCOMING_DAYS_AHEAD)
            if stored is not None and (
                resolve_occurrence(
                    stored, first_day=window.first_day, last_day=window.last_day
                )
                is None
            ):
                continue
            targets.add(InvalidationTarget.for_day(user_id, today))
        return frozenset(targets)

    @staticmethod
    def _touched_important_dates(event_data: Mapping[str, Any]) -> bool:
        """Whether this contact save changed what the dates section would say.

        Two keys mean it did, and they are different events wearing one type.
        ``important_dates`` is a ``("count:2", "count:1")`` pair — strings, not
        numbers — written only when the count moved, so its presence *is* the
        question being asked. ``merged_from`` is a contact merge: the absorbed
        contact's date rows are re-pointed onto the survivor and the absorbed
        row is deleted, so the dates live on under a **different name** — and a
        date line renders the contact's display name, so a summary generated
        before the merge goes on naming somebody who no longer exists.

        A contact whose name merely changed publishes neither key, and that
        stays a recorded limitation rather than an invalidation.
        """
        changed_fields = event_data.get("changed_fields") or {}
        if not isinstance(changed_fields, dict):
            return False
        return bool(IMPORTANT_DATE_FIELDS & set(changed_fields))

    async def _stored_date(self, event_data: Mapping[str, Any]) -> Any:
        """The row this event is about, or ``None`` when it cannot be read.

        Read through the contact's dates rather than by id alone because that is
        the port this domain has; the list is a handful of rows. ``None`` — a
        missing id, a contact since deleted, a date since removed — falls
        through to marking today, which is the safe answer when the window
        cannot be tested.
        """
        contact_id = event_data.get("contact_id")
        date_id = event_data.get("date_id")
        if contact_id is None or date_id is None:
            return None
        dates: Iterable[Any] = await self.contact_repo.get_important_dates(
            int(contact_id)
        )
        return next((row for row in dates if row.id == int(date_id)), None)

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
