"""Unit tests for the journal list's "tasks due" counts.

``TaskReadService.due_task_counts`` answers one question for a whole page of
journals: how many live commitments is each of them waiting on. The repository
settles the two facts SQL can — the task is not done, and this is the journal it
is due in — and this layer settles the third, which SQL deliberately does not
know about: whether such a commitment would already have **lapsed**.

For this surface the lapse rule collapses, and that is what most of these tests
are about. The due journal *is* the row journal, so "would a not-done task due
here be lapsed?" is a question about the journal itself — its date in the user's
configured timezone, and whether it is a cancelled event. It is put to Phase
12's ``derive_lapse_reason`` rather than re-derived, so this file asserts the
boundaries that rule owns are honoured through this path too.

The other subject here is **how many round trips a page costs**. The listing
this feeds is the busiest in the product, so the count query comes first and the
two follow-up reads are skipped entirely when it comes back empty — which is
what most journal pages will do.

The file keeps its own doubles, as ``test_task_read_service.py`` does: those
exist for a service that assembles whole tasks, and nothing here assembles one.

**The timezone cases, worked out rather than asserted by feel.** Each is an
instant where the user's local day and UTC's have already diverged, and each is
paired with its UTC control — either alone would prove only that *something*
lapsed, never that the configured zone was the one consulted.

- *Sydney (UTC+10).* A journal at 13:00Z on 9 Aug is 23:00 on the 9th there;
  ``now`` at 14:30Z the same day is already 00:30 on the **10th**. Sydney has
  turned the page and the journal is behind it; UTC is still on the 9th.
- *New York (UTC-4 in August).* A journal at 23:00Z on 9 Aug is 19:00 on the 9th
  there; ``now`` at 02:00Z on the 10th is 22:00 on that **same** 9th. New York
  is still inside the journal's day; UTC has left it.
"""

import datetime
from unittest.mock import AsyncMock

import pytest
from core_shared.models.journals import EventDateRange, Journal

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_read_service import TaskReadService
from tests.unit.tasks.task_doubles import USER_ID

BUSY_JOURNAL_ID = 101
QUIET_JOURNAL_ID = 102

SYDNEY = "Australia/Sydney"
NEW_YORK = "America/New_York"

# 23:00 on 9 August in Sydney; 19:00 on 9 August in New York.
JOURNAL_AT_SYDNEY_LATE_EVENING = datetime.datetime(
    2026, 8, 9, 13, 0, tzinfo=datetime.UTC
)
# 00:30 on 10 August in Sydney, while UTC is still on the 9th.
NOW_PAST_SYDNEY_MIDNIGHT = datetime.datetime(2026, 8, 9, 14, 30, tzinfo=datetime.UTC)

# 19:00 on 9 August in New York, and 09:00 on the 10th in Sydney.
JOURNAL_AT_NEW_YORK_EVENING = datetime.datetime(2026, 8, 9, 23, 0, tzinfo=datetime.UTC)
# 22:00 on 9 August in New York, while UTC has already reached the 10th.
NOW_BEFORE_NEW_YORK_MIDNIGHT = datetime.datetime(2026, 8, 10, 2, 0, tzinfo=datetime.UTC)

# A fixed instant and three journals placed around it, so the date boundary is
# asserted against something that cannot move between runs.
NOON = datetime.datetime(2026, 8, 9, 12, 0, tzinfo=datetime.UTC)
YESTERDAY = NOON - datetime.timedelta(days=1)
TOMORROW = NOON + datetime.timedelta(days=1)


def make_journal(journal_id: int, start: datetime.datetime) -> Journal:
    """A persisted journal, as the list endpoint has already loaded it."""
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title=f"Journal {journal_id}",
        content="content",
        event_date_range=EventDateRange(start=start, end=start),
    )


