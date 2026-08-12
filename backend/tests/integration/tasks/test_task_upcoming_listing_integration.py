"""Integration tests for the upcoming-window listing against PostgreSQL.

The unit suite proves the selection rule and the service's call counts against
doubles. This proves the same claims against real rows, where four things can be
wrong that a double cannot show.

**The window is a comparison between two timestamps.** The rule works in dates;
the column holds instants. Everything in between — the conversion, the
inclusivity of both ends, the timezone the boundaries were built in — only
exists once a real statement compares a real ``event_date_range_start``, and an
off-by-one there is invisible to a repository double that was simply handed the
tasks it should return.

**Cancellation is a row in a third table.** ``journal_calendar_info`` is what
makes a journal an event and what says it was called off, and it is the only
lapse cause that can reach inside a forward window. Only a real row proves the
batched lookup and the exclusion still meet.

**Owner scoping lives in the statement.** The listing crosses journals rather
than starting from one the caller named, so the ``user_id`` filter is the only
thing standing between a user and everybody else's week.

**Statement counts are the acceptance criterion.** "One query per collection,
not per task" cannot be observed from the answer, which is right either way. The
recorder listens to what actually reached the driver, at two fixture sizes, so a
per-task loop fails whatever number it happens to run to.

Dates here are fixed instants with an injected ``now`` wherever the assertion is
about a *boundary*, and clock-relative only where it is about ordinary
membership. A boundary anchored on a moving clock is a test that passes at 10:00
and fails at 23:59.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import (
    LapseReason,
    TaskStatus,
    TaskValidationError,
    UpcomingTasks,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_read_service import TaskReadService
from tests.integration.statement_recorder import recorded_statements
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_contact,
    create_journal,
    create_task,
    link_contact,
    link_intermediate_journal,
    mark_journal_as_event,
)

pytestmark = pytest.mark.integration

# Midday UTC on a Tuesday, and the anchor for every fixed-date case below. Far
# enough from either midnight that a UTC reading and a Sydney one agree, so a
# test that wants them to *disagree* has to say so.
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
TODAY = date(2026, 8, 11)


def at(day: date, hour: int = 9) -> datetime:
    """An instant on ``day``, in UTC.

    Journals are seeded from an explicit instant rather than a ``days_offset``
    wherever the assertion is about a window edge: an offset is relative to the
    real clock, and a boundary case anchored on a moving clock is a flake
    waiting for the suite to run late in the day.
    """
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=hour)


async def creating_journal(journal_repository: SqlJournalRepository) -> int:
    """The journal the commitments arose in — well in the past, as usual.

    In the past deliberately: the creating anchor must never be what decides
    whether a task is upcoming, and a fixture dating it inside the window could
    not tell a correct implementation from one reading the wrong column.
    """
    return await create_journal(
        journal_repository,
        title="Monday planning",
        start=at(TODAY - timedelta(days=30)),
    )


def listed_ids(upcoming: UpcomingTasks) -> list[int | None]:
    """The task ids in the answer, in the order it hands them out."""
    return [model.task.id for model in upcoming.tasks]


class TestTheWindowAgainstRealTimestamps:
    """Which rows the statement's date comparison actually admits."""

    async def test_a_task_due_inside_the_window_is_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The ordinary case, whole: text, journal and contacts in one answer."""
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Permit Meeting",
            start=at(TODAY + timedelta(days=2)),
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="print the permit",
        )
        contact = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=contact)

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        (model,) = upcoming.tasks
        assert model.task.id == task_id
        assert model.task.text == "print the permit"
        assert model.due_journal.title == "Permit Meeting"
        assert model.due_journal.date == TODAY + timedelta(days=2)
        assert [contact.display_name for contact in model.contacts] == ["Sarah"]

    async def test_a_task_due_today_is_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The near edge, which the future-dated rule excludes and this includes.

        Seeded at 09:00 on the anchor day with ``now`` at midday, so the journal
        starts *before* the instant being judged — the shape a task due earlier
        today really has, and the one an implementation comparing against ``now``
        rather than against local midnight would drop.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="This morning", start=at(TODAY, hour=9)
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [task_id]

    async def test_a_task_due_on_the_boundary_day_is_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """**Inclusive**, at the far edge, at the last hour of that day.

        23:00 rather than 09:00 on purpose: the window's end is the boundary
        day's final microsecond, and a statement that used the day's *start*
        would still pass a fixture seeded in the morning.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Next Tuesday, late",
            start=at(TODAY + timedelta(days=7), hour=23),
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [task_id]

    async def test_a_task_due_the_day_after_the_window_is_not_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """One minute past midnight on the eighth day is outside.

        The other half of the boundary pair: without it, a window that ran a day
        long would pass every test above.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Just too far",
            start=at(TODAY + timedelta(days=8), hour=0),
        )
        await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.tasks == ()
        assert upcoming.total == 0

    async def test_a_task_due_yesterday_is_not_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Behind the window, and lapsed — both true, and it is absent for both."""
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Yesterday", start=at(TODAY - timedelta(days=1))
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)
        read_back = await read_service.read_model(USER_ID, task_id, now=NOW)

        assert upcoming.tasks == ()
        assert read_back.lapse_reason is LapseReason.DATE_PASSED

    async def test_a_narrower_window_admits_fewer_tasks(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """``days_ahead`` reaches the statement, not just the reported window."""
        creating = await creating_journal(journal_repository)
        near = await create_journal(
            journal_repository, title="Tomorrow", start=at(TODAY + timedelta(days=1))
        )
        far = await create_journal(
            journal_repository, title="Friday", start=at(TODAY + timedelta(days=5))
        )
        near_task = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=near
        )
        await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=far
        )

        upcoming = await read_service.read_models_for_upcoming_window(
            USER_ID, days_ahead=2, now=NOW
        )

        assert listed_ids(upcoming) == [near_task]
        assert upcoming.window.last_day == TODAY + timedelta(days=2)

    @pytest.mark.parametrize("days_ahead", [-1, 91])
    async def test_an_out_of_range_window_is_refused(
        self, read_service: TaskReadService, days_ahead: int
    ) -> None:
        """The domain rule, so both surfaces inherit one answer."""
        with pytest.raises(TaskValidationError):
            await read_service.read_models_for_upcoming_window(
                USER_ID, days_ahead=days_ahead, now=NOW
            )


