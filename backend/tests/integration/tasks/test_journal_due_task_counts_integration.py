"""Integration tests for the journal list's "tasks due" counts.

``TaskReadService.due_task_counts`` is pinned at the unit level over doubles;
this file pins it against rows PostgreSQL actually holds. Four things only exist
at this level:

- **a real cancelled event journal.** Cancellation is a string in
  ``journal_calendar_info`` reached through a join, which a mocked set of ids
  replaces entirely. Whether the indicator can see one is a question about SQL.
  It is asserted **with its negative** — a `confirmed` event beside it — because
  the cancelled case alone would pass against a lookup that treated any event
  journal as cancelled.
- **a real past-dated journal.** No API path produces one holding a live task:
  the future-dated invariant is checked when the due journal is set, so the row
  is seeded directly, exactly as the specification says a task lapses — by the
  world moving on around it.
- **a real ``user_settings`` row.** Whether the *configured* zone is the one
  consulted can only be shown where the setting is really stored and really
  read, and it is shown by giving one fixed instant opposite verdicts with the
  row and without it.
- **the round-trip count.** The criterion this phase exists to satisfy is a
  claim about statements, and only the statements the driver receives can settle
  it.

Seeding goes through ``task_seeding``'s raw inserts rather than ``TaskService``
for the reason that module documents: the service can only produce a *not-done*
task due in a *future* journal, and half the cases here are journals that have
since become something else.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.journals import Journal
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import TaskStatus
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
    create_journal,
    create_task,
    mark_journal_as_event,
)

# Midday UTC on 9 August 2026 — the anchor for the today-boundary case, so the
# assertion is about a date rather than about when the suite happened to run.
NOON = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)

# 23:00 on 9 August in Sydney, still the 9th in UTC.
JOURNAL_AT_SYDNEY_LATE_EVENING = datetime(2026, 8, 9, 13, 0, tzinfo=UTC)
# 00:30 on 10 August in Sydney, while UTC has not left the 9th.
NOW_PAST_SYDNEY_MIDNIGHT = datetime(2026, 8, 9, 14, 30, tzinfo=UTC)


async def journals_by_id(
    journal_repository: SqlJournalRepository, journal_ids: list[int]
) -> list[Journal]:
    """Re-read the seeded journals as the listing endpoint would hand them over.

    ``due_task_counts`` takes journal entities rather than ids, because their
    dates are the input the lapse rule needs. Fetching them here keeps the tests
    honest about what the caller actually passes: rows read back from the
    database, not objects a helper made up.

    The repository answers in its own order, so the returned list is re-ordered
    to match ``journal_ids`` — a test that named a page in a particular order
    should be handed it in that order.
    """
    found = await journal_repository.find_by_ids_for_user(USER_ID, journal_ids)
    by_id = {journal.id: journal for journal in found}
    return [by_id[journal_id] for journal_id in journal_ids]


async def seed_due_journal(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    *,
    title: str,
    days_offset: int = 7,
    tasks: int = 1,
    status: TaskStatus = TaskStatus.NOT_DONE,
    event_state: EventState | None = None,
    user_id: str = USER_ID,
) -> int:
    """A journal with ``tasks`` tasks due in it, and its own creating journal."""
    creating_id = await create_journal(
        journal_repository, title=f"{title} — where it arose", days_offset=-14
    )
    due_id = await create_journal(
        journal_repository, title=title, days_offset=days_offset
    )
    if event_state is not None:
        await mark_journal_as_event(async_connection, due_id, event_state=event_state)
    for index in range(tasks):
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text=f"{title} commitment {index}",
            status=status,
            user_id=user_id,
        )
    return due_id


@pytest.mark.integration
class TestCountsAgainstRealRows:
    """What a page of real journals reports, before any lapse is considered."""

    async def test_a_future_journal_reports_its_live_commitments(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Two tasks due in one journal read as two."""
        due_id = await seed_due_journal(
            async_connection, journal_repository, title="Permit Meeting", tasks=2
        )

        counts = await read_service.due_task_counts(
            USER_ID, await journals_by_id(journal_repository, [due_id])
        )

        assert counts == {due_id: 2}

    async def test_terminal_tasks_leave_the_journal_absent(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A journal holding only done and cancelled tasks is waiting on nothing.

        The specification's rule read from the other side: the indicator is
        about commitments still outstanding, so a journal whose tasks are all
        settled looks exactly like one that never had any.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        for status in (TaskStatus.DONE, TaskStatus.CANCELLED):
            await create_task(
                async_connection,
                creating_journal_id=creating_id,
                due_journal_id=due_id,
                text=f"a {status.value} task",
                status=status,
            )

        counts = await read_service.due_task_counts(
            USER_ID, await journals_by_id(journal_repository, [due_id])
        )

        assert counts == {}

    async def test_another_users_task_does_not_light_the_indicator(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A foreign task anchored to the caller's journal stays invisible.

        Nothing in the schema forbids the row, so the owner predicate is the
        only thing keeping one person's commitments off another's list.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(journal_repository, title="Due", days_offset=7)
        await create_task(
            async_connection,
            creating_journal_id=creating_id,
            due_journal_id=due_id,
            text="not yours to see",
            user_id=OTHER_USER_ID,
        )

        counts = await read_service.due_task_counts(
            USER_ID, await journals_by_id(journal_repository, [due_id])
        )

        assert counts == {}


@pytest.mark.integration
class TestLapseAgainstRealJournals:
    """Both lapse causes, derived from rows rather than a configured double."""

    async def test_a_real_past_dated_journal_lights_nothing(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The ordinary lapse: the day named in the commitment has gone.

        Its live sibling is on the page too, so the assertion is that *this*
        journal fell out rather than that the read returned nothing.
        """
        past_id = await seed_due_journal(
            async_connection, journal_repository, title="Last week", days_offset=-3
        )
        future_id = await seed_due_journal(
            async_connection, journal_repository, title="Next week", days_offset=7
        )

        counts = await read_service.due_task_counts(
            USER_ID, await journals_by_id(journal_repository, [past_id, future_id])
        )

        assert counts == {future_id: 1}

    async def test_a_real_cancelled_event_journal_lights_nothing(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """A cancelled meeting a week away still lapses the tasks due in it.

        **The confirmed event beside it is what makes this non-vacuous.** Both
        journals are real events with real ``journal_calendar_info`` rows, so a
        lookup that treated any event journal as cancelled would fail here and
        pass without it.
        """
        cancelled_id = await seed_due_journal(
            async_connection,
            journal_repository,
            title="Called off",
            event_state=EventState.CANCELLED,
        )
        confirmed_id = await seed_due_journal(
            async_connection,
            journal_repository,
            title="Still going ahead",
            event_state=EventState.CONFIRMED,
        )

        counts = await read_service.due_task_counts(
            USER_ID,
            await journals_by_id(journal_repository, [cancelled_id, confirmed_id]),
        )

        assert counts == {confirmed_id: 1}

    async def test_a_journal_dated_today_still_counts(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Today is neither future nor passed, against real rows.

        The boundary the rule owns, asserted here as well because a query that
        compared dates in SQL would be free to draw it somewhere else.

        **The instant is fixed rather than clock-relative**, unlike the cases
        either side of it: those have days of margin, and this one has none, so
        a run that crossed UTC midnight between seeding the journal and reading
        it back would see yesterday and fail for a reason that is not about the
        rule.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        today_id = await create_journal(
            journal_repository, title="Later today", start=NOON
        )
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=today_id
        )

        counts = await read_service.due_task_counts(
            USER_ID,
            await journals_by_id(journal_repository, [today_id]),
            now=NOON,
        )

        assert counts == {today_id: 1}


@pytest.mark.integration
class TestTheConfiguredTimezoneDecides:
    """One fixed instant, two answers, decided by a real settings row."""

    async def test_a_real_sydney_setting_lapses_what_utc_would_not(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ):
        """At 00:30 on the 10th in Sydney, the evening of the 9th is behind them."""
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Australia/Sydney")
        )
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(
            journal_repository,
            title="Late in Sydney",
            start=JOURNAL_AT_SYDNEY_LATE_EVENING,
        )
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        counts = await read_service.due_task_counts(
            USER_ID,
            await journals_by_id(journal_repository, [due_id]),
            now=NOW_PAST_SYDNEY_MIDNIGHT,
        )

        assert counts == {}

    async def test_the_same_rows_still_count_with_no_settings_row(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The control: with no configured zone the fallback is UTC, still on the 9th.

        Identical rows and an identical instant, differing only in whether a
        ``user_settings`` row exists. Without this the test above would show
        only that *something* lapsed.
        """
        creating_id = await create_journal(journal_repository, title="Where it arose")
        due_id = await create_journal(
            journal_repository,
            title="Late in Sydney",
            start=JOURNAL_AT_SYDNEY_LATE_EVENING,
        )
        await create_task(
            async_connection, creating_journal_id=creating_id, due_journal_id=due_id
        )

        counts = await read_service.due_task_counts(
            USER_ID,
            await journals_by_id(journal_repository, [due_id]),
            now=NOW_PAST_SYDNEY_MIDNIGHT,
        )

        assert counts == {due_id: 1}


@pytest.mark.integration
class TestWhatThePageCosts:
    """The criterion is a claim about statements, so the statements are counted."""

    async def test_three_statements_however_many_journals(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """Three for two journals, and still three for eight.

        The count, the timezone and the cancellation lookup — one per thing that
        has to be known, and nothing repeated. The *doubling* is the assertion:
        a fixed number on its own would pass against a loop that happened to run
        a fixed number of times.
        """
        journal_ids = [
            await seed_due_journal(
                async_connection,
                journal_repository,
                title=f"Due {index}",
                days_offset=index + 1,
            )
            for index in range(8)
        ]
        small_page = await journals_by_id(journal_repository, journal_ids[:2])
        large_page = await journals_by_id(journal_repository, journal_ids)

        with recorded_statements(async_connection) as few:
            small = await read_service.due_task_counts(USER_ID, small_page)
        with recorded_statements(async_connection) as many:
            large = await read_service.due_task_counts(USER_ID, large_page)

        assert len(small) == 2
        assert len(large) == 8
        assert len(few) == 3
        assert len(many) == 3

    async def test_a_page_with_nothing_due_costs_one_statement(
        self,
        read_service: TaskReadService,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ):
        """The common path: most journals hold no tasks at all.

        The count comes back empty and there is nothing left to judge, so the
        timezone read and the cancellation lookup never run — which is what
        keeps the listing's ordinary case at the single query the criterion asks
        for.
        """
        journal_ids = [
            await create_journal(
                journal_repository, title=f"Quiet {index}", days_offset=index + 1
            )
            for index in range(8)
        ]
        page = await journals_by_id(journal_repository, journal_ids)

        with recorded_statements(async_connection) as statements:
            counts = await read_service.due_task_counts(USER_ID, page)

        assert counts == {}
        assert len(statements) == 1

    async def test_an_empty_page_costs_nothing(
        self, read_service: TaskReadService, async_connection: AsyncConnection
    ):
        """A filtered listing that matched no journals asks no questions at all."""
        with recorded_statements(async_connection) as statements:
            counts = await read_service.due_task_counts(USER_ID, [])

        assert counts == {}
        assert statements == []
