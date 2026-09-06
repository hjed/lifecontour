"""Integration tests for the contact dates the summary's assembler gathers.

Exercises ``DailySummaryInputAssembler.assemble`` against real contacts, real
``contact_important_dates`` rows and a real ``UpcomingImportantDatesService``.
The unit suite proves the assembler *asks* the right question of a double; only
real rows prove the answer is the week's important dates and nothing else.

Three things are asserted here that no unit test reaches:

- **Which rows the window really admits** — both its edges, and the day past it
  — where the rule works in dates and the stored row is a loose ``(month, day)``
  pair with no date in it at all.
- **That the recurrence rule survives the whole path.** A ``YEAR``-precision row
  has no month or day to place and yields nothing; a 29 February row is observed
  on the 28th in a year without a 29th, which is the case a query built from the
  window's literal days could not even fetch.
- **Whose week it is, and that the day is not looked up twice.** The window is
  anchored on the day the assembler resolved, so a zone far from UTC is never on
  the same date as it — and a deliberately contradictory ``user_settings`` row
  proves the service is not resolving its own.

Every date here is derived from a **fixed instant** with ``now`` injected. The
assertions are about window edges, and a boundary anchored on a moving clock is
a test that passes at 10:00 and fails at 23:59 — the same rule the bracketing
daily-summary suites follow, and for the same reason.
"""

from datetime import UTC, date, datetime, timedelta

import pytest
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.contacts.adapters.sql.contact_importance_repository import (
    SqlContactImportanceRepository,
)
from app.core.contacts.adapters.sql.upcoming_important_date_repository import (
    SqlUpcomingImportantDateRepository,
)
from app.core.contacts.services.upcoming_important_dates_service import (
    UpcomingImportantDatesService,
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
from tests.integration.contacts.upcoming_date_seeding import (
    seed_contact,
    seed_custom_date_type,
    seed_important_date,
)
from tests.integration.tasks.task_seeding import USER_ID, create_journal

pytestmark = pytest.mark.integration

# Midday UTC on a Tuesday, the instant the sibling daily-summary suites use.
# Far enough from either midnight that a UTC reading and the user's agree, so
# the far-east cases below have to say when they want them to disagree.
NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
TODAY = date(2026, 8, 11)
LAST_DAY = date(2026, 8, 18)

# A large positive offset, so one local day never shares a UTC date with UTC's.
FAR_EAST = "Pacific/Kiritimati"  # UTC+14

# A week straddling a 28 February that is not itself a leap day — the only shape
# in which the substitution can be observed at all.
LEAP_NOW = datetime(2026, 2, 25, 12, 0, tzinfo=UTC)
LEAP_TODAY = date(2026, 2, 25)


@pytest.fixture
def assembler(
    async_connection: AsyncConnection,
    journal_repository: SqlJournalRepository,
    user_settings_repository: SqlUserSettingsRepository,
) -> DailySummaryInputAssembler:
    """The assembler over the test's savepoint connection, dates read and all.

    Built from adapters rather than resolved from a container, the shape the
    sibling suites use: what is under test is the assembly, and a container would
    add a graph to construct without adding an assertion. The service shares this
    connection, so a contact seeded in the test is visible to it inside the same
    savepoint.
    """
    return DailySummaryInputAssembler(
        journal_repo=journal_repository,
        mood_repo=SqlMoodDataRepository(async_connection),
        contact_relationship_repo=SqlJournalContactRelationshipRepository(
            async_connection
        ),
        summary_repo=SqlJournalDailySummaryRepository(async_connection),
        upcoming_dates_service=UpcomingImportantDatesService(
            date_resolver=JournalDateResolver(
                user_settings_repo=user_settings_repository
            ),
            candidate_repo=SqlUpcomingImportantDateRepository(async_connection),
            importance_repo=SqlContactImportanceRepository(async_connection),
        ),
    )


def at(day: date, hour: int = 9) -> datetime:
    """An instant on ``day``, in UTC."""
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=hour)


def names(assembled: DailySummaryInput) -> list[str]:
    """Whose dates came back, in the order they came back in.

    Asserts the group was gathered at all, so a caller reading names never
    silently compares an empty list against a day that was never asked.
    """
    gathered = assembled.upcoming_dates
    assert gathered is not None
    return [entry.contact.display_name for entry in gathered.dates]