class TestTheExclusions:
    """Which real rows the listing drops, and where they can still be found."""

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_finished_task_in_the_window_is_not_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        status: TaskStatus,
    ) -> None:
        """Both terminal statuses, filtered in the statement itself."""
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Soon", start=at(TODAY + timedelta(days=2))
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            status=status,
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.tasks == ()

    async def test_a_task_whose_due_journal_was_cancelled_is_not_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """**The fixture that makes the lapsed exclusion non-vacuous.**

        Not done, dated squarely inside the window, and absent only because the
        meeting was called off. A date-passed lapse cannot fall inside a forward
        window by construction, so this is the *only* fixture that fails if the
        lapse check is removed — every other exclusion here is the statement's
        own status filter.

        The same task is asserted still visible on its journal, in the same
        test, because that pair is what the specification actually promises: it
        leaves the dashboard, and it remains where the user can retarget it.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Cancelled meeting",
            start=at(TODAY + timedelta(days=2)),
        )
        await mark_journal_as_event(
            async_connection, due, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)
        on_its_journal = await read_service.read_models_for_journal(
            USER_ID, due, now=NOW
        )

        assert upcoming.tasks == ()
        (still_there,) = on_its_journal.due
        assert still_there.task.id == task_id
        assert still_there.lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED

    async def test_a_confirmed_event_journal_lapses_nothing(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Only ``CANCELLED`` counts, so the exclusion is not "is an event".

        Without this the cancelled case would also pass against an
        implementation that dropped every task whose due journal had a
        ``journal_calendar_info`` row at all.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Meeting", start=at(TODAY + timedelta(days=2))
        )
        await mark_journal_as_event(
            async_connection, due, event_state=EventState.CONFIRMED
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [task_id]

    async def test_a_cancelled_journal_elsewhere_lapses_nothing(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Only the *due* journal decides it.

        The creating journal is cancelled here and the task stays listed, which
        is the half that stops the batched cancellation lookup from being
        applied to whichever journal it happens to find.
        """
        creating = await creating_journal(journal_repository)
        await mark_journal_as_event(
            async_connection, creating, event_state=EventState.CANCELLED
        )
        due = await create_journal(
            journal_repository, title="Still on", start=at(TODAY + timedelta(days=2))
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [task_id]


class TestOwnerScoping:
    """The filter that keeps a cross-journal listing to one user."""

    async def test_another_users_task_is_never_listed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Both users have one due in the same window, and only one comes back."""
        creating = await creating_journal(journal_repository)
        mine_due = await create_journal(
            journal_repository, title="Mine", start=at(TODAY + timedelta(days=2))
        )
        mine = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=mine_due
        )
        theirs_journal = await create_journal(
            journal_repository,
            title="Theirs",
            start=at(TODAY + timedelta(days=2)),
            user_id=OTHER_USER_ID,
        )
        await create_task(
            async_connection,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [mine]

    async def test_the_other_user_sees_their_own(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The other half: the fixture is a real task, not an invisible one.

        Without this, a statement returning nothing at all for anybody would
        pass the exclusion above.
        """
        theirs_journal = await create_journal(
            journal_repository,
            title="Theirs",
            start=at(TODAY + timedelta(days=2)),
            user_id=OTHER_USER_ID,
        )
        theirs = await create_task(
            async_connection,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )

        upcoming = await read_service.read_models_for_upcoming_window(
            OTHER_USER_ID, now=NOW
        )

        assert listed_ids(upcoming) == [theirs]


class TestOrdering:
    """Soonest first, with a tie-break that cannot itself tie."""

    async def test_tasks_are_ordered_by_due_date(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Seeded in the wrong order so the answer's order is the query's."""
        creating = await creating_journal(journal_repository)
        far = await create_journal(
            journal_repository, title="Friday", start=at(TODAY + timedelta(days=5))
        )
        near = await create_journal(
            journal_repository, title="Tomorrow", start=at(TODAY + timedelta(days=1))
        )
        far_task = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=far
        )
        near_task = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=near
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [near_task, far_task]

    async def test_tasks_due_the_same_day_are_ordered_by_id(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The tie-break, over rows written in one transaction.

        Two tasks due in the same journal share a start exactly, so the id is
        the only thing separating them — and every row here shares a
        ``created_at`` too, since it defaults to the transaction timestamp.
        Without the second ordering term the answer would be whatever
        PostgreSQL happened to return.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Tuesday", start=at(TODAY + timedelta(days=2))
        )
        first = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )
        second = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [first, second]

    async def test_a_different_journal_on_the_same_day_still_ties_by_id(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Two journals, same local date, different hours.

        The rule orders by the resolved **date**, so these tie even though their
        instants do not — and the statement's own ``ORDER BY`` over the raw
        timestamp would put the earlier hour first regardless of id. Seeding the
        later-created task at the earlier hour is what makes the two orders
        disagree, so the assertion says which one wins.
        """
        creating = await creating_journal(journal_repository)
        day = TODAY + timedelta(days=3)
        evening = await create_journal(
            journal_repository, title="Evening", start=at(day, hour=20)
        )
        morning = await create_journal(
            journal_repository, title="Morning", start=at(day, hour=8)
        )
        evening_task = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=evening
        )
        morning_task = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=morning
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [evening_task, morning_task]


class TestTimezoneAnchoring:
    """Whose *today* the window starts on, against a real date comparison."""

    async def test_the_window_starts_on_the_users_day_not_utcs(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """Kiritimati has turned the page; UTC has not.

        ``now`` is 12:00Z on the 11th, already 02:00 on the **12th** in
        Kiritimati (+14) — so the window there runs the 12th to the 19th, one
        whole day ahead of the UTC window's 11th to the 18th.

        The journal starts at midnight on the 19th UTC, which is 14:00 on the
        **19th** in Kiritimati: the last day of their window, and a day past the
        end of UTC's. A UTC-anchored implementation drops this task entirely,
        which is what makes the assertion worth making.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Pacific/Kiritimati")
        )
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Kiritimati boundary day",
            start=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.window.first_day == date(2026, 8, 12)
        assert upcoming.window.last_day == date(2026, 8, 19)
        assert listed_ids(upcoming) == [task_id]

    async def test_the_same_rows_are_outside_a_utc_users_window(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The other half of the pair, without which the case proves nothing.

        Same instant, no configured timezone — so the window is UTC's and the
        journal is a day past its end.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Kiritimati boundary day",
            start=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
        )
        await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert upcoming.window.first_day == TODAY
        assert upcoming.tasks == ()

    async def test_a_journal_late_on_the_users_yesterday_is_excluded(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """The near edge in a non-UTC zone, which UTC would still admit.

        11:00Z on the 11th is 01:00 on the **12th** in Kiritimati — today there,
        and inside the window. 09:00Z is 23:00 on the **11th**, which is
        yesterday there and outside it, though both instants are "today" in UTC.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Pacific/Kiritimati")
        )
        creating = await creating_journal(journal_repository)
        their_yesterday = await create_journal(
            journal_repository,
            title="Their yesterday evening",
            start=datetime(2026, 8, 11, 9, 0, tzinfo=UTC),
        )
        their_today = await create_journal(
            journal_repository,
            title="Their small hours",
            start=datetime(2026, 8, 11, 11, 0, tzinfo=UTC),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=their_yesterday,
        )
        today_task = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=their_today
        )

        upcoming = await read_service.read_models_for_upcoming_window(USER_ID, now=NOW)

        assert listed_ids(upcoming) == [today_task]


