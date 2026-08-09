"""Integration tests for the task read model against real PostgreSQL.

The unit tests pin the rule and the assembly; these pin them against rows the
database actually holds. Three things only exist at this level:

- **a real cancelled event journal.** Cancellation is a string in
  ``journal_calendar_info``, reached through a join the unit tests replace with
  a mocked set. Whether the read model can see it at all is a question about
  SQL.
- **a real past-dated journal.** No API path can produce a lapsed task — the
  future-dated invariant is checked when the due journal is set — so the row is
  seeded directly, exactly as the specification says a task becomes lapsed:
  by the world moving on around it.
- **the round-trip count.** An N+1 is invisible to every functional assertion
  here; only the statements PostgreSQL receives can show it.

Seeding goes through ``task_seeding``'s raw inserts rather than ``TaskService``
for the reason that module documents: the service can only make a *not-done*
task due in a *future* journal, and every interesting case here is a task that
has since become something else.
"""

from datetime import UTC, date, datetime

import pytest
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import LapseReason, TaskNotFoundError, TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
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
    make_task_container,
    mark_journal_as_event,
)

# 23:00 on 9 August in Sydney, and 09:00 that morning in UTC terms is behind it.
JOURNAL_AT_SYDNEY_LATE_EVENING = datetime(2026, 8, 9, 13, 0, tzinfo=UTC)
# 00:30 on 10 August in Sydney, while UTC has not left the 9th.
NOW_PAST_SYDNEY_MIDNIGHT = datetime(2026, 8, 9, 14, 30, tzinfo=UTC)


async def seed_task(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    *,
    due_days_offset: int = 7,
    status: TaskStatus = TaskStatus.NOT_DONE,
    due_event_state: EventState | None = None,
) -> tuple[int, int, int]:
    """A task with a creating journal in the past and a due journal placed by offset.

    Returns:
        ``(task_id, creating_journal_id, due_journal_id)``.
    """
    creating_id = await create_journal(
        journal_repository, title="Monday Planning", days_offset=-14
    )
    due_id = await create_journal(
        journal_repository, title="Permit Meeting", days_offset=due_days_offset
    )
    if due_event_state is not None:
        await mark_journal_as_event(
            async_connection, due_id, event_state=due_event_state
        )
    task_id = await create_task(
        async_connection,
        creating_journal_id=creating_id,
        due_journal_id=due_id,
        status=status,
    )
    return task_id, creating_id, due_id


