"""Unit tests for the daily summary's event-driven invalidation.

The service under test answers one question — *which days does this event make
stale* — and answers it by marking rows ``PENDING``. It never generates: the
laziness ITER18-005 Phase 7 asks for is a property of this class having no
generator to call, and the tests that matter most here are the ones asserting
nothing happened.

The four defects ITER18-004 Phase 4f recorded against the handler this replaces
each have a test below, named for what they are:

1. a journal moved off a day never invalidated the day it left;
2. deleting a journal invalidated nothing at all;
3. adding or removing a contact on a journal invalidated nothing;
4. journal **tags** were expected to matter and, checked here, do not — the
   summary's agenda entries carry no tags and the prompt renders none, so the
   negative is asserted rather than left as an assumption.
"""

import datetime
import inspect
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import Task

from app.core.journal.services import daily_summary_invalidation_service
from app.core.journal.services.daily_summary_invalidation_service import (
    DailySummaryInvalidationService,
)
from tests.unit.journal.upcoming_date_doubles import stored_date

USER_ID = "user-123"
JOURNAL_ID = 42

SYDNEY = ZoneInfo("Australia/Sydney")
UTC_ZONE = ZoneInfo("UTC")

#: 22:00 UTC on the 27th is 08:00 on the **28th** in Sydney, so the two zones
#: disagree about what day it is — which is the only instant at which "the day
#: is the user's" can be asserted rather than asserted-by-coincidence.
NOW = datetime.datetime(2026, 4, 27, 22, 0, tzinfo=datetime.UTC)
TODAY = datetime.date(2026, 4, 27)
SYDNEY_TODAY = datetime.date(2026, 4, 28)


def _instant(day: int, hour: int = 9) -> datetime.datetime:
    return datetime.datetime(2026, 4, day, hour, 0, tzinfo=datetime.UTC)


def _journal(
    *,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    user_id: str = USER_ID,
) -> Journal:
    return Journal(
        id=JOURNAL_ID,
        user_id=user_id,
        title="A day out",
        content="",
        event_date_range=EventDateRange(
            start=start or _instant(27, 9),
            end=end or _instant(27, 10),
        ),
    )


def _range_string(first: datetime.datetime, last: datetime.datetime) -> str:
    """The wire form ``JournalUpdated`` and ``JournalDeleted`` carry."""
    return f"{first.isoformat()}/{last.isoformat()}"


@pytest.fixture
def journal_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_id.return_value = _journal()
    return repo


@pytest.fixture
def date_resolver() -> AsyncMock:
    resolver = AsyncMock()
    resolver.timezone_for.return_value = UTC_ZONE
    return resolver


@pytest.fixture
def task_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.find_by_id.return_value = Task(
        id=5,
        user_id=USER_ID,
        text="book the venue",
        creating_journal_id=JOURNAL_ID,
        due_journal_id=JOURNAL_ID,
    )
    return repo


@pytest.fixture
def contact_repo() -> AsyncMock:
    repo = AsyncMock()
    # Two days ahead of ``TODAY``, so it is inside the week for both zones.
    repo.get_important_dates.return_value = [stored_date(1, month=4, day=29)]
    return repo


@pytest.fixture
def summary_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.user_ids_with_summaries.return_value = [USER_ID]
    return repo


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """One instant for the whole suite, so "today" is a fact rather than a race."""
    monkeypatch.setattr(daily_summary_invalidation_service, "_utc_now", lambda: NOW)


@pytest.fixture
def service(
    journal_repo: AsyncMock,
    date_resolver: AsyncMock,
    summary_repo: AsyncMock,
    task_repo: AsyncMock,
    contact_repo: AsyncMock,
) -> DailySummaryInvalidationService:
    return DailySummaryInvalidationService(
        journal_repo=journal_repo,
        date_resolver=date_resolver,
        summary_repo=summary_repo,
        task_repo=task_repo,
        contact_repo=contact_repo,
    )