@pytest.fixture
def counting_task_repo() -> AsyncMock:
    """A task repository reporting one commitment due in the busy journal."""
    repo = AsyncMock()
    repo.count_not_done_tasks_by_due_journal.return_value = {BUSY_JOURNAL_ID: 1}
    return repo


@pytest.fixture
def counting_calendar_info_repo() -> AsyncMock:
    """A calendar-info repository reporting nothing cancelled."""
    repo = AsyncMock()
    repo.find_cancelled_journal_ids.return_value = set()
    return repo


@pytest.fixture
def counting_settings_repo() -> AsyncMock:
    """A settings repository with no configured timezone — the UTC fallback."""
    repo = AsyncMock()
    repo.get_timezone.return_value = None
    return repo


@pytest.fixture
def counting_service(
    counting_task_repo: AsyncMock,
    counting_calendar_info_repo: AsyncMock,
    counting_settings_repo: AsyncMock,
) -> TaskReadService:
    """The service under test, over mocked ports.

    The journal and contact repositories are present because the constructor
    requires them and are never touched: this read is handed its journals and
    reads no contact.
    """
    return TaskReadService(
        task_repo=counting_task_repo,
        journal_repo=AsyncMock(),
        contact_repo=AsyncMock(),
        calendar_info_repo=counting_calendar_info_repo,
        date_resolver=JournalDateResolver(counting_settings_repo),
    )


@pytest.mark.unit
class TestTheCountItself:
    """What the repository reports reaches the caller, per journal."""

    async def test_each_journal_carries_its_own_count(
        self, counting_service: TaskReadService, counting_task_repo: AsyncMock
    ) -> None:
        """Two journals, two different counts — not the page's total."""
        counting_task_repo.count_not_done_tasks_by_due_journal.return_value = {
            BUSY_JOURNAL_ID: 3,
            QUIET_JOURNAL_ID: 1,
        }

        counts = await counting_service.due_task_counts(
            USER_ID,
            [
                make_journal(BUSY_JOURNAL_ID, TOMORROW),
                make_journal(QUIET_JOURNAL_ID, TOMORROW),
            ],
            now=NOON,
        )

        assert counts == {BUSY_JOURNAL_ID: 3, QUIET_JOURNAL_ID: 1}

    async def test_a_journal_with_nothing_due_is_absent(
        self, counting_service: TaskReadService
    ) -> None:
        """Absent rather than present with a zero, as the repository is.

        The caller reads through ``.get(journal_id, 0)``, so a page holding
        nothing produces no entries rather than one per row.
        """
        counts = await counting_service.due_task_counts(
            USER_ID,
            [
                make_journal(BUSY_JOURNAL_ID, TOMORROW),
                make_journal(QUIET_JOURNAL_ID, TOMORROW),
            ],
            now=NOON,
        )

        assert counts == {BUSY_JOURNAL_ID: 1}

    async def test_the_repository_is_asked_about_the_whole_page(
        self, counting_service: TaskReadService, counting_task_repo: AsyncMock
    ) -> None:
        """Every journal on the page goes into the one query, scoped to the user."""
        await counting_service.due_task_counts(
            USER_ID,
            [
                make_journal(BUSY_JOURNAL_ID, TOMORROW),
                make_journal(QUIET_JOURNAL_ID, TOMORROW),
            ],
            now=NOON,
        )

        counting_task_repo.count_not_done_tasks_by_due_journal.assert_awaited_once_with(
            [BUSY_JOURNAL_ID, QUIET_JOURNAL_ID], USER_ID
        )