@pytest.mark.integration
class TestLapseAgainstRealJournals:
    """Both causes, derived from rows rather than from a configured double."""

    async def test_a_real_past_dated_journal_lapses_its_task(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The ordinary lapse: the day named in the commitment has gone.

        The row is seeded rather than created through the service because the
        service cannot produce it — which is the specification's point. A task
        becomes lapsed by the calendar moving, not by anything anyone does to
        the task.
        """
        task_id, _, _ = await seed_task(
            async_connection, journal_repository, due_days_offset=-3
        )

        model = await read_service.read_model(USER_ID, task_id)

        assert model.lapsed is True
        assert model.lapse_reason == LapseReason.DATE_PASSED

    async def test_a_real_cancelled_event_journal_lapses_its_task(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A cancelled meeting a week away still lapses the task due in it.

        The due journal is future-dated, so the date cause cannot be what fires
        here — which is what makes the reason worth reporting separately.
        """
        task_id, _, _ = await seed_task(
            async_connection,
            journal_repository,
            due_event_state=EventState.CANCELLED,
        )

        model = await read_service.read_model(USER_ID, task_id)

        assert model.lapse_reason == LapseReason.DUE_JOURNAL_CANCELLED
        assert model.due_journal.cancelled is True

    async def test_a_cancelled_and_passed_journal_reports_the_cancellation(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Both causes at once, against real rows, reports the cancellation.

        The precedence is a decision rather than an accident: cancellation is
        the more specific and more actionable answer, and it is the reason the
        journal-cancellation path is checked against every read surface.
        Asserted here as well as in the rule's own tests, because a later
        reordering of the two branches would still pass the unit suite if only
        one case held it.
        """
        task_id, _, _ = await seed_task(
            async_connection,
            journal_repository,
            due_days_offset=-3,
            due_event_state=EventState.CANCELLED,
        )

        model = await read_service.read_model(USER_ID, task_id)

        assert model.lapse_reason == LapseReason.DUE_JOURNAL_CANCELLED

    async def test_a_real_confirmed_event_journal_lapses_nothing(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The negative of the case above, against a real calendar-info row.

        Without it the cancellation test would pass just as well against a query
        that treated *any* event journal as cancelled.
        """
        task_id, _, _ = await seed_task(
            async_connection,
            journal_repository,
            due_event_state=EventState.CONFIRMED,
        )

        model = await read_service.read_model(USER_ID, task_id)

        assert model.lapsed is False
        assert model.due_journal.cancelled is False

    async def test_a_real_future_journal_with_no_event_row_lapses_nothing(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A plain note journal is not a cancelled event."""
        task_id, _, _ = await seed_task(async_connection, journal_repository)

        model = await read_service.read_model(USER_ID, task_id)

        assert model.lapsed is False
        assert model.lapse_reason is None

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_finished_task_on_a_passed_journal_is_not_lapsed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        status: TaskStatus,
    ):
        """Read back from the database in each terminal status."""
        task_id, _, _ = await seed_task(
            async_connection, journal_repository, due_days_offset=-3, status=status
        )

        model = await read_service.read_model(USER_ID, task_id)

        assert model.task.status is status
        assert model.lapsed is False

    @pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
    async def test_a_finished_task_on_a_cancelled_journal_is_not_lapsed(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        status: TaskStatus,
    ):
        """The other cause, against the same two statuses and real rows."""
        task_id, _, _ = await seed_task(
            async_connection,
            journal_repository,
            status=status,
            due_event_state=EventState.CANCELLED,
        )

        model = await read_service.read_model(USER_ID, task_id)

        assert model.lapsed is False

    async def test_a_cancelled_creating_journal_lapses_nothing(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Cancelling the journal a task arose in changes nothing about the task.

        Checked here because the read model is where it would first go wrong,
        by reading the cancellation off the wrong journal.
        """
        task_id, creating_id, _ = await seed_task(async_connection, journal_repository)
        await mark_journal_as_event(
            async_connection, creating_id, event_state=EventState.CANCELLED
        )

        model = await read_service.read_model(USER_ID, task_id)

        assert model.creating_journal.cancelled is True
        assert model.lapsed is False


@pytest.mark.integration
class TestTheUsersTimezoneDecidesTheDay:
    """Anchored on the stored timezone, never on UTC-today."""

    async def test_a_stored_timezone_flips_the_verdict_at_a_day_boundary(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        """With a real Sydney settings row the task has lapsed; in UTC it has not.

        At 14:30Z on 9 August it is already 00:30 on the 10th in Sydney, so a
        journal at 13:00Z that day — 23:00 Sydney on the 9th — is yesterday
        there and still today in UTC.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        creating_id = await create_journal(
            journal_repository, title="Monday Planning", days_offset=-14
        )
        due_id = await create_journal(
            journal_repository,
            title="Late in Sydney",
            start=JOURNAL_AT_SYDNEY_LATE_EVENING,
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        model = await read_service.read_model(
            USER_ID, task_id, now=NOW_PAST_SYDNEY_MIDNIGHT
        )

        assert model.lapse_reason == LapseReason.DATE_PASSED
        assert model.due_journal.date == date(2026, 8, 9)

    async def test_the_same_rows_fall_back_to_utc_with_no_settings_row(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """No stored timezone means UTC, and UTC has not left the due day.

        The control for the case above. Together they prove the verdict comes
        from ``user_settings`` rather than from the server's clock.
        """
        creating_id = await create_journal(
            journal_repository, title="Monday Planning", days_offset=-14
        )
        due_id = await create_journal(
            journal_repository,
            title="Late in Sydney",
            start=JOURNAL_AT_SYDNEY_LATE_EVENING,
        )
        task_id = await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        model = await read_service.read_model(
            USER_ID, task_id, now=NOW_PAST_SYDNEY_MIDNIGHT
        )

        assert model.lapse_reason is None
        assert model.due_journal.date == date(2026, 8, 9)


@pytest.mark.integration
class TestWhatTheReadModelCarries:
    """The journals by role and the contacts, read back from their own tables."""

    async def test_it_carries_both_anchors_its_mentions_and_its_contacts(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """One read returns everything a journal's task row needs to render."""
        task_id, creating_id, due_id = await seed_task(
            async_connection, journal_repository
        )
        first_mention = await create_journal(
            journal_repository, title="Standup", days_offset=-2
        )
        second_mention = await create_journal(
            journal_repository, title="Retro", days_offset=-1
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=first_mention
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=second_mention
        )
        sarah = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=sarah)

        model = await read_service.read_model(USER_ID, task_id)

        assert (model.creating_journal.id, model.creating_journal.title) == (
            creating_id,
            "Monday Planning",
        )
        assert (model.due_journal.id, model.due_journal.title) == (
            due_id,
            "Permit Meeting",
        )
        assert [ref.title for ref in model.intermediate_journals] == [
            "Standup",
            "Retro",
        ]
        assert [(c.id, c.display_name) for c in model.contacts] == [(sarah, "Sarah")]

    async def test_a_task_with_no_links_carries_empty_collections(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The common case: two anchors and nothing else."""
        task_id, _, _ = await seed_task(async_connection, journal_repository)

        model = await read_service.read_model(USER_ID, task_id)

        assert model.intermediate_journals == ()
        assert model.contacts == ()

    async def test_one_journal_in_two_roles_is_reported_under_both(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Invariant 6's shared journal, and a mention of the due journal too.

        This is the shape a retarget onto an already-attached journal leaves
        behind, and that mention stays removable — so the read model has to
        show it rather than tidy it away.
        """
        shared_id = await create_journal(
            journal_repository, title="Trip Planning", days_offset=7
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=shared_id,
            due_journal_id=shared_id,
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=shared_id
        )

        model = await read_service.read_model(USER_ID, task_id)

        assert model.creating_journal.id == shared_id
        assert model.due_journal.id == shared_id
        assert [ref.id for ref in model.intermediate_journals] == [shared_id]


@pytest.mark.integration
class TestOwnerScopingAgainstRealRows:
    """Another user's task is indistinguishable from one that is not there."""

    async def test_another_users_task_is_not_readable(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A real second user's real task, refused by id."""
        their_journal = await create_journal(
            journal_repository, title="Theirs", days_offset=7, user_id=OTHER_USER_ID
        )
        their_task = await create_task(
            async_connection,
            creating_journal_id=their_journal,
            due_journal_id=their_journal,
            user_id=OTHER_USER_ID,
        )

        with pytest.raises(TaskNotFoundError):
            await read_service.read_model(USER_ID, their_task)

    async def test_an_absent_task_fails_the_same_way(
        self,
        read_service: TaskReadService,
    ):
        """Proved beside the case above, because the pair is the guarantee.

        Either alone would allow the two to be distinguishable; only asserting
        the same error for both says a caller cannot probe for another user's
        tasks.
        """
        with pytest.raises(TaskNotFoundError):
            await read_service.read_model(USER_ID, 999999)


@pytest.mark.integration
class TestRoundTripsAgainstRealPostgres:
    """One statement per collection, counted at the cursor.

    A journal's task list calls this shape once per task, so a stray
    per-journal or per-contact read here is an N+1 there.
    """

    async def test_a_read_costs_one_statement_per_collection(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Three journals and two contacts cost a fixed seven statements.

        Seven, named so the number is a claim rather than a measurement: the
        task; its intermediate journals; its contact links; the user's timezone,
        fetched **once**; the journals for all three roles together; the
        cancellation lookup; and the contact names. One per thing that has to be
        known, and nothing repeated.

        It was nine until the two link reads stopped paying the write path's
        separate ownership statement and started scoping themselves in their own
        join.
        """
        task_id, _, _ = await seed_task(async_connection, journal_repository)
        for title in ("Standup", "Retro"):
            mention = await create_journal(
                journal_repository, title=title, days_offset=-1
            )
            await link_intermediate_journal(
                async_connection, task_id=task_id, journal_id=mention
            )
        for name in ("Sarah", "Mo"):
            contact = await create_contact(async_connection, first_name=name)
            await link_contact(async_connection, task_id=task_id, contact_id=contact)

        with recorded_statements(async_connection) as statements:
            model = await read_service.read_model(USER_ID, task_id)

        assert len(model.intermediate_journals) == 2
        assert len(model.contacts) == 2
        assert len(statements) == 7

    async def test_more_journals_and_contacts_cost_no_more_statements(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The claim that matters: the count does not grow with the collections.

        A fixed number alone would pass against a read that happened to loop
        the same number of times; this one doubles both collections and asserts
        the cost is unchanged.
        """
        task_id, _, _ = await seed_task(async_connection, journal_repository)
        for index in range(6):
            mention = await create_journal(
                journal_repository, title=f"Mention {index}", days_offset=-1
            )
            await link_intermediate_journal(
                async_connection, task_id=task_id, journal_id=mention
            )
        for index in range(6):
            contact = await create_contact(
                async_connection, first_name=f"Person {index}"
            )
            await link_contact(async_connection, task_id=task_id, contact_id=contact)

        with recorded_statements(async_connection) as statements:
            model = await read_service.read_model(USER_ID, task_id)

        assert len(model.intermediate_journals) == 6
        assert len(model.contacts) == 6
        assert len(statements) == 7


@pytest.mark.integration
class TestTheServiceIsResolvable:
    """A controller has to be able to inject this."""

    async def test_the_container_resolves_the_read_service(
        self, async_connection: AsyncConnection
    ):
        """Dishka validates the whole graph, so this also proves it is wireable.

        The read service reaches for ``CalendarInfoRepository``, which no other
        tasks-domain object needs — a provider that had not been registered
        would fail here rather than at the first request in production.
        """
        container = make_task_container(async_connection)

        async with container() as request_container:
            resolved = await request_container.get(TaskReadService)

        assert isinstance(resolved, TaskReadService)
