"""Integration tests for the agenda the daily summary's input assembler gathers.

Exercises ``DailySummaryInputAssembler.assemble`` against real journals, real
``journal_calendar_info`` rows and real contact relationships. A unit test with a
mocked port proves the assembler *asks* the right question; only real SQL proves
the answer is the day's events and nothing else.

Four things are asserted here that no unit test reaches:

- **What reaches the agenda at all** — an event journal on the user's day, and
  not a journal without calendar info, not another user's.
- **Which day that is.** The window is the user's local day, so a zone far from
  UTC is never on the same date as it and a UTC-anchored reading cannot pass.
- **A cancelled event arrives flagged**, not dropped, so the prompt can mark it
  rather than silently presenting it as something the user is doing.
- **A past day reads no agenda at all**, against a day that really has events on
  it — the negative case is worthless if the day is empty anyway.

The clock cannot be frozen for the SQL that windows the day, so journals are
seeded relative to an instant read inside the test — the bracketing
``test_home_dashboard_agenda.py`` uses, whose ``EventSeeder`` this reuses rather
than growing a second one.
"""

import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.journal.adapters.sql.agenda_repository import SqlAgendaRepository
from app.core.journal.adapters.sql.daily_summary_repository import (
    SqlJournalDailySummaryRepository,
)
from app.core.journal.adapters.sql.journal_contact_relationship_repository import (
    SqlJournalContactRelationshipRepository,
)
from app.core.journal.adapters.sql.journal_repository import SqlJournalRepository
from app.core.journal.adapters.sql.mood_data_repository import SqlMoodDataRepository
from app.core.journal.models.agenda import AgendaEntry
from app.core.journal.services.daily_summary_input_assembler import (
    DailySummaryInputAssembler,
)
from tests.integration.api.test_home_dashboard_agenda import (
    OTHER_USER_ID,
    USER_ID,
    EventSeeder,
)

# A large positive offset, so one local day never shares a UTC date with UTC's.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14