def _invalidated(
    summary_repo: AsyncMock,
) -> set[tuple[str, datetime.date, datetime.date]]:
    """Every span this event asked to be marked stale."""
    return {
        (call.args[0], call.args[1], call.args[2])
        for call in summary_repo.invalidate_for_range.call_args_list
    }


class TestAJournalChangeInvalidatesItsWholeSpan:
    """A journal is part of every day it overlaps, so a change makes them stale."""

    @pytest.mark.asyncio
    async def test_a_single_day_journal_invalidates_its_day(
        self, service: DailySummaryInvalidationService, summary_repo: AsyncMock
    ) -> None:
        await service.invalidate_for_event("JournalCreated", {"journal_id": JOURNAL_ID})

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27))
        }

    @pytest.mark.asyncio
    async def test_a_multi_day_journal_invalidates_every_day_in_one_statement(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(24, 18), end=_instant(26, 8)
        )

        await service.invalidate_for_event("JournalUpdated", {"journal_id": JOURNAL_ID})

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 24), datetime.date(2026, 4, 26))
        }
        assert summary_repo.invalidate_for_range.await_count == 1

    @pytest.mark.asyncio
    async def test_the_span_is_read_in_the_users_zone(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        date_resolver: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """22:00 UTC on the 26th is the 27th in Sydney — the day it belongs to.

        The handler this replaces read ``.date()`` off the stored instant, so it
        invalidated the 26th and left the day the user can actually see stale.
        """
        date_resolver.timezone_for.return_value = SYDNEY
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(26, 22), end=_instant(26, 23)
        )

        await service.invalidate_for_event("JournalCreated", {"journal_id": JOURNAL_ID})

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27))
        }

    @pytest.mark.asyncio
    async def test_a_journal_moved_off_a_day_invalidates_the_day_it_left(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """Defect 1 of the four: the old day kept a summary that still counted it."""
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(27, 9), end=_instant(27, 10)
        )

        await service.invalidate_for_event(
            "JournalUpdated",
            {
                "journal_id": JOURNAL_ID,
                "changed_fields": {
                    "event_date_range": [
                        _range_string(_instant(20, 9), _instant(20, 10)),
                        _range_string(_instant(27, 9), _instant(27, 10)),
                    ]
                },
            },
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 20), datetime.date(2026, 4, 20)),
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27)),
        }

    @pytest.mark.asyncio
    async def test_an_edit_that_moved_the_clock_but_not_the_day_costs_one_statement(
        self,
        service: DailySummaryInvalidationService,
        summary_repo: AsyncMock,
    ) -> None:
        await service.invalidate_for_event(
            "JournalUpdated",
            {
                "journal_id": JOURNAL_ID,
                "changed_fields": {
                    "event_date_range": [
                        _range_string(_instant(27, 6), _instant(27, 7)),
                        _range_string(_instant(27, 9), _instant(27, 10)),
                    ]
                },
            },
        )

        assert summary_repo.invalidate_for_range.await_count == 1

    @pytest.mark.asyncio
    async def test_an_unparseable_old_range_still_invalidates_the_current_day(
        self,
        service: DailySummaryInvalidationService,
        summary_repo: AsyncMock,
    ) -> None:
        """The payload arrives back through Redis as a string, so it is data.

        A malformed or legacy value must not cost the invalidation that *can*
        be made, and must not raise into the consumer's retry path.
        """
        await service.invalidate_for_event(
            "JournalUpdated",
            {
                "journal_id": JOURNAL_ID,
                "changed_fields": {"event_date_range": ["not-a-range", "nor-this"]},
            },
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27))
        }

    @pytest.mark.asyncio
    async def test_a_journal_that_no_longer_exists_invalidates_nothing(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        journal_repo.find_by_id.return_value = None

        await service.invalidate_for_event("JournalUpdated", {"journal_id": JOURNAL_ID})

        summary_repo.invalidate_for_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_payload_without_a_journal_id_invalidates_nothing(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        await service.invalidate_for_event("JournalUpdated", {})

        journal_repo.find_by_id.assert_not_awaited()
        summary_repo.invalidate_for_range.assert_not_awaited()


class TestADeletedJournal:
    """Defect 2 of the four: deleting a journal invalidated nothing at all.

    The row is gone by the time the consumer runs, so the day can only come from
    the event — which is why ``JournalDeleted`` now carries the range it had.
    """

    @pytest.mark.asyncio
    async def test_the_carried_range_is_what_makes_the_day_resolvable(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        await service.invalidate_for_event(
            "JournalDeleted",
            {
                "journal_id": JOURNAL_ID,
                "user_id": USER_ID,
                "event_date_range": _range_string(_instant(24, 18), _instant(26, 8)),
            },
        )

        journal_repo.find_by_id.assert_not_awaited()
        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 24), datetime.date(2026, 4, 26))
        }

    @pytest.mark.asyncio
    async def test_the_deleted_journals_day_is_read_in_the_users_zone(
        self,
        service: DailySummaryInvalidationService,
        date_resolver: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        date_resolver.timezone_for.return_value = SYDNEY

        await service.invalidate_for_event(
            "JournalDeleted",
            {
                "journal_id": JOURNAL_ID,
                "user_id": USER_ID,
                "event_date_range": _range_string(_instant(26, 22), _instant(26, 23)),
            },
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27))
        }

    @pytest.mark.asyncio
    async def test_an_event_published_before_the_range_was_carried_is_not_an_error(
        self,
        service: DailySummaryInvalidationService,
        summary_repo: AsyncMock,
    ) -> None:
        """A stream entry outlives a deploy; it must not poison the consumer."""
        await service.invalidate_for_event(
            "JournalDeleted", {"journal_id": JOURNAL_ID, "user_id": USER_ID}
        )

        summary_repo.invalidate_for_range.assert_not_awaited()


