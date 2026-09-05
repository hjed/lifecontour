"""The upcoming-dates read, against a real database.

Two layers are asserted here, and deliberately both.

**The query on its own**, because it filters the window a second time. The pure
rule drops anything that does not resolve inside the window, so a query that
over-fetched would still produce the right answer and quietly become "every
important date this user has, resolved" — the unbounded read this section exists
not to be. ITER18-001 Phase 14 shipped exactly that and only found it by
mutation, so the pair filter gets tests addressed to it directly.

**Statement counts**, because an N+1 is invisible to a functional assertion: the
answer is right either way and only the number of round trips is wrong. This
read must stay at two statements — the candidates and the batched importance
signals — however many contacts the window turns up.
"""

from datetime import UTC, datetime

import pytest
from core_shared.models.contacts.important_date_types import (
    DatePrecision,
    ImportantDateType,
)
from sqlalchemy import text
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
from app.core.journal.services.journal_date_resolver import JournalDateResolver
from app.core.settings.adapters.sql.user_settings_repository import (
    SqlUserSettingsRepository,
)
from app.core.settings.models import UserSettings
from tests.integration.statement_recorder import recorded_statements

pytestmark = pytest.mark.asyncio

USER_ID = "user1"
NOW = datetime(2026, 8, 11, 9, 30, tzinfo=UTC)
TODAY = NOW.date()

#: 00:30 on 12 August in Kiritimati (+14), while UTC is still on the 11th.
JUST_BEFORE_UTC_CATCHES_UP = datetime(2026, 8, 11, 10, 30, tzinfo=UTC)

#: The pairs a seven-day window from 11 August 2026 asks for.
AUGUST_WEEK = ((8, 11), (8, 12), (8, 13), (8, 14), (8, 15), (8, 16), (8, 17), (8, 18))


@pytest.fixture
def repository(
    async_connection: AsyncConnection,
) -> SqlUpcomingImportantDateRepository:
    """The read under test, on the test's savepoint connection."""
    return SqlUpcomingImportantDateRepository(async_connection)


async def _contact(
    connection: AsyncConnection,
    contact_id: int,
    *,
    first_name: str = "Ada",
    last_name: str | None = "Lovelace",
    middle_name: str | None = None,
    nick_name: str | None = None,
    photo_url: str | None = None,
) -> None:
    """A bare contact with the display fields a dashboard row shows."""
    await connection.execute(
        text("""
            INSERT INTO contacts (
                id, first_name, middle_name, last_name, nick_name, photo_url,
                created_at, updated_at
            )
            VALUES (:id, :first_name, :middle_name, :last_name, :nick_name,
                    :photo_url, :now, :now)
        """),
        {
            "id": contact_id,
            "first_name": first_name,
            "middle_name": middle_name,
            "last_name": last_name,
            "nick_name": nick_name,
            "photo_url": photo_url,
            "now": NOW,
        },
    )


async def _important_date(
    connection: AsyncConnection,
    date_id: int,
    contact_id: int,
    *,
    month: int | None,
    day: int | None,
    year: int | None = None,
    precision: DatePrecision = DatePrecision.DAY_MONTH,
    date_type: ImportantDateType = ImportantDateType.BIRTHDAY,
    custom_date_type_id: int | None = None,
) -> None:
    """One stored important date, at whatever precision the test needs."""
    await connection.execute(
        text("""
            INSERT INTO contact_important_dates (
                id, contact_id, date_type, precision, year, month, day,
                custom_date_type_id, created_at, updated_at
            )
            VALUES (:id, :contact_id, :date_type, :precision, :year, :month,
                    :day, :custom_date_type_id, :now, :now)
        """),
        {
            "id": date_id,
            "contact_id": contact_id,
            "date_type": date_type.value,
            "precision": precision.value,
            "year": year,
            "month": month,
            "day": day,
            "custom_date_type_id": custom_date_type_id,
            "now": NOW,
        },
    )


async def _custom_date_type(
    connection: AsyncConnection, type_id: int, name: str = "Sobriety"
) -> None:
    """A user-named date type, so its name can travel with the row."""
    await connection.execute(
        text("""
            INSERT INTO custom_date_types (id, name, created_at, updated_at)
            VALUES (:id, :name, :now, :now)
        """),
        {"id": type_id, "name": name, "now": NOW},
    )