@pytest.mark.unit
class TestLapsedCommitmentsDoNotCount:
    """A journal that can no longer be acted on is not waiting on anything.

    The three branches of ``derive_lapse_reason`` that a journal can reach on
    its own — before today, on today, and cancelled — each asserted through this
    path rather than only at the rule.
    """

    async def test_a_past_dated_journal_lights_nothing(
        self, counting_service: TaskReadService
    ) -> None:
        """Its not-done tasks have lapsed, and lapsed tasks leave quietly."""
        counts = await counting_service.due_task_counts(
            USER_ID, [make_journal(BUSY_JOURNAL_ID, YESTERDAY)], now=NOON
        )

        assert counts == {}

    async def test_a_journal_dated_today_still_counts(
        self, counting_service: TaskReadService
    ) -> None:
        """Today is neither future nor passed.

        Mirrors ``derive_lapse_reason``'s strictly-before boundary. An inclusive
        one would darken the indicator on a journal the user is still going to
        open later the same day.
        """
        counts = await counting_service.due_task_counts(
            USER_ID, [make_journal(BUSY_JOURNAL_ID, NOON)], now=NOON
        )

        assert counts == {BUSY_JOURNAL_ID: 1}

    async def test_a_future_journal_counts(
        self, counting_service: TaskReadService
    ) -> None:
        """The ordinary case, stated so the boundary tests have a control."""
        counts = await counting_service.due_task_counts(
            USER_ID, [make_journal(BUSY_JOURNAL_ID, TOMORROW)], now=NOON
        )

        assert counts == {BUSY_JOURNAL_ID: 1}

    async def test_a_cancelled_journal_lights_nothing_even_when_future_dated(
        self,
        counting_service: TaskReadService,
        counting_calendar_info_repo: AsyncMock,
    ) -> None:
        """Cancellation carries no date condition.

        The moment the commitment was pinned to is not going to happen, whenever
        it was scheduled for — and the future date is what shows the *date*
        cause demonstrably cannot be the one that fired.
        """
        counting_calendar_info_repo.find_cancelled_journal_ids.return_value = {
            BUSY_JOURNAL_ID
        }

        counts = await counting_service.due_task_counts(
            USER_ID, [make_journal(BUSY_JOURNAL_ID, TOMORROW)], now=NOON
        )

        assert counts == {}


@pytest.mark.unit
class TestTheConfiguredTimezoneDecides:
    """Each zone paired with its UTC control, in both directions.

    Either direction alone would prove only that something lapsed. The pair is
    what proves the *configured* zone is the one consulted, and neither case can
    be satisfied by an implementation that quietly anchors on UTC.
    """

    async def test_sydney_has_turned_the_page_while_utc_has_not(
        self, counting_service: TaskReadService, counting_settings_repo: AsyncMock
    ) -> None:
        """Past local midnight in Sydney, the journal is behind the user."""
        counting_settings_repo.get_timezone.return_value = SYDNEY

        counts = await counting_service.due_task_counts(
            USER_ID,
            [make_journal(BUSY_JOURNAL_ID, JOURNAL_AT_SYDNEY_LATE_EVENING)],
            now=NOW_PAST_SYDNEY_MIDNIGHT,
        )

        assert counts == {}

    async def test_the_same_instant_still_counts_in_utc(
        self, counting_service: TaskReadService
    ) -> None:
        """The control for the case above: UTC is still on the journal's day."""
        counts = await counting_service.due_task_counts(
            USER_ID,
            [make_journal(BUSY_JOURNAL_ID, JOURNAL_AT_SYDNEY_LATE_EVENING)],
            now=NOW_PAST_SYDNEY_MIDNIGHT,
        )

        assert counts == {BUSY_JOURNAL_ID: 1}

    async def test_new_york_is_still_inside_the_day_utc_has_left(
        self, counting_service: TaskReadService, counting_settings_repo: AsyncMock
    ) -> None:
        """The opposite direction: the configured zone keeps the indicator lit."""
        counting_settings_repo.get_timezone.return_value = NEW_YORK

        counts = await counting_service.due_task_counts(
            USER_ID,
            [make_journal(BUSY_JOURNAL_ID, JOURNAL_AT_NEW_YORK_EVENING)],
            now=NOW_BEFORE_NEW_YORK_MIDNIGHT,
        )

        assert counts == {BUSY_JOURNAL_ID: 1}

    async def test_the_same_instant_has_already_lapsed_in_utc(
        self, counting_service: TaskReadService
    ) -> None:
        """The control for the case above: UTC has moved past the journal's day."""
        counts = await counting_service.due_task_counts(
            USER_ID,
            [make_journal(BUSY_JOURNAL_ID, JOURNAL_AT_NEW_YORK_EVENING)],
            now=NOW_BEFORE_NEW_YORK_MIDNIGHT,
        )

        assert counts == {}