class TestTheTypeEventsThatWerePublishedAndIgnored:
    """``event_count`` is derived from types, and the EVENT type *is* the agenda.

    Neither was in the set the previous handler matched, so adding or removing a
    type left the day's counters and its agenda stale.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", ["JournalTypeAdded", "JournalTypeRemoved"])
    async def test_a_type_change_invalidates_the_journals_span(
        self,
        service: DailySummaryInvalidationService,
        summary_repo: AsyncMock,
        event_type: str,
    ) -> None:
        await service.invalidate_for_event(event_type, {"journal_id": JOURNAL_ID})

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27))
        }


class TestAContactChangingOnAJournal:
    """Defect 3 of the four: ``contact_count`` could be wrong with no correction.

    ``JournalContactService`` publishes ``ContactSummaryRefreshRequested``, whose
    aggregate is the contact — so the journal it happened on has to travel on the
    payload for this to be answerable at all.
    """

    @pytest.mark.asyncio
    async def test_a_refresh_caused_by_a_journal_invalidates_that_journals_span(
        self, service: DailySummaryInvalidationService, summary_repo: AsyncMock
    ) -> None:
        await service.invalidate_for_event(
            "ContactSummaryRefreshRequested",
            {"contact_id": 7, "journal_id": JOURNAL_ID},
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27))
        }

    @pytest.mark.asyncio
    async def test_a_refresh_caused_by_a_contact_edit_invalidates_nothing(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """Most of these events come from contact edits and name no journal."""
        await service.invalidate_for_event(
            "ContactSummaryRefreshRequested", {"contact_id": 7, "journal_id": None}
        )

        journal_repo.find_by_id.assert_not_awaited()
        summary_repo.invalidate_for_range.assert_not_awaited()


class TestWhatMustNotInvalidate:
    """Every negative here is a summary that would be thrown away for nothing."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "event_type",
        [
            "JournalTagAssigned",
            "JournalTagRemoved",
            "JournalTagDeleted",
            "JournalTagMerged",
            "JournalTagRenamed",
        ],
    )
    async def test_journal_tag_events_invalidate_nothing(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
        event_type: str,
    ) -> None:
        """Defect 4 of the four, checked and found not to be one.

        ITER18-004 Phase 4f predicted tags would matter here because the
        dashboard's agenda card renders them (**W15**). The *summary*'s agenda
        does not: ``AgendaEntry`` carries no tags and the prompt builder renders
        none, so invalidating on a tag change would discard a cached summary the
        change cannot alter. Asserted rather than assumed, so that indexing tags
        into the prompt cannot ship without this failing.
        """
        await service.invalidate_for_event(event_type, {"journal_id": JOURNAL_ID})

        journal_repo.find_by_id.assert_not_awaited()
        summary_repo.invalidate_for_range.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("event_type", ["TaskJournalLinked", "TaskJournalUnlinked"])
    async def test_a_tasks_intermediate_journal_links_invalidate_nothing(
        self,
        service: DailySummaryInvalidationService,
        task_repo: AsyncMock,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
        event_type: str,
    ) -> None:
        """A task's *mention* links are on the read model and never rendered.

        ``_task_line`` and ``_past_task_line`` render the text, the due journal,
        the contacts and the resolution — ``intermediate_journals`` is populated
        and dropped. Attaching a journal to a task therefore cannot change a
        prompt, and invalidating on it would pay for a regeneration that
        produces the same prose.
        """
        await service.invalidate_for_event(
            event_type, {"task_id": 5, "user_id": USER_ID, "journal_id": JOURNAL_ID}
        )

        task_repo.find_by_id.assert_not_awaited()
        journal_repo.find_by_id.assert_not_awaited()
        summary_repo.invalidate_for_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_unhandled_event_type_invalidates_nothing(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        await service.invalidate_for_event("ContactCreated", {"contact_id": 1})

        journal_repo.find_by_id.assert_not_awaited()
        summary_repo.invalidate_for_range.assert_not_awaited()

    def test_nothing_that_could_generate_a_summary_is_injected(self) -> None:
        """Laziness is structural, not a decision taken per event.

        The constructor takes four reads — journal, task, contact and the
        user's timezone — and the summary repository. No prompt builder, no AI
        client, no ``DailySummaryService``, so no event this consumer receives *can* cost
        a generation. That is what "never regenerated underneath the user" means
        at this layer, and a signature is the only place it can be asserted
        rather than described.
        """
        parameters = set(
            inspect.signature(DailySummaryInvalidationService.__init__).parameters
        )

        assert parameters == {
            "self",
            "journal_repo",
            "date_resolver",
            "summary_repo",
            "task_repo",
            "contact_repo",
        }


class TestATaskChangeFollowsItsDueJournal:
    """A task's days are its **due** journal's, and the two halves differ.

    The current day's prompt lists the not-done tasks whose due journal starts
    inside the week ahead; a past day's lists what was due in that day's
    journals. So a change to a task ahead of the user makes *today* stale and a
    change to one behind them makes *that day* stale — never both.
    """

    @pytest.mark.asyncio
    async def test_a_task_due_today_makes_today_stale(
        self,
        service: DailySummaryInvalidationService,
        summary_repo: AsyncMock,
    ) -> None:
        await service.invalidate_for_event(
            "TaskCreated",
            {"task_id": 5, "user_id": USER_ID, "due_journal_id": JOURNAL_ID},
        )

        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}

    @pytest.mark.asyncio
    async def test_a_task_due_later_this_week_makes_today_stale_not_its_own_day(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """The forward-looking list is rendered on today's prompt and no other."""
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(30), end=_instant(30, 10)
        )

        await service.invalidate_for_event(
            "TaskCreated",
            {"task_id": 5, "user_id": USER_ID, "due_journal_id": JOURNAL_ID},
        )

        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}

    @pytest.mark.asyncio
    async def test_a_task_due_beyond_the_week_makes_nothing_stale(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """No prompt names it, so regenerating anything would be waste."""
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(27) + datetime.timedelta(days=8),
            end=_instant(27, 10) + datetime.timedelta(days=8),
        )

        await service.invalidate_for_event(
            "TaskCreated",
            {"task_id": 5, "user_id": USER_ID, "due_journal_id": JOURNAL_ID},
        )

        summary_repo.invalidate_for_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_task_due_on_a_past_day_makes_that_day_stale(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """That day's prompt says what was due on it and how it resolved."""
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(20), end=_instant(20, 10)
        )

        await service.invalidate_for_event(
            "TaskUpdated",
            {
                "task_id": 5,
                "user_id": USER_ID,
                "changed_fields": {"status": ["not_done", "done"]},
            },
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 20), datetime.date(2026, 4, 20))
        }

    @pytest.mark.asyncio
    async def test_a_task_due_in_a_past_multi_day_journal_covers_every_day(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(20), end=_instant(22, 10)
        )

        await service.invalidate_for_event(
            "TaskUpdated", {"task_id": 5, "user_id": USER_ID, "changed_fields": {}}
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 20), datetime.date(2026, 4, 22))
        }

    @pytest.mark.asyncio
    async def test_an_update_carries_no_journal_so_the_task_is_read(
        self,
        service: DailySummaryInvalidationService,
        task_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """``TaskUpdated`` names only what changed — never an anchor it kept."""
        await service.invalidate_for_event(
            "TaskUpdated",
            {
                "task_id": 5,
                "user_id": USER_ID,
                "changed_fields": {"status": ["not_done", "done"]},
            },
        )

        task_repo.find_by_id.assert_awaited_once_with(5, USER_ID)
        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}

    @pytest.mark.asyncio
    async def test_a_task_that_no_longer_exists_makes_nothing_stale(
        self,
        service: DailySummaryInvalidationService,
        task_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        task_repo.find_by_id.return_value = None

        await service.invalidate_for_event(
            "TaskUpdated", {"task_id": 5, "user_id": USER_ID, "changed_fields": {}}
        )

        summary_repo.invalidate_for_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_the_day_is_the_users_not_utcs(
        self,
        service: DailySummaryInvalidationService,
        date_resolver: AsyncMock,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """Judged from Sydney, where it is already the 28th.

        The window opens on the user's today, so a task due on the 27th is
        *behind* this user and makes that past day stale rather than today.
        """
        date_resolver.timezone_for.return_value = SYDNEY
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(27, 1), end=_instant(27, 2)
        )

        await service.invalidate_for_event(
            "TaskCreated",
            {"task_id": 5, "user_id": USER_ID, "due_journal_id": JOURNAL_ID},
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27))
        }
        assert (USER_ID, SYDNEY_TODAY, SYDNEY_TODAY) not in _invalidated(summary_repo)


