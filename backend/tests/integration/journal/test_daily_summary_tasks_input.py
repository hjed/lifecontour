"""Integration tests for the tasks the daily summary's input assembler gathers.

Exercises ``DailySummaryInputAssembler.assemble`` against real tasks, real
journals and a real ``TaskReadService``. The unit suite proves the assembler
*asks* the right question of a double; only real rows prove the answer is the
week's outstanding commitments and nothing else.

Three things are asserted here that no unit test reaches:

- **Which tasks the window really admits** — inside, on the boundary day, and
  past it — where the rule works in dates and the column holds instants.
- **That the exclusions survive the whole path.** Done and cancelled tasks are
  dropped by the statement; a task whose **due journal was cancelled** is
  dropped by the pure rule reading a verdict assembled from a third table. That
  last fixture is the only one that makes the lapse check non-vacuous — a
  date-passed lapse cannot fall inside a forward window by construction — so it
  is required here as it is at every other level.
- **Whose week it is.** The window is anchored on the user's today, so a zone
  far from UTC is never on the same date as it and a UTC-anchored reading cannot
  pass.

Every date here is a **fixed instant** with ``now`` injected. The assertions are
about window edges, and a boundary anchored on a moving clock is a test that
passes at 10:00 and fails at 23:59 — the reason the bracketing
``test_task_upcoming_listing_integration.py`` fixes its dates too, whose seeding
helpers this reuses rather than growing a second set.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import TaskStatus
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_repository import SqlContactRepository
from app.core.journal.adapters.sql.calendar_info_repository import (
    SqlCalendarInfoRepository,
)
from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.services.daily_summary_input_assembler import (
    DailySummaryInputAssembler,
)
from app.core.journal.services.daily_summary_models import DailySummaryInput
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from app.core.tasks.adapters.sql.task_repository import SqlTaskRepository
from app.core.tasks.services.task_read_service import TaskReadService
from tests.integration.tasks.task_seeding import (
    OTHER_USER_ID,
    USER_ID,
    create_contact,
    create_journal,
    create_task,
    link_contact,
    mark_journal_as_event,
)

pytestmark = pytest.mark.integration

# Midday UTC on a Tuesday. Far enough from either midnight that a UTC reading
# and the user's agree, so the far-east case below has to say when it wants them
# to disagree.
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
TODAY = date(2026, 8, 11)

# A large positive offset, so one local day never shares a UTC date with UTC's.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14


def at(day: date, hour: int = 9) -> datetime:
    """An instant on ``day``, in UTC."""
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=hour)


@pytest.fixture
def assembler(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    user_settings_repository: SqlUserSettingsRepository,
) -> DailySummaryInputAssembler:
    """The assembler over the test's savepoint connection, tasks read and all.

    Built from adapters rather than resolved from a container, the shape
    ``test_daily_summary_agenda_input.py`` uses: what is under test is the
    assembly, and a container would add a graph to construct without adding an
    assertion. The read service shares this connection, so a task seeded in the
    test is visible to it inside the same savepoint.
    """
    return DailySummaryInputAssembler(
        journal_repo=journal_repository,
        mood_repo=SqlMoodDataRepository(async_connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(
            async_connection
        ),
        summary_repo=SqlJournalDailySummaryRepository(async_connection),
        task_read_service=TaskReadService(
            task_repo=SqlTaskRepository(async_connection),
            journal_repo=journal_repository,
            contact_repo=SqlContactRepository(async_connection),
            calendar_info_repo=SqlCalendarInfoRepository(async_connection),
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
        ),
    )


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


def gathered_texts(assembled: DailySummaryInput) -> list[str]:
    """The task text the input carries, in the order it carries it."""
    assert assembled.upcoming_tasks is not None
    return [model.task.text for model in assembled.upcoming_tasks.tasks]


class TestTheWeeksCommitmentsReachTheInput:
    """What the window admits, against real timestamps."""

    async def test_a_task_due_inside_the_window_arrives_with_its_contact(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The ordinary case, whole — the commitment and the person on it.

        The contact is the half the phase adds beyond "there is a task": the
        summary's value is in connecting a commitment to a person, and it cannot
        do that from a row it was handed without one.
        """
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

        assembled = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert assembled.upcoming_tasks is not None
        (model,) = assembled.upcoming_tasks.tasks
        assert model.task.text == "print the permit"
        assert model.due_journal.title == "Permit Meeting"
        assert model.due_journal.date == TODAY + timedelta(days=2)
        assert [c.display_name for c in model.contacts] == ["Sarah"]

    async def test_the_boundary_day_is_inside_and_the_day_after_is_not(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """ "Inclusive" is the word an off-by-one gets wrong, so both sides.

        The boundary journal is seeded at **23:00** on purpose: a window built
        from the day's *start* would still admit a morning fixture, and pass.
        """
        creating = await creating_journal(journal_repository)
        boundary = await create_journal(
            journal_repository,
            title="Seventh day",
            start=at(TODAY + timedelta(days=7), hour=23),
        )
        beyond = await create_journal(
            journal_repository,
            title="Eighth day",
            start=at(TODAY + timedelta(days=8)),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=boundary,
            text="on the boundary",
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=beyond,
            text="past the boundary",
        )

        assembled = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert gathered_texts(assembled) == ["on the boundary"]

    async def test_the_window_travels_with_the_tasks(
        self,
        assembler: DailySummaryInputAssembler,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A quiet week is still a week, and the prompt has to be able to say so."""
        await creating_journal(journal_repository)

        assembled = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert assembled.upcoming_tasks is not None
        assert assembled.upcoming_tasks.tasks == ()
        assert assembled.upcoming_tasks.window.first_day == TODAY
        assert assembled.upcoming_tasks.window.last_day == TODAY + timedelta(days=7)


class TestOnlyOutstandingCommitmentsAreOffered:
    """Nothing already dealt with is handed over as still outstanding."""

    @pytest.mark.parametrize(
        "status", [TaskStatus.DONE, TaskStatus.CANCELLED], ids=["done", "cancelled"]
    )
    async def test_a_finished_task_is_absent(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        status: TaskStatus,
    ) -> None:
        """Dropped by the statement, before the rule ever sees it."""
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Permit Meeting",
            start=at(TODAY + timedelta(days=2)),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="already dealt with",
            status=status,
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="still outstanding",
        )

        assembled = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert gathered_texts(assembled) == ["still outstanding"]

    async def test_a_task_whose_due_journal_was_cancelled_is_absent(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The only fixture that makes the lapse exclusion bite.

        A date-passed lapse cannot fall inside a forward window — the window
        starts today — so a rule filtering on status and dates alone would look
        correct against every other case here. This one is not-done, dated
        squarely inside the window, and lapsed only because the event it is due
        at was called off. Presenting it as outstanding would have the summary
        tell the user to prepare for a meeting that is not happening.
        """
        creating = await creating_journal(journal_repository)
        cancelled_due = await create_journal(
            journal_repository,
            title="Meeting that was called off",
            start=at(TODAY + timedelta(days=3)),
        )
        await mark_journal_as_event(
            async_connection, cancelled_due, event_state=EventState.CANCELLED
        )
        live_due = await create_journal(
            journal_repository,
            title="Meeting that is going ahead",
            start=at(TODAY + timedelta(days=3)),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=cancelled_due,
            text="lapsed by cancellation",
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=live_due,
            text="still outstanding",
        )

        assembled = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert gathered_texts(assembled) == ["still outstanding"]

    async def test_another_users_task_is_absent(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The listing crosses journals, so owner scoping is all that separates."""
        theirs = await create_journal(
            journal_repository,
            title="Their planning",
            start=at(TODAY - timedelta(days=30)),
            user_id=OTHER_USER_ID,
        )
        their_due = await create_journal(
            journal_repository,
            title="Their meeting",
            start=at(TODAY + timedelta(days=2)),
            user_id=OTHER_USER_ID,
        )
        await create_task(
            async_connection,
            creating_journal_id=theirs,
            due_journal_id=their_due,
            text="not mine",
            user_id=OTHER_USER_ID,
        )

        assembled = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert gathered_texts(assembled) == []


class TestTasksAreGatheredForTheCurrentDayOnly:
    """A summary of last Tuesday describes last Tuesday."""

    @pytest.mark.parametrize("offset", [-1, 1], ids=["past", "future"])
    async def test_another_day_gathers_no_tasks_but_still_gathers_its_journals(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        offset: int,
    ) -> None:
        """The negative runs against a day that really has a week ahead of it.

        The task is dated inside the window a *today* reading would build, and
        the day being summarised has a journal of its own, so a green result
        means the guard fired rather than that there was nothing to find. An
        absence assertion on an empty fixture proves nothing either way.
        """
        day = TODAY + timedelta(days=offset)
        creating = await creating_journal(journal_repository)
        await create_journal(
            journal_repository, title="That day's journal", start=at(day, hour=10)
        )
        due = await create_journal(
            journal_repository,
            title="Permit Meeting",
            start=at(TODAY + timedelta(days=2)),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="print the permit",
        )

        assembled = await assembler.assemble(USER_ID, day, "UTC", now=NOW)

        assert assembled.upcoming_tasks is None
        assert [entry.title for entry in assembled.journals] == ["That day's journal"]


class TestTheWindowIsAnchoredOnTheUsersDay:
    """Whose today it is, where UTC's answer and the user's cannot agree."""

    async def test_a_far_east_users_window_is_their_own(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """Kiritimati has turned the page; UTC has not.

        ``now`` is 12:00Z on the 11th, already 02:00 on the **12th** in
        Kiritimati (+14), so their window runs the 12th to the 19th while UTC's
        would run the 11th to the 18th. The due journal starts at midnight on
        the 19th UTC — 14:00 on the 19th there, the last day of their window and
        a day past the end of UTC's. A UTC-anchored reading drops it entirely,
        which is what makes the assertion worth making.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Kiritimati boundary day",
            start=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="their last day",
        )

        assembled = await assembler.assemble(
            USER_ID, date(2026, 8, 12), FAR_EAST, now=NOW
        )

        assert assembled.upcoming_tasks is not None
        assert assembled.upcoming_tasks.window.first_day == date(2026, 8, 12)
        assert assembled.upcoming_tasks.window.last_day == date(2026, 8, 19)
        assert gathered_texts(assembled) == ["their last day"]

    async def test_the_zone_the_assembly_resolved_beats_a_later_settings_change(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """The stored row disagrees with the caller, and the caller wins.

        This is the race the arrangement stands in for. In production the
        assembler is handed the zone ``DailySummaryService`` read from this very
        row; a second read inside the listing is a **second statement**, and
        under READ COMMITTED a timezone changed in between is visible to it and
        not to the day the prompt is labelled with. So the row is seeded as UTC
        while the assembly is handed Kiritimati: a listing resolving its own
        zone would build UTC's 11th-to-18th window and drop this task entirely,
        while the prompt above it still said Kiritimati's 12th.

        The bracketing case seeds the row and the argument to agree, which is
        what production does; this one exists because that case cannot fail for
        this reason.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="UTC")
        )
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Kiritimati boundary day",
            start=datetime(2026, 8, 19, 0, 0, tzinfo=UTC),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="their last day",
        )

        assembled = await assembler.assemble(
            USER_ID, date(2026, 8, 12), FAR_EAST, now=NOW
        )

        assert assembled.upcoming_tasks is not None
        assert assembled.upcoming_tasks.window.first_day == date(2026, 8, 12)
        assert gathered_texts(assembled) == ["their last day"]