@pytest.mark.unit
class TestWhatThePageCosts:
    """The listing is the busiest read in the product, so the reads are counted."""

    async def test_an_empty_page_reads_nothing_at_all(
        self,
        counting_service: TaskReadService,
        counting_task_repo: AsyncMock,
        counting_settings_repo: AsyncMock,
        counting_calendar_info_repo: AsyncMock,
    ) -> None:
        """A filtered listing that matched no journals asks no questions."""
        assert await counting_service.due_task_counts(USER_ID, [], now=NOON) == {}

        counting_task_repo.count_not_done_tasks_by_due_journal.assert_not_awaited()
        counting_settings_repo.get_timezone.assert_not_awaited()
        counting_calendar_info_repo.find_cancelled_journal_ids.assert_not_awaited()

    async def test_a_page_with_nothing_due_asks_no_follow_up_questions(
        self,
        counting_service: TaskReadService,
        counting_task_repo: AsyncMock,
        counting_settings_repo: AsyncMock,
        counting_calendar_info_repo: AsyncMock,
    ) -> None:
        """The common page costs exactly the one query the criterion asks for.

        Most journals hold no tasks, so the timezone read and the cancellation
        lookup are skipped rather than run to filter an empty mapping — there is
        nothing to judge, and this is the path nearly every listing takes.
        """
        counting_task_repo.count_not_done_tasks_by_due_journal.return_value = {}

        counts = await counting_service.due_task_counts(
            USER_ID, [make_journal(BUSY_JOURNAL_ID, TOMORROW)], now=NOON
        )

        assert counts == {}
        counting_task_repo.count_not_done_tasks_by_due_journal.assert_awaited_once()
        counting_settings_repo.get_timezone.assert_not_awaited()
        counting_calendar_info_repo.find_cancelled_journal_ids.assert_not_awaited()

    async def test_only_journals_with_something_due_are_checked_for_cancellation(
        self,
        counting_service: TaskReadService,
        counting_calendar_info_repo: AsyncMock,
    ) -> None:
        """The second read is narrowed by the first, not handed the whole page.

        Asking about every journal on the page would make the cancellation
        lookup as wide as the listing to answer a question about the handful of
        journals that could change the outcome.
        """
        await counting_service.due_task_counts(
            USER_ID,
            [
                make_journal(BUSY_JOURNAL_ID, TOMORROW),
                make_journal(QUIET_JOURNAL_ID, TOMORROW),
            ],
            now=NOON,
        )

        counting_calendar_info_repo.find_cancelled_journal_ids.assert_awaited_once_with(
            [BUSY_JOURNAL_ID]
        )

    async def test_the_timezone_is_read_once_for_the_whole_page(
        self, counting_service: TaskReadService, counting_settings_repo: AsyncMock
    ) -> None:
        """Not once per journal — the reason the date rule takes resolved dates."""
        counting_task_repo_counts = {BUSY_JOURNAL_ID: 1, QUIET_JOURNAL_ID: 2}
        counting_service.task_repo.count_not_done_tasks_by_due_journal.return_value = (  # type: ignore[attr-defined]
            counting_task_repo_counts
        )

        await counting_service.due_task_counts(
            USER_ID,
            [
                make_journal(BUSY_JOURNAL_ID, TOMORROW),
                make_journal(QUIET_JOURNAL_ID, TOMORROW),
            ],
            now=NOON,
        )

        counting_settings_repo.get_timezone.assert_awaited_once_with(USER_ID)