class TestARetargetInvalidatesBothDays:
    """The criterion in its own words: the day that lost it and the day that gained it."""

    @pytest.mark.asyncio
    async def test_both_journals_days_are_marked(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        was = _journal(start=_instant(20), end=_instant(20, 10))
        now = _journal(start=_instant(27), end=_instant(27, 10))
        journal_repo.find_by_id.side_effect = lambda journal_id: (
            was if journal_id == 1 else now
        )

        await service.invalidate_for_event(
            "TaskDueJournalRetargeted",
            {
                "task_id": 5,
                "user_id": USER_ID,
                "changed_fields": {"due_journal_id": [1, 2]},
            },
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 20), datetime.date(2026, 4, 20)),
            (USER_ID, TODAY, TODAY),
        }

    @pytest.mark.asyncio
    async def test_a_merge_that_moved_the_due_anchor_marks_what_it_can(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """The absorbed journal is **deleted by the merge**, so it has no days.

        ``TaskJournalLinksRepointed`` carries ``(absorbed, survivor)``, and the
        absorbed row is gone by the time this runs — its own ``JournalDeleted``
        carried its days, which is what covers the day it was on. The survivor
        resolves, and that is the half this event can answer.
        """
        journal_repo.find_by_id.side_effect = lambda journal_id: (
            None if journal_id == 1 else _journal()
        )

        await service.invalidate_for_event(
            "TaskJournalLinksRepointed",
            {
                "task_id": 5,
                "user_id": USER_ID,
                "source_journal_id": 1,
                "target_journal_id": 2,
                "changed_fields": {"due_journal_id": [1, 2]},
            },
        )

        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}

    @pytest.mark.asyncio
    async def test_a_merge_that_left_the_due_anchor_alone_reads_the_task(
        self,
        service: DailySummaryInvalidationService,
        task_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """Only some merges move the anchor, so the pair may be absent entirely."""
        await service.invalidate_for_event(
            "TaskJournalLinksRepointed",
            {
                "task_id": 5,
                "user_id": USER_ID,
                "source_journal_id": 1,
                "target_journal_id": 2,
                "changed_fields": {"journal_1": [1, None]},
            },
        )

        task_repo.find_by_id.assert_awaited_once_with(5, USER_ID)
        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}


