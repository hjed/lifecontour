"""Unit tests for the past-day listing: what was due here, and what became of it.

``read_models_due_in_journals`` is the daily summary's read of a day that has
already happened. Its siblings answer *what is still live*; this answers *how it
resolved*, and the difference is a filter that must **not** be there — so the
first thing below is that a done and a cancelled task both come back, which is
what separates a correct implementation from a copy of the upcoming window's.

Three further things this file owns, none of which a functional assertion can
see:

- **Whose day it is.** ``today`` is resolved in the acting user's zone, and the
  lapse verdict on every row hangs off it. A fixture at midday cannot tell that
  apart from UTC's today, so the cases below sit at an instant where the two
  disagree.
- **That an already-resolved zone is used rather than re-read.** The caller —
  the summary's input assembler — has read ``user_settings`` to decide which day
  it is summarising, and a second read is a second statement that a concurrent
  settings change can land between.
- **One read per collection.** A day's journals hold any number of tasks, and a
  functional test passes either way; only the call counts show an N+1.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from core_shared.models.journals import EventDateRange, Journal
from core_shared.models.tasks import LapseReason, Task, TaskStatus

from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.tasks.services.task_read_service import TaskReadService
from tests.unit.tasks.task_doubles import OTHER_USER_ID, USER_ID

pytestmark = pytest.mark.unit

# The journal every task below arose in — well in the past, as a creating
# journal almost always is, so it can never be mistaken for the due anchor.
CREATED_IN_ID = 100

# The day being summarised holds two journals; a third sits outside it, so a
# read that ignored its argument would be visible.
MORNING_ID = 200
AFTERNOON_ID = 210
ANOTHER_DAY_ID = 300

# A journal a task merely mentions, which must never make it part of the day.
MENTIONED_ID = 400

UTC = datetime.UTC
KIRITIMATI = ZoneInfo("Pacific/Kiritimati")  # UTC+14, the furthest ahead there is

# Midday UTC on a Tuesday. In Kiritimati it is already 02:00 on Wednesday, which
# is the whole reason this instant was chosen.
NOW = datetime.datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
TODAY_UTC = datetime.date(2026, 8, 11)
TODAY_KIRITIMATI = datetime.date(2026, 8, 12)

# The day the summary is about: yesterday, in UTC's reckoning.
SUMMARY_DAY = datetime.date(2026, 8, 10)


def make_journal(
    journal_id: int, day: datetime.date, *, title: str = "Site visit"
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
    due_journal_id: int = MORNING_ID,
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
    """A task repository holding one outstanding task due on the day."""
    repo = AsyncMock()
    repo.find_tasks_due_in_journals.return_value = [make_task(1)]
    repo.list_intermediate_journal_ids_for_tasks.return_value = {}
    repo.list_contact_ids_for_tasks.return_value = {}
    return repo


@pytest.fixture
def journal_repo() -> AsyncMock:
    """A journal repository that knows every journal these tests name."""
    repo = AsyncMock()
    known = {
        CREATED_IN_ID: make_journal(
            CREATED_IN_ID, SUMMARY_DAY - datetime.timedelta(days=30), title="Monday"
        ),
        MORNING_ID: make_journal(MORNING_ID, SUMMARY_DAY, title="Morning standup"),
        AFTERNOON_ID: make_journal(AFTERNOON_ID, SUMMARY_DAY, title="Site visit"),
        ANOTHER_DAY_ID: make_journal(
            ANOTHER_DAY_ID, SUMMARY_DAY + datetime.timedelta(days=3)
        ),
        MENTIONED_ID: make_journal(
            MENTIONED_ID, SUMMARY_DAY - datetime.timedelta(days=2)
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


def seed_many(task_repo: AsyncMock, count: int) -> None:
    """``count`` tasks due on the day, each carrying a mention and a contact.

    Every task is due in the day and mentions a journal elsewhere, so the
    fixture exercises the anchor batch, the mention batch and the contact batch
    at once.
    """
    tasks = [make_task(task_id) for task_id in range(1, count + 1)]
    task_repo.find_tasks_due_in_journals.return_value = tasks
    task_repo.list_intermediate_journal_ids_for_tasks.return_value = {
        task.id: [MENTIONED_ID] for task in tasks
    }
    task_repo.list_contact_ids_for_tasks.return_value = {task.id: [7] for task in tasks}


class TestEveryResolutionIsReported:
    """Nothing is filtered out — the finished tasks *are* the answer."""

    @pytest.mark.parametrize(
        "status",
        [TaskStatus.NOT_DONE, TaskStatus.DONE, TaskStatus.CANCELLED],
        ids=["not-done", "done", "cancelled"],
    )
    async def test_a_task_in_any_status_comes_back(
        self, service: TaskReadService, task_repo: AsyncMock, status: TaskStatus
    ) -> None:
        """The exclusion the upcoming window applies is absent here, by design.

        A summary of a past day says what became of each commitment, and two of
        the three answers are the statuses its siblings exist to drop.
        """
        task_repo.find_tasks_due_in_journals.return_value = [
            make_task(1, status=status)
        ]

        models = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID], now=NOW
        )

        assert [model.task.status for model in models] == [status]

    async def test_the_repository_is_asked_for_exactly_the_days_journals(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The day is a set of journal ids, handed straight through.

        Not a window: the caller resolved which journals the day holds, and a
        second definition of that here is the drift the reuse exists to avoid.
        """
        await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID, AFTERNOON_ID], now=NOW
        )

        task_repo.find_tasks_due_in_journals.assert_awaited_once_with(
            [MORNING_ID, AFTERNOON_ID], USER_ID
        )

    async def test_a_day_with_no_journals_reads_nothing_at_all(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The quiet day the always-eligible rule exists for costs no query.

        Asserted as ``assert_not_awaited`` rather than as an empty answer: a
        service that asked anyway and got nothing back would satisfy the second
        and fail the user's database.
        """
        models = await service.read_models_due_in_journals(USER_ID, [], now=NOW)

        assert models == []
        task_repo.find_tasks_due_in_journals.assert_not_awaited()

    async def test_a_task_carries_its_journals_and_its_contacts(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        contact_repo: AsyncMock,
    ) -> None:
        """The whole read model, because the prompt renders all of it.

        The contact is the half that makes a summary worth reading: its value is
        in connecting a commitment to a person, which it cannot do from a row it
        was handed without one.
        """
        task_repo.list_intermediate_journal_ids_for_tasks.return_value = {
            1: [MENTIONED_ID]
        }
        task_repo.list_contact_ids_for_tasks.return_value = {1: [7]}
        contact_repo.find_names_by_ids.return_value = {7: ("Sarah", "Chen", None)}

        (model,) = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID], now=NOW
        )

        assert model.due_journal.title == "Morning standup"
        assert model.due_journal.date == SUMMARY_DAY
        assert model.creating_journal.title == "Monday"
        assert [journal.id for journal in model.intermediate_journals] == [MENTIONED_ID]
        assert [contact.display_name for contact in model.contacts] == ["Sarah Chen"]

    async def test_the_repositorys_order_is_preserved(
        self, service: TaskReadService, task_repo: AsyncMock
    ) -> None:
        """The day's own sequence, decided by the query and not re-sorted here.

        The statement orders by the due journal's start then the task id, which
        is the order the prompt should read down. Re-sorting would be a second
        definition of it that could disagree.
        """
        task_repo.find_tasks_due_in_journals.return_value = [
            make_task(9, due_journal_id=MORNING_ID),
            make_task(2, due_journal_id=AFTERNOON_ID),
        ]

        models = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID, AFTERNOON_ID], now=NOW
        )

        assert [model.task.id for model in models] == [9, 2]


class TestTheLapseVerdictTravels:
    """*How* an unfinished commitment lapsed is part of the answer here."""

    async def test_an_unfinished_task_on_a_past_day_lapsed_because_the_day_passed(
        self, service: TaskReadService
    ) -> None:
        """The ordinary past-day verdict, and the one the summary reports most."""
        (model,) = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID], now=NOW
        )

        assert model.lapse_reason is LapseReason.DATE_PASSED

    async def test_a_cancelled_due_journal_is_reported_as_the_cause(
        self, service: TaskReadService, calendar_info_repo: AsyncMock
    ) -> None:
        """Cancellation outranks the passed date, as the pure rule decides.

        The two are different news — "the day went by" and "the meeting was
        called off" — so the reason is carried rather than a bare boolean.
        """
        calendar_info_repo.find_cancelled_journal_ids.return_value = {MORNING_ID}

        (model,) = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID], now=NOW
        )

        assert model.lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED

    @pytest.mark.parametrize(
        "status", [TaskStatus.DONE, TaskStatus.CANCELLED], ids=["done", "cancelled"]
    )
    async def test_a_finished_task_never_lapses(
        self, service: TaskReadService, task_repo: AsyncMock, status: TaskStatus
    ) -> None:
        """A commitment met or called off cannot then be let slide.

        Read from ``build_task_read_model`` rather than re-derived, so the
        summary and the journal cannot disagree about the same task.
        """
        task_repo.find_tasks_due_in_journals.return_value = [
            make_task(1, status=status)
        ]

        (model,) = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID], now=NOW
        )

        assert model.lapse_reason is None


class TestWhoseDayItIs:
    """The zone the verdict is judged in, and where it comes from."""

    async def test_today_is_resolved_in_the_users_zone(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        journal_repo: AsyncMock,
        settings_repo: AsyncMock,
    ) -> None:
        """A journal on the user's *today* has not passed, though UTC's has.

        At this instant Kiritimati is already on the 12th while UTC is on the
        11th, so a task due in a journal dated the 12th is outstanding for this
        user and would read as lapsed under a UTC-anchored today.
        """
        settings_repo.get_timezone.return_value = "Pacific/Kiritimati"
        journal_repo.find_by_ids_for_user.side_effect = None
        journal_repo.find_by_ids_for_user.return_value = [
            make_journal(CREATED_IN_ID, SUMMARY_DAY - datetime.timedelta(days=30)),
            make_journal(MORNING_ID, TODAY_KIRITIMATI, title="Their today"),
        ]
        task_repo.find_tasks_due_in_journals.return_value = [make_task(1)]

        (model,) = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID], now=NOW
        )

        assert model.due_journal.date == TODAY_KIRITIMATI
        assert model.lapse_reason is None

    async def test_an_injected_zone_is_used_and_settings_are_never_read(
        self, service: TaskReadService, settings_repo: AsyncMock
    ) -> None:
        """The caller that already resolved the zone must not cause a second read.

        Two reads of ``user_settings`` in one request are two statements under
        READ COMMITTED: a change committed between them is visible to the second
        and not the first, and the daily summary's window is seconds wide because
        it makes a model call in between. The asymmetry with ``now`` was the
        defect the upcoming window's review found; this listing is born with both
        halves injectable.
        """
        models = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID], now=NOW, timezone=KIRITIMATI
        )

        assert [model.due_journal.date for model in models] == [SUMMARY_DAY]
        settings_repo.get_timezone.assert_not_awaited()

    async def test_the_zone_is_resolved_when_the_caller_omits_it(
        self, service: TaskReadService, settings_repo: AsyncMock
    ) -> None:
        """Every surface omits it, so the default has to work on its own."""
        await service.read_models_due_in_journals(USER_ID, [MORNING_ID], now=NOW)

        settings_repo.get_timezone.assert_awaited_once_with(USER_ID)

    async def test_the_acting_user_scopes_every_read(
        self, service: TaskReadService, task_repo: AsyncMock, journal_repo: AsyncMock
    ) -> None:
        """The id reaches the statements rather than being checked afterwards."""
        await service.read_models_due_in_journals(OTHER_USER_ID, [MORNING_ID], now=NOW)

        assert task_repo.find_tasks_due_in_journals.await_args.args[1] == OTHER_USER_ID
        assert journal_repo.find_by_ids_for_user.await_args.args[0] == OTHER_USER_ID


class TestOneReadPerCollection:
    """The cost is invariant in the task count, which no answer can show."""

    @pytest.mark.parametrize("count", [1, 8], ids=["one-task", "eight-tasks"])
    async def test_the_statement_count_does_not_grow_with_the_day(
        self,
        service: TaskReadService,
        task_repo: AsyncMock,
        journal_repo: AsyncMock,
        contact_repo: AsyncMock,
        calendar_info_repo: AsyncMock,
        count: int,
    ) -> None:
        """A busy day costs the same reads as a quiet one.

        A day's journals can hold twenty commitments between them, and the
        answer is correct either way — only the number of round trips is wrong,
        which is why it is asserted directly.
        """
        seed_many(task_repo, count)

        models = await service.read_models_due_in_journals(
            USER_ID, [MORNING_ID], now=NOW
        )

        assert len(models) == count
        assert task_repo.find_tasks_due_in_journals.await_count == 1
        assert task_repo.list_intermediate_journal_ids_for_tasks.await_count == 1
        assert task_repo.list_contact_ids_for_tasks.await_count == 1
        assert journal_repo.find_by_ids_for_user.await_count == 1
        assert calendar_info_repo.find_cancelled_journal_ids.await_count == 1
        assert contact_repo.find_names_by_ids.await_count == 1

    async def test_a_day_referencing_nobody_skips_the_name_lookup(
        self, service: TaskReadService, contact_repo: AsyncMock
    ) -> None:
        """The floor is lower than the ceiling, and the skip is deliberate."""
        await service.read_models_due_in_journals(USER_ID, [MORNING_ID], now=NOW)

        contact_repo.find_names_by_ids.assert_not_awaited()