class TestTheWeeksDatesAgainstRealContacts:
    """What the window admits, and what travels with each row."""

    async def test_a_birthday_in_the_window_arrives_with_its_contact(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        await seed_contact(
            async_connection, 1, now=NOW, first_name="Ada", last_name="Lovelace"
        )
        await seed_important_date(
            async_connection,
            10,
            1,
            now=NOW,
            month=8,
            day=14,
            year=1991,
            precision=DatePrecision.FULL,
        )

        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert result.upcoming_dates is not None
        assert names(result) == ["Ada Lovelace"]
        entry = result.upcoming_dates.dates[0]
        assert entry.occurrence.occurs_on == date(2026, 8, 14)
        assert entry.occurrence.days_away == 3

    async def test_the_derived_years_travel_with_a_full_precision_date(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """The phase's third criterion, proved against a real row."""
        await seed_contact(async_connection, 1, now=NOW)
        await seed_important_date(
            async_connection,
            10,
            1,
            now=NOW,
            month=8,
            day=14,
            year=1991,
            precision=DatePrecision.FULL,
        )

        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert result.upcoming_dates is not None
        assert result.upcoming_dates.dates[0].occurrence.years == 35

    async def test_a_date_without_a_stored_year_carries_no_count(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """``DAY_MONTH`` is a real precision, not a partially-filled ``FULL``."""
        await seed_contact(async_connection, 1, now=NOW)
        await seed_important_date(async_connection, 10, 1, now=NOW, month=8, day=14)

        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert result.upcoming_dates is not None
        assert result.upcoming_dates.dates[0].occurrence.years is None

    async def test_both_window_edges_are_included(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """Today counts — the point of a section that exists to give notice."""
        await seed_contact(async_connection, 1, now=NOW, first_name="First")
        await seed_contact(async_connection, 2, now=NOW, first_name="Last")
        await seed_important_date(
            async_connection, 10, 1, now=NOW, month=TODAY.month, day=TODAY.day
        )
        await seed_important_date(
            async_connection, 11, 2, now=NOW, month=LAST_DAY.month, day=LAST_DAY.day
        )

        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert names(result) == ["First Lovelace", "Last Lovelace"]

    async def test_the_day_after_the_window_is_absent(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """Seeded beside a date that *is* in the window, so the absence bites."""
        await seed_contact(async_connection, 1, now=NOW, first_name="Inside")
        await seed_contact(async_connection, 2, now=NOW, first_name="Outside")
        await seed_important_date(async_connection, 10, 1, now=NOW, month=8, day=14)
        await seed_important_date(async_connection, 11, 2, now=NOW, month=8, day=19)

        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert names(result) == ["Inside Lovelace"]

    async def test_a_year_precision_row_places_nothing(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """No month and no day, so there is no occurrence to resolve.

        Seeded beside a row that does resolve, because a suite where nothing
        comes back cannot tell a working precision rule from a broken query.
        """
        await seed_contact(async_connection, 1, now=NOW, first_name="Placed")
        await seed_contact(async_connection, 2, now=NOW, first_name="Unplaceable")
        await seed_important_date(async_connection, 10, 1, now=NOW, month=8, day=14)
        await seed_important_date(
            async_connection,
            11,
            2,
            now=NOW,
            month=None,
            day=None,
            year=1991,
            precision=DatePrecision.YEAR,
        )

        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert names(result) == ["Placed Lovelace"]

    async def test_a_custom_types_name_travels_with_the_row(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """The prompt renders the user's own word for it, so it has to arrive."""
        await seed_contact(async_connection, 1, now=NOW)
        await seed_custom_date_type(async_connection, 7, now=NOW, name="Sobriety")
        await seed_important_date(
            async_connection,
            10,
            1,
            now=NOW,
            month=8,
            day=14,
            date_type=ImportantDateType.CUSTOM,
            custom_date_type_id=7,
        )

        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert result.upcoming_dates is not None
        stored = result.upcoming_dates.dates[0].occurrence.important_date
        assert stored.custom_date_type_name == "Sobriety"

    async def test_a_favourite_leads_a_shared_day(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """Importance breaks ties *within* a day, from real signals."""
        await seed_contact(async_connection, 1, now=NOW, first_name="Ordinary")
        await seed_contact(
            async_connection, 2, now=NOW, first_name="Favourite", is_favourite=True
        )
        await seed_important_date(async_connection, 10, 1, now=NOW, month=8, day=14)
        await seed_important_date(async_connection, 11, 2, now=NOW, month=8, day=14)

        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert names(result) == ["Favourite Lovelace", "Ordinary Lovelace"]

    async def test_a_quiet_week_is_gathered_and_empty(
        self, assembler: DailySummaryInputAssembler
    ) -> None:
        """Distinct from never asked, and it still carries its window."""
        result = await assembler.assemble(USER_ID, TODAY, "UTC", now=NOW)

        assert result.upcoming_dates is not None
        assert result.upcoming_dates.dates == ()
        assert result.upcoming_dates.window.first_day == TODAY
        assert result.upcoming_dates.window.last_day == LAST_DAY


class TestTheLeapDayAgainstRealRows:
    """A 29 February row in a year that has no 29 February."""

    async def test_it_is_observed_on_the_twenty_eighth(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """A query built from the window's literal days would never fetch it.

        Which is why the candidate pairs add ``(2, 29)`` and why this case is
        worth a real row: the failure is silent — a leap-day birthday simply
        absent, in three years out of four.
        """
        await seed_contact(async_connection, 1, now=LEAP_NOW)
        await seed_important_date(
            async_connection,
            10,
            1,
            now=LEAP_NOW,
            month=2,
            day=29,
            year=1992,
            precision=DatePrecision.FULL,
        )

        result = await assembler.assemble(USER_ID, LEAP_TODAY, "UTC", now=LEAP_NOW)

        assert result.upcoming_dates is not None
        occurrence = result.upcoming_dates.dates[0].occurrence
        assert occurrence.occurs_on == date(2026, 2, 28)
        assert occurrence.observed_for_leap_day is True


class TestDatesAreGatheredForTheCurrentDayOnly:
    """A past day describes itself; a future day is not today either."""

    async def test_a_past_day_gathers_no_dates_but_still_gathers_its_journals(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        """The absence is not vacuous: the date is inside today's own window.

        A today-anchored reading would return it, so this fails the moment the
        guard stops asking which day it is. The journal proves the rest of the
        assembly still ran.
        """
        yesterday = TODAY - timedelta(days=1)
        await create_journal(journal_repository, title="Yesterday", start=at(yesterday))
        await seed_contact(async_connection, 1, now=NOW)
        await seed_important_date(async_connection, 10, 1, now=NOW, month=8, day=14)

        result = await assembler.assemble(USER_ID, yesterday, "UTC", now=NOW)

        assert result.upcoming_dates is None
        assert [entry.title for entry in result.journals] == ["Yesterday"]

    async def test_a_future_day_gathers_no_dates_but_still_gathers_its_journals(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        journal_repository: SqlJournalRepository,
    ) -> None:
        tomorrow = TODAY + timedelta(days=1)
        await create_journal(journal_repository, title="Tomorrow", start=at(tomorrow))
        await seed_contact(async_connection, 1, now=NOW)
        await seed_important_date(async_connection, 10, 1, now=NOW, month=8, day=14)

        result = await assembler.assemble(USER_ID, tomorrow, "UTC", now=NOW)

        assert result.upcoming_dates is None
        assert [entry.title for entry in result.journals] == ["Tomorrow"]


class TestWhoseWeekItIs:
    """The window is the user's, and the day is resolved exactly once."""

    async def test_a_far_east_users_window_runs_a_day_ahead_of_utcs(
        self, assembler: DailySummaryInputAssembler, async_connection: AsyncConnection
    ) -> None:
        """Midday on the 11th in UTC is already the 12th in Kiritimati (+14).

        Their week therefore runs the 12th to the 19th while UTC's runs the 11th
        to the 18th, and the date seeded on the 19th is past the end of a
        UTC-anchored window — so a UTC reading could not pass this.
        """
        await seed_contact(async_connection, 1, now=NOW, first_name="Kiritimati")
        await seed_important_date(async_connection, 10, 1, now=NOW, month=8, day=19)

        result = await assembler.assemble(USER_ID, date(2026, 8, 12), FAR_EAST, now=NOW)

        assert result.upcoming_dates is not None
        assert result.upcoming_dates.window.first_day == date(2026, 8, 12)
        assert result.upcoming_dates.window.last_day == date(2026, 8, 19)
        assert names(result) == ["Kiritimati Lovelace"]

    async def test_the_stored_settings_row_is_never_consulted(
        self,
        assembler: DailySummaryInputAssembler,
        async_connection: AsyncConnection,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """A contradictory row is what makes "no second read" observable.

        ``user_settings`` says UTC while the assembly is handed Kiritimati. A
        service resolving its own day would build the 11th-to-18th window and
        drop the 19th; handing ``today`` down means the row is never read, so the
        two cannot disagree — which is the whole of the second decision this
        phase records.
        """
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="UTC")
        )
        await seed_contact(async_connection, 1, now=NOW, first_name="Kiritimati")
        await seed_important_date(async_connection, 10, 1, now=NOW, month=8, day=19)

        result = await assembler.assemble(USER_ID, date(2026, 8, 12), FAR_EAST, now=NOW)

        assert result.upcoming_dates is not None
        assert result.upcoming_dates.window.last_day == date(2026, 8, 19)
        assert names(result) == ["Kiritimati Lovelace"]