class TestADeletedTask:
    """The one event whose day cannot be resolved at all."""

    @pytest.mark.asyncio
    async def test_today_is_marked_without_reading_anything(
        self,
        service: DailySummaryInvalidationService,
        task_repo: AsyncMock,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """``TaskDeleted`` is deliberately minimal and the row is gone.

        Today is marked because a deleted task still named in today's prose is
        the visible harm; a past day that named it keeps doing so, and that is
        recorded as a limitation rather than papered over.
        """
        await service.invalidate_for_event(
            "TaskDeleted", {"task_id": 5, "user_id": USER_ID}
        )

        task_repo.find_by_id.assert_not_awaited()
        journal_repo.find_by_id.assert_not_awaited()
        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}


class TestAnImportantDateChange:
    """The current day only — and whose current day is its own question.

    ``contacts`` carries no owner column, so an important-date event names no
    user. Invalidation only ever touches rows that exist, so the set that can be
    affected *is* the users who already have a summary row, which is where the
    users come from.
    """

    @pytest.mark.asyncio
    async def test_a_date_falling_in_the_week_marks_today(
        self, service: DailySummaryInvalidationService, summary_repo: AsyncMock
    ) -> None:
        await service.invalidate_for_event(
            "ImportantDateAdded", {"contact_id": 101, "date_id": 1}
        )

        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}

    @pytest.mark.asyncio
    async def test_a_date_outside_the_week_marks_nothing(
        self,
        service: DailySummaryInvalidationService,
        contact_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """Most contact edits re-save every date, so this is the common case.

        ``update_contact`` deletes a contact's dates and re-adds them, which
        republishes one of these per surviving date — so without the window test
        every contact edit would cost an AI call for a birthday six months away.
        """
        contact_repo.get_important_dates.return_value = [
            stored_date(1, month=11, day=3)
        ]

        await service.invalidate_for_event(
            "ImportantDateAdded", {"contact_id": 101, "date_id": 1}
        )

        summary_repo.invalidate_for_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_deleted_date_marks_today_without_a_window_test(
        self,
        service: DailySummaryInvalidationService,
        contact_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """There is no row left to test, so the safe answer is the only one."""
        await service.invalidate_for_event(
            "ImportantDateDeleted",
            {"contact_id": 101, "date_id": 1, "date_type": "birthday"},
        )

        contact_repo.get_important_dates.assert_not_awaited()
        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}

    @pytest.mark.asyncio
    async def test_a_contact_update_that_changed_the_date_count_marks_today(
        self, service: DailySummaryInvalidationService, summary_repo: AsyncMock
    ) -> None:
        """The app's *delete* path, which publishes no deletion event.

        ``update_contact`` replaces a contact's dates wholesale: the removed one
        leaves no event of its own, and the survivors' ``ImportantDateAdded``
        events say nothing about it. This count pair is the only announcement
        that a date went away.
        """
        await service.invalidate_for_event(
            "ContactUpdated",
            {
                "contact_id": 101,
                "changed_fields": {"important_dates": ["count:2", "count:1"]},
            },
        )

        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}

    @pytest.mark.asyncio
    async def test_a_contact_update_that_touched_no_dates_marks_nothing(
        self, service: DailySummaryInvalidationService, summary_repo: AsyncMock
    ) -> None:
        """A renamed contact is a limitation this phase records, not a target."""
        await service.invalidate_for_event(
            "ContactUpdated",
            {
                "contact_id": 101,
                "changed_fields": {"first_name": ["Ada", "Augusta"]},
            },
        )

        summary_repo.invalidate_for_range.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_date_row_that_is_gone_marks_today(
        self,
        service: DailySummaryInvalidationService,
        contact_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """Deleted between the write and this consumer running."""
        contact_repo.get_important_dates.return_value = []

        await service.invalidate_for_event(
            "ImportantDateAdded", {"contact_id": 101, "date_id": 1}
        )

        assert _invalidated(summary_repo) == {(USER_ID, TODAY, TODAY)}

    @pytest.mark.asyncio
    async def test_each_user_gets_their_own_today(
        self,
        service: DailySummaryInvalidationService,
        date_resolver: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        """Two users, two zones, two days — and the same date row.

        A single "today" for the whole system would mark the wrong row for
        whichever of them is not in UTC.
        """
        summary_repo.user_ids_with_summaries.return_value = [USER_ID, "user-sydney"]
        date_resolver.timezone_for.side_effect = lambda user_id: (
            SYDNEY if user_id == "user-sydney" else UTC_ZONE
        )

        await service.invalidate_for_event(
            "ImportantDateAdded", {"contact_id": 101, "date_id": 1}
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, TODAY, TODAY),
            ("user-sydney", SYDNEY_TODAY, SYDNEY_TODAY),
        }

    @pytest.mark.asyncio
    async def test_a_system_with_no_summaries_yet_marks_nothing(
        self, service: DailySummaryInvalidationService, summary_repo: AsyncMock
    ) -> None:
        """Invalidation creates no rows, so there is nothing to do."""
        summary_repo.user_ids_with_summaries.return_value = []

        await service.invalidate_for_event(
            "ImportantDateAdded", {"contact_id": 101, "date_id": 1}
        )

        summary_repo.invalidate_for_range.assert_not_awaited()


class TestAJournalMergeMovingTheTargetsDates:
    """A merge moves the surviving journal's dates, and the day it left matters.

    ``JournalMergeService`` used to publish ``changed_fields["event_date_range"]``
    as a ``{start, end}`` mapping of the **new** range alone. Nothing could use
    that: the history projection skips any value that is not a two-element
    sequence, and this mapping has no old range in it at all, so the day the
    target moved off kept a summary that still counted it. The merge now
    publishes the same ``(old, new)`` pair every other date change does.
    """

    @pytest.mark.asyncio
    async def test_the_pair_a_merge_now_publishes_marks_both_days(
        self,
        service: DailySummaryInvalidationService,
        journal_repo: AsyncMock,
        summary_repo: AsyncMock,
    ) -> None:
        journal_repo.find_by_id.return_value = _journal(
            start=_instant(27, 9), end=_instant(27, 10)
        )

        await service.invalidate_for_event(
            "JournalUpdated",
            {
                "journal_id": JOURNAL_ID,
                "changed_fields": {
                    "event_date_range": [
                        _range_string(_instant(20, 9), _instant(20, 10)),
                        _range_string(_instant(27, 9), _instant(27, 10)),
                    ],
                    "merged_from": [7, 42],
                },
            },
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 20), datetime.date(2026, 4, 20)),
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27)),
        }

    @pytest.mark.asyncio
    async def test_the_mapping_it_used_to_publish_marks_only_the_current_day(
        self,
        service: DailySummaryInvalidationService,
        summary_repo: AsyncMock,
    ) -> None:
        """Pinned so the old shape cannot come back unnoticed.

        A mapping carries no old range, so there is nothing to recover from it —
        which is why the fix had to be at the publisher rather than here.
        """
        await service.invalidate_for_event(
            "JournalUpdated",
            {
                "journal_id": JOURNAL_ID,
                "changed_fields": {
                    "event_date_range": {
                        "start": _instant(27, 9).isoformat(),
                        "end": _instant(27, 10).isoformat(),
                    }
                },
            },
        )

        assert _invalidated(summary_repo) == {
            (USER_ID, datetime.date(2026, 4, 27), datetime.date(2026, 4, 27))
        }