class TestWhichRowsTheQueryFetches:
    """Addressed to the SQL, because the pure rule filters the window again."""

    async def test_it_fetches_a_date_whose_pair_is_in_the_window(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=14)

        rows = await repository.candidates_for(AUGUST_WEEK)

        assert [row.important_date.id for row in rows] == [10]

    async def test_it_fetches_neither_side_of_the_window(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        """The day before the first pair and the day after the last.

        Without this the statement could drop its filter entirely and every test
        above would still pass, because the pure rule would remove the extra
        rows before anybody looked.
        """
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=10)
        await _important_date(
            async_connection,
            11,
            1,
            month=8,
            day=19,
            date_type=ImportantDateType.WORK_ANNIVERSARY,
        )

        rows = await repository.candidates_for(AUGUST_WEEK)

        assert rows == []

    async def test_a_year_precision_row_is_never_a_candidate(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        """It has no month or day, so no pair can match it — the schema's
        NULL-by-precision constraint and the pair join agree without a second
        rule saying so."""
        await _contact(async_connection, 1)
        await _important_date(
            async_connection,
            10,
            1,
            month=None,
            day=None,
            year=2019,
            precision=DatePrecision.YEAR,
            date_type=ImportantDateType.FIRST_MET,
        )

        rows = await repository.candidates_for(AUGUST_WEEK)

        assert rows == []

    async def test_a_leap_day_row_is_fetched_when_the_28th_is_asked_for(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        """The pair the window adds for a common year's 28 February."""
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=2, day=29)

        rows = await repository.candidates_for(((2, 27), (2, 28), (2, 29)))

        assert [row.important_date.id for row in rows] == [10]

    async def test_it_matches_the_pair_and_not_the_month_or_day_alone(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        """14 September and 3 August are each half a match and neither is one."""
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=9, day=14)
        await _important_date(
            async_connection,
            11,
            1,
            month=8,
            day=3,
            date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
        )

        rows = await repository.candidates_for(AUGUST_WEEK)

        assert rows == []

    async def test_no_pairs_is_answered_without_asking_the_database(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        with recorded_statements(async_connection) as statements:
            rows = await repository.candidates_for(())

        assert rows == []
        assert statements == []


class TestWhatTravelsWithARow:
    """A dashboard row renders a contact and a type; both come from this read."""

    async def test_the_stored_date_comes_back_whole(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        await _contact(async_connection, 1)
        await _important_date(
            async_connection,
            10,
            1,
            month=8,
            day=14,
            year=1991,
            precision=DatePrecision.FULL,
            date_type=ImportantDateType.MARRIAGE_ANNIVERSARY,
        )

        [row] = await repository.candidates_for(AUGUST_WEEK)

        assert row.important_date.contact_id == 1
        assert row.important_date.date_type is ImportantDateType.MARRIAGE_ANNIVERSARY
        assert row.important_date.precision is DatePrecision.FULL
        assert (row.important_date.year, row.important_date.month) == (1991, 8)
        assert row.important_date.day == 14

    async def test_a_custom_type_carries_its_name(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        """The badge shows what the user called it, not the word "custom"."""
        await _contact(async_connection, 1)
        await _custom_date_type(async_connection, 5)
        await _important_date(
            async_connection,
            10,
            1,
            month=8,
            day=14,
            date_type=ImportantDateType.CUSTOM,
            custom_date_type_id=5,
        )

        [row] = await repository.candidates_for(AUGUST_WEEK)

        assert row.important_date.custom_date_type_name == "Sobriety"

    async def test_the_contact_comes_back_as_a_row_shows_them(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        await _contact(
            async_connection,
            1,
            first_name="Augusta",
            middle_name="Ada",
            last_name="King",
            photo_url="https://example.test/ada.png",
        )
        await _important_date(async_connection, 10, 1, month=8, day=14)

        [row] = await repository.candidates_for(AUGUST_WEEK)

        assert row.contact.id == 1
        assert row.contact.display_name == "Augusta Ada King"
        assert row.contact.photo_url == "https://example.test/ada.png"

    async def test_a_nickname_is_the_display_name(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        """The contacts domain's own display rule, not a second one in SQL."""
        await _contact(async_connection, 1, nick_name="Ada")
        await _important_date(async_connection, 10, 1, month=8, day=14)

        [row] = await repository.candidates_for(AUGUST_WEEK)

        assert row.contact.display_name == "Ada"


class TestTheBatchShape:
    """One statement, however many contacts the window turns up."""

    async def test_many_contacts_are_answered_in_one_statement(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        for contact_id in range(1, 7):
            await _contact(async_connection, contact_id)
            await _important_date(
                async_connection, 100 + contact_id, contact_id, month=8, day=14
            )

        with recorded_statements(async_connection) as statements:
            rows = await repository.candidates_for(AUGUST_WEEK)

        assert len(rows) == 6
        assert len(statements) == 1

    async def test_rows_come_back_in_a_stable_order(
        self,
        async_connection: AsyncConnection,
        repository: SqlUpcomingImportantDateRepository,
    ) -> None:
        """The display order is the pure rule's; this only has to be repeatable,
        so two reads of the same rows cannot differ before ranking."""
        await _contact(async_connection, 1)
        await _important_date(async_connection, 12, 1, month=8, day=14)
        await _important_date(
            async_connection,
            11,
            1,
            month=8,
            day=15,
            date_type=ImportantDateType.WORK_ANNIVERSARY,
        )

        rows = await repository.candidates_for(AUGUST_WEEK)

        assert [row.important_date.id for row in rows] == [11, 12]


@pytest.fixture
def service(
    async_connection: AsyncConnection,
    user_settings_repository: SqlUserSettingsRepository,
) -> UpcomingImportantDatesService:
    """The whole read, on the test's savepoint connection.

    Real repositories rather than doubles: what these tests exist to prove is
    that the pair filter, the recurrence rule and the ranking agree against a
    real database, and a double would prove only that they agree with the
    double.
    """
    return UpcomingImportantDatesService(
        date_resolver=JournalDateResolver(user_settings_repo=user_settings_repository),
        candidate_repo=SqlUpcomingImportantDateRepository(async_connection),
        importance_repo=SqlContactImportanceRepository(async_connection),
    )


class TestTheWindowAgainstRealRows:
    """Both edges, and both sides of both edges."""

    async def test_a_date_on_the_first_day_is_included(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        """Today is in the window — the whole point of a section giving notice."""
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=11)

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert [date.occurrence.days_away for date in result.dates] == [0]

    async def test_a_date_on_the_last_day_is_included(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=18)

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert [date.occurrence.days_away for date in result.dates] == [7]

    async def test_the_day_either_side_of_the_window_is_excluded(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=10)
        await _important_date(
            async_connection,
            11,
            1,
            month=8,
            day=19,
            date_type=ImportantDateType.WORK_ANNIVERSARY,
        )

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert result.dates == ()
        assert result.total == 0

    async def test_a_window_crossing_the_year_boundary_finds_a_january_date(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=1, day=2)

        result = await service.upcoming_dates(
            USER_ID, today=datetime(2026, 12, 30, tzinfo=UTC).date()
        )

        assert [date.occurrence.occurs_on for date in result.dates] == [
            datetime(2027, 1, 2, tzinfo=UTC).date()
        ]


class TestEachPrecisionAgainstRealRows:
    """The precision rule is Phase 9's; this proves the stored column reaches it."""

    async def test_a_day_month_date_has_an_occurrence_and_no_years(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=14)

        [date] = (await service.upcoming_dates(USER_ID, today=TODAY)).dates

        assert date.occurrence.occurs_on.day == 14
        assert date.occurrence.years is None

    async def test_a_full_date_carries_its_derived_years(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        await _contact(async_connection, 1)
        await _important_date(
            async_connection,
            10,
            1,
            month=8,
            day=14,
            year=1991,
            precision=DatePrecision.FULL,
        )

        [date] = (await service.upcoming_dates(USER_ID, today=TODAY)).dates

        assert date.occurrence.years == 35

    async def test_a_year_precision_date_never_appears(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        await _contact(async_connection, 1)
        await _important_date(
            async_connection,
            10,
            1,
            month=None,
            day=None,
            year=2019,
            precision=DatePrecision.YEAR,
            date_type=ImportantDateType.FIRST_MET,
        )

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert result.dates == ()

    async def test_a_leap_day_birthday_is_observed_on_the_28th(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        """2027 has no 29 February. Without the candidate pair the row is never
        fetched, and the section is silently missing a birthday."""
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=2, day=29)

        result = await service.upcoming_dates(
            USER_ID, today=datetime(2027, 2, 26, tzinfo=UTC).date(), days_ahead=3
        )

        [date] = result.dates
        assert date.occurrence.occurs_on == datetime(2027, 2, 28, tzinfo=UTC).date()
        assert date.occurrence.observed_for_leap_day


class TestTheOrderAgainstRealSignals:
    """The ranking, with the importance signals read from real rows."""

    async def test_the_favourite_leads_a_shared_day(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        await _contact(async_connection, 1)
        await _contact(async_connection, 2)
        await async_connection.execute(
            text("UPDATE contacts SET is_favourite = TRUE WHERE id = 2"),
        )
        await _important_date(async_connection, 10, 1, month=8, day=14)
        await _important_date(async_connection, 11, 2, month=8, day=14)

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert [date.contact.id for date in result.dates] == [2, 1]

    async def test_a_sooner_date_still_leads_a_more_important_contact(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        await _contact(async_connection, 1)
        await _contact(async_connection, 2)
        await async_connection.execute(
            text("UPDATE contacts SET is_favourite = TRUE WHERE id = 2"),
        )
        await _important_date(async_connection, 10, 1, month=8, day=12)
        await _important_date(async_connection, 11, 2, month=8, day=16)

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert [date.contact.id for date in result.dates] == [1, 2]

    async def test_a_contact_with_no_signals_at_all_still_appears(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        """No journals, no recorded changes, not a favourite: the row still shows."""
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=14)

        result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert [date.contact.id for date in result.dates] == [1]
        assert result.dates[0].importance.journal_count_30d == 0


class TestWhoseDayTheWindowStartsOn:
    """Against a real settings row, not a stubbed timezone."""

    async def test_the_window_starts_on_the_users_day_not_utcs(
        self,
        async_connection: AsyncConnection,
        service: UpcomingImportantDatesService,
        user_settings_repository: SqlUserSettingsRepository,
    ) -> None:
        """At 10:30Z on the 11th it is already 00:30 on the **12th** in
        Kiritimati (+14), so their window runs the 12th to the 19th. A date on
        the 19th is inside it and a whole day past the end of UTC's."""
        await user_settings_repository.save(
            UserSettings(user_id=USER_ID, timezone="Pacific/Kiritimati")
        )
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=19)

        result = await service.upcoming_dates(USER_ID, now=JUST_BEFORE_UTC_CATCHES_UP)

        assert result.window.first_day == datetime(2026, 8, 12, tzinfo=UTC).date()
        assert [date.contact.id for date in result.dates] == [1]

    async def test_the_same_row_is_outside_a_utc_users_window(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        """The other half of the pair, without which the case proves nothing:
        with no settings row the zone is UTC, whose window ends on the 18th."""
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=19)

        result = await service.upcoming_dates(USER_ID, now=JUST_BEFORE_UTC_CATCHES_UP)

        assert result.window.first_day == TODAY
        assert result.dates == ()


class TestTheRoundTrips:
    """Two statements, whatever the window turns up."""

    async def test_six_contacts_cost_two_statements(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        for contact_id in range(1, 7):
            await _contact(async_connection, contact_id)
            await _important_date(
                async_connection, 100 + contact_id, contact_id, month=8, day=14
            )

        with recorded_statements(async_connection) as statements:
            result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert len(result.dates) == 6
        assert len(statements) == 2

    async def test_one_contact_costs_the_same_two_statements(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        """The pair with the test above: an N+1 shows as a difference between
        these two numbers, and a single fixture cannot show one at all."""
        await _contact(async_connection, 1)
        await _important_date(async_connection, 10, 1, month=8, day=14)

        with recorded_statements(async_connection) as statements:
            await service.upcoming_dates(USER_ID, today=TODAY)

        assert len(statements) == 2

    async def test_an_empty_window_costs_one_statement(
        self, async_connection: AsyncConnection, service: UpcomingImportantDatesService
    ) -> None:
        """The signals read short circuits on an empty batch, so a quiet week
        never pays for a second round trip."""
        with recorded_statements(async_connection) as statements:
            result = await service.upcoming_dates(USER_ID, today=TODAY)

        assert result.dates == ()
        assert len(statements) == 1