class TestOneStatementPerCollection:
    """The fourth acceptance criterion, against what reached the driver."""

    async def seed_tasks(
        self,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        count: int,
    ) -> None:
        """``count`` tasks in the window, each with a mention and a contact.

        Every collection the assembler batches is non-empty, so a skipped query
        cannot be mistaken for a batched one.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Due", start=at(TODAY + timedelta(days=3))
        )
        mention = await create_journal(
            journal_repository, title="Mention", start=at(TODAY - timedelta(days=10))
        )
        for index in range(count):
            task_id = await create_task(
                async_connection,
                creating_journal_id=creating,
                due_journal_id=due,
                text=f"task {index}",
            )
            await link_intermediate_journal(
                async_connection, task_id=task_id, journal_id=mention
            )
            contact = await create_contact(
                async_connection, first_name=f"Person{index}"
            )
            await link_contact(async_connection, task_id=task_id, contact_id=contact)

    async def test_two_tasks_cost_one_statement_per_collection(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Seven: the timezone, the windowed task query, the mentions, the
        contacts, the journals for every role together, the cancellation lookup
        and the contact names. One per thing that has to be known.
        """
        await self.seed_tasks(async_connection, journal_repository, 2)

        with recorded_statements(async_connection) as statements:
            upcoming = await read_service.read_models_for_upcoming_window(
                USER_ID, now=NOW
            )

        assert upcoming.total == 2
        assert len(statements) == 7

    async def test_more_tasks_cost_no_more_statements(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The claim that matters: the cost does not grow with the task count.

        A fixed number on its own would also pass against a loop that ran a
        fixed number of times, so the fixture triples.
        """
        await self.seed_tasks(async_connection, journal_repository, 6)

        with recorded_statements(async_connection) as statements:
            upcoming = await read_service.read_models_for_upcoming_window(
                USER_ID, now=NOW
            )

        assert upcoming.total == 6
        assert len(statements) == 7

    async def test_an_empty_window_costs_two(
        self, read_service: TaskReadService, async_connection: AsyncConnection
    ) -> None:
        """Nothing to assemble, so nothing is assembled.

        The timezone and the windowed query, and then every batch below is
        skipped because it has no ids to ask about. The floor is worth pinning:
        an empty dashboard is the request a user makes most often, and it should
        not cost the same as a full one.
        """
        with recorded_statements(async_connection) as statements:
            upcoming = await read_service.read_models_for_upcoming_window(
                USER_ID, now=NOW
            )

        assert upcoming.total == 0
        assert len(statements) == 2


class TestTheRepositoryOnItsOwnTerms:
    """The statement beneath the service, asked directly.

    The service applies the pure rule on top, which would mask a query that
    returned too *much*. These cases ask the repository itself, so what the SQL
    admits is asserted rather than what survived the filter afterwards.
    """

    async def test_it_returns_only_not_done_tasks_in_the_window(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The status filter is the statement's, not the rule's."""
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Soon", start=at(TODAY + timedelta(days=2))
        )
        outstanding = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )
        for status in (TaskStatus.DONE, TaskStatus.CANCELLED):
            await create_task(
                async_connection,
                creating_journal_id=creating,
                due_journal_id=due,
                status=status,
            )

        found = await task_repository.find_upcoming_tasks(
            USER_ID,
            window_start=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
            window_end=datetime.combine(
                TODAY + timedelta(days=7), datetime.max.time(), tzinfo=UTC
            ),
        )

        assert [task.id for task in found] == [outstanding]

    async def test_a_cancelled_due_journal_is_not_filtered_here(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The lapse is deliberately **not** the statement's business.

        There is one definition of lapsed and it lives in the read model, over a
        cancellation lookup the assembler already makes. A second copy in SQL
        could drift from it, so the query is asserted to leave this task in and
        the service is asserted elsewhere to take it out.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Cancelled", start=at(TODAY + timedelta(days=2))
        )
        await mark_journal_as_event(
            async_connection, due, event_state=EventState.CANCELLED
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=due
        )

        found = await task_repository.find_upcoming_tasks(
            USER_ID,
            window_start=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
            window_end=datetime.combine(
                TODAY + timedelta(days=7), datetime.max.time(), tzinfo=UTC
            ),
        )

        assert [task.id for task in found] == [task_id]

    async def test_both_window_ends_are_inclusive(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A journal starting exactly on either bound is inside it."""
        creating = await creating_journal(journal_repository)
        start_instant = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC)
        end_instant = datetime.combine(
            TODAY + timedelta(days=7), datetime.max.time(), tzinfo=UTC
        )
        first = await create_journal(
            journal_repository, title="Exactly the start", start=start_instant
        )
        last = await create_journal(
            journal_repository, title="Exactly the end", start=end_instant
        )
        first_task = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=first
        )
        last_task = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=last
        )

        found = await task_repository.find_upcoming_tasks(
            USER_ID, window_start=start_instant, window_end=end_instant
        )

        assert [task.id for task in found] == [first_task, last_task]

    async def test_it_fetches_neither_side_of_the_window(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The statement must not over-fetch and leave the rule to tidy up.

        Written because a mutation exposed the gap: dropping the upper bound
        from the ``BETWEEN`` left every service-level test green, since the pure
        rule filters the window a second time. The answer stays right and the
        query silently becomes "every future task of this user's, resolved" —
        exactly the unbounded listing this endpoint exists not to be. Only a
        question put to the repository directly can see that.
        """
        creating = await creating_journal(journal_repository)
        before = await create_journal(
            journal_repository, title="Last week", start=at(TODAY - timedelta(days=7))
        )
        after = await create_journal(
            journal_repository, title="Next month", start=at(TODAY + timedelta(days=30))
        )
        inside = await create_journal(
            journal_repository, title="Thursday", start=at(TODAY + timedelta(days=3))
        )
        for due in (before, after):
            await create_task(
                async_connection, creating_journal_id=creating, due_journal_id=due
            )
        wanted = await create_task(
            async_connection, creating_journal_id=creating, due_journal_id=inside
        )

        found = await task_repository.find_upcoming_tasks(
            USER_ID,
            window_start=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
            window_end=datetime.combine(
                TODAY + timedelta(days=7), datetime.max.time(), tzinfo=UTC
            ),
        )

        assert [task.id for task in found] == [wanted]

    async def test_another_users_task_is_not_fetched(
        self,
        task_repository: SqlTaskRepository,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Owner scoping is the statement's, not a filter applied afterwards.

        Asserted here as well as at service level for the reason above: a
        missing ``user_id`` predicate would fetch every user's tasks and the
        answer would still be right, because nothing downstream re-checks it —
        it would simply be wrong about *whose* rows it had read.
        """
        theirs_journal = await create_journal(
            journal_repository,
            title="Theirs",
            start=at(TODAY + timedelta(days=2)),
            user_id=OTHER_USER_ID,
        )
        await create_task(
            async_connection,
            creating_journal_id=theirs_journal,
            due_journal_id=theirs_journal,
            user_id=OTHER_USER_ID,
        )

        found = await task_repository.find_upcoming_tasks(
            USER_ID,
            window_start=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
            window_end=datetime.combine(
                TODAY + timedelta(days=7), datetime.max.time(), tzinfo=UTC
            ),
        )

        assert found == []

    async def test_an_empty_window_returns_nothing_rather_than_failing(
        self, task_repository: SqlTaskRepository
    ) -> None:
        """A user with no tasks at all is an ordinary caller."""
        found = await task_repository.find_upcoming_tasks(
            USER_ID,
            window_start=datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC),
            window_end=datetime.combine(
                TODAY + timedelta(days=7), datetime.max.time(), tzinfo=UTC
            ),
        )

        assert found == []
