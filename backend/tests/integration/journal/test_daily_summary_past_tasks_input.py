"""Integration tests for how a past day's commitments reach the summary's input.

Exercises ``DailySummaryInputAssembler.assemble`` for a day already behind the
user's today, against real tasks, real journals and a real ``TaskReadService``.
The unit suite proves the assembler *asks* the right question of a double; only
real rows prove the answer is what was due in that day's journals, in whatever
state each commitment now stands.

Four things are asserted here that no unit test reaches:

- **That nothing is filtered.** Done and cancelled tasks are the *answers* on
  this read, and both are dropped by the sibling listing whose statement this
  one is easily mistaken for. The headline case below — a task finished after
  the day it was due — is the acceptance criterion in one fixture.
- **That the day is its journals**, resolved by the summary's own overlap query.
  A task due elsewhere never appears, however close its date.
- **That the anchor is the *due* one.** A journal that merely recorded or
  mentioned a commitment is not a journal it was due in, and the creating anchor
  is almost always in the past — so a query reading the wrong column would look
  right on a fixture and be wrong on every real day.
- **Whose day it is.** The past/today guard is judged in the user's zone, so a
  zone far from UTC is never on the same date as it and a UTC-anchored reading
  cannot pass.

Every date here is a **fixed instant** with ``now`` injected, for the reason the
bracketing ``test_daily_summary_tasks_input.py`` fixes its own: an assertion
about a day boundary anchored on a moving clock is one that passes at 10:00 and
fails at 23:59. Its seeding helpers are reused rather than a second set grown.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from core_shared.models.journals.event_state import EventState
from core_shared.models.tasks import LapseReason, TaskStatus
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
    link_intermediate_journal,
    mark_journal_as_event,
)

pytestmark = pytest.mark.integration

# Midday UTC on a Tuesday. Far enough from either midnight that a UTC reading
# and the user's agree, so the far-east case below has to say when it wants them
# to disagree.
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
TODAY = date(2026, 8, 11)

# The day being summarised: yesterday, so its commitments have all resolved one
# way or another.
YESTERDAY = TODAY - timedelta(days=1)

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

    Built from adapters rather than resolved from a container, the shape the
    agenda and upcoming-window suites beside this one use: what is under test is
    the assembly, and a container would add a graph to construct without adding
    an assertion. The read service shares this connection, so a task seeded in
    the test is visible to it inside the same savepoint.
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
    """The journal the commitments arose in — well before the day in question.

    Before it deliberately: the creating anchor must never be what decides which
    day a commitment belongs to, and a fixture dating it *on* the summarised day
    could not tell a correct implementation from one reading the wrong column.
    """
    return await create_journal(
        journal_repository,
        title="Monday planning",
        start=at(YESTERDAY - timedelta(days=30)),
    )


def resolutions(assembled: DailySummaryInput) -> list[tuple[str, TaskStatus]]:
    """Each gathered commitment as ``(text, status)``, in the order gathered."""
    assert assembled.past_day_tasks is not None
    return [(model.task.text, model.task.status) for model in assembled.past_day_tasks]


def texts(assembled: DailySummaryInput) -> list[str]:
    """The task text the input carries, in the order it carries it."""
    return [text for text, _ in resolutions(assembled)]


class TestHowTheDaysCommitmentsResolved:
    """Every state a commitment can be in by the time the day is summarised."""

    async def test_a_task_completed_after_the_day_reads_as_done(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The acceptance criterion, in one fixture.

        The task was due yesterday and is done today. Nothing reconstructs what
        was true at the end of yesterday — no field history is replayed — so the
        summary describes it as done, which is what the user sees on the journal
        and the honest answer to "what became of this". A summary insisting it
        was still outstanding would be the one contradicting the product.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="book the venue",
            status=TaskStatus.DONE,
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert assembled.past_day_tasks is not None
        (model,) = assembled.past_day_tasks
        assert model.task.text == "book the venue"
        assert model.task.status is TaskStatus.DONE
        assert model.lapse_reason is None
        assert model.due_journal.title == "Site visit"

    async def test_an_unfinished_task_lapsed_because_the_day_passed(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The ordinary past-day verdict, derived against the user's today."""
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="call the council",
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert assembled.past_day_tasks is not None
        (model,) = assembled.past_day_tasks
        assert model.task.status is TaskStatus.NOT_DONE
        assert model.lapse_reason is LapseReason.DATE_PASSED

    async def test_a_cancelled_due_journal_is_named_as_the_lapse_cause(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Cancellation outranks the passed date, and travels from a third table.

        The verdict comes from ``journal_calendar_info`` by way of the batched
        cancellation lookup, so this is the only fixture here that exercises that
        half of the rule at all — every other past-day task would read as
        date-passed whether the lookup ran or not.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Meeting that was called off",
            start=at(YESTERDAY),
        )
        await mark_journal_as_event(
            async_connection, due, event_state=EventState.CANCELLED
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="bring the permit",
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert assembled.past_day_tasks is not None
        (model,) = assembled.past_day_tasks
        assert model.lapse_reason is LapseReason.DUE_JOURNAL_CANCELLED

    async def test_a_cancelled_task_is_reported_rather_than_dropped(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Calling a commitment off is a resolution, not an absence.

        Together with the done case above this is what separates this read from
        the week's window, whose statement drops exactly these two statuses.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="chase the invoice",
            status=TaskStatus.CANCELLED,
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert resolutions(assembled) == [("chase the invoice", TaskStatus.CANCELLED)]

    async def test_a_day_resolving_several_ways_carries_all_of_them(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A real day is mixed, and the read must not favour one outcome."""
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        for task_text, status in (
            ("pack the rope", TaskStatus.DONE),
            ("call the council", TaskStatus.CANCELLED),
            ("return the key", TaskStatus.NOT_DONE),
        ):
            await create_task(
                async_connection,
                creating_journal_id=creating,
                due_journal_id=due,
                text=task_text,
                status=status,
            )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert resolutions(assembled) == [
            ("pack the rope", TaskStatus.DONE),
            ("call the council", TaskStatus.CANCELLED),
            ("return the key", TaskStatus.NOT_DONE),
        ]

    async def test_the_linked_contact_travels_with_the_commitment(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The person is half of what makes a resolution worth reporting."""
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="return Sarah's book",
        )
        contact = await create_contact(async_connection, first_name="Sarah")
        await link_contact(async_connection, task_id=task_id, contact_id=contact)

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert assembled.past_day_tasks is not None
        (model,) = assembled.past_day_tasks
        assert [c.display_name for c in model.contacts] == ["Sarah"]


class TestTheDayIsItsJournals:
    """Which commitments belong to the day, and which only look as though they do."""

    async def test_a_task_due_on_another_day_is_absent(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The day is the journals the summary is describing, and nothing else.

        The neighbouring day is seeded with a commitment of its own so the
        absence is not vacuous: a read that ignored its journal ids would return
        both, and one that returned nothing would fail the first assertion.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        elsewhere = await create_journal(
            journal_repository,
            title="The day before",
            start=at(YESTERDAY - timedelta(days=1)),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="on the day",
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=elsewhere,
            text="the day before",
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert texts(assembled) == ["on the day"]

    async def test_a_task_retargeted_off_the_day_is_absent(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """A commitment that has moved on is no part of how this day resolved.

        Retargeting leaves the previous due journal behind as an *intermediate*
        link, which is exactly the shape a read consulting the wrong table would
        pick up — so the day's journal is seeded as that link and the task's due
        anchor is next week's.
        """
        creating = await creating_journal(journal_repository)
        left_behind = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        moved_to = await create_journal(
            journal_repository,
            title="Next week's review",
            start=at(TODAY + timedelta(days=6)),
        )
        task_id = await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=moved_to,
            text="moved on",
        )
        await link_intermediate_journal(
            async_connection, task_id=task_id, journal_id=left_behind
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert texts(assembled) == []

    async def test_a_task_merely_created_on_the_day_is_absent(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Writing a commitment down is not the same as owing it that day.

        The creating anchor is nearly always in the past, so a read consulting it
        would attribute half the user's commitments to whatever day they were
        first mentioned.
        """
        arose_here = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        due = await create_journal(
            journal_repository,
            title="Next week's review",
            start=at(TODAY + timedelta(days=6)),
        )
        await create_task(
            async_connection,
            creating_journal_id=arose_here,
            due_journal_id=due,
            text="arose here, owed later",
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert texts(assembled) == []

    async def test_another_users_task_is_absent(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Nothing in the schema stops a foreign task anchoring to a journal.

        So the predicate is the only thing keeping one person's commitments out
        of another's summary, and a real second user's row is the only way to
        show it is there. The acting user's own task on the same journal is what
        makes the assertion about *scoping* rather than about emptiness.
        """
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="Site visit", start=at(YESTERDAY)
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="mine",
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="not mine",
            user_id=OTHER_USER_ID,
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert texts(assembled) == ["mine"]

    async def test_a_multi_day_journal_running_through_the_day_counts(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The day's journals are matched by overlap, and the tasks follow them.

        A trip that began two days ago and ends tomorrow is one of this day's
        journals — the summary describes it — so a commitment due in it is part
        of this day too. A read that had built its own window over the due
        journal's *start* would miss it, which is the whole reason the journal
        ids travel rather than a date span.
        """
        creating = await creating_journal(journal_repository)
        spanning = await create_journal(
            journal_repository,
            title="Three-day trip",
            start=at(YESTERDAY - timedelta(days=2)),
            end=at(TODAY + timedelta(days=1)),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=spanning,
            text="due in the trip",
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert texts(assembled) == ["due in the trip"]


class TestNothingIsGatheredForAnyOtherDay:
    """A resolution belongs to a day that has been, and to no other."""

    @pytest.mark.parametrize("offset", [0, 1], ids=["today", "future"])
    async def test_the_current_and_future_days_gather_nothing(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        offset: int,
    ) -> None:
        """And still gather that day's journals, so the absence is not vacuous.

        The task is dated inside the day being asked about, so a read that had
        run would have found it. An absence assertion on an empty fixture proves
        nothing.
        """
        day = TODAY + timedelta(days=offset)
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository, title="That day's journal", start=at(day)
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="due that day",
        )

        assembled = await assembler.assemble(USER_ID, day, "UTC", now=NOW)

        assert assembled.past_day_tasks is None
        assert assembled.journal_count == 1

    async def test_a_past_day_with_nothing_due_is_gathered_and_empty(
        self,
        assembler: DailySummaryInputAssembler,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """Gathered-and-empty is a fact about the day; ``None`` is a day never asked.

        The distinction is load-bearing: only one of the two is something a
        prompt could say out loud.
        """
        await create_journal(
            journal_repository, title="A quiet day", start=at(YESTERDAY)
        )

        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert assembled.past_day_tasks == []

    async def test_a_past_day_with_no_journals_at_all_is_still_gathered(
        self, assembler: DailySummaryInputAssembler
    ) -> None:
        """The quiet-day case the always-eligible rule exists for.

        No journals means no query underneath, but the answer is still *asked
        and empty* rather than *never asked* — the guard above is about which
        day it is, not about how much is in it.
        """
        assembled = await assembler.assemble(USER_ID, YESTERDAY, "UTC", now=NOW)

        assert assembled.past_day_tasks == []


class TestWhoseDayItIs:
    """The past/today boundary is the user's, never UTC's."""

    async def test_a_far_east_users_day_is_judged_in_their_zone(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """At this instant Kiritimati is a day ahead of UTC, so the guard flips.

        UTC's today is the 11th; theirs is already the 12th. So the 11th is a
        *past* day for them and a UTC-anchored guard would call it today and
        gather nothing. The task is seeded on the 11th so the two readings differ
        in what they return rather than only in what they compute.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )
        creating = await creating_journal(journal_repository)
        due = await create_journal(
            journal_repository,
            title="Their eleventh",
            # 08:00 UTC on the 11th is 22:00 on the 11th in Kiritimati, so the
            # journal is on their 11th as well as UTC's — the fixture is about
            # which day is *today*, not about which day the journal lands on.
            start=at(TODAY, hour=8),
        )
        await create_task(
            async_connection,
            creating_journal_id=creating,
            due_journal_id=due,
            text="their lapsed commitment",
        )

        assembled = await assembler.assemble(USER_ID, TODAY, FAR_EAST, now=NOW)

        assert texts(assembled) == ["their lapsed commitment"]

    async def test_the_same_instant_gathers_nothing_for_their_today(
        self,
        assembler: DailySummaryInputAssembler,
        journal_repository: SqlJournalRepository,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """The other side of the same boundary, at the same instant.

        Their 12th is today, so it gathers no resolutions at all — which is what
        makes the case above an assertion about the *zone* rather than about the
        date arithmetic happening to work out.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone=FAR_EAST)
        )
        await create_journal(
            journal_repository, title="Their twelfth", start=at(TODAY, hour=13)
        )

        assembled = await assembler.assemble(
            USER_ID, TODAY + timedelta(days=1), FAR_EAST, now=NOW
        )

        assert assembled.past_day_tasks is None