@pytest.fixture
def assembler(async_connection: AsyncConnection) -> DailySummaryInputAssembler:
    """The assembler over the test's savepoint connection, agenda port and all."""
    return DailySummaryInputAssembler(
        journal_repo=SqlJournalRepository(async_connection),
        mood_repo=SqlMoodDataRepository(async_connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(
            async_connection
        ),
        summary_repo=SqlJournalDailySummaryRepository(async_connection),
        agenda_repo=SqlAgendaRepository(async_connection),
    )


@pytest.fixture
def event_seeder(async_connection: AsyncConnection) -> EventSeeder:
    """The agenda suite's seeder, on this test's connection."""
    return EventSeeder(async_connection)


def today_in_zone(timezone: str) -> datetime.date:
    return datetime.datetime.now(ZoneInfo(timezone)).date()


def titles(agenda: list[AgendaEntry]) -> list[str]:
    return [entry.title for entry in agenda]


@pytest.mark.integration
@pytest.mark.asyncio
class TestTodaysAgendaAgainstRealJournals:
    """The current day's events, read the way the dashboard reads them."""

    async def test_assembles_the_days_events_with_their_people_and_places(
        self, assembler: DailySummaryInputAssembler, event_seeder: EventSeeder
    ) -> None:
        """Times, location and participants all travel with the entry."""
        today = today_in_zone("UTC")
        timed = await event_seeder.event(
            title="Design review", hour=9, location="Level 3 boardroom", on_day=today
        )
        await event_seeder.participant(timed, "Alice", "Smith")
        await event_seeder.all_day_on(today, title="Public holiday", written_in="UTC")

        result = await assembler.assemble(USER_ID, today, "UTC")

        # All-day is pinned above the timed entry, as the agenda orders them.
        assert titles(result.agenda) == ["Public holiday", "Design review"]
        review = result.agenda[1]
        assert review.location == "Level 3 boardroom"
        assert [person.name for person in review.participants] == ["Alice Smith"]
        assert review.start_time == datetime.time(9, 0)

    async def test_a_journal_without_calendar_info_is_not_on_the_agenda(
        self, assembler: DailySummaryInputAssembler, event_seeder: EventSeeder
    ) -> None:
        """A note about the day is not something scheduled on it."""
        today = today_in_zone("UTC")
        await event_seeder.event(
            title="Just a note", with_calendar_info=False, on_day=today
        )

        result = await assembler.assemble(USER_ID, today, "UTC")

        assert result.agenda == []

    async def test_another_users_event_is_never_assembled(
        self, assembler: DailySummaryInputAssembler, event_seeder: EventSeeder
    ) -> None:
        """Nothing in a summary is shared between users."""
        today = today_in_zone("UTC")
        await event_seeder.event(
            title="Their standup", user_id=OTHER_USER_ID, on_day=today
        )

        result = await assembler.assemble(USER_ID, today, "UTC")

        assert result.agenda == []

    async def test_a_cancelled_event_arrives_flagged_rather_than_dropped(
        self, assembler: DailySummaryInputAssembler, event_seeder: EventSeeder
    ) -> None:
        """The prompt cannot mark an entry the assembler never handed it."""
        today = today_in_zone("UTC")
        await event_seeder.event(title="Dentist", event_state="cancelled", on_day=today)

        result = await assembler.assemble(USER_ID, today, "UTC")

        assert titles(result.agenda) == ["Dentist"]
        assert result.agenda[0].is_cancelled is True

    async def test_the_day_is_the_users_local_day(
        self, assembler: DailySummaryInputAssembler, event_seeder: EventSeeder
    ) -> None:
        """Fourteen hours ahead of UTC, the user's today is its own date.

        07:00 on the user's today is **yesterday** in UTC, so a window anchored
        on UTC's date would not reach it. That is what this asserts: not merely
        that the event is found, but that it is found on a day UTC has not
        started yet.
        """
        local_today = today_in_zone(FAR_EAST)
        await event_seeder.event(
            title="Morning swim", timezone=FAR_EAST, hour=7, on_day=local_today
        )

        result = await assembler.assemble(USER_ID, local_today, FAR_EAST)

        assert titles(result.agenda) == ["Morning swim"]

    async def test_tomorrows_event_is_not_on_todays_agenda(
        self, assembler: DailySummaryInputAssembler, event_seeder: EventSeeder
    ) -> None:
        """The window has a far end, and only the query can prove where it is.

        Assembled for the user's **today**, so the agenda query really runs —
        unlike an assertion about some other date, which the current-day guard
        would answer without asking the database at all. 07:00 tomorrow in
        UTC+14 is *this* UTC day, so a window anchored on UTC's date would put
        tomorrow's event on today's agenda; the local window must not.
        """
        local_today = today_in_zone(FAR_EAST)
        await event_seeder.event(
            title="Tomorrow's swim",
            timezone=FAR_EAST,
            hour=7,
            day_offset=1,
            on_day=local_today,
        )

        result = await assembler.assemble(USER_ID, local_today, FAR_EAST)

        assert result.agenda == []


@pytest.mark.integration
@pytest.mark.asyncio
class TestOnlyTheCurrentDayReadsAnAgenda:
    """Forward-looking material belongs to today, on real data too."""

    async def test_a_past_day_assembles_no_agenda(
        self, assembler: DailySummaryInputAssembler, event_seeder: EventSeeder
    ) -> None:
        """Yesterday really has an event on it, and still gets no agenda."""
        today = today_in_zone("UTC")
        yesterday = today - datetime.timedelta(days=1)
        await event_seeder.event(
            title="Yesterday's standup", day_offset=-1, on_day=today
        )

        result = await assembler.assemble(USER_ID, yesterday, "UTC")

        assert result.agenda == []
        # The day's journals are still assembled — only the agenda is withheld.
        assert result.journal_count == 1

    async def test_a_future_day_assembles_no_agenda(
        self, assembler: DailySummaryInputAssembler, event_seeder: EventSeeder
    ) -> None:
        """The rule is "the current day", not "today or later"."""
        today = today_in_zone("UTC")
        tomorrow = today + datetime.timedelta(days=1)
        await event_seeder.event(title="Tomorrow's standup", day_offset=1, on_day=today)

        result = await assembler.assemble(USER_ID, tomorrow, "UTC")

        assert result.agenda == []
        assert result.journal_count == 1
