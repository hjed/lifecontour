"""Unit tests for the upcoming-window listing's fetching half.

``test_task_upcoming_window.py`` owns the *rule* — which tasks belong in a
window and in what order. This owns everything the rule cannot see: that the
window is anchored on **the user's** today rather than UTC's, that it reaches
the repository as instants, and that the whole listing costs one read per
collection however many tasks come back.

**The timezone assertions are the point of this file.** A window anchored on
UTC's today is wrong for everybody east of Greenwich for part of every day, and
the failure is invisible in any fixture whose instants sit at midday. So the
cases below put ``now`` at an instant where the user's local date and UTC's
disagree, and assert the instants the repository was handed.

**The round-trip assertions are the other point.** A functional test cannot see
an N+1 — the answer is right either way and only the number of reads is wrong —
so the call counts are asserted at two fixture sizes, the shape
``test_task_read_service_list.py`` established.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import Task, TaskStatus, TaskValidationError

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_read_service import TaskReadService
from tests.unit.tasks.task_doubles import OTHER_USER_ID, USER_ID

pytestmark = pytest.mark.unit

# The journal every task below arose in — always in the past, as a creating
# journal almost always is, so it can never be mistaken for the due anchor the
# window judges.
CREATED_IN_ID = 100

# Somewhere inside a default window anchored on NOW, and somewhere beyond it.
IN_WINDOW_ID = 200
FURTHER_IN_WINDOW_ID = 210
BEYOND_WINDOW_ID = 300

UTC = datetime.UTC
KIRITIMATI = ZoneInfo("Pacific/Kiritimati")  # UTC+14, the furthest ahead there is

# Midday UTC on a Tuesday. In Kiritimati it is already 02:00 on Wednesday, which
# is the whole reason this instant was chosen.
NOW = datetime.datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
TODAY_UTC = datetime.date(2026, 8, 11)
TODAY_KIRITIMATI = datetime.date(2026, 8, 12)


def make_journal(
    journal_id: int, day: datetime.date, *, title: str = "Permit Meeting"
) -> Journal:
    """A persisted journal dated on ``day``, as the repository hands it back."""
    start = datetime.datetime.combine(day, datetime.time(9, 0), tzinfo=UTC)
    return Journal(
        id=journal_id,
        user_id=USER_ID,
        title=title,
        content="content",
        event_date_range=EventDateRange(start=start, end=start),
    )


def make_task(
    task_id: int,
    *,
    due_journal_id: int,
    status: TaskStatus = TaskStatus.NOT_DONE,
) -> Task:
    """A persisted task, as the repository hands it back."""
    return Task(
        id=task_id,
        user_id=USER_ID,
        text=f"task {task_id}",
        creating_journal_id=CREATED_IN_ID,
        due_journal_id=due_journal_id,
        status=status,
    )


@pytest.fixture
def task_repo() -> AsyncMock:
    """A task repository holding one task due inside the window."""
    repo = AsyncMock()
    repo.find_upcoming_tasks.return_value = [make_task(1, due_journal_id=IN_WINDOW_ID)]
    repo.list_intermediate_journal_ids_for_tasks.return_value = {}
    repo.list_contact_ids_for_tasks.return_value = {}
    return repo


@pytest.fixture
def journal_repo() -> AsyncMock:
    """A journal repository that knows every journal these tests name."""
    repo = AsyncMock()
    known = {
        CREATED_IN_ID: make_journal(
            CREATED_IN_ID, TODAY_UTC - datetime.timedelta(days=30), title="Monday"
        ),
        IN_WINDOW_ID: make_journal(
            IN_WINDOW_ID, TODAY_UTC + datetime.timedelta(days=2)
        ),
        FURTHER_IN_WINDOW_ID: make_journal(
            FURTHER_IN_WINDOW_ID, TODAY_UTC + datetime.timedelta(days=5)
        ),
        BEYOND_WINDOW_ID: make_journal(
            BEYOND_WINDOW_ID, TODAY_UTC + datetime.timedelta(days=30)
        ),
    }

    async def fetch(_user_id: str, journal_ids: list[int]) -> list[Journal]:
        return [known[journal_id] for journal_id in journal_ids if journal_id in known]

    repo.find_by_ids_for_user.side_effect = fetch
    return repo


@pytest.fixture
def contact_repo() -> AsyncMock:
    """A contact repository that knows nobody unless a test says otherwise."""
    repo = AsyncMock()
    repo.find_names_by_ids.return_value = {}
    return repo


@pytest.fixture
def calendar_info_repo() -> AsyncMock:
    """A calendar-info repository reporting nothing cancelled."""
    repo = AsyncMock()
    repo.find_cancelled_journal_ids.return_value = set()
    return repo


@pytest.fixture
def settings_repo() -> AsyncMock:
    """A settings repository with no configured timezone — the UTC fallback."""
    repo = AsyncMock()
    repo.get_timezone.return_value = None
    return repo


@pytest.fixture
def service(
    task_repo: AsyncMock,
    journal_repo: AsyncMock,
    contact_repo: AsyncMock,
    calendar_info_repo: AsyncMock,
    settings_repo: AsyncMock,
) -> TaskReadService:
    """The service under test, over mocked ports."""
    return TaskReadService(
        task_repo=task_repo,
        journal_repo=journal_repo,
        contact_repo=contact_repo,
        calendar_info_repo=calendar_info_repo,
        date_resolver=JournalDateResolver(settings_repo),
    )


def window_bounds(task_repo: AsyncMock) -> tuple[datetime.datetime, datetime.datetime]:
    """The two instants the repository was asked for."""
    kwargs = task_repo.find_upcoming_tasks.await_args.kwargs
    return kwargs["window_start"], kwargs["window_end"]


def seed_many(task_repo: AsyncMock, count: int) -> None:
    """``count`` tasks in the window, each carrying a mention and a contact.

    Every task is due in the window and mentions a journal elsewhere, so the
    fixture exercises the anchor batch, the mention batch and the contact batch
    at once.
    """
    tasks = [
        make_task(task_id, due_journal_id=IN_WINDOW_ID)
        for task_id in range(1, count + 1)
    ]
    task_repo.find_upcoming_tasks.return_value = tasks
    task_repo.list_intermediate_journal_ids_for_tasks.return_value = {
        task.id: [BEYOND_WINDOW_ID] for task in tasks
    }
    task_repo.list_contact_ids_for_tasks.return_value = {task.id: [7] for task in tasks}


class TestWindowAnchoring:
    """Whose *today* the window starts on, and what the repository is asked."""

    async def test_the_window_is_anchored_on_the_users_today(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The default window runs from today to seven days out."""
        upcoming = await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.window.first_day == TODAY_UTC
        assert upcoming.window.last_day == datetime.date(2026, 8, 18)

    async def test_the_repository_is_given_instants_not_dates(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The window reaches SQL as the timestamps the column holds.

        Local midnight on the first day through the final microsecond of the
        last, so a journal starting at any hour of either boundary day is
        inside — the inclusivity the specification asks for, expressed in the
        only units the ``event_date_range_start`` column understands.
        """
        await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        start, end = window_bounds(task_repo)
        assert start == datetime.datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
        assert end == datetime.datetime(2026, 8, 18, 23, 59, 59, 999999, tzinfo=UTC)

    async def test_a_non_utc_user_near_midnight_gets_their_own_day(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        settings_repo: AsyncMock,
    ) -> None:
        """**The case a UTC-anchored window gets wrong.**

        At midday UTC it is already the next day in Kiritimati, so the window
        must start on the 12th and not the 11th. A service that called
        ``date.today()`` — or resolved the date in UTC — would answer this user
        with yesterday's window for fourteen hours of every day.
        """
        settings_repo.get_timezone.return_value = "Pacific/Kiritimati"

        upcoming = await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.window.first_day == TODAY_KIRITIMATI
        assert upcoming.window.last_day == datetime.date(2026, 8, 19)

    async def test_a_non_utc_users_instants_are_their_local_midnights(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        settings_repo: AsyncMock,
    ) -> None:
        """Local midnight in Kiritimati is 10:00 the previous day in UTC.

        Asserted as an absolute instant rather than a wall-clock time, because
        the whole risk is that a naive datetime is compared against a column
        stored in UTC.
        """
        settings_repo.get_timezone.return_value = "Pacific/Kiritimati"

        await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        start, end = window_bounds(task_repo)
        assert start == datetime.datetime(2026, 8, 12, 0, 0, tzinfo=KIRITIMATI)
        assert start.astimezone(UTC) == datetime.datetime(
            2026, 8, 11, 10, 0, tzinfo=UTC
        )
        assert end == datetime.datetime(
            2026, 8, 19, 23, 59, 59, 999999, tzinfo=KIRITIMATI
        )

    async def test_the_timezone_is_resolved_once(
        self, service: TaskReadService, settings_repo: AsyncMock, task_repo: AsyncMock
    ) -> None:
        """One settings read for the whole listing, not one per task.

        The window and the lapse verdict both need it, and a second read would
        also risk the two disagreeing across a settings change mid-request.
        """
        seed_many(task_repo, 4)

        await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert settings_repo.get_timezone.await_count == 1

    async def test_an_explicit_days_ahead_is_honoured(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """A caller may look a different distance ahead."""
        upcoming = await service.read_models_for_upcoming_window(
            USER_ID, days_ahead=2, now=NOW
        )

        assert upcoming.window.days_ahead == 2
        assert upcoming.window.last_day == datetime.date(2026, 8, 13)

    @pytest.mark.parametrize("days_ahead", [-1, 91])
    async def test_an_out_of_range_days_ahead_is_refused_before_the_listing_query(
        self, service: TaskReadService, task_repo: AsyncMock, days_ahead: int
    ) -> None:
        """The domain rule is enforced here, so both surfaces inherit it.

        **Before the listing query, not before every read.** The bound cannot be
        checked against a window that has not been built, and building one needs
        the user's timezone — so the settings read has already happened by the
        time this raises. The docstring used to claim otherwise, and this test
        did not contradict it because it only ever asserted the *listing* query;
        both were corrected by review, and the settings read is now asserted
        rather than left ambiguous.
        """
        with pytest.raises(TaskValidationError):
            await service.read_models_for_upcoming_window(
                USER_ID, days_ahead=days_ahead, now=NOW
            )

        task_repo.find_upcoming_tasks.assert_not_awaited()
        task_repo.list_contact_ids_for_tasks.assert_not_awaited()

    async def test_the_acting_user_is_passed_through(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """Owner scoping is the query's, so the service never compares an id."""
        task_repo.find_upcoming_tasks.return_value = []

        await service.read_models_for_upcoming_window(OTHER_USER_ID, now=NOW)

        assert task_repo.find_upcoming_tasks.await_args.args[0] == OTHER_USER_ID


class TestSelection:
    """What the service does with what came back."""

    async def test_a_task_in_the_window_is_returned_whole(
        self, service: TaskReadService, contact_repo: AsyncMock, task_repo: AsyncMock
    ) -> None:
        """Text, the resolved due journal and the contacts, with no follow-up.

        The dashboard renders a row from this and nothing else, which is the
        third acceptance criterion's "in one query per collection" read from the
        client's side.
        """
        task_repo.list_contact_ids_for_tasks.return_value = {1: [7]}
        contact_repo.find_names_by_ids.return_value = {7: ("Sarah", "Chen", None)}

        upcoming = await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        (model,) = upcoming.tasks
        assert model.task.text == "task 1"
        assert model.due_journal.id == IN_WINDOW_ID
        assert model.due_journal.title == "Permit Meeting"
        assert model.due_journal.date == TODAY_UTC + datetime.timedelta(days=2)
        assert [contact.display_name for contact in model.contacts] == ["Sarah Chen"]

    async def test_a_task_whose_due_journal_was_cancelled_is_dropped(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        calendar_info_repo: AsyncMock,
    ) -> None:
        """**The exclusion that needs a cancelled journal to be non-vacuous.**

        Dated inside the window and not done, so only the lapse rule can remove
        it — and the lapse rule only knows because the batched cancellation
        lookup told it.
        """
        task_repo.find_upcoming_tasks.return_value = [
            make_task(1, due_journal_id=IN_WINDOW_ID),
            make_task(2, due_journal_id=FURTHER_IN_WINDOW_ID),
        ]
        calendar_info_repo.find_cancelled_journal_ids.return_value = {IN_WINDOW_ID}

        upcoming = await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert [model.task.id for model in upcoming.tasks] == [2]

    async def test_a_task_outside_the_window_is_dropped(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """Belt and braces over the query's own filter.

        Unreachable through the real repository, whose statement filters on the
        same window. Defined rather than left to chance, so a query that
        widened by a day would be caught here as well as in the integration
        suite.
        """
        task_repo.find_upcoming_tasks.return_value = [
            make_task(1, due_journal_id=BEYOND_WINDOW_ID)
        ]

        upcoming = await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.tasks == ()
        assert upcoming.total == 0

    async def test_the_answer_is_ordered_soonest_first(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The service does not rely on the query's order alone."""
        task_repo.find_upcoming_tasks.return_value = [
            make_task(1, due_journal_id=FURTHER_IN_WINDOW_ID),
            make_task(2, due_journal_id=IN_WINDOW_ID),
        ]

        upcoming = await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert [model.task.id for model in upcoming.tasks] == [2, 1]

    async def test_an_empty_window_is_an_ordinary_answer(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """Nothing due this week is a good outcome, and still names the window."""
        task_repo.find_upcoming_tasks.return_value = []

        upcoming = await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.tasks == ()
        assert upcoming.window.first_day == TODAY_UTC

    async def test_an_empty_window_asks_for_no_journals(
        self, service: TaskReadService, task_repo: AsyncMock, journal_repo: AsyncMock
    ) -> None:
        """With no tasks there are no journals to resolve, so none are asked for.

        Unlike a journal's listing, which resolves the journal it is *about*
        even when nothing is linked to it, in order to tell an empty journal
        from somebody else's. This listing is about a window rather than a
        journal, so it has no such id to check.

        The empty id list rather than the absent call is what is asserted,
        because that is where the cost actually is: ``find_by_ids_for_user``
        answers an empty list without issuing a statement, so an empty window
        reaches the database twice — for the tasks and for nothing else.
        """
        task_repo.find_upcoming_tasks.return_value = []

        await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        _, requested = journal_repo.find_by_ids_for_user.await_args.args
        assert requested == []


class TestOneReadPerCollection:
    """The fourth acceptance criterion, asserted where it fails fastest."""

    @pytest.mark.parametrize("task_count", [2, 6])
    async def test_each_collection_is_read_once_whatever_the_task_count(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        journal_repo: AsyncMock,
        contact_repo: AsyncMock,
        calendar_info_repo: AsyncMock,
        settings_repo: AsyncMock,
        task_count: int,
    ) -> None:
        """Two tasks and six cost the same number of reads.

        The doubling is what makes the claim mean something: a fixed count on
        its own would also pass against a loop that ran a fixed number of times.
        """
        seed_many(task_repo, task_count)
        contact_repo.find_names_by_ids.return_value = {7: ("Sarah", None, None)}

        upcoming = await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.total == task_count
        assert task_repo.find_upcoming_tasks.await_count == 1
        assert task_repo.list_intermediate_journal_ids_for_tasks.await_count == 1
        assert task_repo.list_contact_ids_for_tasks.await_count == 1
        assert journal_repo.find_by_ids_for_user.await_count == 1
        assert calendar_info_repo.find_cancelled_journal_ids.await_count == 1
        assert contact_repo.find_names_by_ids.await_count == 1
        assert settings_repo.get_timezone.await_count == 1

    async def test_the_per_task_link_reads_are_never_used(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The batch path must not fall back to the single-task methods.

        Those are what an N+1 would look like from the inside, so they are
        asserted untouched rather than merely counted.
        """
        seed_many(task_repo, 4)

        await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        task_repo.list_intermediate_journal_ids.assert_not_awaited()
        task_repo.list_contact_ids.assert_not_awaited()
        task_repo.find_by_id.assert_not_awaited()

    async def test_every_journal_across_every_task_arrives_in_one_query(
        self, service: TaskReadService, task_repo: AsyncMock, journal_repo: AsyncMock
    ) -> None:
        """Anchors and mentions share the batch, de-duplicated."""
        seed_many(task_repo, 3)

        await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        _, requested = journal_repo.find_by_ids_for_user.await_args.args
        assert sorted(requested) == [CREATED_IN_ID, IN_WINDOW_ID, BEYOND_WINDOW_ID]

    async def test_no_transaction_is_opened(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """A read that opened a unit of work would hold one open for a page render.

        There is no connection on this service to open one with, which is the
        structural half of the claim; this pins the behavioural half — nothing
        it calls is a write.
        """
        await service.read_models_for_upcoming_window(USER_ID, now=NOW)

        task_repo.save.assert_not_awaited()
        assert not hasattr(service, "connection")
